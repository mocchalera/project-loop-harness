# 0127: Implement transactional event outbox and idempotent JSONL projector

- **Status:** Proposed
- **Milestone:** M1 / Trust Foundation
- **Priority:** P0
- **Estimated size:** XL
- **Dependencies:** `0126`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

現行event pathはJSONLとSQLiteを原子的に更新できず、process crashで片側だけ残り得る。監査・recoveryを製品価値にするには、state mutationとevent persistenceを同一transactionへ入れ、JSONLを安全に投影する必要がある。

## Goal

domain state、event row、outbox rowを一つのSQLite transactionでcommitし、JSONL projectorが重複なく追従できるようにする。

## Scope

- 次の空きmigrationでevent sequence/outbox tableと必要indexを追加する。
- 明示的transaction coordinatorまたはunit-of-workを導入する。
- `append_event`をJSONL直接writeからevent/outbox insertへ変更する。
- commit後にprojectorを呼び、pending recordをevent orderでJSONLへappendする。
- event ID/sequenceでidempotencyを保証し、retry時のduplicateを検出する。
- projector failureをstate mutation failureとしてrollbackしないが、pending/diagnosticを返す。
- legacy projectで既存JSONLを破壊せず、新eventから追従できるようにする。
- 全mutation callerを新transaction contractへ移行する。

## Proposed implementation

- connection commitをcaller任せにする現在のpathをcharacterizeし、二重commitやnested transactionを避ける。
- JSONL writeはflush/fsync policyをADRに従って実装し、platform差をtest可能にする。
- projector cursorをJSONL内のevent IDまたはside metadataで確認する。
- outbox recordにはattempts、last_error、delivered_atを持たせる。
- projectorはstdoutへprogressを混ぜず、structured resultを返す。
- package downgrade時に新schemaを破壊しない。

## Likely affected surfaces

- `src/pcl/db.py`
- `src/pcl/migrations.py`
- `src/pcl/events.py`
- new outbox/projector module
- all mutation command tests

## Invariants

- DB transaction commit前に新eventをJSONLへ出さない。
- 同じevent IDをJSONLへ複数回論理追加しない。
- projector failureでcommit済みdomain stateを消さない。
- read-only commandsがoutbox stateを変更しない（明示flushを除く）。

## Non-goals

- full audit repair UI。
- JSONLから任意DB versionへの完全rebuild。
- background daemon。
- cloud sink。

## Acceptance criteria

- Given mutation transaction rolls back, when files are inspected, then new eventはDB/outbox/JSONLのいずれにもcommit済みとして現れない。
- Given DB commit succeeds and projector fails, then state/event/outboxは残り、JSONL pendingが明示される。
- Given projector retries same outbox record, then JSONLのlogical event countは1のまま。
- Existing mutation testsが新contractで通り、legacy fixtureを開いて新eventを追加できる。

## Required tests

- Migration upgrade from all supported fixture versions.
- Transaction rollback tests.
- Projector failure/retry/duplicate tests.
- Event ordering under sequential and concurrent writes.
- JSONL line parsing and fsync policy tests.
- Package install artifact includes migrations.

## Evidence required to close

- migration SQL and schema snapshot。
- failure/retry test output。
- before/after legacy fixture。
- event count/order assertion。

## Rollout and rollback

- feature flagは不要だが、migration前backupを自動案内。
- projector errorをwarningではなくstructured recoverable statusで返す。
- 重大不具合時はprevious packageでread-only inspection可能にする。

## Open questions

- projectorを各mutation後に同期attemptするか、explicit flushのみか。
- fsyncをdefaultにするperformance trade-off。

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
