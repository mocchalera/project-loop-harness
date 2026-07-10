# 0126: Add MCP external conformance fixtures and compatibility matrix

- **Status:** Proposed
- **Milestone:** M1 / Trust Foundation
- **Priority:** P0
- **Estimated size:** M
- **Dependencies:** `0125`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

内部unit testだけでは外部clientとの接続、process lifecycle、stdout discipline、tool schema互換性の問題を見逃す。相互運用性を製品価値にするには、実clientまたは標準準拠fixtureで継続確認が必要。

## Goal

MCPのsupported surfaceをprocess-levelに検証し、どのclient/versionを確認済みかを公開できるcompatibility matrixを作る。

## Scope

- 独立したJSON-RPC/MCP conformance client fixtureをtest用に用意する。
- initialize、initialized notification、tools/list、代表的read-only tools/call、shutdown/EOFを検査する。
- 少なくとも1つの公式SDKまたは外部標準準拠clientをdev/test-onlyで利用する検討を行う。
- Claude Code、Codex等の対象client向けmanual smoke手順を文書化する。
- client name、version、OS、result、known limitationをcompatibility matrixへ記録する。
- protocol schema errorとPLH domain errorを区別する。

## Proposed implementation

- runtime dependencyではなくtest extraまたはsubprocess fixtureを優先する。
- external client versionをpinし、更新はDependabot等の通常review対象にする。
- CIでcredentialやGUIを必要とするclient smokeは必須にせず、再現可能なmanual evidence pathを持つ。
- wire transcriptからproject path、secret、user contentをredactする。

## Likely affected surfaces

- `tests/mcp/`
- CI workflow
- `docs/mcp-compatibility.md`
- test extras / lock metadata

## Invariants

- 内部clientだけを「external conformance」と呼ばない。
- 未確認clientをsupportedと記載しない。
- test用SDKをruntime dependencyへ漏らさない。

## Non-goals

- すべてのMCP clientのsupport。
- HTTP/SSE transport。
- MCP tool inventory拡張。

## Acceptance criteria

- Conformance fixtureがserver subprocessを起動し、initializeからtools/callまで成功する。
- Invalid params、unknown method、pre-initialize callのexpected errorがfixtureで固定される。
- Compatibility matrixにtested date、client version、platform、resultがある。
- CIがprotocol regressionを検出し、external/manual smoke手順が第三者に再現可能。

## Required tests

- Independent process client test.
- Official SDK/client test where feasible.
- Protocol negative matrix.
- Windows path/stdin handling smoke.
- No stdout contamination under debug logging.

## Evidence required to close

- wire transcript fixture。
- CI run link/id。
- manual client smoke record。
- compatibility matrix diff。

## Rollout and rollback

- 初期matrixは少数clientでよい。
- 新clientをsupportedにする前に同じfixtureを追加。
- failureはknown limitationとして公開し、隠さない。

## Open questions

- CIへofficial SDKを入れるlicense/maintenance cost。
- 対象clientの最低version。

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
