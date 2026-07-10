# 0149: Run knowledge-proposal/v0 as an Evidence-backed experiment

- **Status:** Proposed
- **Milestone:** M7 / Adaptive Cost & Learning
- **Priority:** P2
- **Estimated size:** M
- **Dependencies:** `0135`, `0142`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

作業で得たproject固有知見を次回へ活かしたいが、モデル生成Knowledgeを自動注入すると誤り・陳腐化・矛盾が累積する。専用Knowledge tableを作る前に運用価値を検証すべき。

## Goal

propose→accept/reject/supersede/expireをgeneric Evidenceとeventで試し、accepted項目だけを明示opt-in context候補にする。

## Scope

- `knowledge-proposal/v0` schema、fixtures、validatorをpackage化する。
- `pcl knowledge propose/show/review/accept/reject/supersede`のthin CLIを追加する。
- provenance Evidenceを必須にする。
- scope、revision validity、expiry、confidence、statusを保持する。
- accepted KnowledgeをContext Packへ含める場合、選択理由とfreshnessを表示する。
- exact duplicate、explicit supersedes、conflicting scopeをdeterministicに検出する。
- 自動semantic contradiction判定はproposalに留める。

## Proposed implementation

- 専用knowledge tableを作らずEvidence metadata/eventで実験する。
- default status proposed。
- auto-accept/auto-injectしない。
- accepted itemがrepo revisionを越えて有効か検査する。
- context inclusionはpolicyでdefault offまたはexplicit opt-in。

## Likely affected surfaces

- knowledge schema
- Evidence metadata/view
- CLI review
- context selector
- events/docs

## Invariants

- provenanceなしaccept不可。
- モデル生成を自動acceptしない。
- expired/supersededをcontextへ入れない。
- 矛盾を自動で勝敗決定しない。

## Non-goals

- Knowledge graph/table。
- organization sync。
- embedding search。
- automatic wiki publishing。

## Acceptance criteria

- ProposalをEvidenceとして追加し、provenanceを追跡できる。
- Accept/reject/supersedeがactor/reason付きeventになる。
- Acceptedのみがexplicit context selection候補。
- Expired/superseded/conflicting itemがneeds_reviewまたは除外される。
- 利用実績をentity promotion判断用に集計できる。

## Required tests

- Schema/provenance.
- Lifecycle events.
- Duplicate/supersede/expiry.
- Context inclusion filter.
- No auto-accept.
- Legacy/no knowledge.

## Evidence required to close

- sample proposals/lifecycle。
- context selection output。
- promotion metrics report。

## Rollout and rollback

- experimental label。
- 2 external reposで価値が出るまでtable化しない。
- accepted item review cadenceを設ける。

## Open questions

- accept authority。
- default expiry。
- human-written knowledgeも同じcontractにするか。

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
