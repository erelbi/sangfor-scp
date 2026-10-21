"""SCPClient core behaviour: EC2 signing, URLs, responses/errors, pagination,
task polling and token login. No network: HTTP goes through a fake adapter."""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from requests.adapters import BaseAdapter

from sangfor_scp import SCPClient
from sangfor_scp.auth import ec2 as ec2_module
from sangfor_scp.auth import token as token_module
from sangfor_scp.auth.ec2 import EC2Signer
from sangfor_scp.exceptions import (
    SCPAuthError,
    SCPBadRequestError,
    SCPError,
    SCPNotFoundError,
    SCPRateLimitError,
    SCPServerError,
    SCPTaskError,
    SCPTimeoutError,
)
from sangfor_scp.resources import tasks as tasks_module

HOST = "https://scp.example.test"


# ------------------------------------------------------------------ #
# Fake HTTP layer                                                     #
# ------------------------------------------------------------------ #

class FakeAdapter(BaseAdapter):
    """Answers every request with handler(prepared_request) -> (status, body)."""

    def __init__(self, handler: Callable[[requests.PreparedRequest], Any]):
        super().__init__()
        self.handler = handler
        self.requests: List[requests.PreparedRequest] = []

    def send(self, request, **kwargs):
        self.requests.append(request)
        status, body = self.handler(request)
        resp = requests.Response()
        resp.status_code = status
        resp.request = request
        resp.url = request.url
        if isinstance(body, (dict, list)):
            resp._content = json.dumps(body).encode()
            resp.headers["Content-Type"] = "application/json"
        else:
            resp._content = (body or "").encode()
        return resp

    def close(self):
        pass


def make_client(handler) -> "tuple[SCPClient, FakeAdapter]":
    client = SCPClient(host=HOST + "/", access_key="AK", secret_key="SK", region="r1")
    adapter = FakeAdapter(handler)
    client._session.mount("https://", adapter)
    return client, adapter


def ok(data: Any) -> "tuple[int, dict]":
    return 200, {"errcode": "", "message": "", "data": data}


# ------------------------------------------------------------------ #
# EC2 (AWS4-HMAC-SHA256) signing                                      #
# ------------------------------------------------------------------ #

FIXED_NOW = _dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=_dt.timezone.utc)


@pytest.fixture
def frozen_time(monkeypatch):
    class FrozenDatetime(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return FIXED_NOW

    class FakeDatetimeModule:
        datetime = FrozenDatetime
        timezone = _dt.timezone

    monkeypatch.setattr(ec2_module, "datetime", FakeDatetimeModule)


def reference_signature(secret: str, method: str, path: str, body: bytes) -> str:
    """Independent SigV4 derivation (x-amz-date is the only signed header)."""
    amzdate, datestamp = "20260102T030405Z", "20260102"
    canonical = "\n".join([
        method, path, "", f"x-amz-date:{amzdate}\n", "x-amz-date",
        hashlib.sha256(body).hexdigest(),
    ])
    scope = f"{datestamp}/r1/open-api/aws4_request"
    to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amzdate, scope,
        hashlib.sha256(canonical.encode()).hexdigest(),
    ])
    key = ("AWS4" + secret).encode()
    for part in (datestamp, "r1", "open-api", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    return hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()


def prepared(method: str, url: str, body: Optional[dict] = None) -> requests.PreparedRequest:
    return requests.Request(method, url, json=body).prepare()


def test_ec2_signature_matches_reference(frozen_time):
    signer = EC2Signer("AK", "SK", region="r1")
    body = {"name": "vm1"}
    req = signer(prepared("POST", HOST + "/janus/20180725/servers?x=1", body))

    assert req.headers["X-Amz-Date"] == "20260102T030405Z"
    expected = reference_signature("SK", "POST", "/janus/20180725/servers", req.body)
    assert req.headers["Authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AK/20260102/r1/open-api/aws4_request, "
        f"SignedHeaders=x-amz-date, Signature={expected}"
    )


def test_ec2_signature_known_answer(frozen_time):
    req = EC2Signer("AK", "SK", region="r1")(prepared("GET", HOST + "/janus/20180725/servers"))
    assert req.headers["Authorization"].endswith(
        "Signature=" + reference_signature("SK", "GET", "/janus/20180725/servers", b"")
    )
    # Pinned value: guards against accidental changes to the canonical request
    assert req.headers["Authorization"].endswith(
        "Signature=dde898bf9430aca989e4f86e88e71492e0e4f350a6b3fd6d71fcf871958b8782"
    )


def test_ec2_signature_depends_on_body_and_secret(frozen_time):
    url = HOST + "/janus/20180725/servers"
    sig = lambda sk, body: EC2Signer("AK", sk, region="r1")(  # noqa: E731
        prepared("POST", url, body)).headers["Authorization"]
    assert sig("SK", {"a": 1}) != sig("SK", {"a": 2})
    assert sig("SK", {"a": 1}) != sig("SK2", {"a": 1})


# ------------------------------------------------------------------ #
# Client construction and URLs                                        #
# ------------------------------------------------------------------ #

def test_client_requires_credentials():
    with pytest.raises(SCPAuthError):
        SCPClient(host=HOST)


def test_url_building():
    client, _ = make_client(lambda r: ok({}))
    assert client.host == HOST
    assert client.url("/servers") == HOST + "/janus/20180725/servers"
    assert client.url("/janus/20210225/x") == HOST + "/janus/20210225/x"


def test_resources_are_attached():
    client, _ = make_client(lambda r: ok({}))
    for name in ("servers", "networks", "images", "volumes", "eips", "tasks",
                 "alarms", "metrics", "system", "tenants", "resource_pools"):
        assert getattr(client, name)._client is client


# ------------------------------------------------------------------ #
# Requests and responses                                              #
# ------------------------------------------------------------------ #

def test_request_is_signed_and_unwraps_data():
    client, adapter = make_client(lambda r: ok({"id": "vm-1"}))
    assert client.request("GET", "/servers/vm-1") == {"id": "vm-1"}

    req = adapter.requests[0]
    assert req.method == "GET"
    assert req.url == HOST + "/janus/20180725/servers/vm-1"
    assert req.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AK/")
    assert "X-Amz-Date" in req.headers


def test_none_params_are_dropped():
    client, adapter = make_client(lambda r: ok([]))
    client.request("GET", "/servers", params={"az_id": "az1", "name": None})
    query = parse_qs(urlparse(adapter.requests[0].url).query)
    assert query == {"az_id": ["az1"]}


def test_idempotent_post_gets_client_token():
    client, adapter = make_client(lambda r: ok({"task_id": "t1"}))
    client.request("POST", "/servers", json={"name": "a"}, idempotent=True)
    client.request("POST", "/servers", json={"name": "a"}, idempotent=True)
    client.request("POST", "/servers", json={"name": "a"})

    tokens = [r.headers.get("X-Client-Token") for r in adapter.requests]
    assert tokens[0] and tokens[1] and tokens[0] != tokens[1]
    assert tokens[2] is None
    assert json.loads(adapter.requests[0].body) == {"name": "a"}


def test_response_without_wrapper_and_204():
    responses = iter([(200, {"total": 3}), (204, "")])
    client, _ = make_client(lambda r: next(responses))
    assert client.request("GET", "/x") == {"total": 3}
    assert client.request("DELETE", "/x") is None


@pytest.mark.parametrize("status, exc", [
    (400, SCPBadRequestError),
    (401, SCPAuthError),
    (404, SCPNotFoundError),
    (429, SCPRateLimitError),
    (500, SCPServerError),
    (502, SCPError),
])
def test_http_errors_map_to_exceptions(status, exc):
    body = {"errcode": "0x01020003", "message": "boom"}
    client, _ = make_client(lambda r: (status, body))
    with pytest.raises(exc) as info:
        client.request("GET", "/servers/x")
    err = info.value
    assert err.status_code == status
    assert err.errcode == "0x01020003"
    assert err.message == "boom"
    assert err.response == body


def test_non_json_error_body():
    client, _ = make_client(lambda r: (500, "<html>gateway</html>"))
    with pytest.raises(SCPServerError) as info:
        client.request("GET", "/x")
    assert info.value.message == "<html>gateway</html>"


# ------------------------------------------------------------------ #
# Pagination                                                          #
# ------------------------------------------------------------------ #

def test_list_all_follows_next_page_num():
    pages = {
        "0": {"data": [{"id": 1}, {"id": 2}], "next_page_num": "1", "total_size": 3},
        "1": {"data": [{"id": 3}], "next_page_num": "", "total_size": 3},
    }

    def handler(r):
        query = parse_qs(urlparse(r.url).query)
        assert query["page_size"] == ["2"]
        assert query["az_id"] == ["az1"]
        return ok(pages[query["page_num"][0]])

    client, adapter = make_client(handler)
    ids = [s["id"] for s in client.servers.list_all(page_size=2, az_id="az1")]
    assert ids == [1, 2, 3]
    assert len(adapter.requests) == 2


def test_count_reads_total_size_from_first_page():
    client, adapter = make_client(lambda r: ok({"data": [{}], "next_page_num": "1",
                                                 "total_size": 42}))
    assert client.servers.count() == 42
    assert parse_qs(urlparse(adapter.requests[0].url).query)["page_size"] == ["1"]


# ------------------------------------------------------------------ #
# Task polling                                                        #
# ------------------------------------------------------------------ #

@pytest.fixture
def no_sleep(monkeypatch):
    clock = {"now": 0.0}
    monkeypatch.setattr(tasks_module.time, "sleep",
                        lambda s: clock.__setitem__("now", clock["now"] + s))
    monkeypatch.setattr(tasks_module.time, "monotonic", lambda: clock["now"])
    return clock


def task_client(states: List[Any]):
    seq = iter(states)

    def handler(r):
        item = next(seq)
        if isinstance(item, Exception):
            raise item
        return item

    return make_client(handler)


def test_wait_returns_on_finish_and_reports_progress(no_sleep):
    client, adapter = task_client([
        ok({"status": "waiting", "progress": -2}),
        ok({"status": "doing", "progress": 40}),
        ok({"status": "finish", "progress": 100, "task_id": "t1"}),
    ])
    seen = []
    result = client.tasks.wait("t1", poll_interval=1, progress_callback=seen.append)
    assert result["task_id"] == "t1"
    assert [s["progress"] for s in seen] == [-2, 40, 100]
    assert adapter.requests[0].url == HOST + "/janus/20180725/tasks/t1"


def test_wait_retries_transient_errors(no_sleep):
    client, _ = task_client([
        requests.ConnectionError("reset"),
        (500, {"message": "busy"}),
        ok({"status": "finish", "progress": 100}),
    ])
    assert client.tasks.wait("t1", poll_interval=1)["status"] == "finish"


def test_wait_raises_on_failure(no_sleep):
    client, _ = task_client([ok({"status": "failure", "progress": -1,
                                 "description": "no space"})])
    with pytest.raises(SCPTaskError) as info:
        client.tasks.wait("t1")
    assert "no space" in info.value.message
    assert info.value.task_id == "t1"


def test_wait_raises_on_cancel(no_sleep):
    client, _ = task_client([ok({"status": "canceled", "progress": 10})])
    with pytest.raises(SCPTaskError):
        client.tasks.wait("t1")


def test_wait_times_out(no_sleep):
    client, _ = task_client([ok({"status": "doing", "progress": 5})] * 10)
    with pytest.raises(SCPTimeoutError) as info:
        client.tasks.wait("t1", timeout=6, poll_interval=3)
    assert info.value.timeout == 6
    assert "doing" in info.value.message


# ------------------------------------------------------------------ #
# Token authentication                                                #
# ------------------------------------------------------------------ #

class _Resp:
    def __init__(self, status: int, body: Dict[str, Any]):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def test_token_login_flow(monkeypatch):
    calls: Dict[str, Any] = {}

    def fake_get(url, **kw):
        calls.setdefault("get", []).append(url)
        return _Resp(200, {"data": {"public_key": "ABCDEF\\n"}})

    def fake_post(url, json=None, headers=None, **kw):
        calls["post"] = (url, json, headers)
        return _Resp(200, {"data": {"access": {"token": {"id": "tok-1"}}}})

    monkeypatch.setattr(token_module.requests, "get", fake_get)
    monkeypatch.setattr(token_module.requests, "post", fake_post)
    monkeypatch.setattr(token_module, "encrypt_password",
                        lambda pw, mod: f"enc({pw},{mod})")

    client = SCPClient(host=HOST, username="admin", password="secret")
    adapter = FakeAdapter(lambda r: ok({"id": "vm-1"}))
    client._session.mount("https://", adapter)

    assert calls["get"] == [HOST + "/janus/v2/public-key"]
    url, body, headers = calls["post"]
    assert url == HOST + "/janus/authenticate"
    assert body["auth"]["passwordCredentials"] == {
        "username": "admin", "password": "enc(secret,ABCDEF)"}
    assert headers["Cookie"].startswith("aCMPAuthToken=")

    client.request("GET", "/servers/vm-1")
    assert adapter.requests[0].headers["Authorization"] == "Token tok-1"
    assert not client._token_auth.is_expired()


def test_token_login_failure(monkeypatch):
    monkeypatch.setattr(token_module.requests, "get",
                        lambda url, **kw: _Resp(200, {"data": {"public_key": "AB"}}))
    monkeypatch.setattr(token_module.requests, "post",
                        lambda url, **kw: _Resp(401, {"message": "bad password"}))
    monkeypatch.setattr(token_module, "encrypt_password", lambda pw, mod: "x")
    with pytest.raises(SCPAuthError) as info:
        SCPClient(host=HOST, username="admin", password="wrong")
    assert info.value.status_code == 401


def test_encrypt_password_roundtrip():
    crypto = None
    for name in ("Crypto", "Cryptodome"):
        try:
            crypto = __import__(name + ".PublicKey.RSA", fromlist=["RSA"])
            cipher_mod = __import__(name + ".Cipher.PKCS1_v1_5", fromlist=["new"])
            break
        except ImportError:
            continue
    if crypto is None:
        pytest.skip("pycryptodome / pycryptodomex not installed")

    key = crypto.generate(1024)
    modulus = format(key.n, "x")
    encrypted = token_module.encrypt_password("p@ss", modulus)
    plain = cipher_mod.new(key).decrypt(bytes.fromhex(encrypted), None)
    assert plain == b"p@ss"
