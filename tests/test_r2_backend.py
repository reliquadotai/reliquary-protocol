"""Unit tests for R2ObjectBackend.

These tests do NOT hit the real R2 — they stub ``urllib.request.urlopen``
so the Protocol surface (put/get/list/delete + key validation + 404 semantics)
is exercised without creds. A separate live smoke test in
``scripts/smoke_r2.py`` drives the real bucket.
"""

from __future__ import annotations

import io
import json
from typing import Iterable
from unittest import mock

import pytest

from reliquary_protocol.storage.r2 import (
    R2BackendError,
    R2ConfigError,
    R2ObjectBackend,
    R2RequestError,
    _validate_key,
)


def _backend() -> R2ObjectBackend:
    return R2ObjectBackend(
        account_id="acct-abc",
        bucket="reliquary",
        cf_api_token="cfat_test",
        public_url=None,
    )


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _fake_urlopen(responses: Iterable[_FakeResponse | Exception]):
    """Returns an urlopen-like callable that serves queued responses."""
    queue = list(responses)
    calls: list[tuple[str, str, bytes | None]] = []

    def opener(req, timeout=None):  # noqa: ARG001 - mimics urlopen sig
        url = req.full_url if hasattr(req, "full_url") else str(req)
        method = getattr(req, "method", "GET") or "GET"
        data = req.data if hasattr(req, "data") else None
        calls.append((method, url, data))
        if not queue:
            raise AssertionError(f"unexpected extra call: {method} {url}")
        nxt = queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    opener.calls = calls  # type: ignore[attr-defined]
    return opener


def test_from_env_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("RELIQUARY_R2_ACCOUNT_ID", "RELIQUARY_R2_BUCKET", "RELIQUARY_R2_CF_API_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(R2ConfigError):
        R2ObjectBackend.from_env()


def test_from_env_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELIQUARY_R2_ACCOUNT_ID", "acct-xyz")
    monkeypatch.setenv("RELIQUARY_R2_BUCKET", "reliquary")
    monkeypatch.setenv("RELIQUARY_R2_CF_API_TOKEN", "cfat_abc")
    monkeypatch.setenv("RELIQUARY_R2_PUBLIC_URL", "https://pub-x.r2.dev")
    backend = R2ObjectBackend.from_env()
    assert backend.account_id == "acct-xyz"
    assert backend.bucket == "reliquary"
    assert backend.public_url == "https://pub-x.r2.dev"


def test_init_rejects_empty_inputs() -> None:
    with pytest.raises(R2ConfigError):
        R2ObjectBackend(account_id="", bucket="b", cf_api_token="t")


def test_put_sends_authorization_and_bytes() -> None:
    backend = _backend()
    opener = _fake_urlopen([_FakeResponse(b'{"success":true}')])
    with mock.patch("urllib.request.urlopen", opener):
        backend.put("verdicts/0/hotkey/completion.json", b"{}")
    method, url, data = opener.calls[0]  # type: ignore[attr-defined]
    assert method == "PUT"
    assert url.endswith("/verdicts/0/hotkey/completion.json")
    assert data == b"{}"


def test_get_returns_bytes_on_200() -> None:
    backend = _backend()
    opener = _fake_urlopen([_FakeResponse(b"hello")])
    with mock.patch("urllib.request.urlopen", opener):
        out = backend.get("any/key.bin")
    assert out == b"hello"


def test_get_returns_none_on_404() -> None:
    backend = _backend()
    import urllib.error

    err = urllib.error.HTTPError(
        url="https://api.cloudflare.com/...", code=404, msg="Not Found",
        hdrs=None, fp=io.BytesIO(b""),  # type: ignore[arg-type]
    )
    opener = _fake_urlopen([err])
    with mock.patch("urllib.request.urlopen", opener):
        assert backend.get("missing.bin") is None


def test_get_raises_on_non_404_error() -> None:
    backend = _backend()
    import urllib.error

    err = urllib.error.HTTPError(
        url="...", code=500, msg="Internal", hdrs=None, fp=io.BytesIO(b"boom"),  # type: ignore[arg-type]
    )
    opener = _fake_urlopen([err])
    with mock.patch("urllib.request.urlopen", opener):
        with pytest.raises(R2RequestError) as exc:
            backend.get("any.bin")
    assert exc.value.status == 500


def test_list_paginates_until_empty_cursor() -> None:
    backend = _backend()
    page1 = {
        "success": True,
        "result": [{"key": "a.json"}, {"key": "b.json"}],
        "result_info": {"cursor": "CURSOR-1"},
    }
    page2 = {
        "success": True,
        "result": [{"key": "c.json"}],
        "result_info": {},
    }
    opener = _fake_urlopen(
        [_FakeResponse(json.dumps(page1).encode()), _FakeResponse(json.dumps(page2).encode())],
    )
    with mock.patch("urllib.request.urlopen", opener):
        keys = backend.list("verdicts/")
    assert keys == ["a.json", "b.json", "c.json"]


def test_delete_404_is_silent() -> None:
    backend = _backend()
    import urllib.error

    err = urllib.error.HTTPError(
        url="...", code=404, msg="Not Found", hdrs=None, fp=io.BytesIO(b""),  # type: ignore[arg-type]
    )
    opener = _fake_urlopen([err])
    with mock.patch("urllib.request.urlopen", opener):
        backend.delete("already-gone")  # should not raise


def test_delete_non_404_raises() -> None:
    backend = _backend()
    import urllib.error

    err = urllib.error.HTTPError(
        url="...", code=500, msg="Internal", hdrs=None, fp=io.BytesIO(b""),  # type: ignore[arg-type]
    )
    opener = _fake_urlopen([err])
    with mock.patch("urllib.request.urlopen", opener):
        with pytest.raises(R2RequestError):
            backend.delete("any")


def test_public_url_preferred_when_set() -> None:
    backend = R2ObjectBackend(
        account_id="acct", bucket="reliquary", cf_api_token="cfat",
        public_url="https://pub.example/reliquary",
    )
    # Public fetch returns bytes → API is never called.
    opener = _fake_urlopen([_FakeResponse(b"public-hit")])
    with mock.patch("urllib.request.urlopen", opener):
        assert backend.get("k") == b"public-hit"
    # Exactly one call (to the public URL) — no API fallback.
    assert len(opener.calls) == 1  # type: ignore[attr-defined]
    assert opener.calls[0][1].startswith("https://pub.example/reliquary/")  # type: ignore[attr-defined]


def test_public_url_falls_back_to_api_on_miss() -> None:
    backend = R2ObjectBackend(
        account_id="acct", bucket="reliquary", cf_api_token="cfat",
        public_url="https://pub.example/reliquary",
    )
    import urllib.error

    public_err = urllib.error.HTTPError(
        url="...", code=404, msg="Not Found", hdrs=None, fp=io.BytesIO(b""),  # type: ignore[arg-type]
    )
    api_hit = _FakeResponse(b"api-hit")
    opener = _fake_urlopen([public_err, api_hit])
    with mock.patch("urllib.request.urlopen", opener):
        assert backend.get("k") == b"api-hit"
    assert len(opener.calls) == 2  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "bad",
    ["", "/abs/path", "../escape", "with\x00null", "..", "seg/../other"],
)
def test_rejects_unsafe_keys(bad: str) -> None:
    backend = _backend()
    with pytest.raises(ValueError):
        backend.put(bad, b"x")


def test_validate_key_accepts_valid_paths() -> None:
    _validate_key("verdicts/1/hotkey/abc.json")
    _validate_key("checkpoints/run-1/window_42/manifest.json")


def test_network_error_wraps_as_backend_error() -> None:
    backend = _backend()
    import urllib.error

    url_err = urllib.error.URLError("connection refused")
    opener = _fake_urlopen([url_err])
    with mock.patch("urllib.request.urlopen", opener):
        with pytest.raises(R2BackendError):
            backend.put("k", b"x")
