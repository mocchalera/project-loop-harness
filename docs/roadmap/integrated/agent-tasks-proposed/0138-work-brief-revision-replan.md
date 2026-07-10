# 0138: Add immutable Work Brief revisions and pcl replan

- **Status:** Proposed
- **Milestone:** M4 / Replan & Assurance
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** `0128`, `0135`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

要求・制約・前提が変わったとき、retryだけでは旧contractに基づくTask/Evidenceを区別できない。in-place編集は何が変わったかを失う。

## Goal

旧briefを保持したまま新revisionを作り、理由と影響候補を監査可能に記録する`pcl replan`を実装する。

## Scope

- `pcl replan --target --reason --brief <file> [--invalidate ...] [--dry-run]`を設計する。
- 新Work Brief artifactへrevision、supersedes、created_byを設定する。
- 旧approved briefをsupersededにし、新briefをdraftまたはapprovedへ進める。
- `work.replanned` eventと関連Decisionを記録する。
- 変更点（acceptance、constraint、assumption、route）のsemantic-free structural diffを生成する。
- impact candidateを表示し、0139が使うinvalidation plan artifactを作る。
- replan前後のhandoffを保持する。

## Proposed implementation

- brief contentをin-place変更しない。
- revision numberだけでなくartifact hash/refでchainを検証する。
- 新brief approvalをhuman gateにする条件をpolicyから取得する。
- 旧briefに依存するpacketを削除しない。
- no-op replanを検出し、不要なrevisionを作らない。

## Likely affected surfaces

- brief application
- Evidence metadata/link
- replan CLI
- events/Decision
- structural diff
- handoff

## Invariants

- 旧revisionはimmutable。
- replan理由なしでapply不可。
- no-opでrevision増加しない。
- stale propagation前でもimpact候補を隠さない。

## Non-goals

- 自動semantic rewrite。
- 全dependent artifactのstale化（0139）。
- Option再生成。

## Acceptance criteria

- Constraint変更を含むreplanでrevision 2がrevision 1をsupersedeし、両方取得できる。
- Dry-runがdiff、impact candidates、必要human gateを示しmutationしない。
- No-op briefは拒否またはexplicit no-opになる。
- Replan eventにreason、actor、old/new refs、policy versionがある。
- Resumeがcurrent briefとreplan summaryを返す。

## Required tests

- Revision chain integrity.
- Dry-run/no-op.
- Approval required/optional policy paths.
- Missing old artifact.
- Concurrent replan conflict.
- Handoff before/after.

## Evidence required to close

- old/new brief and diff。
- event audit。
- dry-run output。
- concurrency conflict result。

## Rollout and rollback

- 最初はexplicit commandのみ。
- 自動triggerは提案を返すだけ。
- dogfoodでreplan理由taxonomyを収集。

## Open questions

- 新briefをdefault draftにするか。
- 既存Decision entityとの1:1/1:N関係。

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
