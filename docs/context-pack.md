# Context Pack

`pcl context pack` builds a read-only, focused handoff for another agent.

It is intended for PM/orchestrator agents that need to pass just enough
project-loop context to a worker without dumping all local state, parsing
generated dashboard HTML, or reconstructing prompt/evidence paths manually.

## Command

```bash
pcl context pack --job J-0001
pcl context pack --job J-0001 --role verifier --max-tokens 12000 --json
```

## Contract

JSON mode returns `context-pack/v1`:

```json
{
  "ok": true,
  "context_pack": {
    "contract_version": "context-pack/v1",
    "target": {"type": "agent_job", "id": "J-0001"},
    "reader_role": "verifier",
    "budget": {
      "max_tokens": 12000,
      "approx_char_limit": 48000,
      "approx_chars_per_token": 4
    },
    "approx_char_count": 1000,
    "truncated": false,
    "included_sections": ["machine_context_rules", "target_job"],
    "omitted_sections": [],
    "source_commands": [
      "pcl jobs read J-0001 --json",
      "pcl prompt job J-0001 --json",
      "pcl validate --json"
    ],
    "source_paths": [".project-loop/evidence/agent-runs/J-0001/prompt.md"],
    "markdown": "# Context Pack: J-0001\n..."
  }
}
```

`--max-tokens` is an approximate budget control. The command uses a fixed
four-characters-per-token estimate so output is deterministic and dependency
free. When the budget is too small, the command returns a truncated pack with
`omitted_sections` metadata instead of failing.

## Boundaries

- The command is read-only.
- It does not write context packs to disk in v1.
- It does not execute external agents.
- It does not add or require schema migrations.
- It does not read or parse `.project-loop/dashboard/dashboard.html`.

Agents should use `pcl` JSON commands, reports, evidence paths, or
`.project-loop/dashboard/dashboard-data.json` for follow-up machine context.
