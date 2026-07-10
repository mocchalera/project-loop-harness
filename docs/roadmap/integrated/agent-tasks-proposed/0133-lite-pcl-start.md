# 0133: Add Lite pcl start entry point

- **Status:** Proposed
- **Milestone:** M2 / Product Wedge
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** `0131`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

初回利用者がGoal、Feature、Story、Task、Workflow等を理解してから価値へ到達する構造は重い。明確な仕事を一つ始めるだけの集約commandが必要。

## Goal

一つの自然言語intentから、必要最小のproject stateとactive work targetを作り、次のagent actionを返す`pcl start`を提供する。

## Scope

- `pcl start "<intent>"`、`--dry-run`、`--json`、`--profile`、`--no-init`等のcontractを設計する。
- 未初期化directoryでは、明示されたstart操作として最小project初期化を行うかpreviewする。
- 既存projectでは一つのGoal/Task等、現在modelに沿う最小targetを作る。
- active workが既にある場合、重複作成せずresume/explicit `--new`を案内する。
- intent text、actor、repository revision、created IDsをstart receipt/eventへ残す。
- LLMなしで動作し、意味的なacceptanceを勝手に生成しない。
- M3導入後にWork Brief/routeをadditiveに結べるextension pointを作る。

## Proposed implementation

- 既存`pcl init`とentity creation serviceを再利用し、DB直接writeを増やさない。
- auto-initが作るfilesをdry-runで完全列挙する。
- non-interactive `--json`ではconfirmation待ちをせず、必要actionをstructuredに返す。
- intent stringをshell commandやpathとして解釈しない。
- 最初のnext actionはagent-neutral text/JSONにする。

## Likely affected surfaces

- CLI
- init service
- Goal/Task creation services
- events
- start receipt/JSON fixture
- golden path docs

## Invariants

- 一回のstartで重複active workを作らない。
- LLM呼び出しなし。
- 既存project filesを暗黙上書きしない。
- 細かい既存commandsを廃止しない。

## Non-goals

- Discovery questions。
- automatic option generation。
- agent process launch。
- acceptance criteria自動生成。

## Acceptance criteria

- Empty repoでstart dry-runが予定files/stateを示し、mutationしない。
- Empty repoでstart apply後、active targetとnext safe actionが返る。
- Existing active workで再startするとduplicateを作らずresume案内になる。
- `--json`がcreated IDs、profile request、next actionをstable schemaで返す。
- 既存advanced workflowは従来commandで利用可能。

## Required tests

- Uninitialized/initialized/active-work matrices.
- Dry-run zero mutation.
- Idempotency and explicit `--new`.
- Intent text escaping/unicode.
- Windows path.
- CLI help/JSON snapshots.

## Evidence required to close

- 3-command demo transcript。
- created state/event audit。
- dry-run diff zero。
- time-to-first-value manual measure。

## Rollout and rollback

- README topへ置くのはM2 gate後。
- advanced users向けcommandsはそのまま。
- auto-init反発をdogfoodで観測。

## Open questions

- auto-initをdefaultにするか。
- 作る最小entityをGoal+TaskとするかTaskのみとするか。
- default profileをauto/directどちらにするか。

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
