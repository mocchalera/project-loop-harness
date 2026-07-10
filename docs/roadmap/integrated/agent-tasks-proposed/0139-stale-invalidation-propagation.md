# 0139: Propagate constraints, stale state, and invalidation after replan

- **Status:** Proposed
- **Milestone:** M4 / Replan & Assurance
- **Priority:** P0
- **Estimated size:** XL
- **Dependencies:** `0138`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

Replan後に旧前提へ依存するTask、Evidence、Verification、packetがcurrentに見えると、誤った完了やhandoffにつながる。削除ではなく、有効性状態と理由を伝播する必要がある。

## Goal

parent-child constraint referencesとgeneric link graphからeffective constraints、stale/invalidationを計算し、説明・再検証・finish blockへ接続する。

## Scope

- `current / stale / invalidated / superseded`のvalidity modelを実装する。
- parent Work Briefからchild Goal/Taskへconstraintを参照伝播する。
- constraintを`invariant / inherited_default / local`に分け、effective constraint setを解決する。
- `inherited_default`のoverrideにはDecision/actor/reasonを要求し、`invariant`はpolicy上許可された明示Replanなしに上書きできない。
- brief→target→task/evidence/verification/packetのgeneric dependency traversalを定義する。
- replan invalidation planをdry-runし、適用時に理由付きvalidity record/eventを作る。
- `pcl stale list/show/explain/recheck`等のread/repair surfaceを提供する。
- critical stale Evidenceがある場合のfinish behaviorをpolicyで決める。
- repository revision mismatchとcontext receipt freshnessを接続する。
- parent constraint変更時、影響childをstaleにし、黙って新制約へ置き換えない。
- revalidation成功時にcurrentへ戻す手続きを記録する。

## Proposed implementation

- 既存Evidence rowを破壊変更せず、generic validity metadata/tableを検討する。
- constraint本文をchildへ複製せず、source refとresolved snapshot/hashを保持する。
- graph cycleを検出し、無限伝播を防ぐ。
- automatic invalidatedは限定し、多くはstale→recheckとする。
- why-chainを保持し、どのbrief changeが影響したか説明する。
- large graphのquery/transaction sizeを測る。

## Likely affected surfaces

- validity domain/storage
- link graph query
- replan application
- finish validation
- context/handoff
- CLI

## Invariants

- stale artifactを削除しない。
- 理由なしでvalidityを変更しない。
- revalidation前にcurrentへ戻さない。
- cycleでpartial silent successしない。

## Non-goals

- semantic dependency inference by LLM。
- arbitrary deep product decompositionやSubgoal planner。
- cross-project invalidation。
- Knowledge staleness全般。

## Acceptance criteria

- Acceptance criterion削除/変更fixtureで依存verification/packetがstaleになる。
- Parentの`invariant` constraintがchildのeffective setへ参照付きで現れ、無断overrideが拒否される。
- `inherited_default` overrideがDecisionと理由付きで成功し、handoffに差分が現れる。
- Unrelated Evidenceはcurrentのまま。
- `stale explain`がroot changeから対象までのpathを返す。
- Critical staleがfinishをblockし、recheck後に解除できる。
- Dry-run/applyが同じimpact setを返す（concurrent change除外）。

## Required tests

- Dependency graph and constraint-resolution fixtures.
- Cycle and large fan-out.
- Unrelated/non-propagating links.
- Finish block/revalidate.
- Concurrent graph change.
- JSON explain output.

## Evidence required to close

- before/after graph and effective-constraint report。
- why-chain fixture。
- finish block packet。
- performance measure。

## Rollout and rollback

- 最初はbrief-linked artifactに限定。
- 自動invalidated ruleを少なく保つ。
- false stale率をdogfood指標にする。

## Open questions

- validityをEvidence row fieldにするかgeneric relationにするか。
- packet自体をstaleにする基準。

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
