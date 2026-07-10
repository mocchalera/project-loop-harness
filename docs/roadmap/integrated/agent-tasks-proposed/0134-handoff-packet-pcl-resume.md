# 0134: Implement handoff-packet/v1 and read-only pcl resume

- **Status:** Proposed
- **Milestone:** M2 / Product Wedge
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** `0132`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

sessionやmodelを変えると、利用者は会話履歴、diff、test結果、decisionを再説明する。現行Context Packは有用だが、再開のための安定した外部packetと単純なentry pointが必要。

## Goal

現在のwork targetを小さいhandoff packetへ集約し、`pcl resume`でread-onlyに取得できるようにする。

## Scope

- `handoff-packet/v1` schema、fixtures、validatorをpackage化する。
- `pcl resume [--target] [--format json|markdown] [--output]`を実装する。
- current Work/Goal/Task、latest completion/incomplete packet、Decision、Evidence、blocker、riskを選択する。
- verifiedとunverifiedを分離する。
- next safe actionと対応commandを返す。
- context refsにfreshness/hashを付け、本文全量は既定でinlineしない。
- multiple active targets時は勝手に選ばずcandidate listを返す。
- 生成行為はread-onlyとし、export file以外のstateを変更しない。

## Proposed implementation

- packet selectionはdeterministic orderingとtarget-bound linksを使う。
- latestだけでなく、superseded/stale判定を考慮する。
- Markdown rendererはJSON contractの派生でありsource of truthにしない。
- packet sizeとomitted sectionsを記録する。
- `--json` stdout purityを保つ。

## Likely affected surfaces

- contracts
- context/handoff selection
- CLI resume
- Markdown renderer
- fixtures/docs

## Invariants

- resumeはstateを変更しない。
- full transcriptを既定で含めない。
- unverified claimをverified欄へ入れない。
- 複数targetを曖昧に自動選択しない。

## Non-goals

- agentを自動起動。
- Master Trace生成。
- remote sync。
- context embedding。

## Acceptance criteria

- Active/incomplete/completed targetごとにvalid handoff packetを生成できる。
- 別sessionのtest agentがpacketだけからdocumented next checkを再実行できる。
- Multiple targetではexit/JSONがselection requiredを明示する。
- Packet generation前後でDB/event countが変わらない。
- MarkdownとJSONが同じverified/unverified semanticsを持つ。

## Required tests

- Schema fixtures.
- Selection matrices including stale/superseded.
- Read-only database hash/count assertion.
- Packet size/omission.
- Cross-session replay integration.
- CLI output formats.

## Evidence required to close

- sample handoff packets。
- read-only assertion。
- resume usability dogfood notes。
- schema/package tests。

## Rollout and rollback

- M2ではCLI exportのみ。
- agent-specific adaptersは後続。
- packet field不足をM3/M6でadditive拡張。

## Open questions

- default target selectionをlatest activeにするか、常に明示させるか。
- Markdown rendererの安定性をcontractに含めるか。

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
