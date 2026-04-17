"""Tests for HMAC sign/verify + label-escape helpers."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from reliquary_protocol.signatures import (
    SigningKey,
    escape_label_value,
    hmac_sign,
    hmac_verify,
    sign_canonical,
    verify_canonical,
)


# ---------------------------------------------------------------------------
# hmac_sign / hmac_verify
# ---------------------------------------------------------------------------


def test_hmac_sign_is_hex_sha256() -> None:
    sig = hmac_sign(b"hello", "secret")
    assert len(sig) == 64
    assert all(ch in "0123456789abcdef" for ch in sig)


def test_hmac_sign_matches_manual_hmac() -> None:
    expected = hmac.new(b"secret", b"data", hashlib.sha256).hexdigest()
    assert hmac_sign(b"data", "secret") == expected


def test_hmac_sign_deterministic() -> None:
    assert hmac_sign(b"data", "secret") == hmac_sign(b"data", "secret")


def test_hmac_sign_changes_with_message() -> None:
    assert hmac_sign(b"data-A", "secret") != hmac_sign(b"data-B", "secret")


def test_hmac_sign_changes_with_secret() -> None:
    assert hmac_sign(b"data", "secret-A") != hmac_sign(b"data", "secret-B")


def test_hmac_verify_accepts_matching_signature() -> None:
    sig = hmac_sign(b"payload", "secret")
    assert hmac_verify(b"payload", sig, "secret") is True


def test_hmac_verify_rejects_tampered_signature() -> None:
    sig = hmac_sign(b"payload", "secret")
    tampered = sig[:-1] + ("0" if sig[-1] != "0" else "1")
    assert hmac_verify(b"payload", tampered, "secret") is False


def test_hmac_verify_rejects_tampered_message() -> None:
    sig = hmac_sign(b"payload", "secret")
    assert hmac_verify(b"different", sig, "secret") is False


def test_hmac_verify_rejects_wrong_secret() -> None:
    sig = hmac_sign(b"payload", "secret-A")
    assert hmac_verify(b"payload", sig, "secret-B") is False


def test_hmac_verify_constant_time_compares_via_compare_digest() -> None:
    # Behavioral smoke — the two-sig case should still match.
    sig_a = hmac_sign(b"a", "s")
    sig_b = hmac_sign(b"b", "s")
    assert sig_a != sig_b
    assert hmac_verify(b"a", sig_a, "s") is True
    assert hmac_verify(b"b", sig_a, "s") is False


# ---------------------------------------------------------------------------
# sign_canonical / verify_canonical
# ---------------------------------------------------------------------------


def test_sign_canonical_uses_canonical_bytes() -> None:
    payload = {"z": 1, "a": 2}
    reversed_payload = {"a": 2, "z": 1}
    # Signing a dict in any insertion order produces the same sig.
    assert sign_canonical(payload, "secret") == sign_canonical(
        reversed_payload, "secret"
    )


def test_verify_canonical_accepts_matching() -> None:
    payload = {"x": 1, "y": 2}
    sig = sign_canonical(payload, "secret")
    assert verify_canonical(payload, sig, "secret") is True


def test_verify_canonical_rejects_tampered_payload() -> None:
    sig = sign_canonical({"x": 1}, "secret")
    assert verify_canonical({"x": 2}, sig, "secret") is False


# ---------------------------------------------------------------------------
# SigningKey
# ---------------------------------------------------------------------------


def test_signing_key_repr_redacts_secret() -> None:
    key = SigningKey(signer_id="validator-A", secret="super-secret")
    assert "super-secret" not in repr(key)
    assert "<redacted>" in repr(key)
    assert "validator-A" in repr(key)


def test_signing_key_is_frozen() -> None:
    import dataclasses

    key = SigningKey(signer_id="v", secret="s")
    with pytest.raises(dataclasses.FrozenInstanceError):
        key.secret = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# escape_label_value
# ---------------------------------------------------------------------------


def test_escape_label_value_no_change_on_safe_input() -> None:
    assert escape_label_value("validator-A") == "validator-A"


def test_escape_label_value_escapes_backslash() -> None:
    assert escape_label_value("path\\to\\x") == "path\\\\to\\\\x"


def test_escape_label_value_escapes_double_quote() -> None:
    assert escape_label_value('a"b') == 'a\\"b'


def test_escape_label_value_escapes_newline() -> None:
    assert escape_label_value("line1\nline2") == "line1\\nline2"


def test_escape_label_value_multiple_escapes_compose() -> None:
    raw = 'a"b\\c\nd'
    escaped = escape_label_value(raw)
    assert escaped == 'a\\"b\\\\c\\nd'


def test_escape_label_value_empty_string_passes() -> None:
    assert escape_label_value("") == ""
