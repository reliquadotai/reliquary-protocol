"""Authoritative Reliquary protocol constants.

Proof sketch + mesh consensus + copycat + logprob + distribution
parameters. No environment overrides — these are mathematical
parameters of the protocol, not runtime knobs. An attempt to mutate
any of these at import time must be treated as a protocol fork and
requires a coordinated version bump across both subnets.

Mirrors the `reliquary_inference/protocol/constants.py` values as of
v1 and is the authoritative source going forward.
"""

from __future__ import annotations

# -- Identity --
LEDGER_PROOF_VERSION: str = "v5"

# -- Proof sketch --
PRIME_Q: int = 2_147_483_647
CHALLENGE_K: int = 32
LAYER_INDEX: int = -1
PROOF_TOPK: int = 16
PROOF_NUM_BUCKETS: int = 8
PROOF_COEFF_RANGE: int = 127
# Tightened 2026-04-28 from 6000 to 1000. See
# reliquary-ledger/reliquary_inference/protocol/constants.py for the
# calibration methodology and data. Both packages must stay in sync;
# alignment is enforced by tests/test_shared_protocol_alignment.py.
PROOF_SKETCH_TOLERANCE_BASE: int = 1000
PROOF_SKETCH_TOLERANCE_GROWTH: float = 5.0

# -- Attention kernel --
ATTN_IMPLEMENTATION: str = "flash_attention_2"

# -- RNG labels (sketch vs open vs task) --
RNG_LABEL: dict[str, bytes] = {
    "sketch": b"sketch",
    "open": b"open",
    "task": b"task",
}

# -- Copycat detection --
COPYCAT_AMBIGUITY_WINDOW_SECONDS: float = 2.0
COPYCAT_WINDOW_THRESHOLD: float = 0.05
COPYCAT_INTERVAL_THRESHOLD: float = 0.03
COPYCAT_INTERVAL_LENGTH: int = 12
COPYCAT_GATE_DURATION_WINDOWS: int = 12

# -- Mesh consensus --
MESH_STAKE_CAP_FRACTION: float = 0.10
MESH_MIN_QUORUM_STAKE_FRACTION: float = 0.50
MESH_OUTLIER_THRESHOLD: float = 0.25
MESH_OUTLIER_RATE_GATE: float = 0.05

# -- Distribution / logprob --
# Tightened 2026-04-28 from 0.15 to 0.01. See
# reliquary-ledger/reliquary_inference/protocol/constants.py for the
# methodology. Honest miner LP-drift on RTX 6000B is exactly zero;
# 0.01 = 100× the noise floor + 9× below cheater p95.
LOGPROB_DRIFT_THRESHOLD: float = 0.01
LOGPROB_DRIFT_QUORUM: float = 0.51
DISTRIBUTION_RATIO_BAND_HIGH: float = 1.15
DISTRIBUTION_RATIO_BAND_LOW: float = 0.85
DISTRIBUTION_MIN_POSITIONS: int = 8


PROTOCOL_CONSTANT_NAMES: tuple[str, ...] = (
    "LEDGER_PROOF_VERSION",
    "PRIME_Q",
    "CHALLENGE_K",
    "LAYER_INDEX",
    "PROOF_TOPK",
    "PROOF_NUM_BUCKETS",
    "PROOF_COEFF_RANGE",
    "PROOF_SKETCH_TOLERANCE_BASE",
    "PROOF_SKETCH_TOLERANCE_GROWTH",
    "ATTN_IMPLEMENTATION",
    "COPYCAT_AMBIGUITY_WINDOW_SECONDS",
    "COPYCAT_WINDOW_THRESHOLD",
    "COPYCAT_INTERVAL_THRESHOLD",
    "COPYCAT_INTERVAL_LENGTH",
    "COPYCAT_GATE_DURATION_WINDOWS",
    "MESH_STAKE_CAP_FRACTION",
    "MESH_MIN_QUORUM_STAKE_FRACTION",
    "MESH_OUTLIER_THRESHOLD",
    "MESH_OUTLIER_RATE_GATE",
    "LOGPROB_DRIFT_THRESHOLD",
    "LOGPROB_DRIFT_QUORUM",
    "DISTRIBUTION_RATIO_BAND_HIGH",
    "DISTRIBUTION_RATIO_BAND_LOW",
    "DISTRIBUTION_MIN_POSITIONS",
)


__all__ = list(PROTOCOL_CONSTANT_NAMES) + ["PROTOCOL_CONSTANT_NAMES", "RNG_LABEL"]
