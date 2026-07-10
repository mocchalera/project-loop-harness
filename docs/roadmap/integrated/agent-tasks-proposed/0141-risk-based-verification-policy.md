# 0141: Enforce risk-based verification and human-gate policy

- **Status:** Proposed
- **Milestone:** M4 / Replan & Assurance
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** `0137`, `0140`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

maker≠checkerを全taskへ強制すると高コストだが、auth/migration等を自己承認だけで閉じるのも危険。riskごとの最低Evidence・separation・human gateをpolicy化する必要がある。

## Goal

R0〜R4とresolved policyに基づき、finish前に必要check、separation、approvalを評価し、未達なら説明付きで停止する。

## Scope

- path/change metadataからrisk signalをfinish時に再評価する。
- R0〜R4のdefault minimum verification matrixを定義する。
- required Evidence class、separation、human gate、check categoryをpolicyへ追加する。
- `pcl verify plan/explain`またはfinish planへ不足項目を表示する。
- unmet requirementをstructured blockerにする。
- override可能/不可能なruleとactor/reasonを定義する。
- completion packetへresolved risk、requirements、met/unmetを含める。

## Proposed implementation

- risk detectionはroute開始時だけでなくactual diffで再計算する。
- R3/R4はsame-agent model judgmentだけでclose不可。
- deterministic checkが存在しない場合はそれを明示しhuman/observational Evidenceへ上げる。
- false positiveを減らすためpath ruleをproject override可能にするが、critical invariantは保護する。
- policy explanationをhuman-readableとJSONで同一semanticsにする。

## Likely affected surfaces

- risk signal extractor
- policy resolver
- verification validator
- finish
- packet
- CLI explain

## Invariants

- model capabilityでrisk floorを下げない。
- human gate未達をcompletedにしない。
- overrideをauditなしで許可しない。
- check不存在をpassed扱いしない。

## Non-goals

- automatic human notification。
- remote approval service。
- security certification。

## Acceptance criteria

- R0 docs taskがself-review/lintで閉じられる。
- R1 local code fixがdeterministic testを要求する。
- R2 public API changeがindependent reviewまたは指定checkを要求する。
- R3 auth/migration fixtureがseparate verifier + deterministic checks + configured human gateなしに閉じられない。
- Override attemptがallowed/denied ruleに従い、理由とactorを残す。

## Required tests

- Risk matrix fixtures.
- Actual diff raises risk after start.
- Missing deterministic checks.
- Override permissions/invariants.
- Finish outcomes and packet fields.
- Project rule customization.

## Evidence required to close

- risk matrix output。
- blocked/approved sample packets。
- override audit。
- false positive dogfood log。

## Rollout and rollback

- 初回はwarning/advisory modeを短期間提供可能。
- R3/R4 enforcementを先にhard enable。
- R1/R2はdogfood後にdefault。

## Open questions

- R2で別agentを必須にするかseparate contextで足りるか。
- human gate timeout/identity。

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
