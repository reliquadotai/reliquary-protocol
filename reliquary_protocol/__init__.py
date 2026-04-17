"""Shared protocol primitives for Reliquary Ledger + Forge."""

from __future__ import annotations

from .artifacts import ArtifactType, ArtifactTypes, content_addressable_id
from .canonicalization import (
    CANONICAL_SEPARATORS,
    canonical_bytes,
    sha256_canonical,
    sha256_json,
    stable_json_dumps,
)
from .constants import (
    ATTN_IMPLEMENTATION,
    CHALLENGE_K,
    COPYCAT_AMBIGUITY_WINDOW_SECONDS,
    COPYCAT_GATE_DURATION_WINDOWS,
    COPYCAT_INTERVAL_LENGTH,
    COPYCAT_INTERVAL_THRESHOLD,
    COPYCAT_WINDOW_THRESHOLD,
    DISTRIBUTION_MIN_POSITIONS,
    DISTRIBUTION_RATIO_BAND_HIGH,
    DISTRIBUTION_RATIO_BAND_LOW,
    LAYER_INDEX,
    LEDGER_PROOF_VERSION,
    LOGPROB_DRIFT_QUORUM,
    LOGPROB_DRIFT_THRESHOLD,
    MESH_MIN_QUORUM_STAKE_FRACTION,
    MESH_OUTLIER_RATE_GATE,
    MESH_OUTLIER_THRESHOLD,
    MESH_STAKE_CAP_FRACTION,
    PRIME_Q,
    PROOF_COEFF_RANGE,
    PROOF_NUM_BUCKETS,
    PROOF_SKETCH_TOLERANCE_BASE,
    PROOF_SKETCH_TOLERANCE_GROWTH,
    PROOF_TOPK,
    RNG_LABEL,
)
from .signatures import (
    SigningKey,
    escape_label_value,
    hmac_sign,
    hmac_verify,
)


VERSION = "0.1.0"


__all__ = [
    "VERSION",
    "ATTN_IMPLEMENTATION",
    "ArtifactType",
    "ArtifactTypes",
    "CANONICAL_SEPARATORS",
    "CHALLENGE_K",
    "COPYCAT_AMBIGUITY_WINDOW_SECONDS",
    "COPYCAT_GATE_DURATION_WINDOWS",
    "COPYCAT_INTERVAL_LENGTH",
    "COPYCAT_INTERVAL_THRESHOLD",
    "COPYCAT_WINDOW_THRESHOLD",
    "DISTRIBUTION_MIN_POSITIONS",
    "DISTRIBUTION_RATIO_BAND_HIGH",
    "DISTRIBUTION_RATIO_BAND_LOW",
    "LAYER_INDEX",
    "LEDGER_PROOF_VERSION",
    "LOGPROB_DRIFT_QUORUM",
    "LOGPROB_DRIFT_THRESHOLD",
    "MESH_MIN_QUORUM_STAKE_FRACTION",
    "MESH_OUTLIER_RATE_GATE",
    "MESH_OUTLIER_THRESHOLD",
    "MESH_STAKE_CAP_FRACTION",
    "PRIME_Q",
    "PROOF_COEFF_RANGE",
    "PROOF_NUM_BUCKETS",
    "PROOF_SKETCH_TOLERANCE_BASE",
    "PROOF_SKETCH_TOLERANCE_GROWTH",
    "PROOF_TOPK",
    "RNG_LABEL",
    "SigningKey",
    "canonical_bytes",
    "content_addressable_id",
    "escape_label_value",
    "hmac_sign",
    "hmac_verify",
    "sha256_canonical",
    "sha256_json",
    "stable_json_dumps",
]
