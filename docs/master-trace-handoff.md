# Master Trace Handoff

M0 master-trace handoff is a dogfood workflow for pull-based agent
continuation. The master records its working trace as evidence, an external
agent builds a line-referenced intent index over that trace, and the worker
pulls the next task through `pcl next` and `pcl context pack`.

The goal is to preserve the master's reasoning without turning it into a long
push brief. M0 uses existing Project Loop Harness commands only. It does not
add a first-class trace entity, does not make `pcl` call an LLM, and does not
change context-pack behavior.

## Command Sequence

Capture the master transcript as a normal local artifact. Keep line numbers
stable once an index has been generated:

```bash
mkdir -p .work/fable
$EDITOR .work/fable/session-2026-07-08.md
```

Build an intent index outside `pcl`. The index is model-derived, so every item
must point back to transcript line ranges instead of standing on its own:

```json
{
  "contract_version": "intent-index/v0",
  "source_transcript": ".work/fable/session-2026-07-08.md",
  "items": [
    {
      "kind": "task_hint",
      "summary": "Write docs/master-trace-handoff.md",
      "source_ref": {
        "path": ".work/fable/session-2026-07-08.md",
        "line_start": 69,
        "line_end": 87
      }
    }
  ]
}
```

Record both artifacts with copied adhoc evidence:

```bash
python -m pcl evidence add \
  --file .work/fable/session-2026-07-08.md \
  --summary "Master transcript for M0 pull-context handoff" \
  --command "external master session transcript" \
  --copy \
  --json

python -m pcl evidence add \
  --file .work/fable/intent-index-2026-07-08.json \
  --summary "Model-derived intent index for M0 pull-context handoff" \
  --command "external intent-indexing agent over the master transcript" \
  --copy \
  --json
```

Create a goal and a worker task. Because M0 has no evidence-to-task link yet,
put the evidence IDs and durable copied paths directly in the task description:

```bash
python -m pcl goal create \
  --title "M0 dogfood: pull-context master-trace handoff" \
  --json

python -m pcl task create \
  --goal G-0002 \
  --title "Worker: infer and execute the next documented slice from the master trace" \
  --description "Pull-context experiment (M0). Read, in order: intent index evidence E-0023 at .project-loop/evidence/adhoc-files/e-0023/01-intent-index-2026-07-08.json; master transcript evidence E-0022 at .project-loop/evidence/adhoc-files/e-0022/01-session-2026-07-08.md. The index is model-derived; follow source_ref line numbers back into the transcript before acting." \
  --owner codex-worker \
  --risk low \
  --json
```

The worker starts from the control plane, not from chat history:

```bash
python -m pcl next --strict --json
python -m pcl context pack --task T-0004 --json
```

Then the worker reads the evidence paths named by the task description, follows
every `source_ref` line range back into the transcript, implements only the
inferred slice, verifies it, records output evidence with `--copy`, advances the
task through `python -m pcl`, and runs validation and rendering:

```bash
python -m pcl evidence add --file <artifact> --summary "<summary>" --copy --json
python -m pcl task status T-0004 done --reason "<evidence-backed reason>" --json
python -m pcl validate --strict --json
python -m pcl render --json
```

## Known Hole

Task context packs do not include unrelated adhoc evidence today. They render
task fields, dependencies, linked goal/feature/defect context, sibling tasks,
recent events, and optional code context. They do not discover copied adhoc
evidence by task, because `pcl evidence add` has no `--task`, `--goal`, or
`--job` attachment flag in M0.

That hole was reproduced during this dogfood slice:

- Reproduction evidence: `E-0024`
- Copied artifact:
  `.project-loop/evidence/adhoc-files/e-0024/01-pack-hole-reproduction.md`
- Observation: throwaway task `T-0005` had no evidence refs in its description;
  `python -m pcl context pack --task T-0005 --json` returned no `evidence`
  section, `source_paths: []`, and no mentions of `E-0022` or `E-0023`.

The M0 workaround is explicit: put the evidence IDs and durable copied paths in
the task description. That is intentionally plain and reviewable, but it is
manual and easy to omit.

## Intent Index Rules

Intent indexes are model-derived claims over the transcript. Treat each index
item as a pointer, not as a verified fact.

Before acting, the worker must:

1. Open the copied intent index evidence named by the task.
2. Read each relevant `source_ref.path`, `line_start`, and `line_end`.
3. Verify the claim against the copied transcript lines named by the task
   description. If `source_ref.path` names the original working path, use the
   copied transcript path as the durable read target.
4. Follow transcript constraints as binding when they are confirmed there.

This keeps the index useful for navigation without letting an indexing model
become the source of truth.

## Discarded Options

- Letting the worker read raw conversation logs or `.project-loop/events.jsonl`
  directly. That has no clear responsibility boundary and can expose discarded
  ideas or sensitive material. Evidence artifacts plus `pcl` commands are the
  sanctioned read surface.
- Adding a `master_trace_context` section to context packs as the first code
  change. That is too specific for the first fix. If M0 shows the workaround is
  too weak, the smaller general feature is evidence-to-task linking.
- Calling an LLM from `pcl` core to build intent indexes. That violates the
  local-only, dependency-light direction. External agents may create indexes;
  `pcl` records their outputs as evidence.

## Next Decision

If M0 confirms that task-description evidence refs are too awkward, consider
cutting the next implementation task for generic evidence-to-task linking:

```text
python -m pcl evidence add --task T-XXXX
```

The additive context-pack behavior would be a linked adhoc evidence section
for task packs, listing each linked evidence ID, summary, manifest path, member
path, and `stored_path` when copied. It should not inline transcript or index
contents by default, and it should stay within the existing
`context-pack/v1` contract.

Do not cut that task from this runbook alone. M1 remains a master/operator
decision after reviewing the M0 friction.
