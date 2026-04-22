# Changelog

All notable changes to **reliquary-protocol** are documented here. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
both Reliquary subnets pin to an exact version of this package so a
version bump here requires a coordinated pin bump on
[`reliquary-inference`](https://github.com/0xgrizz/reliquary-inference) and
[`reliquary`](https://github.com/0xgrizz/reliquary) in the same release window.

## [Unreleased]

### Added
- `R2ObjectBackend.list_detailed(prefix)` — returns
  `[{key, size, uploaded, etag}]` so callers that need to sort by
  upload time (audit index, metrics rollup) don't have to body-fetch
  every historical artifact just to sort them.
- `R2ObjectBackend` retry loop (`max_retries = 3`) with exponential
  backoff on 429 / 5xx / socket-timeout. Default request timeout
  raised 30 s → 120 s to match observed CF API tail latency under
  mesh load.
- Additional tests: `test_transient_429_retries_then_succeeds`,
  `test_transient_timeout_retries_then_succeeds`,
  `test_404_not_retried`, `test_list_detailed_reads_last_modified_field`,
  `test_list_detailed_falls_back_on_alternate_field_names`.

### Changed
- `R2ObjectBackend.list` is now a thin wrapper over `list_detailed` —
  keys-only callers keep working; metadata-aware callers opt in.

### Fixed
- CF R2 list API returns `last_modified` (snake_case), not the
  `uploaded` the previous implementation read. `list_detailed` now
  normalises the field name so downstream callers see a consistent
  `uploaded` key. Unblocks key-sorted artifact scanning in audit.py.
- 4xx-other-than-429 surfaces immediately; retrying those would mask
  caller-contract bugs.

## [0.1.0] - 2026-04-18

Initial public release. Shared protocol surface for the two Reliquary
subnets:

- Canonical serialization (`stable_json_dumps`, `sha256_json`,
  `canonical_bytes`).
- Protocol constants (`PRIME_Q`, `CHALLENGE_K`, `PROOF_TOPK`, sketch
  tolerance, mesh stake cap + quorum).
- Signature primitives (HMAC-SHA256 sign / verify helpers).
- Artifact identity (`content_addressable_id` + `ArtifactTypes` enum).
- Storage backends (`R2ObjectBackend` + filesystem backends).
- Bridge envelopes (`sign_envelope`, `verify_envelope`, `RolloutBundle`,
  `envelope_from_dict`).
