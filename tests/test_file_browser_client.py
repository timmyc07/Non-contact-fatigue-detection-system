from pathlib import Path

import requests

from gui.file_browser_client import FileBrowserClient


def test_upload_recreates_body_after_authentication_retry(tmp_path: Path, monkeypatch):
    path = tmp_path / "metrics.db"
    path.write_bytes(b"complete database body")
    client = FileBrowserClient()
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


def test_failed_reconfiguration_does_not_reuse_previous_site_token(monkeypatch):
    client = FileBrowserClient()
    client._base_url = "http://old.invalid"
    client._token = "old-site-token"
    client._token_expires = float("inf")
    monkeypatch.setattr(client, "_do_login_locked", lambda: False)

    assert not client.configure("http://new.invalid", "user", "password")
    assert not client.is_authenticated()
    assert client._token is None
