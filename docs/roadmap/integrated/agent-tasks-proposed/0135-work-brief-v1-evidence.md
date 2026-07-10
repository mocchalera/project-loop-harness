# 0135: Introduce work-brief/v1 as an Evidence-backed contract

- **Status:** Proposed
- **Milestone:** M3 / Adaptive Entry
- **Priority:** P0
- **Estimated size:** M
- **Dependencies:** `0131`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

GoalやTaskだけでは、問題、desired outcome、non-goal、assumption、constraintの根拠が薄い。一方、Intent専用tableを早期導入すると既存entityとの重複が増える。

## Goal

Work Briefをversioned JSON artifactとしてEvidenceへ保存し、既存targetへlinkして実行contractに使えるようにする。

## Scope

- `work-brief/v1` schema、fixtures、validatorをpackage化する。
- `pcl brief create/add/show/approve`等のthin CLIを設計する。
- generic Evidence kind `work-brief`とtarget linkを利用する。
- approved briefの解決規則を実装する。
- assumption status、constraint strength、Evidence refsを検証する。
- `pcl start`から最小draftをadditiveに作成できるよう統合する。
- Context Pack/Handoffへbrief refと要約を追加する。

## Proposed implementation

- 専用`intents` tableを作らない。
- brief本文の更新はin-placeではなく将来revisionへ移行できるimmutable storageにする。
- 初期taskではrevision=1のみを完全supportし、0138でsupersedes flowを追加する。
- JSON以外のhuman-friendly authoringはrenderer/import layerに置く。
- approval actorとtimestampはevent/metadataへ残す。

## Likely affected surfaces

- contracts/schema
- Evidence kinds/links
- brief application/CLI
- start integration
- context/handoff renderer

## Invariants

- Work Briefをfactとみなさない。assumption statusを保持する。
- 専用tableを追加しない。
- approvedでないbriefをcritical execution contractとして暗黙採用しない。

## Non-goals

- Option generation。
- Replan/revision。
- LLMによるbrief補完。
- Knowledge。

## Acceptance criteria

- Valid briefをEvidenceとして追加しtargetへlinkできる。
- Invalid/unsupported schemaはtarget stateを変更せず拒否される。
- Approved briefがresume/contextにref付きで現れる。
- Multiple draft/approved artifactの解決がdeterministicで曖昧時はerrorになる。
- Existing projects without briefは引き続き動き、absenceを明示できる。

## Required tests

- Schema fixtures.
- Evidence add/link/resolve.
- Approval event and actor.
- No-brief backward compatibility.
- Ambiguous multiple approved negative.
- Wheel schema package data.

## Evidence required to close

- sample work brief。
- link/audit output。
- context/handoff diff。
- negative fixture results。

## Rollout and rollback

- advisoryから開始。
- M4 enforcementまでbrief不在をblockしない。
- dogfoodでfield不足を収集。

## Open questions

- authoring formatをJSONのみで始めるかYAML/Markdown frontmatterを許すか。
- approvalを既存Decision entityへ結ぶか。

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
