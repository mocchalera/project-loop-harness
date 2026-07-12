# ADR-005: External Council Profile Boundary

- **Status:** Proposed
- **Date proposed:** 2026-07-11
- **Contract freeze prepared:** 2026-07-12
- **Decision owner:** PLH maintainer / human owner
- **Related:** Adaptive Loop Architecture, Work Brief, Route Recommendation, Agent Adapter Contract

## Context

PLHはモデル非依存・ローカルファーストのcontrol planeであり、モデル出力をEvidenceなしにfact扱いしない。曖昧または高リスクな実装では、複数の高性能モデルを独立提案・反証・統合へ使うと、実装前に手戻り要因を減らせる可能性がある。一方、provider SDK、認証情報、価格、モデル更新、network retryをCoreへ入れると、zero-dependency、determinism、監査境界が崩れる。

また、Councilを完全な別製品にすると、PLHが既に持つWork Brief、Evidence、Decision、Verification、Completion、Handoffを重複実装する。

## Decision

1. PLH CoreはProfileの入出力contractとEvidence/Decision統合を提供する。
2. モデル選択・協調は別package/processの外部runnerへ置く。
3. PLHは外部runnerを暗黙に実行しない。
4. ProfileはSQLiteを直接変更しない。
5. Profile outputはversioned `profile-output-bundle/v1`として明示ingestする。
6. MVPではClaims/ProfileRun/Optionの専用tableを作らない。
7. human decisionは既存Decisionをauthoritative stateとして使う。
8. Councilはモデル名・モデル数を固定せず、1〜4participantをtaskごとに選ぶ。
9. full transcript/hidden chain-of-thoughtはcanonical Evidenceにしない。
10. MVPはbuilt-in data-only manifestだけを発見し、schema 8を維持する。
11. paid/network実行権限はproject configではなく、request basisへ
    hash-bindされたhuman `approval-provenance/v1`だけが与える。
12. runner statusやモデル合意はWork Brief、Test、Feature、Goalを
    自動承認・完了しない。

## Human outcome

Pending. The maintainer must record exactly one of Accept, Modify, or Reject
before task 0155 starts. Preparing and reviewing the proposal contracts does
not imply acceptance.


## Consequences

### Positive

- PLH Coreのモデル非依存性、zero runtime dependencies、local-first性を維持できる。
- runnerを単体モデル、Fusion型、Fugu型、自社runnerへ差し替えられる。
- model/provider更新がPLH releaseをblockしない。
- human decisions、Evidence、auditを一元化できる。
- invalid/budget-exhaustedな結果を明示的に停止できる。

### Negative

- PLHとrunnerの二段installが必要。
- request/bundle contractのversioning責任が増える。
- filesystem + DBのEvidence durabilityを慎重に扱う必要がある。
- 外部runner内部の品質はPLHだけでは保証できない。
- model cost/privacyの正確性はrunnerのhonest reportingへ依存する。

### Mitigation

- fixture runnerとcontract conformance testsを提供する。
- exact modelが得られない場合はpinning statusを正直に記録する。
- PLHはmodel judgmentをdeterministic evidenceの代替にしない。
- bundle path/hash/schema/cross-referenceをfail closedで検査する。

## Alternatives considered

### A. Provider SDKをPLH Coreへ直接実装

**Reject.** Coreのdependency、credential、network、release cadenceがprovider事情へ依存する。

### B. Councilを完全な別製品として実装

**Reject.** Evidence、Decision、human gate、audit、completionを重複実装し、二つのsource of truthを作る。

### C. 既存Agent Job一件だけでCouncilを扱う

**Bootstrapのみ採用。** 最初のdogfoodには使えるが、participants、budget、claims、proposalを型付きで扱えない。

### D. 同一repositoryへprovider codeも含める

**Reject for production boundary.** 初期experimentは可能でも、package/release分離が曖昧になる。

## Revisit conditions

- Profile outputを高頻度に横断検索する必要が生じた。
- ProfileRun/Claimの専用tableがないことで明確な性能・UX問題が出た。
- PLHがhosted execution platformへ製品方針を変える。
- 外部runner contractを複数実装が採用し、version negotiationが必要になった。
