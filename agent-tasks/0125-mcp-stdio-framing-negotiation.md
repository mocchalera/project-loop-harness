# 0125: Make MCP stdio transport and protocol negotiation specification-compliant

- **Status:** Proposed
- **Milestone:** M1 / Trust Foundation
- **Priority:** P0
- **Estimated size:** M
- **Dependencies:** `0124`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

現行serverはMCP 2025-06-18を宣言しながらstdioで`Content-Length` framingを使い、initializeで要求されたprotocol versionを対応可否に関係なく返す。自己実装clientとのtestだけでは外部相互運用性を保証できない。

## Goal

MCP stdioを宣言versionの仕様へ合わせ、unsupported versionを正しくnegotiateし、stdoutを純粋なprotocol channelにする。

## Scope

- stdio reader/writerを1 JSON-RPC message per lineへ変更する。
- message内改行、size limit、invalid JSON、empty line、EOFを明示処理する。
- supported protocol versionsを定数またはordered setで管理する。
- client requested versionがunsupportedならserver supported versionを返す。
- notification、request、responseのID semanticsを既存behaviorと照合する。
- protocol以外のlog/diagnosticをstderrへ送る。
- 既存Content-Length fixture/clientを更新または明示的にlegacy扱いする。

## Proposed implementation

- transport parserとMCP method dispatchを分離し、framing testをprocess boundaryで行えるようにする。
- newline-delimited outputはcompact JSONを使い、payload自身にliteral newlineを出さない。
- line length上限を設定し、超過時はprotocol errorまたはsafe terminationにする。
- initialize前に許可されるmethod、initialize後のstate transitionをcharacterizeする。
- legacy modeを残す場合はhidden/experimental opt-inとし、defaultにしない。

## Likely affected surfaces

- `src/pcl/mcp_server.py`
- MCP process/transport tests
- MCP documentation and help
- any internal MCP client fixture

## Invariants

- runtime dependencyを不要に増やさない。
- stdoutにbanner、logging、tracebackを混ぜない。
- unsupported versionをechoしない。
- MCP修正でPLH core state semanticsを変えない。

## Non-goals

- 新しいMCP toolの追加。
- remote HTTP transport。
- agent runtime固有adapter。
- outbox/recovery変更。

## Acceptance criteria

- Given newline-delimited initialize request, when server reads stdin, then 1行のJSON-RPC responseをstdoutへ返す。
- Given unsupported requested version, when initialize runs, then serverがsupportするversionを返し、requested versionを無条件にechoしない。
- Given malformed/oversized line, when processed, then protocol channelを壊さずdocumented errorまたはterminationになる。
- Given normal session, when stderr logging is enabled, then stdoutの各non-empty lineがvalid JSON-RPC messageである。

## Required tests

- Transport unit tests for LF/CRLF, EOF, malformed JSON, oversized line.
- Process-level initialize → tools/list → tools/call test.
- Version negotiation matrix.
- stdout purity test.
- Regression test for notifications without response ID.

## Evidence required to close

- official spec sections used。
- before/after wire transcript。
- process-level test output。
- compatibility behavior documented。

## Rollout and rollback

- MCPをexperimental表示している場合は修正後も実client test完了まで維持。
- breaking legacy framingはrelease noteで明示。
- rollbackはlegacy flagではなくprevious package versionで可能にする。

## Open questions

- 複数protocol versionを同時supportするか、current oneのみか。
- legacy Content-Length modeを一releaseだけ残す価値があるか。

## Agent execution protocol

実装担当エージェントは開始前に次を返す。

1. 対象commit SHAと、依存taskがmerge済みである証拠。
2. 変更予定path。
3. 既存contractをcharacterizeするtestまたは確認結果。
4. scope外に見える問題と、今回は触れない理由。

完了時は次を返す。

1. 変更概要と設計判断。
2. 実行した全test command、exit code、失敗・skip。
3. schema/migration/CLI互換性への影響。
4. 生成したEvidenceまたはpacket refs。
5. 未確認事項、残存risk、rollback方法。
6. Acceptance criteriaを一項目ずつ満たした根拠。

「実装した」「テストは通るはず」「レビュー済み」という主張だけではcloseしない。
