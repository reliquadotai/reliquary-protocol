"""HMAC-SHA256 sign/verify helpers + label-escaping utilities.

Used by both subnets for verdict signing (mesh), trace signing
(distillation), and any other integrity-bound artifact. Single source
of truth so the two subnets never diverge on byte-layout.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from .canonicalization import canonical_bytes


@dataclass(frozen=True)
class SigningKey:
    """Opaque wrapper around a signing secret.

    Using a frozen dataclass rather than raw str keeps the key material
    out of naive ``repr`` surfaces and documents intent.
    """

    signer_id: str
    secret: str

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"SigningKey(signer_id={self.signer_id!r}, secret=<redacted>)"


def hmac_sign(message: bytes, secret: str) -> str:
    """Return the HMAC-SHA256 hex digest of ``message`` under ``secret``.

    ``message`` should typically be the output of
    :func:`reliquary_protocol.canonicalization.canonical_bytes` on the
    artifact payload so the signature binds to a deterministic byte form.
    """
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def hmac_verify(message: bytes, signature: str, secret: str) -> bool:
    """Constant-time HMAC verification.

    Returns True iff ``signature`` equals ``hmac_sign(message, secret)``.
    Comparison uses :func:`hmac.compare_digest` to avoid timing leaks.
    """
    expected = hmac_sign(message, secret)
    return hmac.compare_digest(signature, expected)


def sign_canonical(payload: object, secret: str) -> str:
    """Convenience: sign the canonical-bytes form of ``payload``."""
    return hmac_sign(canonical_bytes(payload), secret)


def verify_canonical(payload: object, signature: str, secret: str) -> bool:
    """Convenience: verify ``signature`` against ``canonical_bytes(payload)``."""
    return hmac_verify(canonical_bytes(payload), signature, secret)


def escape_label_value(value: str) -> str:
    """Escape a Prometheus label value per the 0.0.4 exposition spec.

    Backslashes → ``\\\\``, newlines → ``\\n``, double-quotes → ``\\"``.
    Any other character passes through verbatim. Centralized here so
    both subnets emit byte-identical escapes.
    """
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


__all__ = [
    "SigningKey",
    "escape_label_value",
    "hmac_sign",
    "hmac_verify",
    "sign_canonical",
    "verify_canonical",
]
