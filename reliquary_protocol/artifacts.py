"""Artifact type enum + content-addressable id helpers.

Every cross-runtime artifact — task_batch, completion, verdict,
scorecard, window_manifest, run_manifest, eval_bundle — carries a
content-addressable id derived from its payload via canonical sha256.
Both runtimes derive the id the same way so an artifact hashes
identically wherever it's produced.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from .canonicalization import sha256_json


class ArtifactType(str, Enum):
    """Enumeration of cross-runtime artifact types.

    Each runtime may additionally define local-only artifact types
    (e.g. Forge's ``distill_pack``), but this enum lists what the
    other runtime is allowed to consume.
    """

    TASK_BATCH = "task_batch"
    COMPLETION = "completion"
    VERDICT = "verdict"
    SCORECARD = "scorecard"
    WINDOW_MANIFEST = "window_manifest"
    RUN_MANIFEST = "run_manifest"
    POLICY = "policy"
    ROLLOUT = "rollout"
    DISTILL_TRACE = "distill_trace"
    CHECKPOINT = "checkpoint"
    EVAL_BUNDLE = "eval_bundle"


#: Backwards-compatible tuple form — use this when you just need to
#: iterate over the names without importing the Enum itself.
ArtifactTypes: tuple[str, ...] = tuple(item.value for item in ArtifactType)


def content_addressable_id(payload: dict[str, Any]) -> str:
    """Return the canonical sha256 id for an artifact payload.

    Equivalent to :func:`reliquary_protocol.canonicalization.sha256_json`;
    exposed with a distinct name to document *intent* at the call site.
    """
    return sha256_json(payload)


__all__ = [
    "ArtifactType",
    "ArtifactTypes",
    "content_addressable_id",
]
