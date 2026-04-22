"""Deterministic eval-holdout index derivation.

The Reliquary eval harness runs the current policy against a fixed
held-out slice of the task dataset (typically Hendrycks MATH) and
publishes an :class:`~reliquary_protocol.bridge.EvalBundle` tagged with
the policy hash + the holdout task ids. For third parties to re-run
the eval independently, the holdout slice must be derivable from a
small set of public constants — the seed + the dataset size + the
holdout size — without any shared random state.

This module owns that derivation. Both runtimes (Ledger side, which
excludes these indices from the miner sampling pool, and Forge side,
which actually evaluates the policy) derive identical sets by calling
:func:`derive_eval_holdout_indices`.

The derivation is byte-stable across Python / platform / endian:

- Seed material is a UTF-8-encoded label concatenated with dataset
  parameters (no locale-dependent separators).
- The underlying RNG is Python's :class:`random.Random` with the
  standard Mersenne Twister; seeded from the first 8 hex chars of
  ``sha256(seed_material)``. This is the same primitive the Ledger
  already uses for window-batch deterministic sampling, so the
  two sides converge on the same draw order by construction.
- ``random.sample`` without replacement is deterministic given the
  seed + population size + sample size.

A protocol version bump is required to change any of: the label
format, the RNG algorithm, the seed-material encoding, or the sampling
call. Client code MUST pass :data:`HOLDOUT_LABEL_VERSION` through so
a silent upgrade doesn't land a different holdout under the same
published bundle.
"""

from __future__ import annotations

import hashlib
import random
from typing import Sequence

#: Incrementing version tag for the derivation label. If the algorithm
#: ever changes, bump this; published eval bundles carry the version
#: string so third-party reproduction stays exact.
HOLDOUT_LABEL_VERSION: str = "v1"

#: Default holdout size — 500 problems is the canonical MATH-500 slice
#: size used in published reasoning benchmarks, and at M=1 pass@1 greedy
#: it's small enough to complete in under 20 min on a single Blackwell.
DEFAULT_HOLDOUT_SIZE: int = 500

#: Default seed — any stable string works; keep this versioned to the
#: label so a deliberate re-seed requires a label bump too.
DEFAULT_HOLDOUT_SEED: str = "reliquary_eval_holdout_v1"


def derive_eval_holdout_indices(
    *,
    seed: str,
    dataset_size: int,
    holdout_size: int = DEFAULT_HOLDOUT_SIZE,
    label_version: str = HOLDOUT_LABEL_VERSION,
) -> list[int]:
    """Return a deterministic sorted list of holdout indices.

    Parameters
    ----------
    seed
        Public seed string. Two callers with the same ``seed`` +
        ``label_version`` + ``dataset_size`` + ``holdout_size`` derive
        byte-identical index lists on any platform.
    dataset_size
        Total number of problems in the source dataset. Must be >= ``holdout_size``.
    holdout_size
        Number of indices to draw. Capped at ``dataset_size``.
    label_version
        Algorithm version. Changing this deliberately produces a fresh
        holdout slice; the published :class:`EvalBundle` pins the
        version string so third parties can reproduce.

    Returns
    -------
    list[int]
        Sorted ascending list of ``holdout_size`` distinct indices in
        ``range(dataset_size)``.
    """
    if dataset_size <= 0:
        raise ValueError(f"dataset_size must be positive; got {dataset_size}")
    if holdout_size < 0:
        raise ValueError(f"holdout_size must be non-negative; got {holdout_size}")
    effective_size = min(int(holdout_size), int(dataset_size))
    seed_material = (
        f"reliquary_eval_holdout|{label_version}|{seed}|"
        f"dataset_size={int(dataset_size)}|holdout_size={effective_size}"
    )
    digest = hashlib.sha256(seed_material.encode("utf-8")).hexdigest()
    rng_seed = int(digest[:16], 16)
    rng = random.Random(rng_seed)
    indices = rng.sample(range(int(dataset_size)), effective_size)
    return sorted(indices)


def holdout_contains(
    index: int,
    *,
    seed: str,
    dataset_size: int,
    holdout_size: int = DEFAULT_HOLDOUT_SIZE,
    label_version: str = HOLDOUT_LABEL_VERSION,
) -> bool:
    """Return True iff ``index`` is in the derived holdout slice.

    Convenience for the Ledger-side sampling guard — avoids the caller
    materializing the full list when they just want an exclusion check.
    Internally still derives the full set (cached per seed/size by
    :func:`_cached_holdout_set`) so the check is O(1) after the first call.
    """
    return int(index) in _cached_holdout_set(
        seed=seed,
        dataset_size=dataset_size,
        holdout_size=holdout_size,
        label_version=label_version,
    )


def canonical_holdout_task_ids(
    *, indices: Sequence[int], task_id_fn
) -> list[str]:
    """Project holdout indices → sorted task id list.

    ``task_id_fn(index) -> str`` is caller-supplied so this module stays
    agnostic to the exact dataset layout (MATH's task id derivation
    lives in :mod:`reliquary_inference.dataset.task_sources.math_env`).
    The output is sorted lexicographically to match the
    :func:`build_eval_bundle` canonicalization rule.
    """
    return sorted({str(task_id_fn(int(idx))) for idx in indices})


# ---------------------------------------------------------------------------
# Internal cache — avoids re-drawing for every `holdout_contains` call
# ---------------------------------------------------------------------------


_HOLDOUT_CACHE: dict[tuple[str, int, int, str], frozenset[int]] = {}


def _cached_holdout_set(
    *,
    seed: str,
    dataset_size: int,
    holdout_size: int,
    label_version: str,
) -> frozenset[int]:
    key = (str(seed), int(dataset_size), int(holdout_size), str(label_version))
    cached = _HOLDOUT_CACHE.get(key)
    if cached is None:
        cached = frozenset(
            derive_eval_holdout_indices(
                seed=seed,
                dataset_size=dataset_size,
                holdout_size=holdout_size,
                label_version=label_version,
            )
        )
        _HOLDOUT_CACHE[key] = cached
    return cached


__all__ = [
    "DEFAULT_HOLDOUT_SEED",
    "DEFAULT_HOLDOUT_SIZE",
    "HOLDOUT_LABEL_VERSION",
    "canonical_holdout_task_ids",
    "derive_eval_holdout_indices",
    "holdout_contains",
]
