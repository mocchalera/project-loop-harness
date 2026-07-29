# 0214 Non-HEAD Goal packet routing validation

**Verified:** 2026-07-29

**Correction base:** `d64d38df6f218613889fedbf7a2861ad304fbc61`

**Outcome:** the v0.5.5 local release candidate is corrected and ready for
review; it is not published

## Contract and implementation

Release-preparation dogfood recorded that exact-goal packet `E-0686`, emitted
with explicit ancestor base `4ee1299`, exactly matched a current recapture
using that base. `pcl next --target G-0075` nevertheless defaulted its
recapture to HEAD and proposed another long finish.

Task `T-0154`, Feature `F-0083`, approved Story `US-0087`, and Tests
`TC-0202`–`TC-0203` freeze the correction:

- resolve the newest exact-goal packet through the existing completion-proof
  service;
- read its validated `repository.base_revision`;
- pass that base to the shared repository snapshot service;
- require exact repository-object equality;
- fail closed on invalid shape, an unresolvable base, or actual drift.

No completion-packet field, public JSON shape, exit semantic, schema, or
dependency changed. Latest-only, exact-target, Evidence health, low-risk,
timeout precedence, and repository-drift checks remain shared and unchanged.

## Fail-first and source verification

- RED:
  `tests/test_goal_close_routing.py::test_next_routes_current_goal_packet_with_explicit_ancestor_base`
  failed on the release-candidate base because the route type was
  `emit_completion_packet`, not `close_goal`.
- Focused GREEN: 2 passed in 2.62 seconds.
- Goal routing file: 10 passed in 18.43 seconds.
- Related routing/lifecycle suite: 58 passed in 27.54 seconds.
- `PYTHONPATH=src ruff check .`: passed.
- Full source suite: 1,270 passed, 1 skipped in 603.86 seconds.
- Isolated official MCP SDK conformance suite: 9 passed in 2.67 seconds.

The expected source-suite skip is the optional official MCP SDK gate in the
canonical environment.

## Source dogfood

A temporary real Git project reproduced the production shape:

- packet base: `2a331a815bb54440dc27370cd5c28ba544f77dae`;
- later HEAD: `f5993785c4ce2edd61137169924fbb6118657a78`;
- repository remained dirty after that HEAD;
- pre-packet `next --target G-0001` returned
  `emit_completion_packet`;
- packet `E-0003` was `COMPLETED_VERIFIED`;
- post-packet `next --target G-0001` returned the exact
  Evidence-bound `close_goal`;
- DB and events SHA-256 values were unchanged across the read-only `next`;
- executing that route closed only `G-0001`, after which explicit routing
  returned `target_terminal`;
- final strict doctor/validation had zero findings, audit was clean for all
  15 events, and render passed.

The generated scratch configuration initially failed strict doctor because
optional commands were empty. It was corrected rather than weakening strict
validation.

## Build and corrected candidate artifacts

The final candidate artifacts were built after completing Task 0214's source
and release documentation and before adding the self-referential hashes below.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `project_loop_harness-0.5.5-py3-none-any.whl` | 569776 | `25e3cc0532e3b1016a71bbeb34f8680f94cd60ff530e7e2bf1ea77d642997bd6` |
| `project_loop_harness-0.5.5.tar.gz` | 1618206 | `0538ad171f8c424025f6241c65d43da19ad003d6a6aed57fb90b0761a73b8c7a` |

- `python -m build --sdist --wheel`: passed.
- `python -m twine check`: passed for both artifacts.
- Extracted-sdist contract verification: passed.
- Version, metadata, runtime dependency, CLI, and MCP entry-point checks:
  passed.

## Installed-wheel non-HEAD routing dogfood

An isolated Python 3.13 environment installed the exact final candidate wheel
with `--no-deps` and with `PYTHONPATH` removed:

- CLI, import, and installed metadata all resolved to `0.5.5` from
  `site-packages`;
- explicit packet base `ab98faa25e173ff6d01d77cac85193a7cec2c2d8`
  remained current at later HEAD
  `f16338c3b3cbc40941e397dc22f8ac366d751662` with dirty source;
- finish emitted 14 ordered JSONL progress records with no dropped record;
- packet `E-0003` was `COMPLETED_VERIFIED`;
- the verification effect was `read_only`;
- `next --target G-0001` returned exact Evidence-bound `close_goal`;
- DB and event hashes were identical before and after that read-only route;
- close affected only `G-0001`, then routing returned `target_terminal`;
- strict doctor/validation returned zero findings, audit was clean for all 15
  events, and render passed.

The earlier preflight-wheel run correctly rejected an
allowlist-incompatible `py_compile` check. A second preflight attempt also
rejected verification input mutation from pytest caches. The exact final
candidate used allowlisted, no-cache Ruff checks; its effect classification was
read-only.

## Project Loop Evidence

- Reproduction: `E-0687`.
- Story/Test plan: `E-0690`.
- Fail-first regression: `E-0691`.
- Targeted/full/source dogfood GREEN: `E-0692`.
- Final candidate artifacts and exact-wheel dogfood bundle: `E-0693`.
- Task closeout packet and final scoped audit are emitted after the coherent
  source commit so their repository binding reflects the reviewed milestone.

## Residual risks and publication boundary

- Local verification uses macOS arm64 and Python 3.13.12. Python 3.10-3.12,
  Linux, Windows, and remote official MCP coverage remain for separately
  authorized remote CI.
- The installed-wheel scratch project used locally installed dev-only Ruff for
  its configured checks. The project wheel itself was installed with
  `--no-deps`; runtime dependencies remain empty.
- Existing license metadata deprecation warnings remain a future packaging
  maintenance item and are not hidden by this correction.
- Final local artifact hashes intentionally precede their self-referential
  insertion into this Evidence note. Any publication must rebuild from the
  reviewed release commit and record or compare public artifact hashes.
- Existing `.claude`, `.playwright-cli`, `.work`, and Project Loop lock/local
  state remains unrelated and outside the release-candidate diff.
- No push, tag, GitHub Release, PyPI/TestPyPI upload, pipx mutation,
  announcement, or external write occurred.
