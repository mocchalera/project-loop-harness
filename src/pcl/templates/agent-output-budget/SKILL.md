---
name: agent-output-budget
description: Route eligible noisy verification argv through pcl exec while preserving command semantics.
---

# Agent Output Budget

This Skill is host-neutral. It describes the policy; it does not execute commands,
rewrite argv, or provide proof or lifecycle authority.

## Classify before routing

Use the public classifier with an already-tokenized JSON argv array:

```bash
pcl agent-output classify --argv-json '["npm","run","verify:full"]' --json
```

- `eligible`: a direct, non-interactive verification command whose useful result is
  bounded success/failure plus diagnostics. This includes exact non-interactive
  installs such as `pip install --no-input`, `python -m pip install --no-input`,
  and `go install`. Use `pcl exec -- <argv...>`.
- `negative`: searches, diffs, file reads, complete-output reports, interactive
  tools, watch/server/REPL/interactive-installer commands, streams, or
  output-as-artifact work. Installs that may prompt remain unchanged.
  Leave the argv unchanged.
- `unknown`: insufficient evidence, shell syntax, malformed quoting, paths, secrets,
  or an unsupported command shape. Leave the argv unchanged.
- `already_wrapped`: `pcl exec -- ...`, `pcl --json exec -- ...`, or
  `python -m pcl exec -- ...` is already bounded. Do not nest another wrapper.

The classifier never reparses a shell string and never reconstructs shell syntax.
Pipelines, redirections, substitutions, compound commands, functions, heredocs,
and newlines remain `unknown`.

## Result handling

- On `PASS`, accept the typed result and do not read diagnostics merely to reconfirm
  success.
- On non-PASS results, inspect only the bounded presentation first; use
  `pcl exec show <run-id> --errors` when a retained diagnostic is needed.
- Do not automatically retry a failed command. Preserve the first failure when a
  separately authorized higher-level flow retries.
- Do not upload raw logs. Retained diagnostics remain bounded and local.

## Host boundary

Host observations and future hooks are audit-only. They must preserve the observed
argv and result, must not deny, rewrite, replace, retry, or invoke the observed
command, and must not add execution authority. Host-specific projections are
generated from this Skill and the canonical policy; edit neither a projection nor
the host's normal interactive terminal semantics by hand.
