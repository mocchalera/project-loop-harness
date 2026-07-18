# Security Policy

Project Loop Harness is a local-first CLI/runtime. It stores project-loop state
in the target repository's local `.project-loop/` directory.

## Supported Versions

The current public release line is `0.5.x`.

| Version | Supported |
| --- | --- |
| `0.5.x` | Yes |
| `0.4.x` | Yes |
| `<0.4` | No |

## Reporting A Vulnerability

Please open a GitHub security advisory or a private issue with enough detail to
reproduce the problem. Do not include real secrets, production credentials, or
private project data in public issues.

## Security Boundaries

- Agents must not edit `.project-loop/project.db` directly.
- Agents must not edit `.project-loop/events.jsonl` directly.
- Generated dashboard HTML is a view, not source of truth.
- Workflow execution uses a guarded host-subprocess executor; agent execution
  requires explicit opt-in. The executor does not isolate the OS, network, or
  filesystem and must not be treated as a sandbox.
- The optional MCP server defaults to read-only behavior and redacts
  secret-shaped values.

If you are using Project Loop Harness in a sensitive repository, keep local
state, evidence, and generated reports out of public commits unless your team
has reviewed them.

## Copied Evidence

`pcl evidence add --copy` stores copied evidence files under
`.project-loop/evidence/adhoc-files/`. Those files may contain sensitive source
files or project data selected by the caller.

Copied evidence must not be committed unless it has been intentionally curated
for publication. `.project-loop/` is gitignored by default and should stay out
of normal source-control commits.

Redaction is the caller's responsibility. `pcl` performs path-shape sensitive
guards for sensitive-looking evidence paths, introduced in task 0096, but
`pcl` is not a secret scanner and does not claim copied content is secret-free.

## Guarded Execution Output

`pcl workflow guard --execute` and `pcl loop execute` use argv lists with
`shell=False`, run in the project root, and inherit an environment allowlist
instead of the full parent environment. `PCL_AGENT_COMMAND` is passed only for
an explicitly enabled agent adapter. These controls reduce accidental leakage;
they do not provide process, network, or filesystem isolation.
Additional variables require an explicit repeatable `--allow-env NAME`; Evidence
records inherited names but never environment values.

Stdout and stderr are drained incrementally with a default 1 MiB cap per stream.
Evidence records original and retained byte counts, truncation reason, timeout
termination, binary/encoding metadata, and whether redaction changed output.
Default secret-shaped filters and optional `--redact-pattern` expressions run
before artifacts are stored, and no raw-output fallback is retained. This is a
best-effort privacy filter, not secret detection or malware scanning. Review
Evidence before publication even when `redacted=true`.

MCP and other read-only exposure surfaces must not reveal raw evidence contents
by default. They may expose claims, metadata, IDs, paths, hashes, and health
signals for review, but those values are not verified facts about the copied
content.

Generated dashboard HTML is a human view, not a machine context source. Agents
and integrations should use `pcl` JSON commands, reports, evidence paths, or
`.project-loop/dashboard/dashboard-data.json` for machine-readable context.

The release checklist (`docs/release-checklist.md`) includes a `SECURITY.md`
supported-versions check for each release.
