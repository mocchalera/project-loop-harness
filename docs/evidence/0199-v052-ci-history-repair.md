# 0199 v0.5.2 CI history repair

**Recorded:** 2026-07-18

**Failed run:** `29638536535`

## Finding

The first v0.5.2 release-candidate push passed local QA, Ubuntu/Windows MCP
conformance, and Windows CLI smoke, but the Python 3.10-3.13 test jobs each
failed the same five layered-ablation tests.

The failures were deterministic checkout-depth failures:

- `git rev-parse 7fa22b2` could not resolve the frozen baseline commit;
- `git show 7fa22b23917a7847dee56d574d16a14d9649e086:...` could not read its
  frozen Skill bytes;
- fixture materialization then failed closed because its source commit was
  unavailable.

GitHub Actions `actions/checkout@v4` fetches only the triggering commit by
default. The local repository passed because it has the required history.

## Repair

The Python test job now sets `fetch-depth: 0`. MCP conformance and Windows CLI
smoke keep their shallow checkout because they do not inspect historical Git
objects. No runtime, package, schema, or test expectation changed.

The release remains blocked until the replacement CI run passes every job.
