"""Web 服務擁有 File Browser thread 與 HTTP session 的收尾契約。"""

from __future__ import annotations

import threading
import time

import pytest
import requests

from gui import web_server
from gui.file_browser_client import FileBrowserClient
from gui.web_server import MetricsBuffer, PlaybackManager, WebServerThread


def _client_factory(monkeypatch):
    clients = []
    closed = []

    def factory():
        client = FileBrowserClient()
        close_session = client._session.close

        def login():
            client._token = "synthetic-token"
            client._token_expires = float("inf")
            return True

        def close():
            closed.append((client, threading.current_thread().name))
            close_session()

        monkeypatch.setattr(client, "_do_login_locked", login)
        monkeypatch.setattr(client._session, "close", close)
        clients.append(client)
        return client

    monkeypatch.setattr(web_server, "FileBrowserClient", factory)
    return clients, closed


def _wait_for_port(server):
    deadline = time.monotonic() + 2.0
    while server.port == 0 and server.is_alive() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert server.port != 0


@pytest.mark.parametrize("state", ["running", "not-started", "bind-failed"])
def test_stop_closes_file_browser_in_its_background_owner(tmp_path, monkeypatch, state):
    clients, closed = _client_factory(monkeypatch)
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0)
    client = clients[0]
    client.configure("https://file-browser.invalid", "user", "password")
    heartbeat = client._heartbeat_thread
    if state == "bind-failed":
        monkeypatch.setattr(web_server, "make_server", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("bind failed")))
    if state != "not-started":
        server.start()
        if state == "running":
            _wait_for_port(server)
    try:
        assert server.stop(join_timeout=2.0)
        assert server.stop(join_timeout=2.0)
        assert server.is_finalized
        assert client.is_closed
        assert not heartbeat.is_alive()
        assert not client.is_authenticated()
        assert len(closed) == 1
        assert closed[0][1] != threading.current_thread().name
    finally:
        server.stop(join_timeout=2.0)
        if server.ident is not None:
            server.join(timeout=2.0)
        client.logout()


def test_restart_gets_a_new_file_browser_session(tmp_path, monkeypatch):
    clients, closed = _client_factory(monkeypatch)
    for _ in range(2):
        server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0)
        client = clients[-1]
        assert not client.is_authenticated()
        client.configure("https://file-browser.invalid", "user", "password")
        server.start()
        _wait_for_port(server)
        assert server.stop(join_timeout=2.0)
        server.join(timeout=2.0)
    assert len(closed) == 2
    assert clients[0]._session is not clients[1]._session
    assert all(client.is_closed for client in clients)


def test_request_stop_does_not_wait_for_an_inflight_file_browser_http_call(tmp_path, monkeypatch):
    clients, closed = _client_factory(monkeypatch)
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0)
    client = clients[0]
    client.configure("https://file-browser.invalid", "user", "password")
    entered = threading.Event()
    release = threading.Event()
    results = []
    errors = []

    def request(*args, **kwargs):
        entered.set()
        assert release.wait(2.0)
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"items":[]}'
        response._content_consumed = True
        return response

    monkeypatch.setattr(client._session, "request", request)
    server.start()
    _wait_for_port(server)

    def read():
        try:
            results.append(requests.get(f"http://127.0.0.1:{server.port}/api/fb/recordings", timeout=3))
        except Exception as exc:
            errors.append(exc)

    reader = threading.Thread(target=read)
    reader.start()
    try:
        assert entered.wait(2.0)
        server.request_stop()
        assert not server.is_finalized
        assert not server.stop(join_timeout=0.01)
        assert not closed
    finally:
        release.set()
        reader.join(timeout=3.0)
        server.stop(join_timeout=2.0)
        server.join(timeout=2.0)
        client.logout()
    assert not errors
    assert results[0].status_code == 200
    assert server.is_finalized
    assert len(closed) == 1


def test_not_started_server_only_creates_one_cleanup_owner(tmp_path, monkeypatch):
    clients, closed = _client_factory(monkeypatch)
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0)
    entered = threading.Event()
    release = threading.Event()
    close_client = clients[0].close
    calls = []

    def close():
        calls.append(True)
        entered.set()
        assert release.wait(2.0)
        close_client()

    monkeypatch.setattr(clients[0], "close", close)
    server.request_stop()
    try:
        assert entered.wait(1.0)
        owner = server._cleanup_thread
        for _ in range(10):
            server.request_stop()
        assert server._cleanup_thread is owner
        assert calls == [True]
        assert not server.is_finalized
    finally:
        release.set()
        assert server.stop(join_timeout=None)
    assert len(closed) == 1
    server.start()
    server.join(timeout=2.0)
    assert server.port == 0
    assert server.is_finalized
    assert len(closed) == 1


def test_failed_session_close_is_not_finalized_and_can_retry(tmp_path, monkeypatch):
    clients, closed = _client_factory(monkeypatch)
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0)
    close_session = clients[0]._session.close
    attempts = []

    def close():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("session close failed")
        close_session()

    monkeypatch.setattr(clients[0]._session, "close", close)
    try:
        assert not server.stop(join_timeout=2.0)
        assert not server.is_finalized
        server._cleanup_thread.join(timeout=2.0)
        assert server.stop(join_timeout=2.0)
        assert server.is_finalized
        assert clients[0].is_closed
        assert len(closed) == 1
    finally:
        server.stop(join_timeout=2.0)


@pytest.mark.parametrize("started", [False, True])
def test_failed_finalization_is_reported_only_after_its_owner_exits(tmp_path, monkeypatch, started):
    clients, _closed = _client_factory(monkeypatch)
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0)
    close_session = clients[0]._session.close
    finalize = server._finalize
    entered = threading.Event()
    release = threading.Event()
    attempts = []

    def close():
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("session close failed")
        close_session()

    def delayed_finalize():
        finalize()
        if len(attempts) == 1:
            entered.set()
            assert release.wait(2.0)

    monkeypatch.setattr(clients[0]._session, "close", close)
    monkeypatch.setattr(server, "_finalize", delayed_finalize)
    if started:
        server.start()
        _wait_for_port(server)
    server.request_stop()
    try:
        assert entered.wait(1.0)
        assert not server.finalization_failed
        assert not server.is_finalized
        server.request_stop()
        assert attempts == [True]
    finally:
        release.set()
        owner = server if started else server._cleanup_thread
        owner.join(timeout=2.0)
    assert server.finalization_failed
    assert server.stop(join_timeout=2.0)
    assert not server.finalization_failed
    assert server.is_finalized


@pytest.mark.parametrize("started", [False, True])
def test_stop_none_joins_its_owner_after_finalization_event(tmp_path, monkeypatch, started):
    _client_factory(monkeypatch)
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0)
    finalize = server._finalize
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    results = []

    def delayed_finalize():
        finalize()
        entered.set()
        assert release.wait(2.0)

    def stop():
        results.append(server.stop(join_timeout=None))
        completed.set()

    monkeypatch.setattr(server, "_finalize", delayed_finalize)
    if started:
        server.start()
        _wait_for_port(server)
    server.request_stop()
    waiter = threading.Thread(target=stop)
    try:
        assert entered.wait(1.0)
        assert server.is_finalized
        waiter.start()
        assert not completed.wait(0.02)
    finally:
        release.set()
        owner = server if started else server._cleanup_thread
        owner.join(timeout=2.0)
        if waiter.ident is not None:
            waiter.join(timeout=2.0)
    assert not owner.is_alive()
    assert completed.is_set()
    assert results == [True]


def test_stop_timeout_budget_is_shared_between_event_and_owner_join(tmp_path, monkeypatch):
    from types import SimpleNamespace

    _client_factory(monkeypatch)
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0)
    now = [40.0]
    joined = []
    owner_alive = [True]

    def wait(timeout):
        assert timeout == 5.0
        now[0] += 3.0
        return True

    def join(timeout):
        joined.append(timeout)
        owner_alive[0] = False

    monkeypatch.setattr(web_server.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(server, "request_stop", lambda: None)
    monkeypatch.setattr(server, "_stopped_event", SimpleNamespace(wait=wait, is_set=lambda: True))
    monkeypatch.setattr(server, "_cleanup_thread", SimpleNamespace(ident=1, join=join, is_alive=lambda: owner_alive[0]))
    try:
        assert server.stop(join_timeout=5.0)
        assert joined == [2.0]
    finally:
        server.app.extensions["ncfd_file_browser_client"].close()


@pytest.mark.parametrize("started", [False, True])
def test_stop_from_its_owner_never_waits_for_itself(tmp_path, monkeypatch, started):
    clients, _closed = _client_factory(monkeypatch)
    server = WebServerThread(MetricsBuffer(), PlaybackManager(tmp_path), host="127.0.0.1", port=0)
    close_client = clients[0].close
    wait = server._stopped_event.wait
    results = []
    errors = []

    def checked_wait(timeout):
        if threading.current_thread() in (server, server._cleanup_thread):
            raise RuntimeError("owner must not wait for itself")
        return wait(timeout)

    def close():
        try:
            results.append(server.stop(join_timeout=None))
        except RuntimeError as exc:
            errors.append(exc)
        close_client()

    monkeypatch.setattr(server._stopped_event, "wait", checked_wait)
    monkeypatch.setattr(clients[0], "close", close)
    if started:
        server.start()
        _wait_for_port(server)
    assert server.stop(join_timeout=2.0)
    owner = server if started else server._cleanup_thread
    owner.join(timeout=2.0)
    assert not errors
    assert results == [False]
