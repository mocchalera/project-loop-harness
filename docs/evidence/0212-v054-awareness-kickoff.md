# 0212 v0.5.4 awareness campaign kickoff

- **Date:** 2026-07-23 JST
- **Goal / Tasks:** G-0066 / T-0136 / T-0137
- **Decision:** DEC-0008
- **Human source:** Cockpit Ask `ask_00c0f7319a0b`
- **Selected outcome:** 認知拡大
- **Authority boundary:** every external post or message requires a separate
  exact human approval before execution

## Prepared artifacts

1. `README.md` no longer presents the cancelled v0.5.2 cohort as current work.
   The proof boundary is version-neutral and states that v0.5.4 has no current
   external cohort result.
2. `docs/launch/v0.5.4/awareness-plan-30d.md` fixes the audience, message,
   baseline, 30-day metrics, weekly sequence, channel roles, approval gates,
   observation contract, and stop conditions.
3. The first external action remains the existing immutable X draft `E-0587`.
   It is selected but not posted.

## GitHub baseline

Captured with the authenticated GitHub API at `2026-07-22T16:54:21Z`:

```json
{"stars":0,"forks":0,"open_issues":0,"watchers":0}
{"views_14d":27,"view_uniques_14d":4}
{"clones_14d":899,"clone_uniques_14d":192}
```

Clone data may include CI, bots, and tooling. It is explicitly excluded from
the campaign's success criteria and must not be described as a user count.

## Verification

```text
git diff --check
exit 0

rg -n "v0\.5\.2 is being judged|frozen cohort method" \
  README.md docs/launch/v0.5.4/awareness-plan-30d.md
no matches

PYTHONPATH=src pytest -q tests/test_adoption_docs.py tests/test_distribution.py
8 passed in 7.36s
```

The current official Hacker News Guidelines were rechecked on 2026-07-23 and
still state that generated or AI-edited text must not be posted. HN remains
outside this campaign's agent-authored channel plan.

## Hashes at evidence preparation

| Path | SHA-256 |
| --- | --- |
| `README.md` | `78c474f21b862ca23084dd4cfeac4d22c8b929b3f3e6eb4d4ff3e38ef81cbd4b` |
| `docs/launch/v0.5.4/awareness-plan-30d.md` | `5eed5a8b9b98b5c6b28683f7b972f88ef4e88641057676fc13dd81622bd4a726` |
| `docs/launch/v0.5.4/x-post-draft.md` | `d0ca157f87a95a1eef47eec6377e76097c8eb6bd48af13e57463fd2d62bb2391` |

## External-action record

- X post: not performed.
- Zenn or Reddit publication: not performed.
- Direct message or recruitment: not performed.
- Push or release mutation: not performed.
