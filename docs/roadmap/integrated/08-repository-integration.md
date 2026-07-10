# Repository Integration and Planning-PR Procedure

## 1. 目的

このbundleを一度に「実装済み計画」として`main`へ置くのではなく、既存のapproved growth plan、task queue、contractと衝突しない形で議論・承認・分割する。

## 2. 推奨する最初のPlanning PR

### Branch

```text
docs/integrated-roadmap-2026-07
```

### 入れるもの

```text
docs/roadmap/integrated/
  00-executive-roadmap.md
  01-adaptive-loop-architecture.md
  02-contracts-and-data-model.md
  03-implementation-plan.md
  04-evaluation-and-rollout.md
  05-pdm-discussion-guide.md
  06-cli-contract-draft.md
  07-state-machines-and-events.md
  adr/
  schemas/
  examples/
```

### 最初のPRでは入れないもの

- runtime code。
- migration。
- package version変更。
- `agent-tasks/0123`以降をactive/approvedとして扱う変更。
- 既存growth planの削除。

## 3. Planning PRのreview order

1. PdMが`00`、`04`、`05`をreviewし、対象ユーザー、wedge、go/no-goを決定。
2. Architecture reviewerがADR-001〜004、`01`、`02`、`07`をreview。
3. Maintainerが現行コードと`03`、`06`、個別taskの前提を照合。
4. Decision recordへAccept/Reject/Modifyを記録。
5. Accepted部分だけをcurrent growth planへ反映。
6. `0123`〜`0130`をactive queueへコピーし、ownerを割り当てる。

## 4. 既存計画との関係

このbundleは現行growth planを自動的に上書きしない。承認後、現行planの冒頭に次のどちらかを明記する。

### Supersedeする場合

```text
Status: Superseded by docs/roadmap/integrated/00-executive-roadmap.md
Superseded at: <date>
Decision: <decision-id>
```

### 部分統合する場合

```text
Status: Active with integrated amendments
Amendments: <paths and decision IDs>
```

同じmilestone名で異なるscopeを二重管理しない。

## 5. Task activation

個別task fileは以下のstatusを使う。

```text
Proposed → Accepted → Ready → In Progress → Review → Done
                    ↘ Blocked / Superseded / Rejected
```

`Ready`へ上げる条件:

- dependenciesがDone。
- relevant ADRがAccepted。
- task前提がcurrent mainで再確認済み。
- owner/reviewer/target SHAが設定済み。
- migration/contract collisionがない。
- acceptance testsが実行可能な表現になっている。

## 6. Task分割の原則

XL taskを一人のagentへ丸ごと渡さない。たとえば`0127`は、同一親taskのsub-PRとして次へ分けられる。

```text
0127-A migration and storage schema
0127-B transaction coordinator and event write path
0127-C JSONL projector and retry
0127-D caller migration and compatibility
0127-E integrated failure tests
```

ただし、部分PRがmergeされても親taskはend-to-end acceptanceを満たすまでDoneにしない。

## 7. Schema proposalの置き場所

Planning段階では`docs/.../schemas/`へ置く。`0131`等でruntime contractとしてAcceptedした時点で、package dataのcanonical pathへコピーまたは移動し、次を追加する。

- loader API。
- positive/negative fixtures。
- wheel/sdist inclusion test。
- compatibility/deprecation policy。
- generated docs。

proposal schemaをruntimeが暗黙に受け付けない。

## 8. Agentへの入力bundle

一taskにつき、次の小さいbundleを作る。

```text
TASK.md
RELEVANT_ADR.md
RELEVANT_SCHEMA.json
CURRENT_CONTRACT_FIXTURES/
ALLOWED_PATHS.txt
BASELINE_TESTS.md
```

30 task全体や全roadmapを毎回contextへ入れない。依存と非対象をtask fileから選択し、context budgetを守る。

## 9. Review gate checklist

### Product

- 解くpainが1文で言える。
- Direct pathへ新概念を強制しない。
- 成功と失敗を測れる。
- featureがNorth Starへどう寄与するか説明できる。

### Architecture

- source of truthが一つ。
- crash pointとrecoveryがある。
- public contractとDB schemaが分離。
- read-only/mutation境界が明確。
- LLM/model-specific dependencyがcoreへ入っていない。

### Implementation

- 既存behavior characterization testがある。
- negative testがある。
- migration/rollbackがある。
- docs/help/JSON fixtureが同期。
- 完了Evidenceを第三者が再確認できる。

## 10. 最初の実行順

Planning PR承認後、次だけをactiveにする。

```text
0123 release baseline
0124 MCP protocol fix          ┐ parallel after 0123
0126 outbox ADR/failure model  ┘
0130 guarded executor review   ─ parallel where safe
```

`0127`はADR-002がAcceptedになるまで開始しない。`0131`のcontract designは並行review可能だが、`0132`のfinish integrationはM1 gate後にmergeする。
