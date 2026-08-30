# Bounded agent command execution

`pcl exec` runs one non-interactive argv command without requiring `pcl init`.
It is intended for tests, lint, type checks, builds, validation, package
installation, code generation, and local CI-equivalent checks whose primary
result is pass/fail.

```bash
pcl exec -- npm test
pcl exec --json -- pytest
pcl exec --timeout-seconds 300 -- cargo test
```

The command does not invoke a shell. Pipelines, redirects, substitutions,
interactive commands, watch mode, servers, REPLs, file reads, searches, diffs,
and reports should be run directly instead.

## Output contract

- PASS: at most 5 lines and 2 KiB; command stdout/stderr is not retained.
- Non-PASS: at most 120 lines and 24 KiB; diagnostics prefer error blocks,
  stderr tail, and stdout tail.
- No automatic retry. A later explicit retry does not rewrite the original run.
- Child exit codes are preserved where possible. Timeout uses 124; missing
  executable uses 127; permission-denied spawn uses 126; other infrastructure
  failures use 125; interruption uses 130.

Machine output uses `agent-exec-result/v1`.

## Local diagnostics

Sanitized metadata is stored in the user-local state directory. PASS stores no
command output. Non-PASS stores only the bounded diagnostic projection, not the
full captured stream.

```bash
pcl exec show AX-... --errors
pcl exec show AX-... --tail 40
pcl exec meta AX-... --json
pcl exec gc --dry-run
pcl exec gc
```

Defaults are owner-only files, 72-hour retention, and a 512 MiB total ceiling.
Set `PCL_AGENT_EXEC_STATE_DIR` or `--state-dir` for an explicit local override.
Nothing is uploaded to GitHub, Slack, Fumiori, Drive, AGI Cockpit, or another
service.

Redaction is defense in depth, not proof that output is secret-free. Do not put
credentials in command arguments or test output.
