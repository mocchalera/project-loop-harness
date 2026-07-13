# 0164 guided dashboard validation

## Outcome

The guided dashboard review experience satisfies the implementation and
compatibility acceptance criteria except for the still-pending final Claude
Fable verdict. The operator summary is rendered in HTML only, the existing
`dashboard-data/v1` contract is unchanged, and all bundled Project Loop Skill
copies contain the same presentation rules.

## Automated verification

- `ruff check .`
  - Result: passed.
- `PYTHONPATH=src pytest -q`
  - Result: `963 passed, 1 skipped in 196.02s`.
- Focused dashboard, data-contract, next-action, distribution, adoption, and
  init suites
  - Result: `76 passed in 14.92s`.
- Initial red run for the new behavior
  - Result: four expected failures before implementation; recorded separately
    in `docs/evidence/0164-guided-dashboard-red-tests.md`.

## Browser verification

Cockpit browser verification confirmed:

- the Japanese `今 / 完了 / 次 / あなたの判断 / 注意点` summary appears
  before internal counters and tables;
- advanced Project Loop information is initially closed in native
  `<details>/<summary>` and opens without script;
- navigating to `#row-E-0225` opens the enclosing disclosure and scrolls to
  the evidence row, so existing fragment navigation remains reachable.

The Cockpit screenshot API uses a fixed capture viewport, so the explicit
420 px acceptance check used the documented Playwright fallback against a
temporary local HTTP server. `output/playwright/0164-dashboard-420px.png`
shows the five cards stacked without horizontal overflow or clipped content.
The only browser console message was an expected missing local `favicon.ico`
404; it does not affect the generated dashboard.

## Claude Fable review

Claude Fable's plan review returned "Approve with required amendments". The
implementation incorporates all five required amendments: evidence-backed
terminal `Done` entries, HTML-only derivation, structured localized sentences,
native script-free disclosure with fragment anchors, and separation of routine
silent rendering from the four presentation moments.

A final implementation review was requested at the milestone. After reading
the implementation, Claude Fable stopped with `You've hit your session limit ·
resets 3:40am (Asia/Tokyo)` before producing a verdict. Two fresh review tasks
were attempted; this external model limit is recorded as an unavailable
secondary review, not as evidence of implementation failure. Automated tests,
data-contract tests, and manual browser acceptance remained green.

## Acceptance mapping

1. Localized operator guidance precedes internals: verified by tests and both
   desktop and 420 px browser inspection.
2. Honest state semantics and proof-named `Done`: verified by unit tests and
   rendered output.
3. Progressive disclosure retains detailed panels: verified in Cockpit.
4. Repository render persists Japanese locale: verified by ordinary
   `PYTHONPATH=src python -m pcl render --root . --json` and
   `<html lang="ja">`.
5. Bundled Skill parity: verified by distribution tests.
6. Summary states, localization, determinism, and data contract: covered by the
   passing suite.
7. Desktop, narrow, and fragment navigation: manually verified as above.
8. Plan review findings resolved; final review attempt was blocked by the
   Claude session limit and remains pending before goal closure.
