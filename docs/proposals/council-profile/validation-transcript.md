# Council Profile proposal validation transcript

**Recorded:** 2026-07-12  
**Scope:** task 0154 proposal contracts only  
**Runtime dependency added:** no

The repository test uses only the Python standard library:

```text
$ ruff check tests/test_council_profile_proposal_contracts.py
All checks passed!

$ pytest -q tests/test_council_profile_proposal_contracts.py
........                                                                 [100%]
8 passed
```

It proves:

- exactly seven proposal schemas and their canonical examples are present;
- every schema declares Draft 2020-12 and closes its root object;
- candidate and later authorized requests have one stable basis digest despite
  different wall-clock and receipt-age presentation fields;
- manifest, request, Council run, bundle, and every listed artifact have
  recomputed exact-byte/canonical digests and sizes with consistent refs;
- a semantic route change invalidates the embedded human authorization;
- the targeted negative corpus is complete, including empty/dot path segments;
- the integrated roadmap has the same, visibly superseding
  `decision-proposal/v0` shape;
- `route_profile`, `runner_profile_id`, and `role_profile` are distinct.

An environment-local `jsonschema` installation was used as a proposal
transcript tool only; it is not declared by or imported from PLH runtime code:

```text
profile-manifest.discovery-council.json: PASS
profile-run-request.json: PASS
profile-output-bundle.json: PASS
council-run.json: PASS
claim-set.json: PASS
verification-plan.json: PASS
decision-proposal.json: PASS

profile-manifest-unknown-field.json: REJECT (1 schema finding)
profile-run-request-unsupported-version.json: REJECT (1 schema finding)
profile-output-bundle-bad-status.json: REJECT (1 schema finding)
profile-output-bundle-invalid-path-digest.json: REJECT (2 schema findings)
profile-output-bundle-invalid-segments.json: REJECT (1 schema finding)
```

`decision-proposal-bad-reference.json` and
`profile-run-request-authorization-basis-mismatch.json` are intentionally
schema-valid but semantically invalid; the standard-library repository test
proves those cross-document and digest failures. Runtime diagnostic
conformance belongs to task 0155.

