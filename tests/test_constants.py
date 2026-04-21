"""Tests pinning the protocol constants.

These are the mathematical parameters shared across Ledger + Forge.
A silent change must be caught at CI so neither subnet can accidentally
fork the protocol.
"""

from __future__ import annotations

from reliquary_protocol import constants


def test_ledger_proof_version_is_v5() -> None:
    # v5 is the authoritative on-wire version. It's the value gated by
    # reliquary_inference.protocol.signatures.verify_commit_signature,
    # which accepts "v4" or "v5" only. Earlier v1/v2/v3 labels predate the
    # current HMAC binding format.
    assert constants.LEDGER_PROOF_VERSION == "v5"


def test_prime_q_is_mersenne_m31() -> None:
    assert constants.PRIME_Q == (1 << 31) - 1
    assert constants.PRIME_Q == 2_147_483_647


def test_challenge_and_sketch_shape() -> None:
    assert constants.CHALLENGE_K == 32
    assert constants.PROOF_TOPK == 16
    assert constants.PROOF_NUM_BUCKETS == 8
    assert constants.PROOF_COEFF_RANGE == 127


def test_tolerance_parameters() -> None:
    assert constants.PROOF_SKETCH_TOLERANCE_BASE == 6000
    assert constants.PROOF_SKETCH_TOLERANCE_GROWTH == 5.0


def test_attention_kernel_is_flash_attention_2() -> None:
    assert constants.ATTN_IMPLEMENTATION == "flash_attention_2"


def test_layer_index_is_last_layer() -> None:
    assert constants.LAYER_INDEX == -1


def test_rng_labels_distinct_and_non_empty() -> None:
    labels = constants.RNG_LABEL
    assert set(labels) == {"sketch", "open", "task"}
    assert all(isinstance(v, bytes) and len(v) > 0 for v in labels.values())
    # sketch / open / task MUST be distinct so PRF domains don't collide.
    assert len(set(labels.values())) == 3


def test_mesh_consensus_values() -> None:
    assert constants.MESH_STAKE_CAP_FRACTION == 0.10
    assert constants.MESH_MIN_QUORUM_STAKE_FRACTION == 0.50
    assert constants.MESH_OUTLIER_THRESHOLD == 0.25
    assert constants.MESH_OUTLIER_RATE_GATE == 0.05


def test_copycat_values() -> None:
    assert constants.COPYCAT_AMBIGUITY_WINDOW_SECONDS == 2.0
    assert constants.COPYCAT_WINDOW_THRESHOLD == 0.05
    assert constants.COPYCAT_INTERVAL_THRESHOLD == 0.03
    assert constants.COPYCAT_INTERVAL_LENGTH == 12
    assert constants.COPYCAT_GATE_DURATION_WINDOWS == 12


def test_logprob_values() -> None:
    assert constants.LOGPROB_DRIFT_THRESHOLD == 0.15
    assert constants.LOGPROB_DRIFT_QUORUM == 0.51


def test_distribution_values() -> None:
    assert constants.DISTRIBUTION_RATIO_BAND_LOW == 0.85
    assert constants.DISTRIBUTION_RATIO_BAND_HIGH == 1.15
    assert constants.DISTRIBUTION_MIN_POSITIONS == 8


def test_distribution_band_brackets_one() -> None:
    assert (
        constants.DISTRIBUTION_RATIO_BAND_LOW
        < 1.0
        < constants.DISTRIBUTION_RATIO_BAND_HIGH
    )


def test_protocol_constant_names_covers_every_exported_name() -> None:
    for name in constants.PROTOCOL_CONSTANT_NAMES:
        assert hasattr(constants, name), f"missing {name}"


def test_protocol_constant_names_immutable_tuple() -> None:
    assert isinstance(constants.PROTOCOL_CONSTANT_NAMES, tuple)
