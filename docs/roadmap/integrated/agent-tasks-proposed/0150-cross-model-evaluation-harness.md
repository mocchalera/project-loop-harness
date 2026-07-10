# 0150: Build a reproducible cross-model evaluation harness

- **Status:** Proposed
- **Milestone:** M8 / External Evidence
- **Priority:** P0
- **Estimated size:** XL
- **Dependencies:** `0134`, `0137`, `0141`, `0144`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

機能数や内部dogfoodだけでは、PLHが成功率、false completion、handoff、costに寄与したか分からない。Agent only/Direct/Discover/Assureを同条件で比較するharnessが必要。

## Goal

repo snapshot、task、budget、risk、hidden acceptance、model adapterを固定し、結果・packet・diff・costを再現可能に収集する。

## Scope

- fixture manifestとrunner contractを定義する。
- Agent only、PLH Direct、Discover、Assureのconditionを実行できる。
- strong/medium/weak/local model adapterはoptional interfaceとして分離する。
- deterministic checks、hidden tests、human rubric、failure taxonomyを収集する。
- false completion、resume success、review time、scope drift、cost/overheadを算出する。
- raw resultとaggregated reportを分ける。
- model/version/tool permissions/policy version/repo SHAを記録する。
- secretを含まないpublic fixture subsetを用意する。

## Proposed implementation

- provider credentialをfixtureへ保存しない。
- single runを結論にせずrepetition/varianceを扱う。
- provider token actualとlocal estimateを分離する。
- evaluator modelのjudgmentは独立Evidenceとして記録し、hidden testsと混同しない。
- condition名をrubric reviewerから可能な範囲でblind化する。

## Likely affected surfaces

- evaluation fixture schema
- runner
- model adapter interface
- metrics/report
- sample repos/tasks
- docs

## Invariants

- 失敗runを除外しない。
- Agent only baselineを同じbudget/permissionsで比較する。
- marketing claimをrunner自身が生成しない。
- secretをartifactへ含めない。

## Non-goals

- leaderboard service。
- provider benchmark全般。
- 自動課金。

## Acceptance criteria

- 少なくとも4 task type×2 repo×2 model classのsample suiteを再現可能に実行できる。
- 各runにrepo SHA、condition、policy、budget、diff、checks、packet/resultがある。
- false completionとresume successが定義どおり計算される。
- 同fixture再実行でdeterministic部分が一致し、stochastic varianceを別表示する。
- Public reportから個人情報/secretが除かれる。

## Required tests

- Fixture schema.
- Runner resume/failure.
- Metric calculation golden cases.
- Blind rubric data separation.
- Provider adapter mock.
- Public artifact sanitization.

## Evidence required to close

- sample evaluation report。
- raw run manifest。
- metric golden fixtures。
- reproduction instructions。

## Rollout and rollback

- internal suite→closed partner→public subset。
- 結果が悪くても公開/学習材料にする。
- claimはsample sizeと条件を併記。

## Open questions

- 最初のmodel/provider。
- human review time計測方法。
- 公開fixture license。

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
