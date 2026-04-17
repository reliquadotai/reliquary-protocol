"""Tests for canonical JSON serialization helpers.

These are the bytes every Reliquary content-addressable hash is
computed over. Any accidental change breaks both subnets simultaneously.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from reliquary_protocol.canonicalization import (
    CANONICAL_SEPARATORS,
    canonical_bytes,
    sha256_canonical,
    sha256_json,
    stable_json_dumps,
)


def test_separators_are_compact_no_whitespace() -> None:
    assert CANONICAL_SEPARATORS == (",", ":")


def test_stable_json_dumps_sorts_keys() -> None:
    assert stable_json_dumps({"z": 1, "a": 2}) == '{"a":2,"z":1}'


def test_stable_json_dumps_nested_sort() -> None:
    out = stable_json_dumps({"outer": {"z": 1, "a": 2}})
    assert out == '{"outer":{"a":2,"z":1}}'


def test_stable_json_dumps_ensure_ascii_escapes_unicode() -> None:
    assert "\\u00e9" in stable_json_dumps({"greeting": "héllo"})


def test_stable_json_dumps_insertion_order_invariant() -> None:
    a = stable_json_dumps({"a": 1, "b": 2, "c": 3})
    b = stable_json_dumps({"c": 3, "b": 2, "a": 1})
    assert a == b


def test_stable_json_dumps_empty_dict_and_list() -> None:
    assert stable_json_dumps({}) == "{}"
    assert stable_json_dumps([]) == "[]"


def test_stable_json_dumps_compact_separators() -> None:
    out = stable_json_dumps({"a": [1, 2, 3]})
    assert ", " not in out and ": " not in out


def test_canonical_bytes_is_utf8_of_dumps() -> None:
    payload = {"greeting": "héllo"}
    assert canonical_bytes(payload) == stable_json_dumps(payload).encode("utf-8")


def test_sha256_json_is_64_hex_lowercase() -> None:
    digest = sha256_json({"k": "v"})
    assert len(digest) == 64
    assert all(ch in "0123456789abcdef" for ch in digest)


def test_sha256_json_matches_manual_sha_over_canonical_bytes() -> None:
    payload = {"a": 1, "b": 2}
    manual = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert sha256_json(payload) == manual


def test_sha256_json_insertion_order_invariant() -> None:
    assert sha256_json({"a": 1, "b": 2}) == sha256_json({"b": 2, "a": 1})


def test_sha256_json_changes_with_payload() -> None:
    assert sha256_json({"x": 1}) != sha256_json({"x": 2})


def test_sha256_canonical_returns_32_bytes() -> None:
    digest = sha256_canonical({"k": "v"})
    assert len(digest) == 32
    assert isinstance(digest, bytes)


def test_sha256_canonical_matches_sha256_json_hex() -> None:
    digest_hex = sha256_json({"z": 9})
    digest_bytes = sha256_canonical({"z": 9})
    assert digest_bytes.hex() == digest_hex


def test_rejects_non_json_types() -> None:
    with pytest.raises(TypeError):
        stable_json_dumps({"bytes": b"raw"})


def test_numeric_and_boolean_emission() -> None:
    out = stable_json_dumps({"flag": True, "count": 0})
    assert out == '{"count":0,"flag":true}'
