# 0123: Release v0.3.1 and freeze the implementation baseline

- **Status:** Proposed
- **Milestone:** M0 / proposed v0.3.1
- **Priority:** P0
- **Estimated size:** S
- **Dependencies:** None
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

`main`にはタスク0122までの変更が入り、package versionはv0.3.1相当だが、統合計画の比較基準としてrelease、CLI contract、DB fixture、docsを固定する必要がある。基準が曖昧なままTrust Foundationへ進むと、後続の破壊的変更と既存不具合を区別できない。

## Goal

現在の挙動を「正しい」と無条件に認定するのではなく、再現可能なbaselineとしてtagし、後続taskが差分と互換性を測れる状態にする。

## Scope

- `pyproject.toml`、package metadata、release notes、task indexのversion表記を一致させる。
- `pcl --help`、主要subcommand help、主要`--json`出力のsnapshot fixtureを保存する。
- 空projectと代表的なv0.3.0 fixture DBからv0.3.1へ到達するsmoke testを作る。
- 現在のschema version、migration list、supported Python/OSをrelease artifactへ記録する。
- `0122`までのcompleted taskと未実装の計画を明確に分離する。
- baseline commit SHAとtest commandsを`docs/releases/v0.3.1-baseline.md`等へ残す。

## Proposed implementation

- 既存release workflowとpackage build手順を先にcharacterizeし、新しいrelease mechanismは作らない。
- CLI snapshotは不安定なtimestamp、temporary path、UUIDをnormalizerで除外する。
- DB fixtureには個人情報や実project contentを入れない。
- current known failuresがある場合は隠さずfixtureとrelease noteへ記録する。
- 後続schema contract testが参照できるfixture directoryを一つに決める。

## Likely affected surfaces

- `pyproject.toml`
- release workflow / changelog
- `tests/fixtures/`
- `agent-tasks/README.md`
- schema/migration documentation

## Invariants

- 既存runtime behaviorをこのtaskで意図的に変更しない。
- testが通らない状態をversion bumpだけでreleaseしない。
- 未リリースの統合機能をrelease noteへcompletedとして書かない。

## Non-goals

- MCP framing修正。
- event outbox実装。
- `pcl start/resume`追加。
- 大規模なREADME再構成。

## Acceptance criteria

- Given clean checkout, when documented build/test commands run, then sdist/wheelが作成されcontract testsが成功する。
- Given release artifact, when version surfacesを比較, then package、CLI、release note、task indexがv0.3.1で一致する。
- Given baseline fixture, when future branchでsmoke testを実行, then behavior差分をsnapshotで検出できる。
- Baseline documentにcommit SHA、schema version、known limitations、実行したtestが記録される。

## Required tests

- Full existing test suite.
- Build and install from both sdist and wheel.
- CLI help/JSON snapshot generation twice with zero diff.
- Fixture DB open/migration smoke on supported Python versions.

## Evidence required to close

- test commandとexit code。
- built artifact hashes。
- baseline commit SHA。
- snapshot fixture diffが空であること。

## Rollout and rollback

- release前にmaintainerがnotesをreview。
- release後にtagとpackage artifactを再installしてsmoke。
- 不一致があれば後続taskを開始せずbaselineを修正。

## Open questions

- v0.3.1をPyPIへ公開するか、GitHub release/tagのみか。
- Windows/macOSをrelease gateに含めるか、M1で追加するか。

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
