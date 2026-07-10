# 0142: Define a non-executable Profile contract and plugin boundary

- **Status:** Proposed
- **Milestone:** M5 / Discovery Profile
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** `0135`, `0137`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

AI-PLC的な上流Skillをcoreへ直接入れると、LLM依存・任意code実行・DB直接変更・agent固有promptが混ざる。安全な入出力契約とpermission境界が必要。

## Goal

Profileを「versioned manifest + templates + input/output contracts」として定義し、coreが準備・検証・取り込みできるが、任意plugin codeを自動実行しない境界を作る。

## Scope

- `profile-manifest/v1`を定義する。
- profile ID/version、supported inputs、expected outputs、required human gates、permissions、templatesを表す。
- `pcl profile list/show/validate/prepare/ingest`の最小surfaceを設計する。
- prepareはtarget-bound context bundleとinstructionsを生成する。
- ingestはoutput artifactをschema validation後にEvidence化する。
- ProfileがSQLite/JSONLを直接writeしない規約をenforceする。
- package内built-in profileとexternal directory profileのtrust levelを分ける。

## Proposed implementation

- 初期Profileはdata-only。Python import hookやarbitrary command runnerを作らない。
- permissionsはreadable context categoriesとexpected outputに限定する。
- prompt/templateはclaimでありcore policyを上書きできない。
- profile version/hashをEvidence metadataへ残す。
- agent-specific adapterはProfile外の薄いintegrationにする。

## Likely affected surfaces

- profile manifest/schema
- profile registry/loader
- prepare/ingest application
- CLI
- package data/security docs

## Invariants

- ProfileはDBを直接変更しない。
- coreから外部LLMを暗黙呼び出ししない。
- unknown outputを自動採用しない。
- Profile instructionsがrisk policyをoverrideしない。

## Non-goals

- dynamic Python plugin execution。
- marketplace。
- cloud profile download。
- agent process orchestration。

## Acceptance criteria

- Valid built-in profileをlist/show/validateできる。
- Prepareがtarget-bound bundleとexpected output schemaを生成しstateを変更しない。
- Ingestがvalid outputをEvidenceとしてlinkし、invalid outputを拒否する。
- Manifest permission violation/unknown contractがstructured errorになる。
- External untrusted profileがarbitrary codeを実行できない。

## Required tests

- Manifest positive/negative fixtures.
- Package data loading.
- Prepare read-only.
- Ingest schema/link/audit.
- Path traversal/symlink protection.
- Unknown version/contract.

## Evidence required to close

- manifest example。
- prepare bundle。
- ingest Evidence audit。
- security test output。

## Rollout and rollback

- built-in onlyから開始。
- external directory supportはexplicit trust flag。
- executable pluginは別ADRなしに追加しない。

## Open questions

- external profile discovery path。
- template format。
- profile signingを将来検討するか。

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
