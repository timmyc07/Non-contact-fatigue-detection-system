from pathlib import Path
import threading
from urllib.parse import unquote, urlsplit

import requests
import pytest

from gui.file_browser_client import FileBrowserClient


def test_upload_recreates_body_after_authentication_retry(tmp_path: Path, monkeypatch):
    path = tmp_path / "metrics.db"
    path.write_bytes(b"complete database body")
    client = FileBrowserClient(tmp_path)
    client._base_url = "http://file-browser.invalid"
    bodies = []
    progress = []
    monkeypatch.setattr(client, "_auth_headers", lambda: {"X-Auth": "test"})
    monkeypatch.setattr(client, "_do_login_locked", lambda: True)

    def request(*args, **kwargs):
        bodies.append(b"".join(kwargs["data"]))
        response = requests.Response()
        response.status_code = 401 if len(bodies) == 1 else 200
        response._content = b""
        response._content_consumed = True
        return response

    monkeypatch.setattr(client._session, "request", request)
    client.upload_file(path, path.name, progress_cb=progress.append)

    assert bodies == [path.read_bytes(), path.read_bytes()]
    assert progress == [1.0, 1.0]


@pytest.mark.parametrize("statuses", [(200,), (409, 200), (500,), (409, 500)])
def test_upload_invalidates_only_successful_database_cache_after_client_restart(tmp_path, monkeypatch, statuses):
    cache_dir = tmp_path / "cache"
    original = FileBrowserClient(cache_dir)
    original._base_url = "https://file-browser.invalid"
    original._username = "user"
    response = requests.Response()
    response.status_code = 200
    response._content_consumed = True
    monkeypatch.setattr(response, "iter_content", lambda **kwargs: iter([b"old database"]))
    monkeypatch.setattr(original, "_request", lambda *args, **kwargs: response)
    cached = original.download_db("metrics_same.db")
    original.close()
    client = FileBrowserClient(cache_dir)
    client._base_url = "https://file-browser.invalid"
    client._username = "user"
    source = tmp_path / "new.db"
    source.write_bytes(b"new database")
    statuses_iter = iter(statuses)

    def request(method, *args, **kwargs):
        response = requests.Response()
        response.status_code = next(statuses_iter) if method == "POST" else 200
        response._content_consumed = True
        monkeypatch.setattr(response, "iter_content", lambda **kwargs: iter([source.read_bytes()]))
        return response

    monkeypatch.setattr(client, "_request", request)
    try:
        if statuses[-1] == 500:
            with pytest.raises(requests.HTTPError):
                client.upload_file(source, "metrics_same.db")
            assert cached.read_bytes() == b"old database"
        else:
            client.upload_file(source, "metrics_same.db")
            assert not cached.exists()
            assert client.download_db("metrics_same.db") == cached
            assert cached.read_bytes() == b"new database"
    finally:
        client.close()


@pytest.mark.parametrize("filename", ["same.db", "相同 %?#.db", "literal%2F.db"])
def test_cache_and_successful_overwrite_use_exact_remote_resource(tmp_path, monkeypatch, filename):
    client = FileBrowserClient(tmp_path / "cache")
    client._base_url = "https://file-browser.invalid"
    client._username = "user"
    bodies = {f"a/{filename}": b"database a", f"b/{filename}": b"database b"}
    reads = []

    def request(method, path, **kwargs):
        parsed = urlsplit(path)
        assert not parsed.query and not parsed.fragment
        resource = unquote(parsed.path.split("/", 3)[3])
        if method == "POST":
            bodies[resource] = b"".join(kwargs["data_factory"]())
        else:
            reads.append(resource)
        response = requests.Response()
        response.status_code = 200
        response._content_consumed = True
        monkeypatch.setattr(response, "iter_content", lambda **kwargs: iter([bodies[resource]]))
        return response

    monkeypatch.setattr(client, "_request", request)
    try:
        first = client.download_db(f"/a/{filename}")
        second = client.download_db(f"/b/{filename}")
        assert first != second
        assert first.read_bytes() == b"database a"
        assert second.read_bytes() == b"database b"
        assert client.download_db(f"a/{filename}") == first
        assert client.download_db(f"a//./{filename}") == first
        assert reads == [f"a/{filename}", f"b/{filename}"]
        source = tmp_path / "upload.db"
        source.write_bytes(b"replacement a")
        client.upload_file(source, f"/a/{filename}")
        assert not first.exists()
        assert second.read_bytes() == b"database b"
        assert client.download_db(f"a/{filename}").read_bytes() == b"replacement a"
        response = client.stream_video(f"/a/{filename}", "bytes=0-2")
        assert b"".join(response.iter_content()) == b"replacement a"
        response.close()
    finally:
        client.close()


def test_unidentified_basename_cache_is_not_trusted(tmp_path, monkeypatch):
    import hashlib

    client = FileBrowserClient(tmp_path)
    client._base_url = "https://file-browser.invalid"
    client._username = "user"
    namespace = hashlib.sha256(f"{client._base_url}\0{client._username}".encode()).hexdigest()
    legacy = tmp_path / namespace / "same.db"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"unidentified old database")
    response = requests.Response()
    response.status_code = 200
    response._content_consumed = True
    monkeypatch.setattr(response, "iter_content", lambda **kwargs: iter([b"requested database"]))
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: response)
    try:
        cached = client.download_db("/a/same.db")
        assert cached != legacy
        assert cached.read_bytes() == b"requested database"
    finally:
        client.close()


@pytest.mark.parametrize("remote_path", ["", "/", "../same.db", "a/../same.db", "a\\same.db", "a/\0same.db"])
def test_resource_paths_reject_traversal_before_cache_or_http(tmp_path, monkeypatch, remote_path):
    client = FileBrowserClient(tmp_path / "cache")
    client._base_url = "https://file-browser.invalid"
    calls = []
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: calls.append(args))
    source = tmp_path / "upload.db"
    source.write_bytes(b"database")
    try:
        with pytest.raises(ValueError, match="resource path"):
            client.download_db(remote_path)
        with pytest.raises(ValueError, match="resource path"):
            client.upload_file(source, remote_path)
        assert calls == []
        assert not (tmp_path / "cache").exists()
    finally:
        client.close()


def test_failed_reconfiguration_does_not_reuse_previous_site_token(tmp_path, monkeypatch):
    client = FileBrowserClient(tmp_path)
    client._base_url = "http://old.invalid"
    client._token = "old-site-token"
    client._token_expires = float("inf")
    monkeypatch.setattr(client, "_do_login_locked", lambda: False)

    assert not client.configure("http://new.invalid", "user", "password")
    assert not client.is_authenticated()
    assert client._token is None


@pytest.mark.parametrize("failure", [None, "status", "body"])
def test_download_closes_response_and_removes_partial_file(tmp_path, monkeypatch, failure):
    client = FileBrowserClient(tmp_path)
    response = requests.Response()
    response.status_code = 500 if failure == "status" else 200
    response._content_consumed = True
    closed = []

    def chunks(**kwargs):
        yield b"database"
        if failure == "body":
            raise requests.ConnectionError("body interrupted")

    monkeypatch.setattr(response, "iter_content", chunks)
    monkeypatch.setattr(response, "close", lambda: closed.append(True))
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: response)
    if failure:
        with pytest.raises(requests.RequestException):
            client.download_db("metrics_test.db")
        assert not list(tmp_path.rglob("*.db"))
        assert not list(tmp_path.rglob("*.tmp"))
    else:
        assert client.download_db("metrics_test.db").read_bytes() == b"database"
    assert closed == [True]


def test_video_stream_closes_response_after_http_error(tmp_path, monkeypatch):
    client = FileBrowserClient(tmp_path)
    response = requests.Response()
    response.status_code = 500
    response._content_consumed = True
    closed = []
    monkeypatch.setattr(response, "close", lambda: closed.append(True))
    monkeypatch.setattr(client, "_request", lambda *args, **kwargs: response)
    with pytest.raises(requests.HTTPError):
        client.stream_video("video_test.mp4")
    assert closed == [True]


def test_database_cache_is_scoped_to_server_and_account(tmp_path, monkeypatch):
    client = FileBrowserClient(tmp_path)
    downloaded = []
    monkeypatch.setattr(client, "_do_login_locked", lambda: True)
    monkeypatch.setattr(client, "_start_heartbeat", lambda: None)

    def request(*args, **kwargs):
        body = f"{client._base_url}|{client._username}".encode()
        downloaded.append(body)
        response = requests.Response()
        response.status_code = 200
        response._content_consumed = True
        monkeypatch.setattr(response, "iter_content", lambda **kwargs: iter([body]))
        return response

    monkeypatch.setattr(client, "_request", request)
    paths = []
    for url, username in (("https://first.invalid", "alice"), ("https://second.invalid", "alice"), ("https://second.invalid", "bob")):
        assert client.configure(url, username, "secret-password")
        path = client.download_db("metrics_same.db")
        paths.append(path)
        assert path.read_bytes() == f"{url}|{username}".encode()
        assert "secret-password" not in str(path)
        assert username not in str(path.relative_to(tmp_path))
    assert len(set(paths)) == 3
    assert len(downloaded) == 3
    assert client.configure("https://first.invalid/", "alice", "new-password")
    assert client.download_db("metrics_same.db") == paths[0]
    assert len(downloaded) == 3
    upload = tmp_path / "upload.db"
    upload.write_bytes(b"replacement database")
    client.upload_file(upload, "metrics_same.db")
    assert not paths[0].exists()
    assert paths[1].read_bytes() == b"https://second.invalid|alice"
    assert paths[2].read_bytes() == b"https://second.invalid|bob"


def test_site_change_waits_for_download_to_keep_cache_ownership(tmp_path, monkeypatch):
    client = FileBrowserClient(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    changing_site = threading.Event()
    results = []
    errors = []
    monkeypatch.setattr(client, "_do_login_locked", lambda: True)
    monkeypatch.setattr(client, "_start_heartbeat", lambda: None)
    client.configure("https://first.invalid", "alice", "password")

    def request(*args, **kwargs):
        body = client._base_url.encode()
        response = requests.Response()
        response.status_code = 200
        response._content_consumed = True

        def chunks(**kwargs):
            entered.set()
            assert release.wait(2.0)
            yield body

        monkeypatch.setattr(response, "iter_content", chunks)
        return response

    monkeypatch.setattr(client, "_request", request)

    def download():
        try:
            results.append(client.download_db("metrics_same.db"))
        except Exception as exc:
            errors.append(exc)

    def change_site():
        changing_site.set()
        client.configure("https://second.invalid", "alice", "password")

    downloader = threading.Thread(target=download)
    reconfigure = threading.Thread(target=change_site)
    downloader.start()
    try:
        assert entered.wait(2.0)
        reconfigure.start()
        assert changing_site.wait(2.0)
    finally:
        release.set()
        downloader.join(timeout=2.0)
        if reconfigure.ident is not None:
            reconfigure.join(timeout=2.0)
    assert not downloader.is_alive() and not reconfigure.is_alive()
    assert not errors
    assert results[0].read_bytes() == b"https://first.invalid"
    second = client.download_db("metrics_same.db")
    assert second != results[0]
    assert second.read_bytes() == b"https://second.invalid"


def test_site_change_waits_for_upload_retry_and_cache_invalidation(tmp_path, monkeypatch):
    client = FileBrowserClient(tmp_path / "cache")
    monkeypatch.setattr(client, "_do_login_locked", lambda: True)
    monkeypatch.setattr(client, "_start_heartbeat", lambda: None)
    client.configure("https://first.invalid", "alice", "password")
    original_cache = client._cached_db_path("metrics_same.db")
    original_cache.parent.mkdir(parents=True)
    original_cache.write_bytes(b"old database")
    source = tmp_path / "upload.db"
    source.write_bytes(b"replacement database")
    entered = threading.Event()
    release = threading.Event()
    changing = threading.Event()
    changed = threading.Event()
    calls = []
    errors = []

    def request(*args, **kwargs):
        calls.append(client._base_url)
        if len(calls) == 1:
            entered.set()
            assert release.wait(2.0)
        response = requests.Response()
        response.status_code = 409 if len(calls) == 1 else 200
        response._content_consumed = True
        return response

    def upload():
        try:
            client.upload_file(source, "metrics_same.db")
        except Exception as exc:
            errors.append(exc)

    def configure():
        changing.set()
        client.configure("https://second.invalid", "alice", "password")
        changed.set()

    monkeypatch.setattr(client, "_request", request)
    uploader = threading.Thread(target=upload)
    reconfigure = threading.Thread(target=configure)
    uploader.start()
    try:
        assert entered.wait(1.0)
        reconfigure.start()
        assert changing.wait(1.0)
        assert not changed.wait(0.02)
    finally:
        release.set()
        uploader.join(timeout=2.0)
        if reconfigure.ident is not None:
            reconfigure.join(timeout=2.0)
        client.close()
    assert not uploader.is_alive() and not reconfigure.is_alive()
    assert not errors
    assert calls == ["https://first.invalid", "https://first.invalid"]
    assert not original_cache.exists()
    assert changed.is_set()


def test_restarted_heartbeat_cannot_clear_previous_threads_stop_event(tmp_path, monkeypatch):
    client = FileBrowserClient(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    client._token = "test-token"
    client._base_url = "https://file-browser.invalid"
    refreshes = []

    def refresh():
        refreshes.append(True)
        if len(refreshes) == 1:
            entered.set()
            assert release.wait(3.0)

    monkeypatch.setattr(client, "_ensure_token", refresh)
    client._start_heartbeat()
    previous = client._heartbeat_thread
    try:
        assert entered.wait(2.0)
        client._stop_heartbeat()
        client._start_heartbeat()
        current = client._heartbeat_thread
        assert current is not previous
        release.set()
        previous.join(timeout=0.2)
        assert not previous.is_alive()
        assert current.is_alive()
    finally:
        release.set()
        client._stop_heartbeat()
        previous.join(timeout=2.0)


def test_close_is_terminal_idempotent_and_a_new_client_can_connect(tmp_path, monkeypatch):
    client = FileBrowserClient(tmp_path)
    closed = []
    monkeypatch.setattr(client._session, "close", lambda: closed.append(True))

    def login():
        client._token = "test-token"
        client._token_expires = float("inf")
        return True

    monkeypatch.setattr(client, "_do_login_locked", login)
    assert client.configure("https://file-browser.invalid", "user", "password")
    heartbeat = client._heartbeat_thread
    client.close()
    client.close()
    assert client.is_closed
    assert not client.is_authenticated()
    assert not heartbeat.is_alive()
    assert closed == [True]
    assert client.get_info() == {"base_url": None, "username": None}
    with pytest.raises(RuntimeError, match="closed"):
        client.configure("https://file-browser.invalid", "user", "password")
    with pytest.raises(RuntimeError, match="closed"):
        client._request("GET", "/api/resources/")
    replacement = FileBrowserClient(tmp_path)
    try:
        assert replacement._session is not client._session
        monkeypatch.setattr(replacement, "_do_login_locked", lambda: True)
        monkeypatch.setattr(replacement, "_start_heartbeat", lambda: None)
        assert replacement.configure("https://file-browser.invalid", "user", "password")
    finally:
        replacement.close()


def test_close_waits_for_inflight_http_before_closing_session(tmp_path, monkeypatch):
    client = FileBrowserClient(tmp_path)
    client._base_url = "https://file-browser.invalid"
    client._token_expires = float("inf")
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    events = []
    errors = []

    def request(*args, **kwargs):
        entered.set()
        assert release.wait(2.0)
        events.append("request-complete")
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"items":[]}'
        response._content_consumed = True
        return response

    monkeypatch.setattr(client._session, "request", request)
    monkeypatch.setattr(client._session, "close", lambda: events.append("session-close"))

    def invoke(action):
        try:
            action()
        except Exception as exc:
            errors.append(exc)

    operation = threading.Thread(target=invoke, args=(client.list_recordings,))
    cleanup = threading.Thread(target=lambda: (invoke(client.close), completed.set()))
    operation.start()
    try:
        assert entered.wait(2.0)
        cleanup.start()
        assert not completed.wait(0.02)
        assert "session-close" not in events
    finally:
        release.set()
        operation.join(timeout=2.0)
        if cleanup.ident is not None:
            cleanup.join(timeout=2.0)
    assert not errors
    assert events == ["request-complete", "session-close"]
    assert client.is_closed


def test_close_closes_active_stream_before_session(tmp_path, monkeypatch):
    client = FileBrowserClient(tmp_path)
    client._base_url = "https://file-browser.invalid"
    client._token_expires = float("inf")
    response = requests.Response()
    response.status_code = 200
    response._content_consumed = True
    events = []
    monkeypatch.setattr(response, "close", lambda: events.append("response-close"))
    monkeypatch.setattr(client._session, "request", lambda *args, **kwargs: response)
    monkeypatch.setattr(client._session, "close", lambda: events.append("session-close"))
    assert client.stream_video("video_test.mp4") is response
    client.close()
    assert events == ["response-close", "session-close"]


def test_close_attempts_all_resources_and_can_retry_after_a_stream_close_error(tmp_path, monkeypatch):
    client = FileBrowserClient(tmp_path)
    responses = [requests.Response(), requests.Response()]
    calls = [0, 0]
    sessions_closed = []
    for index, response in enumerate(responses):
        def close(index=index):
            calls[index] += 1
            if index == 0 and calls[index] == 1:
                raise OSError("stream close failed")

        monkeypatch.setattr(response, "close", close)
        client._active_streams.add(response)
    monkeypatch.setattr(client._session, "close", lambda: sessions_closed.append(True))
    client._base_url = "https://file-browser.invalid"
    client._username = "user"
    client._password = "password"
    with pytest.raises(OSError, match="stream close failed"):
        client.close()
    assert calls == [1, 1]
    assert sessions_closed == [True]
    assert client.get_info() == {"base_url": None, "username": None}
    assert client._password is None
    assert not client.is_closed
    client.close()
    assert calls == [2, 1]
    assert client.is_closed


def test_close_waits_for_a_previous_heartbeat_after_restart(tmp_path, monkeypatch):
    client = FileBrowserClient(tmp_path)
    client._token = "test-token"
    client._base_url = "https://file-browser.invalid"
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    refreshes = []

    def refresh():
        refreshes.append(True)
        if len(refreshes) == 1:
            entered.set()
            assert release.wait(3.0)

    monkeypatch.setattr(client, "_ensure_token", refresh)
    client._start_heartbeat()
    previous = client._heartbeat_thread
    cleanup = threading.Thread(target=lambda: (client.close(), completed.set()))
    try:
        assert entered.wait(1.0)
        client._stop_heartbeat()
        client._start_heartbeat()
        current = client._heartbeat_thread
        assert previous is not current
        cleanup.start()
        assert not completed.wait(0.02)
    finally:
        release.set()
        previous.join(timeout=2.0)
        current.join(timeout=2.0)
        if cleanup.ident is not None:
            cleanup.join(timeout=2.0)
    assert completed.is_set()
    assert not previous.is_alive()
    assert not current.is_alive()
    assert client.is_closed
