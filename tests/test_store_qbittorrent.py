from __future__ import annotations

import json

import pytest

from bookmallow.store import qbittorrent as qb


class Script:
    """Scripted transport: list of (status, body); records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, data, headers):
        self.calls.append((method, url, data, dict(headers)))
        return self.responses.pop(0)


INFO = [{"hash": "abc", "name": "Book", "progress": 0.5, "state": "downloading", "content_path": "/downloads/bookmallow/Book",
         "size": 1000, "downloaded": 500}]


@pytest.mark.parametrize("response", [(200, "Ok."), (204, "")])
def test_login_sets_headers_and_accepts_ok(response):
    t = Script([response])
    c = qb.QbtClient("http://qbt:8080/", "admin", "pw", transport=t)
    c.login()
    method, url, data, headers = t.calls[0]
    assert (method, url) == ("POST", "http://qbt:8080/api/v2/auth/login")
    assert data == {"username": "admin", "password": "pw"}
    assert headers["Referer"] == "http://qbt:8080" and headers["Origin"] == "http://qbt:8080"


@pytest.mark.parametrize("response", [(200, "Fails."), (403, "Forbidden"), (401, "Unauthorized")])
def test_login_refused(response):
    c = qb.QbtClient("http://qbt:8080", "admin", "pw", transport=Script([response]))
    with pytest.raises(qb.QbtError) as exc:
        c.login()
    assert exc.value.code == "qbt_auth"


def test_add_find_info_delete_category():
    t = Script([(200, "Ok."), (200, json.dumps(INFO)), (200, json.dumps(INFO)), (200, "[]"), (200, ""), (409, "exists"), (200, "")])
    c = qb.QbtClient("http://qbt:8080", "u", "p", transport=t)
    c.add("magnet:?xt=1", "bookmallow", ["bookmallow", "job-1234"])
    assert t.calls[0][2] == {"urls": "magnet:?xt=1", "category": "bookmallow", "tags": "bookmallow,job-1234"}
    found = c.find_by_tag("job-1234")
    assert t.calls[1][0] == "GET" and t.calls[1][1] == "http://qbt:8080/api/v2/torrents/info?tag=job-1234"
    assert found.hash == "abc" and found.progress == 0.5 and found.content_path == "/downloads/bookmallow/Book"
    assert c.info("abc").name == "Book"
    assert t.calls[2][1] == "http://qbt:8080/api/v2/torrents/info?hashes=abc"
    assert c.info("zzz") is None
    c.delete("abc")
    assert t.calls[4][1] == "http://qbt:8080/api/v2/torrents/delete" and t.calls[4][2] == {"hashes": "abc", "deleteFiles": "true"}
    c.ensure_category("bookmallow")  # 409 = already exists → fine
    c.ensure_category("other")


def test_add_failure_and_http_errors():
    c = qb.QbtClient("http://qbt:8080", "u", "p", transport=Script([(200, "Fails."), (500, "boom")]))
    with pytest.raises(qb.QbtError) as exc:
        c.add("magnet:?xt=1", "cat", [])
    assert exc.value.code == "torrent_add"
    with pytest.raises(qb.QbtError) as exc:
        c.info("abc")
    assert exc.value.code == "provider_error"


def test_default_transport_uses_cookie_jar_opener(monkeypatch):
    class Resp:
        status = 200

        def read(self):
            return b"Ok."

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = {}

    def fake_open(self, req, timeout=None):
        seen["url"], seen["data"], seen["timeout"] = req.full_url, req.data, timeout
        return Resp()

    monkeypatch.setattr(qb.urllib.request.OpenerDirector, "open", fake_open)
    c = qb.QbtClient("http://qbt:8080", "u", "p", timeout=3.0)
    c.login()
    assert seen["url"] == "http://qbt:8080/api/v2/auth/login" and seen["timeout"] == 3.0
    assert b"username=u" in seen["data"] and b"password=p" in seen["data"]


def test_expired_session_logs_in_again_and_retries_once():
    t = Script([(403, "Forbidden"), (200, "Ok."), (200, json.dumps(INFO))])
    c = qb.QbtClient("http://qbt:8080", "u", "p", transport=t)
    assert c.info("abc").hash == "abc"
    assert [call[1] for call in t.calls] == ["http://qbt:8080/api/v2/torrents/info?hashes=abc",
                                             "http://qbt:8080/api/v2/auth/login",
                                             "http://qbt:8080/api/v2/torrents/info?hashes=abc"]


def test_retry_keeps_method_and_data():
    t = Script([(401, ""), (204, ""), (200, "")])
    c = qb.QbtClient("http://qbt:8080", "u", "p", transport=t)
    c.delete("abc")
    assert t.calls[2][0] == "POST" and t.calls[2][2] == {"hashes": "abc", "deleteFiles": "true"}


def test_still_refused_after_relogin_is_qbt_auth():
    t = Script([(403, "Forbidden"), (200, "Ok."), (403, "Forbidden")])
    c = qb.QbtClient("http://qbt:8080", "u", "p", transport=t)
    with pytest.raises(qb.QbtError) as exc:
        c.info("abc")
    assert exc.value.code == "qbt_auth" and len(t.calls) == 3


def test_relogin_refused_is_qbt_auth_without_loop():
    t = Script([(403, "Forbidden"), (403, "Forbidden")])
    c = qb.QbtClient("http://qbt:8080", "u", "p", transport=t)
    with pytest.raises(qb.QbtError) as exc:
        c.info("abc")
    assert exc.value.code == "qbt_auth" and len(t.calls) == 2


@pytest.mark.parametrize("body", ['{"hash": "abc"}', '"x"', "3"])
def test_infos_rejects_non_list_json(body):
    c = qb.QbtClient("http://qbt:8080", "u", "p", transport=Script([(200, body)]))
    with pytest.raises(qb.QbtError) as exc:
        c.info("abc")
    assert exc.value.code == "provider_error"
