# MCP manual client smoke runbook

Use this runbook to verify a real agent client without changing the automated
support matrix prematurely. It exercises only local stdio; no server network
access or MCP credentials are required. The agent client itself may require its
normal authentication and network access.

## Prepare isolated local state

Run from the repository root and substitute absolute paths in every client
configuration:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e .
rm -rf /tmp/pcl-mcp-manual-smoke
.venv/bin/pcl init --target /tmp/pcl-mcp-manual-smoke
.venv/bin/pcl --root /tmp/pcl-mcp-manual-smoke feature add \
  --name "MCP manual smoke" --surface "mcp:manual"
```

Record the output of `sw_vers` and `uname -m` on macOS, or the equivalent OS
version commands on Linux/Windows. Also record the client version. Do not put
absolute home paths, environment values, project content, or secrets in a wire
transcript.

## Claude Code

The command shape follows `claude mcp add --help`. Use local scope so the
configuration is not committed:

```bash
claude --version
claude mcp add --scope local pcl-conformance -- \
  "$(pwd)/.venv/bin/python" -m pcl.mcp_server --stdio \
  --root /tmp/pcl-mcp-manual-smoke
claude mcp get pcl-conformance
claude
```

Inside Claude Code, open `/mcp`, confirm `pcl-conformance` connects, ask it to
list the available `pcl-conformance` tools, then ask it to call
`list_features`. Verify the result includes `MCP manual smoke`. Remove the
temporary registration afterward:

```bash
claude mcp remove pcl-conformance
```

## Codex CLI

The command shape follows `codex mcp add --help`:

```bash
codex --version
codex mcp add pcl-conformance -- \
  "$(pwd)/.venv/bin/python" -m pcl.mcp_server --stdio \
  --root /tmp/pcl-mcp-manual-smoke
codex mcp get pcl-conformance
codex
```

In Codex, confirm the MCP startup succeeds, inspect the exposed tool names, and
request a `list_features` call. Verify the result includes `MCP manual smoke`.
Remove the temporary registration afterward:

```bash
codex mcp remove pcl-conformance
```

## Evidence record

Create a review artifact outside `.project-loop/` with:

- tested date and timezone;
- exact client version and OS/platform;
- server commit SHA and Python version;
- observed initialize/connect result, tool names, and `list_features` result;
- pass/fail and any known limitation;
- redacted diagnostic output when a failure occurs.

Only after a maintainer reviews that record should
`docs/mcp-compatibility.md` gain a tested-client row. Never copy credentials,
full local paths, unrelated user content, or raw secrets into the record.
