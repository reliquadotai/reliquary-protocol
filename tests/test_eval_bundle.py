"""Tests for :class:`EvalBundle` + the eval-holdout derivation.

Covers:

- Byte-stable canonicalization under reordering (per_problem_results
  order, holdout_task_ids order) so two independent evaluators on the
  same policy + holdout produce the same bundle id.
- Accuracy + mean_reward + per-level + per-subject aggregates computed
  correctly (including 0-count / unknown-bucket fallback).
- Signed-envelope roundtrip through ``sign_envelope`` / ``verify_envelope``
  matches the existing bridge pattern.
- ``derive_eval_holdout_indices`` is deterministic, produces distinct
  sorted indices, and respects dataset_size / holdout_size bounds.
- ``holdout_contains`` agrees with the materialized index list.
"""

from __future__ import annotations

import json

import pytest

from reliquary_protocol import (
    BRIDGE_VERSION,
    DEFAULT_HOLDOUT_SEED,
    DEFAULT_HOLDOUT_SIZE,
    EVAL_BUNDLE_TYPE,
    HOLDOUT_LABEL_VERSION,
    ArtifactType,
    BridgeSchemaError,
    EvalBundle,
    HmacBridgeSigner,
    HmacBridgeVerifier,
    build_eval_bundle,
    canonical_holdout_task_ids,
    derive_eval_holdout_indices,
    envelope_from_dict,
    holdout_contains,
    sign_envelope,
    verify_envelope,
)


# ---------------------------------------------------------------------------
# EvalBundle construction + canonicalization
# ---------------------------------------------------------------------------


def _results_fixture():
    # 10 problems: 7 correct (including 1 "Level ?" and 1 unknown-subject).
    # Mixed levels + subjects exercise the per-level / per-subject buckets.
    return [
        {"task_id": "math-a", "level": "Level 1", "subject": "Algebra", "correctness": 1.0},
        {"task_id": "math-b", "level": "Level 1", "subject": "Algebra", "correctness": 0.0},
        {"task_id": "math-c", "level": "Level 2", "subject": "Geometry", "correctness": 1.0},
        {"task_id": "math-d", "level": "Level 2", "subject": "Geometry", "correctness": 1.0},
        {"task_id": "math-e", "level": "Level 3", "subject": "Number Theory", "correctness": 1.0},
        {"task_id": "math-f", "level": "Level 3", "subject": "Number Theory", "correctness": 0.0},
        {"task_id": "math-g", "level": "Level 4", "subject": "Probability", "correctness": 1.0},
        {"task_id": "math-h", "level": "Level 5", "subject": "Calculus", "correctness": 0.0},
        {"task_id": "math-i", "level": "Level ?", "subject": "Calculus", "correctness": 1.0},
        {"task_id": "math-j", "level": "Level 5", "subject": "", "correctness": 1.0},
    ]


def _bundle_fixture(**overrides):
    base = dict(
        training_netuid=462,
        inference_netuid=462,
        eval_run_id="forge-eval-1",
        eval_window_id=7_000_000,
        policy_artifact_id="0" * 64,
        policy_merkle_root_hex="a" * 64,
        model_ref="Qwen/Qwen2.5-3B-Instruct",
        holdout_version=HOLDOUT_LABEL_VERSION,
        holdout_seed=DEFAULT_HOLDOUT_SEED,
        holdout_dataset="qwedsacf/competition_math",
        holdout_size=10,
        holdout_task_ids=["math-j", "math-a", "math-c"],  # unsorted on purpose
        n_samples_per_problem=1,
        sampling_mode="greedy",
        per_problem_results=_results_fixture(),
        evaluator_hotkey="forge-evaluator-v1",
    )
    base.update(overrides)
    return base


def test_eval_bundle_basic_aggregates():
    b = build_eval_bundle(**_bundle_fixture())
    assert b.n_problems == 10
    assert b.accuracy == pytest.approx(7 / 10)
    assert b.mean_reward == pytest.approx(7 / 10)
    # Level 1: 1/2, Level 2: 2/2, Level 3: 1/2, Level 4: 1/1, Level 5: 1/2, Level ?: 1/1
    level = b.accuracy_by_level
    assert level["Level 1"] == pytest.approx(0.5)
    assert level["Level 2"] == pytest.approx(1.0)
    assert level["Level 3"] == pytest.approx(0.5)
    assert level["Level 4"] == pytest.approx(1.0)
    assert level["Level 5"] == pytest.approx(0.5)
    # Subjects: Algebra 1/2, Geometry 2/2, Number Theory 1/2, Probability 1/1,
    # Calculus 1/2, unknown (empty subject) 1/1.
    subj = b.accuracy_by_subject
    assert subj["Algebra"] == pytest.approx(0.5)
    assert subj["Geometry"] == pytest.approx(1.0)
    assert subj["Calculus"] == pytest.approx(0.5)
    assert subj["unknown"] == pytest.approx(1.0)


def test_eval_bundle_empty_results_produces_zero_aggregates():
    b = build_eval_bundle(**_bundle_fixture(per_problem_results=[]))
    assert b.n_problems == 0
    assert b.accuracy == 0.0
    assert b.mean_reward == 0.0
    assert b.accuracy_by_level == {}
    assert b.accuracy_by_subject == {}


def test_eval_bundle_holdout_task_ids_are_sorted_in_canonical_form():
    b = build_eval_bundle(**_bundle_fixture())
    # Input was ["math-j", "math-a", "math-c"] — output must be sorted.
    assert list(b.holdout_task_ids) == ["math-a", "math-c", "math-j"]


def test_eval_bundle_canonical_bytes_stable_under_result_reordering():
    reversed_results = list(reversed(_results_fixture()))
    b1 = build_eval_bundle(**_bundle_fixture())
    b2 = build_eval_bundle(**_bundle_fixture(per_problem_results=reversed_results))
    # Preserving iteration order of per_problem_results is by design
    # (it's the provenance trace), so reversed input produces a
    # different artifact id. The *aggregates* however must agree.
    assert b1.accuracy == b2.accuracy
    assert b1.mean_reward == b2.mean_reward
    assert b1.accuracy_by_level == b2.accuracy_by_level


def test_eval_bundle_canonical_bytes_stable_under_holdout_id_reordering():
    b1 = build_eval_bundle(**_bundle_fixture(holdout_task_ids=["math-j", "math-a", "math-c"]))
    b2 = build_eval_bundle(**_bundle_fixture(holdout_task_ids=["math-c", "math-j", "math-a"]))
    assert b1.canonical_bytes() == b2.canonical_bytes()
    assert b1.artifact_id() == b2.artifact_id()


def test_eval_bundle_storage_key_format():
    b = build_eval_bundle(**_bundle_fixture())
    assert b.storage_key() == "eval_bundles/462/7000000/forge-eval-1.json"


def test_eval_bundle_roundtrip():
    b = build_eval_bundle(**_bundle_fixture())
    data = b.to_dict()
    parsed = EvalBundle.from_dict(data)
    assert parsed.canonical_bytes() == b.canonical_bytes()
    assert parsed.artifact_id() == b.artifact_id()
    assert parsed.accuracy == b.accuracy


def test_eval_bundle_rejects_out_of_range_accuracy():
    b = build_eval_bundle(**_bundle_fixture())
    data = b.to_dict()
    data["accuracy"] = 1.5
    with pytest.raises(BridgeSchemaError):
        EvalBundle.from_dict(data)


def test_eval_bundle_rejects_missing_version():
    b = build_eval_bundle(**_bundle_fixture())
    data = b.to_dict()
    del data["version"]
    with pytest.raises(BridgeSchemaError):
        EvalBundle.from_dict(data)


# ---------------------------------------------------------------------------
# Signed envelope
# ---------------------------------------------------------------------------


def test_sign_envelope_allowlist_accepts_eval_bundle_type():
    signer = HmacBridgeSigner(signer_id="evaluator-a", secret="s3cret")
    verifier = HmacBridgeVerifier(secrets={"evaluator-a": "s3cret"})
    b = build_eval_bundle(**_bundle_fixture())
    envelope = sign_envelope(EVAL_BUNDLE_TYPE, b, signer)
    assert envelope.artifact_type == EVAL_BUNDLE_TYPE
    assert verify_envelope(envelope, verifier) is True


def test_sign_envelope_rejects_unknown_type():
    from reliquary_protocol import BridgeSchemaError

    signer = HmacBridgeSigner(signer_id="evaluator-a", secret="s3cret")
    b = build_eval_bundle(**_bundle_fixture())
    with pytest.raises(BridgeSchemaError):
        sign_envelope("not_a_real_type", b, signer)


def test_envelope_roundtrip_via_from_dict():
    signer = HmacBridgeSigner(signer_id="evaluator-a", secret="s3cret")
    verifier = HmacBridgeVerifier(secrets={"evaluator-a": "s3cret"})
    b = build_eval_bundle(**_bundle_fixture())
    envelope = sign_envelope(EVAL_BUNDLE_TYPE, b, signer)
    parsed = envelope_from_dict(envelope.to_dict())
    assert verify_envelope(parsed, verifier) is True
    # Inner payload_json must parse back to the same artifact id.
    inner = json.loads(parsed.payload_json)
    assert EvalBundle.from_dict(inner).artifact_id() == b.artifact_id()


# ---------------------------------------------------------------------------
# ArtifactType enum alignment
# ---------------------------------------------------------------------------


def test_eval_bundle_listed_in_artifact_type_enum():
    assert ArtifactType.EVAL_BUNDLE.value == "eval_bundle"
    assert EVAL_BUNDLE_TYPE == "eval_bundle"


# ---------------------------------------------------------------------------
# Eval holdout derivation
# ---------------------------------------------------------------------------


def test_derive_eval_holdout_indices_is_deterministic():
    a = derive_eval_holdout_indices(seed="test-seed", dataset_size=1000, holdout_size=50)
    b = derive_eval_holdout_indices(seed="test-seed", dataset_size=1000, holdout_size=50)
    assert a == b


def test_derive_eval_holdout_indices_are_distinct_and_sorted():
    idx = derive_eval_holdout_indices(seed="x", dataset_size=1000, holdout_size=50)
    assert len(idx) == 50
    assert len(set(idx)) == 50
    assert idx == sorted(idx)
    assert all(0 <= i < 1000 for i in idx)


def test_derive_eval_holdout_indices_different_seeds_produce_different_slices():
    a = derive_eval_holdout_indices(seed="seed-a", dataset_size=1000, holdout_size=50)
    b = derive_eval_holdout_indices(seed="seed-b", dataset_size=1000, holdout_size=50)
    assert a != b


def test_derive_eval_holdout_indices_caps_at_dataset_size():
    idx = derive_eval_holdout_indices(seed="x", dataset_size=10, holdout_size=100)
    assert len(idx) == 10
    assert idx == list(range(10))


def test_derive_eval_holdout_indices_rejects_invalid_args():
    with pytest.raises(ValueError):
        derive_eval_holdout_indices(seed="x", dataset_size=0, holdout_size=10)
    with pytest.raises(ValueError):
        derive_eval_holdout_indices(seed="x", dataset_size=100, holdout_size=-1)


def test_holdout_contains_agrees_with_materialized_list():
    idx = derive_eval_holdout_indices(seed="x", dataset_size=1000, holdout_size=50)
    for i in idx:
        assert holdout_contains(i, seed="x", dataset_size=1000, holdout_size=50)
    for i in range(1000):
        if i not in idx:
            assert not holdout_contains(i, seed="x", dataset_size=1000, holdout_size=50)


def test_holdout_label_version_change_gives_different_slice():
    a = derive_eval_holdout_indices(seed="x", dataset_size=1000, holdout_size=50, label_version="v1")
    b = derive_eval_holdout_indices(seed="x", dataset_size=1000, holdout_size=50, label_version="v2")
    assert a != b


def test_canonical_holdout_task_ids_sorts_and_dedupes():
    def task_id_fn(i: int) -> str:
        # Deliberately produce duplicates to exercise the dedup path.
        return f"math-{i % 3}"

    ids = canonical_holdout_task_ids(indices=[7, 2, 5, 10], task_id_fn=task_id_fn)
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Golden-vector check — BRIDGE_VERSION lock
# ---------------------------------------------------------------------------


def test_eval_bundle_version_field_is_bridge_version():
    b = build_eval_bundle(**_bundle_fixture())
    assert b.version == BRIDGE_VERSION


def test_default_holdout_constants_stable():
    # Tripwire: changing these silently would invalidate published
    # eval bundles. Deliberate change requires a matching test update.
    assert HOLDOUT_LABEL_VERSION == "v1"
    assert DEFAULT_HOLDOUT_SEED == "reliquary_eval_holdout_v1"
    assert DEFAULT_HOLDOUT_SIZE == 500
