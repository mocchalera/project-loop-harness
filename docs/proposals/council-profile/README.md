# Council Profile proposal contracts

This directory is the pre-runtime contract freeze for v0.5.0 task 0154.
Nothing here invokes an external runner or mutates Project Loop state.

- `ADR-005-external-council-profile-boundary.md` owns the human boundary
  decision.
- `contract-freeze.md` owns canonicalization, terminology, cross-reference,
  claim-to-proof, and authorization semantics that JSON Schema alone cannot
  express.
- `contracts/schemas/` contains the seven Draft 2020-12 proposal schemas.
- `contracts/examples/` contains canonical positive fixtures.
- `contracts/negative/` contains targeted fail-closed fixtures.
- `validation-transcript.md` records the repeatable validation command and
  result for this freeze.

Runtime validators and packaged built-in manifests do not land until task 0155.

