# 0132: Extend existing pcl finish to generate a completion packet

- **Status:** Proposed
- **Milestone:** M2 / Product Wedge
- **Priority:** P0
- **Estimated size:** XL
- **Dependencies:** `0128`, `0131`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

現行`pcl finish`はterminal close-out plannerとして進んでいるが、外部利用可能なpacket、diff固定、check Evidence、terminal outcomeを一つの冪等use caseで生成する必要がある。

## Goal

既存finish contractを後方互換に保ちながら、safe plan→check execution→validation→packet→state commitを実行できる主力commandへ拡張する。

## Scope

- まず現行`pcl finish`のhelp、JSON、exit code、testsをcharacterizeする。
- active target、base/head revision、dirty state、changed pathsを解決する。
- policyまたはproject configからcheck planを作り、実行前に表示する。
- guarded executorでcheckを実行し、stdout/stderr/exit codeをEvidence化する。
- claim-Evidence binding、strict validation、human gate、budget状態を確認する。
- `completion-packet/v1`をcontent-addressed artifactとして保存する。
- packet ref、terminal state、eventを同一transactionでcommitする。
- 同一stateで再実行した場合のidempotencyとNO_CHANGES behaviorを定義する。
- `--dry-run`、`--json`、non-interactive confirmation semanticsを提供する。

## Proposed implementation

- 既存finishがplan-onlyなら、defaultを即breaking変更せず`--apply/--run-checks`等の移行を設計する。
- preconfigured check以外の任意commandを暗黙実行しない。
- git diff hashはpacket生成時のsnapshotと一致させ、途中変更を検出する。
- check失敗後もEvidenceとincomplete packetを残す。
- packet生成後にstate commitが失敗した場合、orphan artifactをauditで検出可能にする。
- large outputは0130 contractに従う。

## Likely affected surfaces

- existing finish implementation
- git/diff helper
- Evidence store
- contracts
- policy/check planner
- events/outbox
- CLI docs

## Invariants

- check未実行をpassedにしない。
- critical blockerを黙ってoverrideしない。
- 同じpacketを重複して別完了として数えない。
- finish実行中のrepo変更を見逃さない。

## Non-goals

- LLMによるclaim生成。
- profile discovery。
- cloud upload。
- 自動PR作成。

## Acceptance criteria

- Given clean successful task, when finish apply runs, then checksとpacketがEvidence化されterminal outcomeがCOMPLETED_VERIFIEDになる。
- Given check failure, then INCOMPLETE_VALIDATION packetが残り、taskをcompletedにしない。
- Given budget/human gate block, then 対応するincomplete outcomeとnext actionを返す。
- Given no changes, then NO_CHANGESを説明し、acceptance Evidence不足ならactive stateを維持する。
- Re-running unchanged completed state returns existing packet or explicit no-op without duplicate logical completion。

## Required tests

- Existing finish regression suite.
- Golden path success/failure/no-change/budget/human gate.
- Repo changes during finish race.
- Idempotency.
- Packet schema validation.
- Outbox/projector failure.
- Cross-platform command path.

## Evidence required to close

- example packets for each outcome。
- test command artifacts。
- before/after state and event audit。
- CLI migration note。

## Rollout and rollback

- 最初のreleaseでold plan-only flagを保持。
- packet emissionをdogfood projectで既定化後、public defaultを判断。
- packet schema v1を壊す変更は避ける。

## Open questions

- interactive defaultでsafe checksを自動実行するか。
- dirty/untracked fileを許容する条件。
- completion packetをgitignore対象にするか。

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
