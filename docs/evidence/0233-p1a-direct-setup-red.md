# P1-A Direct Setup fail-first evidence

Date: 2026-07-30

## Contract source

- Confirmed design: Cockpit task `b8dd2cd6`
- Independent review: Cockpit task `0716f0b4`
- Review disposition: High 0 / Medium 0
- Final tail decision: validation and routing do not mutate canonical dashboard
  artifacts; after the exclusive project-operation lock is acquired, recheck
  the HWM and call the current canonical renderer at most once only when the HWM
  still matches.

## Fail-first result

Before the Direct Setup implementation existed:

```text
PYTHONPATH=src python -m pytest -q tests/test_direct_setup.py
15 failed in 1.09s
```

The failures covered the absent one-call surface and its required strict-spec,
atomicity, idempotency, receipt, projector, tail, and compatibility behavior.
They were retained and expanded rather than weakened during implementation.

## Scope boundary

The red suite did not authorize a schema migration, dependency addition, Story
approval, P1-B terminal acceptance, P1-C Skill routing, hosted service, or
external write.
