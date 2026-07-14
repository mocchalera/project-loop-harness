# Local Skill usage report

`pcl report skill-usage` is an explicit, local, read-only dogfood report for the
bundled `project-control-loop` Skill. It scans existing Codex, Claude, and
Cockpit JSONL logs and reports aggregate Skill execution, normalized `pcl`
command families, friction signals, and advisory improvement candidates.

```bash
pcl report skill-usage
pcl report skill-usage --since 2026-07-01 --until 2026-07-31 --json
pcl report skill-usage --source codex --source claude --output /tmp/pcl-usage.md
```

The default window is the latest 30 days. Default roots are:

- `~/.codex/sessions`
- `~/.claude/projects`
- `~/.agi-tools/data/cockpit/task-reports`

Use `--codex-root`, `--claude-root`, or `--cockpit-root` for fixtures or custom
installations. Missing roots are reported as unavailable rather than treated as
an error. The optional output file is replaced atomically. Output inside a
scanned log root or over authoritative PCL state is rejected.

## Privacy boundary

The scanner processes raw JSONL only in local memory. Its JSON and Markdown
outputs never retain:

- prompts, assistant messages, or tool output;
- command arguments or raw command text;
- session IDs, Cockpit task IDs, or absolute log paths;
- workspace paths or file contents.

The command performs no network request, external transmission, background
monitoring, database mutation, or event append. Cockpit reports are counted as
separate control-plane task signals and are not added to Codex/Claude agent
session totals.

Friction rows contain command breakdowns made only from the same normalized
allowlisted labels used by the command summary. They never contain command
arguments. A typed output signal is associated with every normalized PCL
command in its matching tool call; the breakdown is therefore attribution,
not a partition of the signal total. JSON includes the full breakdown and
Markdown shows the three leading commands.

When a supported Codex or Claude result explicitly reports success, historical
failure wording in its output is not classified as a new finish-check,
guarded-block, timeout, or command-error signal. A successful
`COMPLETED_WITH_RISK` result is counted only when a typed completion outcome is
present. Explicit failures keep normal friction and retry attribution. Results
whose adapter status is unknown retain the best-effort text classification for
backward compatibility.

The report also excludes its own non-failed output from friction
classification. This prevents aggregate or truncated `report skill-usage`
output from recursively creating a new copy of the findings it is displaying.

When `rg` is available, PCL uses it only as a local read accelerator and parses
the selected JSONL records itself. The standard-library streaming fallback
keeps the command functional without `rg`.

## Interpretation limits

The report identifies execution signals, not intent. A command error, timeout,
help probe, or repeated command is an observed signal and does not prove a PCL
defect. `repeated_command` means that the next detected PCL call after a command
error, timeout, or guarded-execution block repeated the same normalized command
family. Routine lifecycle reuse elsewhere in a session is not retry friction.
Unknown transcript adapters and retries separated across log shards can be
undercounted. Results are therefore advisory and must not change the Skill or
project state automatically.

## Improvement loop

1. Run a fixed date-window report and preserve the aggregate artifact.
2. Select one high-frequency candidate for human review.
3. Reproduce the candidate with a minimal sanitized fixture.
4. Register the behavior as a Feature, Story, and Test in PCL.
5. Implement the smallest fix and run the regression suite.
6. Re-run the same report window or a subsequent cohort and compare counts.

Only a reproduced fixture becomes regression evidence. The raw local transcript
never becomes a checked-in fixture.
