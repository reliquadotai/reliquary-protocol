"""Tests for :mod:`reliquary_protocol.bridge` — the cross-subnet bridge."""

from __future__ import annotations

import json

import pytest

from reliquary_protocol import (
    BRIDGE_VERSION,
    BridgeEnvelope,
    BridgeSchemaError,
    BridgeVersionMismatch,
    CHECKPOINT_ATTESTATION_TYPE,
    CheckpointAttestation,
    HmacBridgeSigner,
    HmacBridgeVerifier,
    POLICY_COMMITMENT_TYPE,
    PolicyCommitment,
    ROLLOUT_BUNDLE_TYPE,
    RolloutBundle,
    build_checkpoint_attestation,
    build_policy_commitment,
    build_rollout_bundle,
    canonical_bytes,
    envelope_from_dict,
    sha256_json,
    sign_envelope,
    verify_envelope,
    verify_policy_commitment,
)


# ---------------------------------------------------------------------------
# RolloutBundle
# ---------------------------------------------------------------------------


def _tiny_window_inputs(**overrides):
    base = dict(
        netuid=81,
        window_id=12345,
        manifest={"task_source": "sat", "task_count": 4, "seed": 0xDEADBEEF},
        task_batch={"tasks": [{"id": "t1", "prompt": "p1"}]},
        scorecard={"miner_a": {"score": 0.9}, "miner_b": {"score": 0.3}},
        completions=[
            {"completion_id": "c2", "producer_hotkey": "miner_a", "text": "world"},
            {"completion_id": "c1", "producer_hotkey": "miner_b", "text": "hello"},
        ],
        verdicts=[
            {
                "completion_id": "c1",
                "validator_hotkey": "val_a",
                "verdict": "accept",
            },
            {
                "completion_id": "c2",
                "validator_hotkey": "val_a",
                "verdict": "accept",
            },
        ],
        producer_hotkey="val_a",
        published_at="2026-04-20T00:00:00+00:00",
    )
    base.update(overrides)
    return base


def test_rollout_bundle_canonical_bytes_are_stable_under_input_reordering():
    b1 = build_rollout_bundle(**_tiny_window_inputs())
    reordered = _tiny_window_inputs(
        completions=[
            {"completion_id": "c1", "producer_hotkey": "miner_b", "text": "hello"},
            {"completion_id": "c2", "producer_hotkey": "miner_a", "text": "world"},
        ],
        verdicts=[
            {
                "completion_id": "c2",
                "validator_hotkey": "val_a",
                "verdict": "accept",
            },
            {
                "completion_id": "c1",
                "validator_hotkey": "val_a",
                "verdict": "accept",
            },
        ],
    )
    b2 = build_rollout_bundle(**reordered)
    assert b1.canonical_bytes() == b2.canonical_bytes()
    assert b1.artifact_id() == b2.artifact_id()


def test_rollout_bundle_round_trip_identity():
    b = build_rollout_bundle(**_tiny_window_inputs())
    d = b.to_dict()
    # Serialize → parse → reconstruct → should be byte-identical.
    reparsed = RolloutBundle.from_dict(json.loads(canonical_bytes(d).decode("utf-8")))
    assert reparsed.canonical_bytes() == b.canonical_bytes()
    assert reparsed.artifact_id() == b.artifact_id()


def test_rollout_bundle_default_window_range_matches_window_id():
    b = build_rollout_bundle(**_tiny_window_inputs())
    assert b.window_range == (b.window_id, b.window_id)


def test_rollout_bundle_storage_key_format():
    b = build_rollout_bundle(**_tiny_window_inputs())
    assert b.storage_key() == "rollouts/81/12345-12345/val_a.json"


def test_rollout_bundle_from_dict_rejects_missing_fields():
    d = build_rollout_bundle(**_tiny_window_inputs()).to_dict()
    del d["task_batch"]
    with pytest.raises(BridgeSchemaError, match="task_batch"):
        RolloutBundle.from_dict(d)


def test_rollout_bundle_from_dict_rejects_reversed_window_range():
    d = build_rollout_bundle(**_tiny_window_inputs()).to_dict()
    d["window_range"] = [10, 5]
    with pytest.raises(BridgeSchemaError, match="window_range is reversed"):
        RolloutBundle.from_dict(d)


def test_rollout_bundle_from_dict_rejects_wrong_version():
    d = build_rollout_bundle(**_tiny_window_inputs()).to_dict()
    d["version"] = "999"
    with pytest.raises(BridgeVersionMismatch):
        RolloutBundle.from_dict(d)


def test_rollout_bundle_from_dict_accepts_2tuple_window_range_list():
    d = build_rollout_bundle(**_tiny_window_inputs()).to_dict()
    d["window_range"] = [100, 120]  # JSON-serialized form
    b = RolloutBundle.from_dict(d)
    assert b.window_range == (100, 120)


def test_rollout_bundle_multi_window_range():
    d = _tiny_window_inputs()
    d["window_range"] = (100, 120)
    b = build_rollout_bundle(**d)
    assert b.storage_key() == "rollouts/81/100-120/val_a.json"


def test_rollout_bundle_scorecard_optional():
    d = _tiny_window_inputs(scorecard=None)
    b = build_rollout_bundle(**d)
    assert b.scorecard is None
    reparsed = RolloutBundle.from_dict(b.to_dict())
    assert reparsed.scorecard is None


# ---------------------------------------------------------------------------
# CheckpointAttestation
# ---------------------------------------------------------------------------


def _tiny_attestation_inputs(**overrides):
    base = dict(
        training_netuid=3,
        inference_netuid=81,
        checkpoint_run_id="forge-run-0001",
        checkpoint_window_id=7,
        merkle_root_hex="a" * 64,
        base_snapshot_window_id=0,
        consumed_rollout_windows=[11, 10, 12],  # deliberate unsorted
        consumed_rollout_keys=[
            "rollouts/81/10-10/val_a.json",
            "rollouts/81/11-11/val_a.json",
            "rollouts/81/12-12/val_a.json",
        ],
        policy_authority_hotkey="authority_x",
        smoke_hash_hex="b" * 64,
        signed_at="2026-04-20T00:00:00+00:00",
    )
    base.update(overrides)
    return base


def test_checkpoint_attestation_consumed_windows_sorted_on_build():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    assert a.consumed_rollout_windows == (10, 11, 12)


def test_checkpoint_attestation_id_stable_under_input_order():
    a1 = build_checkpoint_attestation(**_tiny_attestation_inputs())
    reordered = _tiny_attestation_inputs(consumed_rollout_windows=[12, 11, 10])
    a2 = build_checkpoint_attestation(**reordered)
    assert a1.artifact_id() == a2.artifact_id()


def test_checkpoint_attestation_storage_key_format():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    assert a.storage_key() == "attestations/3/forge-run-0001/7.json"


def test_checkpoint_attestation_from_dict_rejects_bad_merkle():
    d = build_checkpoint_attestation(**_tiny_attestation_inputs()).to_dict()
    d["merkle_root_hex"] = "not-hex"
    with pytest.raises(BridgeSchemaError, match="merkle_root_hex"):
        CheckpointAttestation.from_dict(d)


def test_checkpoint_attestation_from_dict_rejects_short_merkle():
    d = build_checkpoint_attestation(**_tiny_attestation_inputs()).to_dict()
    d["merkle_root_hex"] = "a" * 32  # half-length
    with pytest.raises(BridgeSchemaError):
        CheckpointAttestation.from_dict(d)


def test_checkpoint_attestation_from_dict_rejects_negative_window():
    d = build_checkpoint_attestation(**_tiny_attestation_inputs()).to_dict()
    d["consumed_rollout_windows"] = [-1, 10, 11]
    with pytest.raises(BridgeSchemaError, match="negative"):
        CheckpointAttestation.from_dict(d)


def test_checkpoint_attestation_round_trip():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    reparsed = CheckpointAttestation.from_dict(
        json.loads(canonical_bytes(a.to_dict()).decode("utf-8"))
    )
    assert reparsed.canonical_bytes() == a.canonical_bytes()


def test_checkpoint_attestation_version_mismatch_rejected():
    d = build_checkpoint_attestation(**_tiny_attestation_inputs()).to_dict()
    d["version"] = "99"
    with pytest.raises(BridgeVersionMismatch):
        CheckpointAttestation.from_dict(d)


# ---------------------------------------------------------------------------
# PolicyCommitment
# ---------------------------------------------------------------------------


def _make_signer(signer_id: str = "authority_x", secret: str = "secret-a"):
    return HmacBridgeSigner(signer_id=signer_id, secret=secret)


def _make_verifier(*keys):
    return HmacBridgeVerifier(secrets=dict(keys))


def test_policy_commitment_signed_and_verified():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    signer = _make_signer()
    commitment = build_policy_commitment(
        attestation=a,
        effective_at_window=200,
        signer=signer,
    )
    verifier = _make_verifier(("authority_x", "secret-a"))
    assert verify_policy_commitment(commitment, verifier) is True


def test_policy_commitment_tampered_signature_rejected():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    signer = _make_signer()
    commitment = build_policy_commitment(
        attestation=a,
        effective_at_window=200,
        signer=signer,
    )
    # Tamper: flip effective_at_window.
    tampered = PolicyCommitment(
        version=commitment.version,
        training_netuid=commitment.training_netuid,
        inference_netuid=commitment.inference_netuid,
        checkpoint_run_id=commitment.checkpoint_run_id,
        checkpoint_window_id=commitment.checkpoint_window_id,
        attestation_key=commitment.attestation_key,
        attestation_id=commitment.attestation_id,
        effective_at_window=commitment.effective_at_window + 1,
        committed_at=commitment.committed_at,
        signer_hotkey=commitment.signer_hotkey,
        signature=commitment.signature,
    )
    verifier = _make_verifier(("authority_x", "secret-a"))
    assert verify_policy_commitment(tampered, verifier) is False


def test_policy_commitment_unknown_signer_rejected():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    signer = _make_signer(signer_id="rogue", secret="secret-a")
    commitment = build_policy_commitment(
        attestation=a,
        effective_at_window=200,
        signer=signer,
    )
    # Verifier only has authority_x; "rogue" isn't in the table.
    verifier = _make_verifier(("authority_x", "secret-a"))
    assert verify_policy_commitment(commitment, verifier) is False


def test_policy_commitment_storage_key_format():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    signer = _make_signer()
    c = build_policy_commitment(
        attestation=a, effective_at_window=200, signer=signer
    )
    assert c.storage_key() == "commitments/81/policy/200.json"


def test_policy_commitment_attestation_id_matches_attestation():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    signer = _make_signer()
    c = build_policy_commitment(
        attestation=a, effective_at_window=200, signer=signer
    )
    assert c.attestation_id == a.artifact_id()
    assert c.attestation_key == a.storage_key()


def test_policy_commitment_from_dict_round_trip():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    signer = _make_signer()
    c = build_policy_commitment(
        attestation=a, effective_at_window=200, signer=signer
    )
    reparsed = PolicyCommitment.from_dict(
        json.loads(canonical_bytes(c.to_dict()).decode("utf-8"))
    )
    assert reparsed.canonical_bytes() == c.canonical_bytes()
    verifier = _make_verifier(("authority_x", "secret-a"))
    assert verify_policy_commitment(reparsed, verifier) is True


def test_policy_commitment_from_dict_rejects_bad_attestation_id():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    signer = _make_signer()
    c = build_policy_commitment(
        attestation=a, effective_at_window=200, signer=signer
    )
    d = c.to_dict()
    d["attestation_id"] = "not-hex"
    with pytest.raises(BridgeSchemaError, match="attestation_id"):
        PolicyCommitment.from_dict(d)


# ---------------------------------------------------------------------------
# Signed envelope
# ---------------------------------------------------------------------------


def test_sign_envelope_and_verify_rollout_bundle():
    b = build_rollout_bundle(**_tiny_window_inputs())
    signer = _make_signer()
    env = sign_envelope(ROLLOUT_BUNDLE_TYPE, b, signer)
    verifier = _make_verifier(("authority_x", "secret-a"))
    assert verify_envelope(env, verifier) is True


def test_sign_envelope_and_verify_checkpoint_attestation():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    signer = _make_signer()
    env = sign_envelope(CHECKPOINT_ATTESTATION_TYPE, a, signer)
    verifier = _make_verifier(("authority_x", "secret-a"))
    assert verify_envelope(env, verifier) is True


def test_sign_envelope_rejects_unknown_artifact_type():
    b = build_rollout_bundle(**_tiny_window_inputs())
    signer = _make_signer()
    with pytest.raises(BridgeSchemaError, match="unknown artifact_type"):
        sign_envelope("malformed_type", b, signer)


def test_envelope_tampered_payload_detected():
    """Flipping payload_json after signing must be detected."""
    b = build_rollout_bundle(**_tiny_window_inputs())
    signer = _make_signer()
    env = sign_envelope(ROLLOUT_BUNDLE_TYPE, b, signer)
    # Replace payload_json with a different bundle's bytes.
    other = build_rollout_bundle(**_tiny_window_inputs(window_id=99999))
    tampered = BridgeEnvelope(
        envelope_version=env.envelope_version,
        artifact_type=env.artifact_type,
        artifact_id=env.artifact_id,  # stale id!
        payload_json=json.dumps(other.to_dict(), sort_keys=True, separators=(",", ":")),
        signer_id=env.signer_id,
        signed_at=env.signed_at,
        signature=env.signature,
    )
    verifier = _make_verifier(("authority_x", "secret-a"))
    # artifact_id doesn't match tampered payload → False.
    assert verify_envelope(tampered, verifier) is False


def test_envelope_tampered_signature_detected():
    """Flipping signature after signing must be detected."""
    b = build_rollout_bundle(**_tiny_window_inputs())
    signer = _make_signer()
    env = sign_envelope(ROLLOUT_BUNDLE_TYPE, b, signer)
    tampered = BridgeEnvelope(
        envelope_version=env.envelope_version,
        artifact_type=env.artifact_type,
        artifact_id=env.artifact_id,
        payload_json=env.payload_json,
        signer_id=env.signer_id,
        signed_at=env.signed_at,
        signature="0" * 64,
    )
    verifier = _make_verifier(("authority_x", "secret-a"))
    assert verify_envelope(tampered, verifier) is False


def test_envelope_round_trip_via_envelope_from_dict():
    b = build_rollout_bundle(**_tiny_window_inputs())
    signer = _make_signer()
    env = sign_envelope(ROLLOUT_BUNDLE_TYPE, b, signer)
    encoded = json.dumps(env.to_dict())
    decoded = envelope_from_dict(json.loads(encoded))
    verifier = _make_verifier(("authority_x", "secret-a"))
    assert verify_envelope(decoded, verifier) is True


def test_envelope_from_dict_rejects_bad_envelope_version():
    b = build_rollout_bundle(**_tiny_window_inputs())
    signer = _make_signer()
    env = sign_envelope(ROLLOUT_BUNDLE_TYPE, b, signer)
    d = env.to_dict()
    d["envelope_version"] = "99"
    with pytest.raises(BridgeVersionMismatch):
        envelope_from_dict(d)


def test_envelope_artifact_id_matches_sha256_of_payload():
    b = build_rollout_bundle(**_tiny_window_inputs())
    signer = _make_signer()
    env = sign_envelope(ROLLOUT_BUNDLE_TYPE, b, signer)
    expected_id = sha256_json(json.loads(env.payload_json))
    assert env.artifact_id == expected_id


def test_envelope_policy_commitment_payload_round_trip():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    signer = _make_signer()
    c = build_policy_commitment(
        attestation=a, effective_at_window=200, signer=signer
    )
    env = sign_envelope(POLICY_COMMITMENT_TYPE, c, signer)
    verifier = _make_verifier(("authority_x", "secret-a"))
    assert verify_envelope(env, verifier) is True
    # The inner payload round-trips.
    inner = PolicyCommitment.from_dict(json.loads(env.payload_json))
    assert inner.canonical_bytes() == c.canonical_bytes()


# ---------------------------------------------------------------------------
# Version constant sanity
# ---------------------------------------------------------------------------


def test_bridge_version_is_stable_string():
    assert isinstance(BRIDGE_VERSION, str)
    assert BRIDGE_VERSION == "1"


def test_artifact_type_constants_are_distinct():
    assert ROLLOUT_BUNDLE_TYPE != CHECKPOINT_ATTESTATION_TYPE
    assert CHECKPOINT_ATTESTATION_TYPE != POLICY_COMMITMENT_TYPE
    assert ROLLOUT_BUNDLE_TYPE != POLICY_COMMITMENT_TYPE


def test_rollout_bundle_frozen():
    b = build_rollout_bundle(**_tiny_window_inputs())
    with pytest.raises(Exception):
        b.window_id = 999  # type: ignore[misc]


def test_checkpoint_attestation_frozen():
    a = build_checkpoint_attestation(**_tiny_attestation_inputs())
    with pytest.raises(Exception):
        a.merkle_root_hex = "0" * 64  # type: ignore[misc]
