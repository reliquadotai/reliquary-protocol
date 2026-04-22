"""Canonical serialization helpers — the authoritative version.

Every content-addressable hash in either subnet MUST go through these
helpers. The byte format is pinned: ``sort_keys=True``,
``separators=(",", ":")``, ``ensure_ascii=True``, UTF-8 encoding.

Changes here must bump ``reliquary_protocol.VERSION`` and coordinate
across both subnets — see the upgrade runbook in the package README.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

CANONICAL_SEPARATORS: tuple[str, str] = (",", ":")


def stable_json_dumps(data: Any) -> str:
    """Return the canonical JSON text form of ``data``.

    Invariants pinned by tests:
    - dict keys sorted lexicographically at every nesting depth.
    - No whitespace between tokens (``","`` and ``":"`` separators).
    - Non-ASCII characters escaped (``\\uXXXX``) for wire determinism.
    """
    return json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=True,
        separators=CANONICAL_SEPARATORS,
    )


def canonical_bytes(data: Any) -> bytes:
    """UTF-8 bytes of :func:`stable_json_dumps`. Use this for signing."""
    return stable_json_dumps(data).encode("utf-8")


def sha256_json(data: Any) -> str:
    """SHA-256 hex digest over ``stable_json_dumps(data).encode('utf-8')``.

    Output is a 64-char lowercase hex string suitable for use as an
    artifact id, rollout randomness seed, or merkle leaf.
    """
    return hashlib.sha256(canonical_bytes(data)).hexdigest()


def sha256_canonical(data: Any) -> bytes:
    """Same as :func:`sha256_json` but returns raw 32 bytes."""
    return hashlib.sha256(canonical_bytes(data)).digest()


__all__ = [
    "CANONICAL_SEPARATORS",
    "canonical_bytes",
    "sha256_canonical",
    "sha256_json",
    "stable_json_dumps",
]
