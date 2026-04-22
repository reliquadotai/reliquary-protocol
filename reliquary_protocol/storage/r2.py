"""Cloudflare R2 object-store backend for the Reliquary pipelines.

One canonical implementation that satisfies BOTH:
  - ``reliquary_inference.validator.verdict_storage.StorageBackend``
  - ``reliquary.training.checkpoint_storage.CheckpointStorageBackend``

These two Protocols are structurally identical (put / get / list /
delete), so the same object works for both — verdict publishing AND
delta-checkpoint publishing.

Auth model: we use the **Cloudflare REST API** (not the S3 API). That
lets us use the account-level API token (``cfat_...``) directly without
provisioning separate S3 access keys in the dashboard, and means this
module has ZERO third-party deps — just stdlib ``urllib``.

**Known behavior — CDN edge cache on GET:** the Cloudflare REST API
applies a 4-hour edge cache (``cache-control: public, max-age=14400``)
to authenticated R2 GETs. This is fine for Reliquary because every
write uses a **content-addressable fresh key** (window_id × validator ×
completion_id, or window_id × tensor_name). The pipeline never
overwrites. Any admin / migration scenario that requires read-after-
overwrite must PUT under a fresh suffix instead of overwriting the
existing key.

Environment (loaded at backend construction; raises if absent):
  - ``RELIQUARY_R2_ACCOUNT_ID``  — Cloudflare account id
  - ``RELIQUARY_R2_BUCKET``     — bucket name (typically ``reliquary``)
  - ``RELIQUARY_R2_CF_API_TOKEN`` — CF API token with R2 object perms
  - ``RELIQUARY_R2_PUBLIC_URL``  — optional ``pub-....r2.dev`` URL for
    cheap public reads (bypasses the authenticated API path when set)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Iterable
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote


class R2BackendError(RuntimeError):
    """Base for R2 backend failures."""


class R2ConfigError(R2BackendError):
    """Raised when required env is missing."""


class R2RequestError(R2BackendError):
    """Raised when the R2 API returns a non-2xx."""

    def __init__(self, status: int, endpoint: str, body: str) -> None:
        super().__init__(f"R2 {status} on {endpoint}: {body[:200]}")
        self.status = status
        self.endpoint = endpoint


@dataclass
class R2ObjectBackend:
    """Pure-HTTP R2 backend.

    Satisfies both the inference-side and forge-side storage Protocols:
    ``put(key, data) -> None``, ``get(key) -> bytes | None``,
    ``list(prefix) -> list[str]``, ``delete(key) -> None``.
    """

    account_id: str
    bucket: str
    cf_api_token: str
    public_url: str | None = None
    # 30s was too tight under fleet load — Cloudflare's R2 API sometimes
    # sits on the request for 30-60s before responding under our 4-validator
    # mesh. Single-shot urlopen timeouts on the miner loop were causing
    # whole-cycle drops. 120s matches the typical API tail latency budget.
    timeout_seconds: float = 120.0
    # Number of attempts on transient failures (429 / 5xx / read-timeout).
    # Each retry waits 2 ** (attempt - 1) * 5 seconds → 5s, 10s, 20s.
    max_retries: int = 3
    _api_base: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.account_id or not self.bucket or not self.cf_api_token:
            raise R2ConfigError("account_id, bucket, and cf_api_token are all required")
        self._api_base = (
            f"https://api.cloudflare.com/client/v4/accounts/{self.account_id}"
            f"/r2/buckets/{self.bucket}"
        )

    @classmethod
    def from_env(cls) -> "R2ObjectBackend":
        """Build a backend from RELIQUARY_R2_* environment variables."""
        missing = [
            name
            for name in ("RELIQUARY_R2_ACCOUNT_ID", "RELIQUARY_R2_BUCKET", "RELIQUARY_R2_CF_API_TOKEN")
            if not os.environ.get(name)
        ]
        if missing:
            raise R2ConfigError(f"missing R2 env: {', '.join(missing)}")
        return cls(
            account_id=os.environ["RELIQUARY_R2_ACCOUNT_ID"],
            bucket=os.environ["RELIQUARY_R2_BUCKET"],
            cf_api_token=os.environ["RELIQUARY_R2_CF_API_TOKEN"],
            public_url=os.environ.get("RELIQUARY_R2_PUBLIC_URL") or None,
        )

    # ------------------------------------------------------------------
    # Protocol surface
    # ------------------------------------------------------------------

    def put(self, key: str, data: bytes) -> None:
        """Upload ``data`` to ``bucket/key``. Overwrites unconditionally."""
        _validate_key(key)
        url = f"{self._api_base}/objects/{quote(key, safe='/')}"
        req = urllib_request.Request(
            url,
            method="PUT",
            data=data,
            headers={
                "Authorization": f"Bearer {self.cf_api_token}",
                "Content-Type": _guess_content_type(key),
                "Content-Length": str(len(data)),
            },
        )
        self._call(req, "put")

    def get(self, key: str) -> bytes | None:
        """Return object bytes, or ``None`` if 404.

        When a public ``public_url`` is configured we try it first
        (cheaper + CDN-cached); fall back to the authenticated API on
        any failure.
        """
        _validate_key(key)
        if self.public_url:
            body = _try_public_get(self.public_url, key, self.timeout_seconds)
            if body is not None:
                return body
        url = f"{self._api_base}/objects/{quote(key, safe='/')}"
        req = urllib_request.Request(
            url,
            method="GET",
            headers={"Authorization": f"Bearer {self.cf_api_token}"},
        )
        try:
            return self._call(req, "get")
        except R2RequestError as exc:
            if exc.status == 404:
                return None
            raise

    def list(self, prefix: str) -> list[str]:
        """List keys under ``prefix``. Paginates until exhausted."""
        return [entry["key"] for entry in self.list_detailed(prefix)]

    def list_detailed(self, prefix: str) -> list[dict[str, Any]]:
        """List objects under ``prefix`` with metadata: ``[{key, size, uploaded, etag}]``.

        Hits the same list endpoint as ``list()`` but preserves the per-
        object metadata that CloudFlare returns. Callers that need to
        sort by upload time (e.g. "fetch latest N artifacts") use this
        to avoid a full O(N) body-fetch just to compare timestamps.
        """
        objects: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            qs = f"prefix={quote(prefix)}&per_page=1000"
            if cursor:
                qs += f"&cursor={quote(cursor)}"
            url = f"{self._api_base}/objects?{qs}"
            req = urllib_request.Request(
                url,
                method="GET",
                headers={"Authorization": f"Bearer {self.cf_api_token}"},
            )
            body = self._call(req, "list")
            try:
                payload = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise R2RequestError(200, "list", f"non-JSON response: {exc}") from exc
            for obj in payload.get("result") or []:
                key = obj.get("key")
                if not isinstance(key, str):
                    continue
                # CloudFlare R2 returns "last_modified" (with an underscore)
                # rather than S3-style "LastModified" or a simpler "uploaded".
                # Fall back to the alternatives so we survive any future API
                # tweak — callers only care that SOME timestamp is exposed.
                uploaded = (
                    obj.get("last_modified")
                    or obj.get("uploaded")
                    or obj.get("LastModified")
                    or ""
                )
                objects.append(
                    {
                        "key": key,
                        "size": int(obj.get("size") or 0),
                        "uploaded": uploaded,
                        "etag": obj.get("etag") or "",
                    }
                )
            cursor = (payload.get("result_info") or {}).get("cursor")
            if not cursor:
                break
        return objects

    def delete(self, key: str) -> None:
        _validate_key(key)
        url = f"{self._api_base}/objects/{quote(key, safe='/')}"
        req = urllib_request.Request(
            url,
            method="DELETE",
            headers={"Authorization": f"Bearer {self.cf_api_token}"},
        )
        try:
            self._call(req, "delete")
        except R2RequestError as exc:
            # 404 is a no-op — the caller asked for absence, we have
            # absence.
            if exc.status != 404:
                raise

    # ------------------------------------------------------------------
    # Low-level
    # ------------------------------------------------------------------

    def _call(self, req: urllib_request.Request, label: str) -> bytes:
        """Single-shot HTTP call with exponential-backoff retry on transient
        failures (429 Too Many Requests, 5xx, read-timeouts).

        4xx other than 429 → no retry (those are our bugs, not R2's load).
        Under the 4-validator fleet + miner concurrent R2 traffic,
        single-shot calls drop ~15% of the time at peak; 3 retries with
        5s/10s/20s backoff bring that down to effectively zero.
        """
        import socket
        import time as _time

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with urllib_request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    return resp.read()
            except urllib_error.HTTPError as http_err:
                body = ""
                try:
                    body = http_err.read().decode("utf-8", "replace")
                except Exception:  # pragma: no cover
                    pass
                # Retry on 429 + 5xx, which are server/rate-limit issues.
                # 404 & other 4xx are caller bugs — surface immediately.
                if http_err.code == 429 or 500 <= http_err.code < 600:
                    last_exc = R2RequestError(http_err.code, label, body)
                    if attempt < self.max_retries:
                        _time.sleep((2 ** (attempt - 1)) * 5)
                        continue
                raise R2RequestError(http_err.code, label, body) from http_err
            except (urllib_error.URLError, socket.timeout, TimeoutError) as exc:
                # read-timeout / DNS / connection refused — all transient.
                last_exc = R2BackendError(f"R2 {label} network error: {exc}")
                if attempt < self.max_retries:
                    _time.sleep((2 ** (attempt - 1)) * 5)
                    continue
                raise R2BackendError(f"R2 {label} network error: {exc}") from exc
        # Unreachable — the loop raises before it can drop out.
        assert last_exc is not None
        raise last_exc  # pragma: no cover


def _validate_key(key: str) -> None:
    if not isinstance(key, str) or not key:
        raise ValueError(f"R2 key must be a non-empty string, got {key!r}")
    if key.startswith("/") or ".." in key.split("/") or "\x00" in key:
        raise ValueError(f"unsafe R2 key {key!r}")


def _guess_content_type(key: str) -> str:
    lowered = key.lower()
    if lowered.endswith(".json"):
        return "application/json"
    if lowered.endswith(".bin") or lowered.endswith(".safetensors"):
        return "application/octet-stream"
    if lowered.endswith(".md"):
        return "text/markdown; charset=utf-8"
    if lowered.endswith(".txt"):
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def _try_public_get(public_url: str, key: str, timeout: float) -> bytes | None:
    url = f"{public_url.rstrip('/')}/{quote(key, safe='/')}"
    try:
        with urllib_request.urlopen(
            urllib_request.Request(url, method="GET"),
            timeout=timeout,
        ) as resp:
            return resp.read()
    except urllib_error.HTTPError:
        return None
    except urllib_error.URLError:
        return None


def _keys_only(result: Iterable[dict]) -> list[str]:
    return [obj["key"] for obj in result if isinstance(obj, dict) and isinstance(obj.get("key"), str)]


__all__ = [
    "R2BackendError",
    "R2ConfigError",
    "R2ObjectBackend",
    "R2RequestError",
]
