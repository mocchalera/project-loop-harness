# 0140: Record producer/verifier provenance and separation level

- **Status:** Proposed
- **Milestone:** M4 / Replan & Assurance
- **Priority:** P0
- **Estimated size:** M
- **Dependencies:** `0131`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

Verification結果があっても、誰/どのsessionが作り、誰が検証し、何のEvidence classを使ったか不明だとmaker≠checkerを評価できない。別モデルであることと証拠強度も混同されやすい。

## Goal

Verificationへproducer/verifier provenance、separation、Evidence class、fallbackを記録し、packet/reportへ反映する。

## Scope

- 現行Verification schemaとagent/job/session identityを調査する。
- producer agent/session/model(optional)とverifier情報をadditiveに保存する。
- `same_run / separate_context / separate_session / separate_agent / human`を算出または明示する。
- `model_judgment / deterministic_check / observational_artifact / human_judgment`を記録する。
- fallback_usedとfallback reasonを記録する。
- 既存verification recordをunknown provenanceとしてread可能にする。
- completion/handoff packetとdashboard/reportへ要約を追加する。

## Proposed implementation

- model名よりagent/session identityを優先する。
- separationは自己申告だけでなく既存job/session metadataから可能な範囲で算出する。
- unknownをsame_agentへ偽装しない。
- human actor identityの信頼境界をdocsへ記載する。
- このtaskではpolicy blockを行わない。

## Likely affected surfaces

- verification storage/migration
- agent/job/session metadata
- packet serializer
- report/dashboard
- CLI record/show

## Invariants

- 別モデルreviewだけでproof levelを上げない。
- unknown provenanceを独立と扱わない。
- fallbackを隠さない。

## Non-goals

- risk-based enforcement（0141）。
- identity provider integration。
- human approval UI。

## Acceptance criteria

- New verification recordにproducer/verifier/separation/evidence classesが保存・表示される。
- Same-agent/separate-session/separate-agent/human fixtureが正しく分類される。
- Legacy recordはunknownとしてreadできる。
- Completion packetがprovenanceを含み、proof calculatorはEvidence classを正しく使う。

## Required tests

- Migration/backward compatibility.
- Separation classification matrix.
- Fallback cases.
- Packet/report serialization.
- Unknown/null identity.
- Privacy: no hidden prompt/transcript required.

## Evidence required to close

- schema diff。
- classification fixtures。
- sample packet/report。
- legacy migration result。

## Rollout and rollback

- 記録を先に導入し、0141までadvisory。
- unknown率をdogfoodで測る。

## Open questions

- session identityをどう生成・信頼するか。
- human actorをlocal usernameで十分とするか。

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
