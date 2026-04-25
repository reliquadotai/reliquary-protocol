[![CI](https://github.com/reliquadotai/reliquary-protocol/actions/workflows/ci.yml/badge.svg)](https://github.com/reliquadotai/reliquary-protocol/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

# reliquary-protocol

Shared protocol package for the two Reliquary runtimes —
[**Ledger**](https://github.com/reliquadotai/reliquary-ledger) (inference runtime,
testnet netuid 462) and [**Forge**](https://github.com/reliquadotai/reliquary-forge)
(trainer-quorum runtime) — which run as companion protocols under a single
subnet. Canonical serialization, shared crypto primitives, and the on-chain
bridge envelopes live here so both runtimes stay byte-identical.

This package is the single authoritative home of:

- **Canonical serialization**: `stable_json_dumps`, `sha256_json`,
  `canonical_bytes` — byte-exact sort-keys JSON used for every
  content-addressable hash on either runtime.
- **Protocol constants**: proof-layer math parameters (`PRIME_Q`,
  `CHALLENGE_K`, `PROOF_TOPK`, sketch tolerance), consensus parameters
  (mesh stake cap, quorum, outlier gate), distribution validator bands.
- **Signature primitives**: HMAC-SHA256 sign/verify helpers for mesh
  verdicts, distillation traces, and bridge envelopes — the exact same
  format both runtimes emit and check.
- **Artifact identity**: `content_addressable_id(payload)` + the
  `ArtifactTypes` enum covering shared types (task_batch, completion,
  verdict, scorecard, window_manifest, run_manifest, rollout_bundle).
- **Storage backends**: `R2ObjectBackend` with 429/5xx retry + exponential
  backoff, `list_detailed()` exposing CF's `last_modified` for
  key-sorted artifact scans.
- **Bridge envelopes**: `sign_envelope` / `verify_envelope` / `RolloutBundle` /
  `envelope_from_dict` — the wire format Ledger's `RolloutBundlePublisher` and
  Forge's `InferenceRegistryAdapter` use to pass training data between runtimes.

## Why it exists

By the time both runtimes reach Tier 3, proof constants + sig helpers +
artifact schemas have been duplicated across the two repos for months.
A silent drift (one side bumps `PRIME_Q`, the other doesn't; one side
changes the sort-keys ensure_ascii flag) would corrupt every cross-runtime
commit. This package pins the shared surface, versions it, and publishes
it as a dependency so both runtimes lock to the same bytes.

## Versioning

Every release bumps `reliquary_protocol.VERSION`. Each runtime pins an **exact**
version in its own `pyproject.toml` so a coordinated upgrade lands
simultaneously on both sides. Version-upgrade runbook:

1. Bump `reliquary-protocol` minor version.
2. Land the matching bump on `reliquary-forge` and `reliquary-ledger` `pyproject.toml`
   in a single PR each.
3. Testnet bake for 24h — both runtimes running the new protocol version.
4. Mainnet rollout on a well-known block height; validators voting the
   upgrade commit their intent onchain before the cutover.
5. Any runtime still on the old version after the cutover is considered
   out-of-spec and its verdicts are rejected by up-to-date mesh peers.
   Slashing-style enforcement lands when the governance charter is
   committed on-chain (tracked in the protocol paper §12).

## Install

Editable install from the sibling repo layout:

```bash
pip install -e /Users/malouk/GRAIL/reliquary-protocol
```

Or pin in each runtime's `pyproject.toml`:

```toml
[project]
dependencies = ["reliquary-protocol==0.1.0"]
```

## Layout

```
reliquary_protocol/
    __init__.py           # VERSION + public re-exports
    canonicalization.py   # stable_json_dumps, sha256_json
    constants.py          # proof + mesh + distribution constants
    signatures.py         # HMAC sign/verify, label-escape, canonical-envelope helpers
    artifacts.py          # ArtifactTypes enum, content_addressable_id
tests/
    test_canonicalization.py
    test_signatures.py
    test_constants.py
    test_artifacts.py
```

## License

MIT. See the parent repos for lineage.
