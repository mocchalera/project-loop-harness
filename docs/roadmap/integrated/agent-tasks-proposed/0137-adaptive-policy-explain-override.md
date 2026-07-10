# 0137: Implement multi-axis adaptive policy, explanation, and explicit override

- **Status:** Proposed
- **Milestone:** M3 / Adaptive Entry
- **Priority:** P0
- **Estimated size:** XL
- **Dependencies:** `0136`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

単一route presetだけでは、planning、verification、execution粒度、budgetを独立調整できない。また利用者が理由を理解・overrideできなければ制御はブラックボックスになる。

## Goal

versioned policyから複数axisを解決し、`pcl explain`で理由を示し、overrideを監査可能に記録する。

## Scope

- planning depth、verification depth、chunk size、checkpoint frequency、context/tool/time/escalation budgetを実装する。
- project policy file formatを既存config方針とzero-dependency制約に合わせて決める。
- risk、ambiguity、capability placeholder、budget signalのrule merge orderを定義する。
- `pcl policy resolve/explain`または`pcl explain route`を追加する。
- `pcl route set/override --reason --actor`を追加し、元recommendationを保持する。
- policy version/input digest/resolved outputをWork Brief/packetへ参照する。
- invalid config、unknown rule、conflictのfail-safe behaviorを決める。

## Proposed implementation

- 設定format選定前に既存PLH config loaderを調査する。YAML dependencyを安易に追加しない。
- rule precedenceはdefaults→project rules→risk floor→explicit human override等、明文化する。
- overrideでR4 destructive prohibition等のnon-overridable invariantを突破できないようにする。
- explain outputは各fieldの決定元ruleを追跡できる。
- policy file変更でprevious packetの意味が変わらないようversion/hashを固定する。

## Likely affected surfaces

- policy parser/resolver
- route module
- CLI explain/override
- events/Decision integration
- config docs/fixtures

## Invariants

- risk floorをmodel capabilityで下げない。
- overrideはactor/reason/time付き。
- invalid policyを黙ってdefaultへfallbackしない。
- 同じpolicy+inputでdeterministic。

## Non-goals

- provider API price lookup。
- automatic model routing execution。
- profile plugin execution。
- full policy GUI。

## Acceptance criteria

- Example policyから全axisが解決され、fieldごとにsource ruleを説明できる。
- Invalid/conflicting policyがstructured errorになり、silent fallbackしない。
- Override後もoriginal recommendationが取得可能でaudit eventがある。
- Non-overridable risk invariantへのoverrideは拒否される。
- Policy hash/versionがcompletion/handoffへ含まれる。

## Required tests

- Rule precedence matrix.
- Conflict/unknown/invalid config.
- Override audit and permissions.
- Determinism/property tests.
- Policy change does not mutate historical packets.
- CLI JSON and human explanation.

## Evidence required to close

- resolved policy fixtures。
- explain transcript。
- override event audit。
- config format decision。

## Rollout and rollback

- advisory axesから開始。
- verification enforcementは0141。
- default policyは保守的かつDirect overheadを最小化。

## Open questions

- config format（existing/JSON/TOML/YAML）。
- override actor identityの信頼境界。
- R4を完全denyにするかmanual-onlyにするか。

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
