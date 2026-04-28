# Contributors

`reliquary-protocol` is the shared protocol package consumed by
[reliquary-ledger](https://github.com/reliquadotai/reliquary-ledger) and
[reliquary-forge](https://github.com/reliquadotai/reliquary-forge). It
contains canonical serialization, signature verification, R2 backend
abstraction, and the cross-runtime bridge envelopes
(`RolloutBundle`, `CheckpointAttestation`, `PolicyCommitment`).

## Maintainers

- [@0xgrizz](https://github.com/0xgrizz)
- [@0xgrizz](https://github.com/0xgrizz) (formerly active under another GitHub alias on early commits)

## Acknowledgments

### Upstream protocol heritage

The GRAIL hidden-state sketch primitive ported into this package is
derived from the upstream
[`grail`](https://github.com/grail-the-game/grail) project; the
sketch math is a clean-room port of
`grail/protocol/grail_verifier.py`.

### Parallel work — romain13190

[romain13190](https://github.com/romain13190) maintains a parallel
SN81 implementation at
[romain13190/reliquary](https://github.com/romain13190/reliquary)
which derives independently from the same upstream `grail` primitives.
Forensic review confirmed neither codebase imported from the other.
The shared protocol primitives in this package and the upstream
single-repo implementation converge because both descend from `grail`,
not because either copied the other.
