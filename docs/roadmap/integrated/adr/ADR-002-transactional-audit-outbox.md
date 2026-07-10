# ADR-002: SQLite transactionを権威とし、JSONLはTransactional Outboxから投影する

- Status: Proposed
- Date: 2026-07-09
- Owners: Architecture / Reliability

## Context

状態変更とJSONL appendを別々に行うdual-writeは、process kill、disk full、exceptionで片側だけ残る。監査とEvidenceを主要価値にするPLHでは、検出不能な不整合を許容できない。

## Decision

- SQLiteをcurrent stateとcommit済みeventのsource of truthにする。
- domain mutation、event row、outbox rowを同一transactionでcommitする。
- JSONL projectorはcommit後にoutboxを読み、冪等にappendする。
- delivery failureはpendingとして残し、再試行する。
- `pcl audit check/repair/rebuild`で検出・復旧できるようにする。

## Alternatives rejected

### JSONL first, then DB

現在と同じdual-write failureを残す。

### Distributed transaction

ローカルCLIには複雑すぎ、filesystemとの完全2PCも現実的でない。

### JSONLのみをsource of truth

current-state query、constraint、migrationが複雑化する。将来のrebuild capabilityとは分離する。

## Consequences

- migrationとprojector実装が必要。
- JSONLは即時ではなくeventual projectionになる。
- CLIはpending projectionをstatusとして表示できる。
- legacy JSONLとの対応付けが必要。

## Open decision

hash chainをv1 guaranteeに含めるか。改ざん検知を宣言するなら`previous_hash/event_hash`が必要。単なるappend-only/rebuildable auditと表現するなら必須ではない。
