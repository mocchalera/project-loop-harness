# 0213: v0.5.5 local release preparation

- **Status:** Approved; preparation in progress
- **Milestone:** v0.5.5 Finish Reliability and Operability
- **Priority:** P0
- **Size:** M
- **Dependency:** completed PCL real-use friction P0 work and approved P1
  progress/compact-output/Goal-close slices through task 0212
- **Project Loop:** Goal `G-0075`, Task `T-0153`, Feature `F-0082`,
  Story `US-0086`, Tests `TC-0199`–`TC-0201`
- **Candidate base:** `4ee1299215a55cd59b0e132c874d6f2d6760bd5a`
- **DB schema:** remains 8

## Goal

Prepare a reviewable local v0.5.5 release candidate containing the completed
finish-safety, target-bound routing, execution binding, progress visibility,
compact output, and exact Goal completion-packet close-routing milestones.
Keep remote CI and every publication action as a separate, explicitly
authorized operation.

## Release scope

The candidate packages the coherent post-v0.5.4 runtime improvements:

1. deterministic finish input manifests and isolated verification workspaces;
2. structured result/stability Evidence and immutable compatible-check reuse;
3. shared terminal readiness and explicit Task/Goal attach/routing;
4. scoped audit diagnostics and bounded finish/start retry behavior;
5. execution binding and progress receipts;
6. streaming finish progress and compact actual-result projection;
7. current exact-goal completion-packet routing to an evidence-bound close
   command.

Unfinished broader P1 ideas such as completion-packet/v2, automatic Cockpit
ingest, history projection, flake quarantine, DB migrations, and dependency
additions are not part of this candidate.

## Scope

1. Align package, runtime, CLI/MCP fixture, baseline fixture, README current-
   version wording, task indexes, and a new release note on v0.5.5.
2. Describe only behavior and contracts already committed after public v0.5.4.
3. Run source QA, optional MCP conformance, advisory retrieval evaluation, and
   a new source-checkout scratch-project init/doctor/strict-validation/audit/
   render smoke.
4. Build wheel and sdist outside the repository, run Twine and extracted-sdist
   contracts, and run a clean-wheel CLI/MCP/init/doctor/strict-validation/
   audit/render smoke with `PYTHONPATH` removed.
5. Record exact commands, results, artifact hashes, known repository-local
   audit findings, candidate boundary, and residual platform risk as immutable
   Evidence.
6. Commit only task-owned release-candidate files.

## Invariants

- No Git push or tag, GitHub Release, PyPI/TestPyPI upload, pipx mutation,
  external announcement, or other publication action.
- No schema migration, dependency addition, hosted service, telemetry,
  production configuration, or unrelated runtime behavior change.
- Existing `.claude`, `.playwright-cli`, `.work`, and Project Loop lock/local
  state remain outside the release commit.
- Historical release notes, tags, Evidence, and launch records retain their
  original versions and claims.
- Repository audit findings are not weakened, hidden, or called clean when
  they remain `issues_found`.
- Remote Python 3.10–3.13, Linux, Windows, and official MCP CI remain pending
  until a separately authorized push.

## Acceptance

1. `pyproject.toml`, `pcl.__version__`, source CLI output, MCP transcript
   fixture, baseline version fixture, wheel metadata, sdist metadata, installed
   import, and installed metadata agree on `0.5.5`.
2. `TASKS.md`, `agent-tasks/README.md`, and the sdist include task 0212, this
   task 0213, and the v0.5.5 release note.
3. Ruff, the full pytest suite, optional MCP conformance when available, and
   advisory retrieval evaluation pass from the canonical source checkout.
4. A fresh source scratch project passes init, strict doctor/validation, clean
   audit, and render.
5. Wheel and sdist build, Twine, extracted-sdist contracts, metadata checks,
   and clean-wheel smoke pass.
6. Artifact SHA-256 hashes, sizes, source commit boundary, known warnings, and
   publication boundary are reviewable in write-once Evidence.
7. The final local release-candidate commit contains no unrelated or public
   mutation and `G-0075` stops at the publication-approval boundary.

## Stop conditions

Stop and request a new decision before:

- changing DB schema or dependencies;
- intentionally changing a public contract beyond the already completed
  post-v0.5.4 commits;
- repairing or superseding historical Evidence outside this task;
- weakening source, audit, packaging, or clean-install gates;
- pushing commits or tags;
- creating a GitHub Release;
- uploading to PyPI/TestPyPI;
- changing pipx or posting an announcement.
