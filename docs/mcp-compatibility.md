# MCP compatibility matrix

This matrix records observed interoperability; it is not a claim that every
version of a named client is supported. `pcl-mcp` supports local stdio only and
protocol version `2025-06-18`.

## Automated conformance

| Tested date | Client | Client version | Platform | Operations | Result | Known limitations |
|---|---|---:|---|---|---|---|
| 2026-07-10 | Official MCP Python SDK (`mcp`) | 1.28.1 | macOS 26.1 arm64, Python 3.13.12 | subprocess start, `initialize`, initialized notification, `tools/list`, `tools/call` (`list_features`), stdin close/EOF | Pass | Test skips only when `mcp` cannot be imported. The SDK is pinned in the `mcp-test` extra and is not a runtime dependency. |
| 2026-07-10 | Independent stdlib process fixture | repository fixture | macOS 26.1 arm64, Python 3.13.12 | wire framing, lifecycle happy path, negative errors, special-character root, EOF, stdout purity | Pass | This fixture is not an external client support claim. Windows execution is configured in CI but has no run ID in this unpushed worktree. |

The committed wire transcript is
`tests/mcp/fixtures/wire-transcript.json`. It contains no project path, secret,
or user content. The negative matrix in
`tests/mcp/fixtures/negative-matrix.json` distinguishes JSON-RPC/schema errors
(`-32601`/`-32602`) from a PLH domain/approval error (`-32000`).

## Known limitation

The server currently accepts `tools/list` before initialization. The
2025-06-18 MCP lifecycle says initialization must be the first interaction and
clients should not send non-ping requests first, but the 0125 implementation
does not enforce this server-side. The conformance suite carries a strict
expected-failure test so the limitation is visible. Fixing the server lifecycle
belongs to a follow-up task and is intentionally outside 0126.

## Manual clients not yet verified

| Client | Version | Status | Promotion requirement |
|---|---|---|---|
| Claude Code | Not recorded | Not tested | Run the manual smoke runbook, record exact version/platform/date and all observed operations, then add a tested row above. |
| Codex CLI | Not recorded | Not tested | Run the manual smoke runbook, record exact version/platform/date and all observed operations, then add a tested row above. |

Do not move a client into the tested matrix based only on configuration being
accepted or a server appearing in a client list. A tool list and one successful
`list_features` call are required.

## Reproducing the automated checks

From a checkout with Python 3.10 or newer:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev,mcp-test]'
.venv/bin/python -m pytest tests/mcp -ra
```

The test itself performs no network I/O. If the official SDK cannot be
installed in an offline or constrained environment, install only `.[dev]`;
the official-SDK test reports a skip with the install instruction while the
independent process tests still run. The official SDK is MIT-licensed and its
exact pin is updated through normal dependency review.
