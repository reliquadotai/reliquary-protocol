"""Tests for ArtifactType + content_addressable_id."""

from __future__ import annotations

from reliquary_protocol.artifacts import (
    ArtifactType,
    ArtifactTypes,
    content_addressable_id,
)


def test_artifact_type_values_are_lowercase_strings() -> None:
    for member in ArtifactType:
        assert member.value.islower() or "_" in member.value
        assert isinstance(member.value, str)


def test_artifact_type_known_members() -> None:
    known = {
        "task_batch",
        "completion",
        "verdict",
        "scorecard",
        "window_manifest",
        "run_manifest",
        "policy",
        "rollout",
        "distill_trace",
        "checkpoint",
    }
    assert known <= {m.value for m in ArtifactType}


def test_artifact_types_tuple_is_immutable_and_matches_enum() -> None:
    assert isinstance(ArtifactTypes, tuple)
    assert set(ArtifactTypes) == {m.value for m in ArtifactType}


def test_content_addressable_id_is_hex_sha256() -> None:
    digest = content_addressable_id({"a": 1})
    assert len(digest) == 64
    assert all(ch in "0123456789abcdef" for ch in digest)


def test_content_addressable_id_deterministic_under_key_reorder() -> None:
    a = content_addressable_id({"x": 1, "y": 2})
    b = content_addressable_id({"y": 2, "x": 1})
    assert a == b


def test_content_addressable_id_changes_with_payload() -> None:
    a = content_addressable_id({"x": 1})
    b = content_addressable_id({"x": 2})
    assert a != b


def test_content_addressable_id_nested_payload() -> None:
    payload = {
        "artifact_type": "verdict",
        "window_id": 42,
        "payload": {"accepted": True, "scores": {"reward": 1.0}},
    }
    digest = content_addressable_id(payload)
    assert len(digest) == 64
