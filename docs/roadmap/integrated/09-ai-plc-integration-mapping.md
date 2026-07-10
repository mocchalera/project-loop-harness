# AI-PLC Integration Mapping

## 1. 目的

AI-PLCとユーザー提供案のどの部分を採用し、どの部分を変更・延期・拒否したかを明示する。これにより「AI-PLCを取り入れる」という曖昧な合意が、別々の実装解釈へ分裂するのを防ぐ。

## 2. 統合判断の要約

```text
AI-PLCから採用するもの
  曖昧さの判定
  Context収集
  発散と収束
  Human checkpoint
  Backtrack/Replan
  Adaptive Depth
  maker≠checker
  Knowledge Propagationの仮説

PLHが保持する責務
  State
  Audit and recovery
  Evidence
  Verification
  Policy and budget
  Completion packet
  Handoff packet
```

AI-PLCのファイル構成、4段階slash command、Markdown/YAML stateをそのまま移植しない。AI-PLCは上流の進行設計として優れている一方、PLHはCLI、SQLite、JSONL、Evidence、Verificationを持つcontrol planeであり、同じ実装形へ寄せる必要はない。

## 3. 項目別mapping

| AI-PLC / 提供案 | 統合判断 | PLHでの実装 | 時期 |
|---|---|---|---|
| Intent / Collection | 採用。ただしP0の専用tableにはしない | `work-brief/v1` Evidence、source refs、assumptions | M3 / 0135 |
| 発散・Option Set | 採用。ただしOption CRUD/tableを作らない | Discovery Profileが`decision-proposal/v0`を生成 | M5 / 0143–0144 |
| 数値score | 補助としてのみ許可 | trade-off、uncertainty、reversibility、Evidenceを主契約にする | M5 |
| Human checkpoint | 採用 | existing Decision + human-required result | M4–M5 |
| Backtrack | 強く採用 | immutable Work Brief revision、`pcl replan`、stale propagation | M4 / 0138–0139 |
| maker≠checker | 採用。ただし「別モデル=証明」にはしない | verifier separationとEvidence classを別軸で記録 | M4 / 0140–0141 |
| Simple/Standard/Complex | UXの発想を採用、内部モデルは変更 | Direct/Discover/Assure preset + multi-axis policy | M3 / 0136–0137 |
| Context Cascade | 採用 | invariant/default/local constraint refs、parent changeでstale | M4 / 0139 |
| Knowledge Ledger | 仮説を採用、DB化は延期 | `knowledge-proposal/v0` Evidence experiment | M7 / 0149 |
| Story/Spec/Wireframe | coreには入れない | 後続Profile pack。必要性をDiscovery評価後に判断 | M5以降 |
| Cross-project Registry | 現段階では延期 | single-repo contractが安定してから再評価 | v1以降候補 |
| Dynamic workflow generation | 現段階では拒否 | existing deterministic templatesへ接続 | 未定 |
| 4-stage mandatory pipeline | 拒否 | 明確なtaskはDirectでstageをskip | 全期間 |
| Markdown wiki as source of truth | 拒否 | SQLite/Evidenceがsource。Markdownはexport | 全期間 |

## 4. ユーザー提供案から変えた重要点

### Intentを最初のP0にしない

最初のP0はMCP互換、DB/JSONL整合性、recoveryである。監査性の土台が不安定なまま永続化対象を増やすと、壊れるsurfaceが増える。

### 新tableを一括追加しない

提供案の`intents`、`option_sets`、`options`、`option_scores`、`replans`、`knowledge_items`等は、概念としては有益でも現時点では早い。まずartifact contractで実利用し、独立lifecycleとquery不足が証明されたものだけ昇格する。

### `pcl intent / collect / option`を主導線にしない

初心者の主導線は`pcl start → pcl finish → pcl resume`。Discoveryが必要な場合だけ、内部または次actionとしてWork Brief/Decision Proposalへ進む。上流用のthin commandsはadvanced surfaceとして追加できる。

### maker≠checkerを二軸へ分解する

- 誰が検証したか: separate context/session/agent/human。
- 何で検証したか: model judgment/deterministic check/observation/human judgment。

独立性が高くてもEvidenceが弱い場合はproof levelを上げない。

### Adaptive Depthを複数軸へ分解する

scope、risk、model capability、budgetは独立している。1行のauth変更はSimpleだがhigh risk、大規模docs変更はComplexでもlow riskになり得る。したがってplanning depthとverification depthを別にする。

## 5. AI-PLCを尊重しつつコピーしない理由

AI-PLCの強みは、人間とagentが理解しやすいCollection→Inception→Construction→Operation、HITL、Backtrack、発散/収束の手順である。PLHの強みは、モデル外部のstate、Evidence、Verification、recovery、handoffである。

最良の統合は、一方を他方へ置き換えることではない。

```text
AI-PLC-inspired Profile
  produces claims, alternatives, and a revised brief
          ↓ schema validation and human decision
PLH Core
  persists state, evidence, verification, completion, and handoff
```

## 6. 将来の昇格判断

次のEvidenceが揃った場合だけ、Intent/Option/Knowledgeのfirst-class entity化を再検討する。

- 2つ以上の外部repoで反復利用。
- 2 release以上contract fieldが安定。
- generic Evidence queryでは運用不能。
- 専用lifecycle/constraintが明確。
- Direct pathのUXを悪化させない。
- migration/recovery/MCP/dashboardの追加費用に見合う。

## 7. このmappingの失効条件

- PLHがcoding-agent control layerではなく、上流PdM platformを最初の市場として選び直した。
- 外部design partnerがOption/Intentの専用queryを強く要求し、artifact方式が明確に失敗した。
- Profile境界では必要なhuman interactionやstate consistencyを実現できないことが実証された。

この場合は新ADRを作り、mappingを暗黙に変更しない。
