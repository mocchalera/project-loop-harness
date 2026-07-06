# Task 0086: Command Surface Alignment Before v0.2 (P0)

**Status: retroactive record. Implemented in commit `204a857` before
this spec was filed. This file exists to keep the task ledger
complete; do not re-implement.**

## Why

The approved v0.2 design draft proposed `pcl verify feedback`, but the
existing CLI top-level command is `verification` (`pcl verification
record` in README and help). Shipping a second `verify` namespace with
no stated relationship to `verification` would fracture the command
surface right before the feedback loop lands on it
(v0.1.12 review agenda, section 4.2).

## What was implemented (204a857)

- `docs/verification-feedback-design.md` was corrected in place:
  every occurrence of `pcl verify feedback` became
  `pcl verification feedback` (command example, referential-honesty
  note, sequencing entry, approval record).
- Decision recorded: no `verify` alias in v0.2. A short alias may be
  reconsidered later only as an explicit, documented alias — never as
  a parallel namespace.

## Verification

- `grep -rn "pcl verify " docs/ src/ README.md` matches nothing
  outside `docs/plh_v0_1_12_review_agenda.md`, which quotes the old
  proposal as a historical review record and stays unchanged.
- Task 0088 implements the subcommand under the existing
  `verification` parser (`src/pcl/cli.py`), keeping one namespace.
