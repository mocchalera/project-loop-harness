# 0194-0196 Harness Minimization Integration Review

Date: 2026-07-18 (Asia/Tokyo)

## Integrated commits

| Task | Main commit | Reviewer result |
| --- | --- | --- |
| 0194 Skill prose/runtime parity | `d769f66` | Accepted after Skill diff, byte-parity, scope, targeted-test, and Ruff review |
| 0195 shared target resolver | `66c0c5c` | Accepted after public error/payload, policy-boundary, 43-test, and Ruff review |
| 0196 active/historical findings | `5ce17ec` | Accepted after allowlist correction, 55-test, report-contract, dogfood, and Ruff review |

## 0194 proof

- Four loaded/distributed Skill copies are byte-identical.
- Each Skill copy replaces six instruction lines with three runtime-bound
  lines; the manual stale-intent algorithm was removed while human gates,
  Evidence, mutation, and test rules remain.
- Independent reviewer command:
  `PYTHONPATH=src python -m pytest -q tests/test_skill_command_examples.py tests/test_cli_init.py -k 'skill or target_bound' tests/test_codex_plugin.py tests/test_command_guide.py tests/test_distribution.py`
- Result: 32 passed, 43 deselected. Ruff passed on touched tests.

## 0195 proof

- The shared resolver owns only bare `T-`/`G-` grammar and existence lookup.
- `next` retains target routing and its `Next target does not exist` payload;
  `resume` retains candidate selection, packet construction, and Task/Goal
  error messages.
- Independent reviewer command:
  `PYTHONPATH=src python -m pytest -q tests/test_next_actions.py tests/test_resume.py`
- Result: 43 passed. Ruff passed on resolver, callers, and tests.
- Worker full regression: 1090 passed, 1 skipped.

## 0196 proof

- Classification uses finding-code allowlists plus durable entity status or
  Evidence supersession links; it never parses messages or user intent.
- The reviewer rejected the first code-independent Evidence classification.
  The accepted implementation keeps unknown, provenance, and relationship
  finding codes active even for superseded Evidence.
- Independent reviewer focused suite: 55 passed. Ruff passed.
- Worker full regression: 1095 passed, 1 skipped.
- Current repository: strict validation exit 0, 0 errors, 29 warnings,
  `active=3`, `historical=26`. Active findings are current non-superseded
  Evidence drift; historical findings are terminal compatibility gaps.

## Scope audit

No schema migration, dependency addition, hosted service, telemetry,
generated-dashboard edit, or direct `.project-loop` database edit is included
in these commits. Phase 4 evaluation and Phase 5's evidence gate are specified
separately in tasks 0197 and 0198.
