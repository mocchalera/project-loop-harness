# 0164 guided dashboard validation

## Outcome

The guided dashboard review experience satisfies the implementation and
compatibility acceptance criteria after remediation of the human-authorized
Codex substitute review. A clean independent re-review remains pending before
goal closure. The operator summary is rendered in HTML only, the existing
`dashboard-data/v1` contract is unchanged, and all bundled Project Loop Skill
copies contain the same presentation rules.

## Automated verification

- `ruff check .`
  - Result: passed.
- `PYTHONPATH=src pytest -q`
  - Result after Codex remediation: `967 passed, 1 skipped in 404.19s`.
- Focused dashboard, data-contract, next-action, distribution, adoption, and
  init suites
  - Result after Codex remediation: `80 passed in 38.38s`.
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
- after Codex remediation, the collapsed desktop view contains only the five
  structured operator cards; detailed risk, human-decision, and command content
  remains present after expanding the native disclosure.

The Cockpit screenshot API uses a fixed capture viewport, so the explicit
420 px acceptance check used the documented Playwright fallback against a
temporary local HTTP server. `output/playwright/0164-dashboard-420px.png`
shows the five cards stacked without horizontal overflow or clipped content.
The only browser console message was an expected missing local `favicon.ico`
404; it does not affect the generated dashboard.

## Independent review

Claude Fable's plan review returned "Approve with required amendments". The
implementation incorporates all five required amendments: evidence-backed
terminal `Done` entries, HTML-only derivation, structured localized sentences,
native script-free disclosure with fragment anchors, and separation of routine
silent rendering from the four presentation moments.

A final Claude Fable implementation review was requested at the milestone but
the provider stopped at its session limit before producing a verdict. The human
explicitly authorized independent Codex task `e491f178` as the substitute.
Codex returned `Changes required` with four blocking findings: manual actions
were labeled agent-safe, detailed commands remained outside disclosure,
historical Done events ignored current state, and direct state coverage was
incomplete. The findings are saved in
`docs/reviews/0164-guided-dashboard-codex-final-review.md` and were repaired
test-first. A clean substitute re-review is required before closure.

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
8. Claude plan findings and the first Codex substitute-review findings are
   resolved; a clean independent Codex re-review remains pending before goal
   closure.
