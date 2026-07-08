# Task 0100: Evidence-to-Task Linking in Task Context Packs (M1, P2)

Origin: M0 master-trace dogfood (goal G-0002, 2026-07-08; runbook
`docs/master-trace-handoff.md`). M0's workaround — writing evidence
IDs and copied paths into the task description by hand — worked but
is omission-prone: the throwaway reproduction (evidence E-0024)
showed a task without description refs gets a context pack with no
route to adhoc evidence at all. This is the deliberately-generic
alternative to a `master_trace_context` pack section, which was
considered and rejected (see the runbook's Discarded Options).

## Scope

1. `pcl evidence add --task T-XXXX` links the recorded adhoc
   evidence row to an existing task. Invalid/unknown task id is a
   typed error with zero traces (same atomicity discipline as
   0093/0096/0099). Linking is optional; unlinked behavior is
   unchanged.
2. Task context packs gain a linked-evidence section listing, per
   linked evidence row: id, type, summary, manifest path, member
   path(s), `stored_path` when copied, and created_at. Do NOT inline
   member file contents by default.
3. The section is additive within `context-pack/v1` (same rule as
   0067/0078): packs without linked evidence are byte-identical to
   today's output.
4. Section ordering and `--max-tokens` budgeting follow the existing
   section-priority mechanism in `src/pcl/context.py`; document the
   chosen priority in `docs/context-pack.md`.
5. When linked evidence is model-derived (e.g. an intent index), the
   pack must carry the existing "claims, not verified facts"
   vocabulary — reuse the wording pattern from the code-context
   summary sections.

## Out of scope

- Linking to goals/jobs (`--goal`/`--job`); job evidence already
  flows through `_job_evidence`.
- A first-class trace entity or `pcl trace` command family.
- Retroactive linking of existing evidence rows (a separate
  `pcl evidence link` can be a later task if demand appears).
- Any DB migration beyond the minimal link column/table needed.

## Definition of done

- `pcl evidence add --task` round-trips: link recorded, visible in
  `pcl context pack --task ... --json`.
- Additive contract verified by a test asserting packs without links
  are unchanged.
- Tight `--max-tokens` budgets degrade the section per the documented
  priority without breaking required sections.
- `docs/context-pack.md`, `docs/data-model.md`, and command help
  updated.
- `pytest` passes; `pcl validate --strict --json` passes; `pcl init`
  smoke-tested against `/tmp/pcl-demo`.
- The M0 runbook (`docs/master-trace-handoff.md`) gets a short
  "M1 landed" note updating the Known Hole and Next Decision
  sections.
