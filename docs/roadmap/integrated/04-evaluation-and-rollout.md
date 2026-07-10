# Evaluation and Rollout Plan

## 1. なぜ評価が必要か

PLHは工程を増やすことで簡単に「厳格そう」に見える。しかし、工程が増えただけで成功率やhandoffが改善しなければ、利用者の時間を奪う。AI-PLC思想の統合も、導入した機能数ではなく、曖昧な仕事の手戻りが減ったかで判断する。

## 2. 比較条件

### Product condition

1. Agent only。
2. PLH Direct。
3. PLH Discover。
4. PLH Assure。

### Model condition

- strong hosted model。
- medium-cost model。
- weak/local model。
- modelなしのhuman/CLI-only baseline。

### Repository condition

- Python CLI。
- TypeScript web app。
- monorepo。
- brownfield/legacy project。
- testが薄いproject。

### Task condition

- 明確なbug fix。
- feature addition。
- refactor。
- failing test repair。
- migration。
- auth/security変更。
- 曖昧なproduct request。
- 前提変更を途中注入するReplan task。

## 3. 主要指標

| 分類 | 指標 | 定義 |
|---|---|---|
| 正しさ | task success rate | independent rubricとtestsで判定 |
| 信頼 | false completion rate | completedだがcritical acceptance未達 |
| claim品質 | unverified critical claims | packet内のcritical L0/L1 claim数 |
| scope | wrong-file / unnecessary change | golden patchまたはreview rubric比 |
| 人間負担 | interventions / review minutes | taskごとの人間介入とreview時間 |
| cost | tokens / API cost / wall time | provider実値を優先、推定は別表示 |
| overhead | PLH time and commands | Agent onlyとの差分 |
| handoff | resume success | 別session/modelが追加説明なしで次step成功 |
| 再現 | check replay success | packetから第三者がcheckを再実行できる率 |
| recovery | crash recovery rate | injected failure後の検出・修復成功 |
| discovery | scope rework rate | 実装後の大幅goal/approach変更率 |
| routing | override rate / regret | route overrideと結果の相関 |

## 4. 初期目標

目標値であり、達成済みの主張ではない。

- Directの低risk taskでPLH overhead 5%以下。
- Discoverが曖昧taskのscope reworkを25%以上削減。
- weak model条件でtask success +15ポイント、またはhuman intervention -30%。
- resume success 80%以上。
- packet replay success 90%以上。
- Directのhuman checkpointは原則0。
- Discoverの必須human checkpointは原則1。
- supported crash pointのintegrity issue検出100%。
- high-risk taskをmodel self-approvalだけでterminal completedにしない。

## 5. benchmark fixture

各fixtureは次を含む。

```text
repository snapshot SHA
initial request
hidden acceptance tests or rubric
deterministic checks
allowed/forbidden paths
risk classification
time/tool/token budget
expected critical claims
injected interruption or premise change（該当時）
```

一つのモデル出力を正解としない。task outcome、diff、checks、packet、human reviewで評価する。

## 6. 実験手順

1. fixtureを固定し、model/version、temperature、tool permissionsを記録。
2. 各conditionを最低複数回実行し、単一成功例を代表にしない。
3. evaluatorへcondition名を可能な範囲でblind化。
4. raw log、packet、diff、timing、costを保存。
5. model judgmentとdeterministic outcomeを分ける。
6. 失敗例を削除せず、failure taxonomyへ分類。
7. 結果からroute/policyを変更した場合、policy versionを上げて再測定する。

## 7. failure taxonomy

- wrong problem solved。
- acceptance misunderstood。
- scope drift。
- tool misuse。
- test not run。
- test passed but claim unsupported。
- stale context。
- premature completion。
- budget exhaustion hidden。
- human gate bypassed。
- handoff missing critical decision。
- recovery inconsistency。
- profile overhead exceeded benefit。

## 8. dogfood stages

### Stage A: Maintainer dogfood

PLH自身と、性質の異なるもう1 repoで20〜30 tasks。機能開発と評価担当を可能なら分ける。

### Stage B: Closed design partners

5〜10人、最低3種類のagent runtime。週次で次を回収する。

- 最初の価値到達時間。
- 使わなかった理由。
- finish packetがreviewに役立った場面。
- resumeが失敗した情報。
- route recommendationへの不信・override理由。
- PLHを迂回した場面。

### Stage C: Public beta

- compatibility matrix。
- known limitations。
- anonymized benchmark methodology。
- stable contract fixtures。
- issue templatesにpacket添付方法。

## 9. telemetry方針

local-firstを維持する。既定で外部telemetryを送信しない。

`pcl metrics export`等を作る場合も、利用者が内容をinspectして明示exportする。secret、source本文、prompt全文を既定収集しない。集計値とartifact refsを分離する。

## 10. Go / No-Go

### Discoveryをcoreへ近づけてよい条件

- 曖昧taskでreworkが有意に減る。
- Direct taskへのoverheadが増えない。
- Work Brief fieldが複数repoで安定。
- human checkpointが過剰でない。

### Optionをtable化してよい条件

- generic Evidenceでは検索・lifecycleが明確に不足。
- 2 release以上、同じschemaで反復利用。
- Decisionとの重複責務を説明できる。

### Knowledgeをtable化してよい条件

- accepted/rejected/supersededの運用が実際に使われる。
- contradictionとstalenessの管理が複数repoで必要。
- accepted Knowledgeがhandoff成功に寄与する証拠がある。

### No-Go条件

- false completionが改善しない。
- resume packetがtranscriptより大きい。
- Direct taskのoverheadが10%を継続的に超える。
- route recommendationのoverride率が高く、結果も悪い。
- crash recovery contractを満たせないまま監査性を宣伝する。

## 11. 公開可能な主張

公開文言は測定結果に限定する。

良い例:

- 「公開fixture 40件で、handoff packetからのcheck再現率がX%だった」
- 「弱いモデル条件で、Agent only比のhuman intervention中央値がY回減った」

悪い例:

- 「AI開発を自動化する」
- 「監査不能な失敗がなくなる」
- provider実値なしに「tokenを50%削減」
- 別モデルreviewだけを「正しさの証明」と呼ぶ
