"""Cross-subnet bridge artifacts — closed-loop flywheel.

Three content-addressable artifacts cross the SN81 (Ledger) ↔ SN3
(Forge) boundary:

- :class:`RolloutBundle` — a finalized Ledger window packaged for Forge
  consumption (manifest + task batch + scorecard + accepted completions
  + mesh-aggregated verdicts).
- :class:`CheckpointAttestation` — Forge's provenance signature binding
  a promoted checkpoint to the exact Ledger rollout windows that fed
  the training cycle.
- :class:`PolicyCommitment` — the pointer-level artifact that tells
  Ledger "swap to this checkpoint at this window." In production this
  sits onchain (via ``commit_policy_metadata``); during staging /
  testnet it sits at a well-known R2 prefix and is read the same way.

All three:

- Are frozen dataclasses with explicit typing, serializable via
  :func:`to_dict` into JSON-stable shape.
- Canonicalize through :mod:`reliquary_protocol.canonicalization` so
  both subnets derive byte-identical hashes.
- Carry a :data:`BRIDGE_VERSION` tag so a shape change triggers a
  loud reject instead of a silent misparse.

Envelope signing uses the existing HMAC helpers in
:mod:`reliquary_protocol.signatures` during staging. Swapping in
substrate-SDK signatures is a call-site change — the
:class:`BridgeSigner` / :class:`BridgeVerifier` Protocols keep the
envelope shape stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

from .canonicalization import canonical_bytes, sha256_json, stable_json_dumps
from .signatures import hmac_sign, hmac_verify


BRIDGE_VERSION: str = "1"

_ENVELOPE_VERSION: str = "1"

#: The three artifact types that cross the bridge. Kept as string
#: literals so the value appears verbatim in JSON output — prevents
#: accidental collapse to an int or enum name.
ROLLOUT_BUNDLE_TYPE: str = "rollout_bundle"
CHECKPOINT_ATTESTATION_TYPE: str = "checkpoint_attestation"
POLICY_COMMITMENT_TYPE: str = "policy_commitment"


class BridgeError(Exception):
    """Base class for bridge-artifact errors."""


class BridgeVersionMismatch(BridgeError):
    """Raised when an artifact's ``version`` doesn't match the consumer's."""


class BridgeSchemaError(BridgeError):
    """Raised when required fields are missing or malformed."""


class BridgeSignatureError(BridgeError):
    """Raised when an envelope signature fails verification."""


# ---------------------------------------------------------------------------
# Signer / verifier protocols
# ---------------------------------------------------------------------------


class BridgeSigner(Protocol):
    """Opaque signer: maps canonical bytes → signature hex string."""

    signer_id: str

    def __call__(self, message: bytes) -> str:  # pragma: no cover - protocol
        ...


class BridgeVerifier(Protocol):
    """Opaque verifier: (signer_id, message, signature) → bool."""

    def __call__(
        self, signer_id: str, message: bytes, signature: str
    ) -> bool:  # pragma: no cover - protocol
        ...


@dataclass(frozen=True)
class HmacBridgeSigner:
    """Reference :class:`BridgeSigner` for HMAC keys.

    Production use is expected to replace this with a substrate-SDK
    signer; the Protocol shape is stable across backends.
    """

    signer_id: str
    secret: str

    def __call__(self, message: bytes) -> str:
        return hmac_sign(message, self.secret)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"HmacBridgeSigner(signer_id={self.signer_id!r}, secret=<redacted>)"


@dataclass(frozen=True)
class HmacBridgeVerifier:
    """Reference :class:`BridgeVerifier` for HMAC keys.

    Given a mapping from signer_id to secret, verifies an envelope
    signature using :func:`hmac_verify`. Unknown signer_ids return
    False rather than raising, so a caller can treat the return value
    as a simple authorization check.
    """

    secrets: Mapping[str, str]

    def __call__(self, signer_id: str, message: bytes, signature: str) -> bool:
        secret = self.secrets.get(signer_id)
        if secret is None:
            return False
        return hmac_verify(message, signature, secret)


# ---------------------------------------------------------------------------
# RolloutBundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RolloutBundle:
    """Finalized Ledger window artifact consumed by Forge.

    The shape is the canonical counterpart of the ``ImportedWindow``
    dataclass on the Forge side (:mod:`reliquary.inference_adapter`)
    so the Forge consumer can pick this up with zero translation.

    Tuples (not lists) are used for immutable sequence fields so the
    dataclass is cleanly frozen and hashable.
    """

    version: str
    netuid: int
    window_id: int
    window_range: tuple[int, int]
    manifest: Mapping[str, Any]
    task_batch: Mapping[str, Any]
    scorecard: Mapping[str, Any] | None
    completions: tuple[Mapping[str, Any], ...]
    verdicts: tuple[Mapping[str, Any], ...]
    producer_hotkey: str
    published_at: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-stable dict representation."""
        return {
            "version": self.version,
            "netuid": int(self.netuid),
            "window_id": int(self.window_id),
            "window_range": [int(self.window_range[0]), int(self.window_range[1])],
            "manifest": _freeze_mapping(self.manifest),
            "task_batch": _freeze_mapping(self.task_batch),
            "scorecard": (
                _freeze_mapping(self.scorecard) if self.scorecard is not None else None
            ),
            "completions": [_freeze_mapping(c) for c in self.completions],
            "verdicts": [_freeze_mapping(v) for v in self.verdicts],
            "producer_hotkey": self.producer_hotkey,
            "published_at": self.published_at,
        }

    def canonical_bytes(self) -> bytes:
        """Authoritative canonical byte form for signing / hashing."""
        return canonical_bytes(self.to_dict())

    def artifact_id(self) -> str:
        """Content-addressable 64-char hex id."""
        return sha256_json(self.to_dict())

    def storage_key(self) -> str:
        """R2 / local-filesystem key under which the bundle is written.

        Format: ``rollouts/<netuid>/<start>-<end>/<producer_hotkey>.json``.
        The window_range is used rather than window_id so a multi-window
        bundle (future batching) lands at a deterministic key without
        a scheme change.
        """
        start, end = self.window_range
        return (
            f"rollouts/{int(self.netuid)}/{int(start)}-{int(end)}/"
            f"{self.producer_hotkey}.json"
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RolloutBundle":
        _expect_version(data, "RolloutBundle")
        for field_name in (
            "netuid",
            "window_id",
            "window_range",
            "manifest",
            "task_batch",
            "completions",
            "verdicts",
            "producer_hotkey",
            "published_at",
        ):
            if field_name not in data:
                raise BridgeSchemaError(
                    f"RolloutBundle missing required field {field_name!r}"
                )
        wr = data["window_range"]
        if not (isinstance(wr, (list, tuple)) and len(wr) == 2):
            raise BridgeSchemaError(
                f"RolloutBundle.window_range must be a 2-tuple, got {wr!r}"
            )
        wr0, wr1 = int(wr[0]), int(wr[1])
        if wr0 > wr1:
            raise BridgeSchemaError(
                f"RolloutBundle.window_range is reversed: {wr0} > {wr1}"
            )
        completions = tuple(_freeze_mapping(c) for c in data["completions"])
        verdicts = tuple(_freeze_mapping(v) for v in data["verdicts"])
        scorecard = data.get("scorecard")
        return cls(
            version=str(data["version"]),
            netuid=int(data["netuid"]),
            window_id=int(data["window_id"]),
            window_range=(wr0, wr1),
            manifest=_freeze_mapping(data["manifest"]),
            task_batch=_freeze_mapping(data["task_batch"]),
            scorecard=_freeze_mapping(scorecard) if scorecard is not None else None,
            completions=completions,
            verdicts=verdicts,
            producer_hotkey=str(data["producer_hotkey"]),
            published_at=str(data["published_at"]),
        )


def build_rollout_bundle(
    *,
    netuid: int,
    window_id: int,
    window_range: tuple[int, int] | None = None,
    manifest: Mapping[str, Any],
    task_batch: Mapping[str, Any],
    scorecard: Mapping[str, Any] | None,
    completions: Sequence[Mapping[str, Any]],
    verdicts: Sequence[Mapping[str, Any]],
    producer_hotkey: str,
    published_at: str | None = None,
) -> RolloutBundle:
    """Construct a :class:`RolloutBundle` with sensible defaults.

    - ``window_range`` defaults to ``(window_id, window_id)`` for the
      single-window case (most common during integration).
    - ``published_at`` defaults to the current UTC ISO-8601 timestamp.
    - ``completions`` / ``verdicts`` are stable-sorted by their
      ``completion_id`` (if present) then by ``producer_hotkey`` so
      different producers converge on identical canonical bytes.
    """
    if window_range is None:
        window_range = (int(window_id), int(window_id))
    if published_at is None:
        published_at = _utc_now_iso()
    completions_sorted = tuple(_stable_sort(completions))
    verdicts_sorted = tuple(_stable_sort(verdicts))
    return RolloutBundle(
        version=BRIDGE_VERSION,
        netuid=int(netuid),
        window_id=int(window_id),
        window_range=(int(window_range[0]), int(window_range[1])),
        manifest=_freeze_mapping(manifest),
        task_batch=_freeze_mapping(task_batch),
        scorecard=_freeze_mapping(scorecard) if scorecard is not None else None,
        completions=completions_sorted,
        verdicts=verdicts_sorted,
        producer_hotkey=str(producer_hotkey),
        published_at=str(published_at),
    )


# ---------------------------------------------------------------------------
# CheckpointAttestation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckpointAttestation:
    """Forge's provenance signature on a promoted checkpoint.

    Binds the checkpoint's merkle root to the exact Ledger rollout
    windows + R2 keys that fed the RL / distill cycle which produced
    it. Gives any third party an onchain-backed chain of custody from
    any given checkpoint back to its rollout sources.
    """

    version: str
    training_netuid: int
    inference_netuid: int
    checkpoint_run_id: str
    checkpoint_window_id: int
    merkle_root_hex: str
    base_snapshot_window_id: int
    consumed_rollout_windows: tuple[int, ...]
    consumed_rollout_keys: tuple[str, ...]
    policy_authority_hotkey: str
    smoke_hash_hex: str
    signed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "training_netuid": int(self.training_netuid),
            "inference_netuid": int(self.inference_netuid),
            "checkpoint_run_id": self.checkpoint_run_id,
            "checkpoint_window_id": int(self.checkpoint_window_id),
            "merkle_root_hex": self.merkle_root_hex,
            "base_snapshot_window_id": int(self.base_snapshot_window_id),
            "consumed_rollout_windows": [int(w) for w in self.consumed_rollout_windows],
            "consumed_rollout_keys": list(self.consumed_rollout_keys),
            "policy_authority_hotkey": self.policy_authority_hotkey,
            "smoke_hash_hex": self.smoke_hash_hex,
            "signed_at": self.signed_at,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.to_dict())

    def artifact_id(self) -> str:
        return sha256_json(self.to_dict())

    def storage_key(self) -> str:
        """Key format: ``attestations/<training_netuid>/<run_id>/<window>.json``."""
        return (
            f"attestations/{int(self.training_netuid)}/"
            f"{self.checkpoint_run_id}/{int(self.checkpoint_window_id)}.json"
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CheckpointAttestation":
        _expect_version(data, "CheckpointAttestation")
        required = (
            "training_netuid",
            "inference_netuid",
            "checkpoint_run_id",
            "checkpoint_window_id",
            "merkle_root_hex",
            "base_snapshot_window_id",
            "consumed_rollout_windows",
            "consumed_rollout_keys",
            "policy_authority_hotkey",
            "smoke_hash_hex",
            "signed_at",
        )
        for fname in required:
            if fname not in data:
                raise BridgeSchemaError(
                    f"CheckpointAttestation missing required field {fname!r}"
                )
        merkle = str(data["merkle_root_hex"]).lower()
        if not _is_hex_64(merkle):
            raise BridgeSchemaError(
                f"CheckpointAttestation.merkle_root_hex must be 64-char hex; got {merkle!r}"
            )
        smoke = str(data["smoke_hash_hex"]).lower()
        if not _is_hex_64(smoke):
            raise BridgeSchemaError(
                f"CheckpointAttestation.smoke_hash_hex must be 64-char hex; got {smoke!r}"
            )
        consumed_windows = tuple(int(w) for w in data["consumed_rollout_windows"])
        if any(w < 0 for w in consumed_windows):
            raise BridgeSchemaError(
                f"CheckpointAttestation.consumed_rollout_windows negative: {consumed_windows!r}"
            )
        consumed_keys = tuple(str(k) for k in data["consumed_rollout_keys"])
        return cls(
            version=str(data["version"]),
            training_netuid=int(data["training_netuid"]),
            inference_netuid=int(data["inference_netuid"]),
            checkpoint_run_id=str(data["checkpoint_run_id"]),
            checkpoint_window_id=int(data["checkpoint_window_id"]),
            merkle_root_hex=merkle,
            base_snapshot_window_id=int(data["base_snapshot_window_id"]),
            consumed_rollout_windows=consumed_windows,
            consumed_rollout_keys=consumed_keys,
            policy_authority_hotkey=str(data["policy_authority_hotkey"]),
            smoke_hash_hex=smoke,
            signed_at=str(data["signed_at"]),
        )


def build_checkpoint_attestation(
    *,
    training_netuid: int,
    inference_netuid: int,
    checkpoint_run_id: str,
    checkpoint_window_id: int,
    merkle_root_hex: str,
    base_snapshot_window_id: int,
    consumed_rollout_windows: Sequence[int],
    consumed_rollout_keys: Sequence[str],
    policy_authority_hotkey: str,
    smoke_hash_hex: str,
    signed_at: str | None = None,
) -> CheckpointAttestation:
    """Construct a :class:`CheckpointAttestation` with defensive defaults.

    ``consumed_rollout_windows`` is sorted ascending before canonicalization
    so the attestation id is stable regardless of input order.
    """
    if signed_at is None:
        signed_at = _utc_now_iso()
    sorted_windows = tuple(sorted(int(w) for w in consumed_rollout_windows))
    return CheckpointAttestation(
        version=BRIDGE_VERSION,
        training_netuid=int(training_netuid),
        inference_netuid=int(inference_netuid),
        checkpoint_run_id=str(checkpoint_run_id),
        checkpoint_window_id=int(checkpoint_window_id),
        merkle_root_hex=str(merkle_root_hex).lower(),
        base_snapshot_window_id=int(base_snapshot_window_id),
        consumed_rollout_windows=sorted_windows,
        consumed_rollout_keys=tuple(str(k) for k in consumed_rollout_keys),
        policy_authority_hotkey=str(policy_authority_hotkey),
        smoke_hash_hex=str(smoke_hash_hex).lower(),
        signed_at=str(signed_at),
    )


# ---------------------------------------------------------------------------
# PolicyCommitment
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyCommitment:
    """Pointer-level artifact: "apply this checkpoint at this window."

    Simulates onchain ``commit_policy_metadata`` during staging: the
    Ledger policy consumer polls the commitment prefix on the same
    backend and picks up the latest effective-window.
    """

    version: str
    training_netuid: int
    inference_netuid: int
    checkpoint_run_id: str
    checkpoint_window_id: int
    attestation_key: str
    attestation_id: str
    effective_at_window: int
    committed_at: str
    signer_hotkey: str
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "training_netuid": int(self.training_netuid),
            "inference_netuid": int(self.inference_netuid),
            "checkpoint_run_id": self.checkpoint_run_id,
            "checkpoint_window_id": int(self.checkpoint_window_id),
            "attestation_key": self.attestation_key,
            "attestation_id": self.attestation_id,
            "effective_at_window": int(self.effective_at_window),
            "committed_at": self.committed_at,
            "signer_hotkey": self.signer_hotkey,
            "signature": self.signature,
        }

    def canonical_bytes_unsigned(self) -> bytes:
        """Canonical bytes WITHOUT the signature field — sign this."""
        unsigned = {k: v for k, v in self.to_dict().items() if k != "signature"}
        return canonical_bytes(unsigned)

    def canonical_bytes(self) -> bytes:
        """Canonical bytes with signature included — for transport / hashing."""
        return canonical_bytes(self.to_dict())

    def artifact_id(self) -> str:
        return sha256_json(self.to_dict())

    def storage_key(self) -> str:
        """Key format: ``commitments/<inference_netuid>/policy/<effective_window>.json``."""
        return (
            f"commitments/{int(self.inference_netuid)}/policy/"
            f"{int(self.effective_at_window)}.json"
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PolicyCommitment":
        _expect_version(data, "PolicyCommitment")
        required = (
            "training_netuid",
            "inference_netuid",
            "checkpoint_run_id",
            "checkpoint_window_id",
            "attestation_key",
            "attestation_id",
            "effective_at_window",
            "committed_at",
            "signer_hotkey",
            "signature",
        )
        for fname in required:
            if fname not in data:
                raise BridgeSchemaError(
                    f"PolicyCommitment missing required field {fname!r}"
                )
        if not _is_hex_64(str(data["attestation_id"]).lower()):
            raise BridgeSchemaError(
                f"PolicyCommitment.attestation_id must be 64-char hex; "
                f"got {data['attestation_id']!r}"
            )
        return cls(
            version=str(data["version"]),
            training_netuid=int(data["training_netuid"]),
            inference_netuid=int(data["inference_netuid"]),
            checkpoint_run_id=str(data["checkpoint_run_id"]),
            checkpoint_window_id=int(data["checkpoint_window_id"]),
            attestation_key=str(data["attestation_key"]),
            attestation_id=str(data["attestation_id"]).lower(),
            effective_at_window=int(data["effective_at_window"]),
            committed_at=str(data["committed_at"]),
            signer_hotkey=str(data["signer_hotkey"]),
            signature=str(data["signature"]),
        )


def build_policy_commitment(
    *,
    attestation: CheckpointAttestation,
    attestation_key: str | None = None,
    effective_at_window: int,
    signer: BridgeSigner,
    committed_at: str | None = None,
) -> PolicyCommitment:
    """Build + sign a :class:`PolicyCommitment` from a fresh attestation.

    The signature binds the commitment's entire byte-form (except the
    signature field itself) under the policy authority's signing key.
    """
    if committed_at is None:
        committed_at = _utc_now_iso()
    key = attestation_key if attestation_key is not None else attestation.storage_key()
    unsigned = PolicyCommitment(
        version=BRIDGE_VERSION,
        training_netuid=attestation.training_netuid,
        inference_netuid=attestation.inference_netuid,
        checkpoint_run_id=attestation.checkpoint_run_id,
        checkpoint_window_id=attestation.checkpoint_window_id,
        attestation_key=key,
        attestation_id=attestation.artifact_id(),
        effective_at_window=int(effective_at_window),
        committed_at=str(committed_at),
        signer_hotkey=str(signer.signer_id),
        signature="",  # placeholder — replaced below
    )
    sig = signer(unsigned.canonical_bytes_unsigned())
    return PolicyCommitment(
        version=unsigned.version,
        training_netuid=unsigned.training_netuid,
        inference_netuid=unsigned.inference_netuid,
        checkpoint_run_id=unsigned.checkpoint_run_id,
        checkpoint_window_id=unsigned.checkpoint_window_id,
        attestation_key=unsigned.attestation_key,
        attestation_id=unsigned.attestation_id,
        effective_at_window=unsigned.effective_at_window,
        committed_at=unsigned.committed_at,
        signer_hotkey=unsigned.signer_hotkey,
        signature=sig,
    )


def verify_policy_commitment(
    commitment: PolicyCommitment, verifier: BridgeVerifier
) -> bool:
    """Verify the commitment's signature under ``verifier``.

    Returns ``True`` iff the signature over the canonical-minus-signature
    bytes verifies against ``signer_hotkey``.
    """
    return verifier(
        commitment.signer_hotkey,
        commitment.canonical_bytes_unsigned(),
        commitment.signature,
    )


# ---------------------------------------------------------------------------
# Signed-envelope helpers (shared shape across all three artifact types)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BridgeEnvelope:
    """Common signed-envelope wrapper for bridge artifacts.

    Fields:
    - ``envelope_version`` — independent of the inner ``BRIDGE_VERSION``
      so we can evolve the envelope without rev'ing every artifact.
    - ``artifact_type`` — one of the module-level ``*_TYPE`` constants.
    - ``artifact_id`` — 64-char sha256 of inner canonical bytes.
    - ``payload_json`` — inner artifact as canonical-bytes JSON string
      (stringified to keep the envelope's own canonical bytes stable).
    - ``signer_id`` — hotkey string.
    - ``signed_at`` — ISO-8601 UTC.
    - ``signature`` — HMAC over canonical-minus-signature bytes.
    """

    envelope_version: str
    artifact_type: str
    artifact_id: str
    payload_json: str
    signer_id: str
    signed_at: str
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "envelope_version": self.envelope_version,
            "artifact_type": self.artifact_type,
            "artifact_id": self.artifact_id,
            "payload_json": self.payload_json,
            "signer_id": self.signer_id,
            "signed_at": self.signed_at,
            "signature": self.signature,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.to_dict())

    def canonical_bytes_unsigned(self) -> bytes:
        unsigned = {k: v for k, v in self.to_dict().items() if k != "signature"}
        return canonical_bytes(unsigned)


def sign_envelope(
    artifact_type: str,
    payload: Mapping[str, Any] | RolloutBundle | CheckpointAttestation | PolicyCommitment,
    signer: BridgeSigner,
    signed_at: str | None = None,
) -> BridgeEnvelope:
    """Build a signed :class:`BridgeEnvelope` around an inner artifact.

    ``payload`` may be an already-dict'd mapping or a dataclass with a
    ``to_dict`` method; both are normalized to canonical bytes and
    stringified into the envelope.
    """
    if artifact_type not in (
        ROLLOUT_BUNDLE_TYPE,
        CHECKPOINT_ATTESTATION_TYPE,
        POLICY_COMMITMENT_TYPE,
    ):
        raise BridgeSchemaError(f"unknown artifact_type {artifact_type!r}")
    if signed_at is None:
        signed_at = _utc_now_iso()
    if hasattr(payload, "to_dict"):
        payload_dict = payload.to_dict()  # type: ignore[union-attr]
    else:
        payload_dict = dict(payload)
    payload_json = stable_json_dumps(payload_dict)
    artifact_id = sha256_json(payload_dict)
    unsigned = BridgeEnvelope(
        envelope_version=_ENVELOPE_VERSION,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        payload_json=payload_json,
        signer_id=str(signer.signer_id),
        signed_at=str(signed_at),
        signature="",
    )
    sig = signer(unsigned.canonical_bytes_unsigned())
    return BridgeEnvelope(
        envelope_version=unsigned.envelope_version,
        artifact_type=unsigned.artifact_type,
        artifact_id=unsigned.artifact_id,
        payload_json=unsigned.payload_json,
        signer_id=unsigned.signer_id,
        signed_at=unsigned.signed_at,
        signature=sig,
    )


def verify_envelope(envelope: BridgeEnvelope, verifier: BridgeVerifier) -> bool:
    """Verify envelope signature AND that ``artifact_id`` matches payload_json."""
    try:
        import json

        payload_dict = json.loads(envelope.payload_json)
    except Exception as exc:  # pragma: no cover - malformed payload
        raise BridgeSchemaError(f"envelope payload_json is not valid JSON: {exc}") from exc
    recomputed_id = sha256_json(payload_dict)
    if recomputed_id != envelope.artifact_id:
        return False
    return verifier(
        envelope.signer_id, envelope.canonical_bytes_unsigned(), envelope.signature
    )


def envelope_from_dict(data: Mapping[str, Any]) -> BridgeEnvelope:
    """Parse a dict (e.g. from ``json.load``) into an envelope."""
    for fname in (
        "envelope_version",
        "artifact_type",
        "artifact_id",
        "payload_json",
        "signer_id",
        "signed_at",
        "signature",
    ):
        if fname not in data:
            raise BridgeSchemaError(f"envelope missing required field {fname!r}")
    if str(data["envelope_version"]) != _ENVELOPE_VERSION:
        raise BridgeVersionMismatch(
            f"envelope_version {data['envelope_version']!r} != expected {_ENVELOPE_VERSION!r}"
        )
    return BridgeEnvelope(
        envelope_version=str(data["envelope_version"]),
        artifact_type=str(data["artifact_type"]),
        artifact_id=str(data["artifact_id"]).lower(),
        payload_json=str(data["payload_json"]),
        signer_id=str(data["signer_id"]),
        signed_at=str(data["signed_at"]),
        signature=str(data["signature"]),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _expect_version(data: Mapping[str, Any], artifact_name: str) -> None:
    if "version" not in data:
        raise BridgeSchemaError(f"{artifact_name} missing required field 'version'")
    version = str(data["version"])
    if version != BRIDGE_VERSION:
        raise BridgeVersionMismatch(
            f"{artifact_name} version {version!r} != expected {BRIDGE_VERSION!r}"
        )


def _is_hex_64(s: str) -> bool:
    if len(s) != 64:
        return False
    try:
        int(s, 16)
    except ValueError:
        return False
    return True


def _freeze_mapping(m: Mapping[str, Any]) -> dict[str, Any]:
    """Return a plain ``dict`` copy — ensures JSON-stable serializability.

    The canonicalization layer doesn't care about the runtime type
    (dict vs MappingProxyType vs custom), but ``stable_json_dumps``
    does require JSON-serializable values. This copy normalizes any
    nested mapping to plain dicts.
    """
    return {k: _freeze_value(v) for k, v in m.items()}


def _freeze_value(v: Any) -> Any:
    if isinstance(v, Mapping):
        return _freeze_mapping(v)
    if isinstance(v, (list, tuple)):
        return [_freeze_value(x) for x in v]
    return v


def _stable_sort(items: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Stable-sort by ``completion_id`` → ``producer_hotkey`` → canonical bytes.

    A bundle produced by two validators that accept the same completions
    in different orders must canonicalize identically.
    """

    def key(item: Mapping[str, Any]) -> tuple[str, str, bytes]:
        completion_id = str(item.get("completion_id", ""))
        producer = str(item.get("producer_hotkey", item.get("validator_hotkey", "")))
        return completion_id, producer, canonical_bytes(_freeze_mapping(item))

    return sorted((_freeze_mapping(x) for x in items), key=key)


__all__ = [
    "BRIDGE_VERSION",
    "BridgeEnvelope",
    "BridgeError",
    "BridgeSchemaError",
    "BridgeSignatureError",
    "BridgeSigner",
    "BridgeVerifier",
    "BridgeVersionMismatch",
    "CheckpointAttestation",
    "CHECKPOINT_ATTESTATION_TYPE",
    "HmacBridgeSigner",
    "HmacBridgeVerifier",
    "POLICY_COMMITMENT_TYPE",
    "PolicyCommitment",
    "ROLLOUT_BUNDLE_TYPE",
    "RolloutBundle",
    "build_checkpoint_attestation",
    "build_policy_commitment",
    "build_rollout_bundle",
    "envelope_from_dict",
    "sign_envelope",
    "verify_envelope",
    "verify_policy_commitment",
]
