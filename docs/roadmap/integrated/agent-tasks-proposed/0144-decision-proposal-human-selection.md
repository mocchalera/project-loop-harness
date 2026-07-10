# 0144: Implement decision-proposal/v0 ingestion and human selection flow

- **Status:** Proposed
- **Milestone:** M5 / Discovery Profile
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** `0143`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

Discoveryが候補を生成しても、選択・却下理由・human checkpointを既存Decision/Work Briefへ結べなければ、単なるMarkdown案で終わる。Option専用tableを作らずに状態化する必要がある。

## Goal

Decision Proposal artifactを検証・表示し、人間選択を既存Decisionへ記録し、選択結果からWork Brief revisionを承認可能にする。

## Scope

- `decision-proposal/v0` schema、fixtures、validatorをpackage化する。
- Profile output ingest時にcandidate/evidence refs/recommendationを検証する。
- `pcl decision propose/list/show/select`のthin flowまたは既存Decision command拡張を実装する。
- selectでhuman actor、selected candidate、rejected candidates、理由、overrideを記録する。
- selected candidateをWork Brief revision proposalへ適用し、approvalを別stepにできるようにする。
- routeをDirect executionへ進めるnext actionを返す。
- candidateを削除せずartifact historyとして保持する。

## Proposed implementation

- 既存Decision entityと二重source of truthを作らない。
- recommendationとhuman selectionを別field/eventにする。
- candidate IDの一意性、recommended ID存在、Evidence ref解決を検証する。
- numeric scoreはoptional metadataでありselect logicに自動強制しない。
- non-interactive環境ではhuman_required structured resultを返す。

## Likely affected surfaces

- decision proposal schema
- Profile ingest
- existing Decision services/CLI
- brief revision integration
- handoff/report

## Invariants

- 推薦を自動承認しない。
- 却下案と理由を保持する。
- 既存Decisionが最終選択のsource of truth。
- Evidence不在をhigh confidenceにしない。

## Non-goals

- Option table/CRUD。
- automatic portfolio optimization。
- multi-user voting。

## Acceptance criteria

- Valid proposalをingest/list/showできる。
- Human selectで既存Decision recordとactor/reasonが作られる。
- Recommended案と異なる選択でoverride理由が必須になる。
- Selection後にWork Brief revision proposalとnext actionが返る。
- Invalid candidate/ref/proposalはstateを変更しない。

## Required tests

- Schema positive/negative.
- Select recommended/non-recommended.
- Missing human actor/reason.
- Existing Decision integration.
- Non-interactive human-required.
- History/rejected candidates.

## Evidence required to close

- sample proposal/Decision/brief chain。
- audit events。
- negative fixtures。
- handoff summary。

## Rollout and rollback

- M5でexperimental。
- Option table化はevaluation後。
- profile外からもartifact contractを利用可能にする。

## Open questions

- selectionとbrief approvalを一commandにするか分けるか。
- human actor identityの最低要件。

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
