# 0146: Add capability-profile/v0 for model-agnostic adaptation

- **Status:** Proposed
- **Milestone:** M7 / Adaptive Cost & Learning
- **Priority:** P1
- **Estimated size:** M
- **Dependencies:** `0137`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

モデル名ごとのhard-codeは陳腐化し、同じモデルでもtool reliabilityやcontext budgetが環境で異なる。weak/strong modelへの適応には能力と観測実績の抽象化が必要。

## Goal

adapter静的情報、user config、観測値からcapability profileを作り、policy axis調整へ使えるようにする。

## Scope

- planning reliability、tool reliability、structured output、context budget、latency/cost class等のv0 contractを定義する。
- profile sourceをadapter default、user override、observed metricsに分ける。
- 各fieldのprovenanceとfreshnessを保持する。
- `pcl capability show/set/import`等のread/explicit mutation surfaceを設計する。
- policy resolverへchunk size/checkpoint/context budget adjustmentとして接続する。
- model name専用ruleではなくcapability conditionを使う。
- observed schema/tool failure rateの更新はopt-in/localにする。

## Proposed implementation

- model自己申告だけでhigh reliabilityにしない。
- 未知fieldはunknownとして保守的に扱う。
- capabilityが高くてもverification risk floorを下げない。
- provider価格をwebから自動取得しない。
- profileにsecret/API keyを保存しない。

## Likely affected surfaces

- capability contract/storage
- adapter metadata
- policy resolver
- CLI
- metrics provenance

## Invariants

- モデル名hard-codeを避ける。
- verification risk floor不変。
- unknownをhigh扱いしない。
- 秘密情報を含めない。

## Non-goals

- automatic provider selection。
- live price service。
- モデルbenchmark service。

## Acceptance criteria

- Adapter defaultとuser overrideからresolved profileとprovenanceが表示される。
- Low tool reliabilityでchunk/checkpointが強化されるがverification riskは変わらない。
- Historical packetが後のprofile変更で意味を変えない。
- Unknown capabilityでsafe deterministic fallbackになる。

## Required tests

- Merge precedence/provenance.
- Unknown/partial profile.
- Policy integration.
- Historical immutability.
- No secrets.
- Model-name independence fixtures.

## Evidence required to close

- contract fixture。
- resolved profile output。
- policy before/after。
- privacy review。

## Rollout and rollback

- v0 advisory。
- observed metrics更新はdefault off。
- field安定後にv1検討。

## Open questions

- observed metricsの最低sample数。
- profile scopeをagent/model/runtimeのどこに置くか。

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
