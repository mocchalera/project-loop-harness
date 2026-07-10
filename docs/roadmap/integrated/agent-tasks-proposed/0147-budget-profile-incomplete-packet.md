# 0147: Implement budget profiles and explicit budget-exhaustion outcomes

- **Status:** Proposed
- **Milestone:** M7 / Adaptive Cost & Learning
- **Priority:** P1
- **Estimated size:** L
- **Dependencies:** `0131`, `0146`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

低予算運用ではtool call、wall time、context、strong-model escalationに上限が必要。上限到達を隠してcompletedにすると最も危険なfalse completionになる。

## Goal

複数種類のbudgetを計測・説明し、exhaustion時に安全停止と再開可能なincomplete packetを残す。

## Scope

- context bytes、tool calls、wall time、iterations、failed attempts、strong model escalationsのbudgetを定義する。
- providerが実token/costを返す場合と返さない場合を分ける。
- `pcl budget status/explain`を追加する。
- use case開始時にbudget snapshotを固定し、consumption eventを記録する。
- exhaustion時に`INCOMPLETE_BUDGET_EXHAUSTED` completion/handoff packetを生成する。
- verified/unverified、残りcheck、next safe actionを必須にする。
- human override/top-upを明示eventにする。

## Proposed implementation

- charclass token estimateを実課金と同じfieldに入れない。
- wall timeはmonotonic clockを使う。
- parallel jobsのbudget aggregation semanticsを決める。
- check execution中のhard/soft limitを分ける。
- budget不足でEvidence保存まで中断しないようreserved closeout budgetを設ける。

## Likely affected surfaces

- budget domain/meter
- policy
- finish/packet
- events
- CLI
- adapter usage import

## Invariants

- exhaustionをcompletedにしない。
- 実値と推定を区別する。
- closeout/handoff用の最低余力を確保する。
- silent top-upなし。

## Non-goals

- billing。
- provider price scraping。
- automatic credit purchase。

## Acceptance criteria

- Tool-call/wall-time/context fixtureでlimit到達がdeterministicに検出される。
- Exhaustion packetに実行済みcheck、未確認claim、next safe actionがある。
- Actual provider usageとestimated usageが別fieldで表示される。
- Human top-upがreason/actor付きでauditされる。
- Resume後にremaining/renewed budgetから継続できる。

## Required tests

- Each budget dimension.
- Soft vs hard limit.
- Reserved closeout budget.
- Parallel aggregation.
- Actual vs estimated usage.
- Top-up/override audit.

## Evidence required to close

- sample exhaustion packet。
- meter traces。
- resume continuation。
- estimate/actual display。

## Rollout and rollback

- 最初はlocal counters。
- cost currency表示はactual dataがある場合だけ。
- default budgetは無制限ではなく明示null。

## Open questions

- parallel budget allocation。
- hard kill可能なtoolの扱い。
- closeout reserve size。

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
