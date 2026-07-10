# 0136: Add deterministic Direct/Discover/Assure route recommendation

- **Status:** Proposed
- **Milestone:** M3 / Adaptive Entry
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** `0135`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

全taskへ同じ工程を適用すると、明確な修正には重く、曖昧・高risk taskには不足する。routeがモデルの自由判断だけでは再現性と説明可能性がない。

## Goal

Work Brief、project metadata、requested scope、risk signalから、LLMなしでroute presetとreason codesを返す。

## Scope

- `route-decision/v1` schemaとpure resolverを実装する。
- 入力signal catalogとstable reason codesを定義する。
- briefのacceptance/non-goal/assumption、明示path、project configからsignalを抽出する。
- `pcl route recommend --target`または`pcl start`出力へ統合する。
- 同じinput digestとpolicy versionで同じ結果を返す。
- recommendation artifact/eventのpersist方針を決める。
- routeに必要情報がない場合は`unknown`を隠さずdiscover寄りまたはhuman-requiredにする。

## Proposed implementation

- ordered rule evaluationとtie-breakerを文書化する。
- profileはDirect/Discover/Assure、resolved axesは0137で完全化する。
- path risk ruleはcase sensitivityとplatform separatorをnormalizationする。
- model self-reportを入力signalにしない。
- reason codeの表示文言とmachine codeを分ける。

## Likely affected surfaces

- route domain module
- signal extraction
- CLI/start integration
- schema/fixtures
- docs

## Invariants

- LLMなし。
- 同じ入力でdeterministic。
- 理由を必ず返す。
- high-risk signalをstrong modelだから無視しない。

## Non-goals

- full policy configuration。
- runtime enforcement。
- agent model selection。
- semantic code analysis。

## Acceptance criteria

- Clear low-risk briefがDirectを返すfixture。
- Missing acceptance/unverified root causeがDiscoverを返すfixture。
- Auth/migration/dependency等のhigh-risk fixtureがAssureまたはelevated reasonを返す。
- 同じinputを複数回解決してbyte-equivalent decision（timestamp除外）になる。
- 各recommendationにpolicy version、input digest、reason codesがある。

## Required tests

- Rule table unit tests.
- Tie-break and missing-data tests.
- Path normalization Linux/Windows.
- Property test for deterministic output.
- Start integration snapshots.

## Evidence required to close

- signal→route decision table。
- fixture outputs。
- determinism test。
- reason code docs。

## Rollout and rollback

- M3ではadvisory。
- overrideを0137で追加。
- misroute dataをmetrics exportへ含める設計。

## Open questions

- 曖昧かつhigh-riskでprofileをDiscover/Assureのどちらに見せるか。
- route decisionを毎回persistするか開始時だけか。

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
