# 0151: Run external dogfood and design-partner operations

- **Status:** Proposed
- **Milestone:** M8 / External Evidence
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** `0150`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

PLH自身と作者だけのdogfoodは、既存知識・動機・使い方の偏りが強い。外部利用者が10分で価値へ到達し、継続利用するかを確認する必要がある。

## Goal

5〜10人のdesign partnerで3-command UX、packet review、resume、route/Discoveryを観測し、次の製品判断へ使えるEvidenceを集める。

## Scope

- 対象persona、参加条件、repo diversity、agent runtime diversityを定義する。
- privacy/consent付きonboarding guideを作る。
- `pcl metrics export`が必要ならlocal inspectable reportとして最小実装する。
- 週次interviewとtask diary templateを用意する。
- first value time、abandon reason、override、false completion、resume failureを収集する。
- issue templateにcompletion/handoff packet添付とredaction手順を追加する。
- stop/continue/pivot criteriaを事前に決める。

## Proposed implementation

- default telemetry送信なし。
- export前に内容を利用者がinspectできる。
- source code、prompt全文、secretを既定収集しない。
- 成功談だけでなく未使用・離脱理由を同じ重みで記録する。
- agent runtimeごとのadapter issueとcore issueを分離する。

## Likely affected surfaces

- research protocol
- onboarding docs
- local metrics export if needed
- issue templates
- weekly report

## Invariants

- 明示consentなし外部送信しない。
- participant dataをpublic artifactへ直接出さない。
- 使わなかったtaskを除外しない。

## Non-goals

- 大規模public launch。
- sales funnel。
- cloud analytics。

## Acceptance criteria

- 5〜10人、最低3 runtime、複数repo typeの参加計画と実施記録がある。
- 各参加者でtime-to-first-packetと少なくとも1 resume attemptを観測する。
- 離脱/迂回理由がtaxonomy化される。
- M5/M7機能のcontinue/modify/stop decisionがEvidence付きで記録される。
- privacy reviewとdata deletion手順がある。

## Required tests

- If metrics export code exists: schema/redaction/no-network tests.
- Onboarding dry-run with a new user.
- Packet redaction review.

## Evidence required to close

- anonymized research summary。
- decision records。
- first value/resume metrics。
- privacy checklist。

## Rollout and rollback

- closed cohort。
- 重大integrity issueがあれば募集停止。
- public betaは0152 gate後。

## Open questions

- 募集チャネル。
- support burden上限。
- 報酬/謝礼。

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
