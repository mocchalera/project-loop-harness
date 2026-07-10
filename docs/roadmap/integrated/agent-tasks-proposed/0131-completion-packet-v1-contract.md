# 0131: Define and package completion-packet/v1 contract

- **Status:** Proposed
- **Milestone:** M2 / Product Wedge
- **Priority:** P0
- **Estimated size:** M
- **Dependencies:** `0123`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

`pcl finish`がclose-out planを作れても、agent/runtimeをまたいで利用できる安定した完了artifactがなければ、PLHの価値を外部へ渡せない。内部DB rowをそのまま公開するとschema migrationと外部互換性が結合する。

## Goal

claim、check、diff、risk、outcomeを表現するversioned completion packet contract、validator、fixturesを実装する。

## Scope

- `completion-packet/v1` JSON Schemaをpackage dataとして追加する。
- positive、minimal、full、negative fixturesを追加する。
- canonical serializerとschema validatorを追加する。
- claim-scoped proof level calculation rulesを実装またはpure moduleとして定義する。
- packet ID、timestamp、diff hashのcanonicalizationを決める。
- `pcl contract validate --type completion-packet/v1 <file>`相当のread-only検証surfaceを追加する。
- contract documentationとcompatibility policyを追加する。

## Proposed implementation

- 内部DB primary keyやprivate pathを必須fieldにしない。
- Evidence本文ではなくrefを既定にする。
- check statusにpassed/failed/skipped/not_run/timed_outを区別する。
- outcomeとcritical claim proofの整合性validatorを作る。
- unknown additive fieldの扱いをschema/reader policyで決める。
- JSON Schema library dependencyがない場合は既存validation方針に合わせる。

## Likely affected surfaces

- new contracts package
- schema package data
- validator
- CLI contract command
- docs/fixtures

## Invariants

- 別モデルreviewだけでL2以上にしない。
- 実行していないcheckをpassedにしない。
- budget exhaustionをcompleted outcomeにしない。
- packet generationはモデルを呼ばない。

## Non-goals

- `pcl finish` runtime integration。
- handoff packet。
- remote upload。
- UI rendering。

## Acceptance criteria

- Minimal/full fixturesがvalidatorを通り、各negative fixtureが期待reasonで失敗する。
- Packageをwheelからinstallしてschemaを読める。
- Proof calculatorがclaim/Evidence classから決定論的に同じlevelを返す。
- Contract docsにversioning、field semantics、non-guaranteesがある。

## Required tests

- Schema fixture matrix.
- Serializer round-trip and deterministic ordering where promised.
- Proof level table tests.
- Outcome/claim consistency negatives.
- Wheel/sdist package data test.
- CLI stdout/exit code contract.

## Evidence required to close

- schema hash。
- fixture validation output。
- package artifact inspection。
- contract review decision。

## Rollout and rollback

- v1はM2でstable候補。
- field追加はfixture更新必須。
- breaking変更はv2へ。

## Open questions

- strict `additionalProperties=false`をconsumer互換上維持するか。
- packet IDをcontent hashにするかrandom IDにするか。

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
