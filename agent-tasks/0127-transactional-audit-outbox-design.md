# 0127: Finalize transactional audit outbox ADR and failure model

- **Status:** Proposed
- **Milestone:** M1 / Trust Foundation
- **Priority:** P0
- **Estimated size:** M
- **Dependencies:** `0124`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

SQLite state、event row、JSONL、Evidence fileが複数stepで更新されるため、どの時点をcommitとみなすかが曖昧。実装前にsource of truth、failure semantics、legacy migration、repair保証を決める必要がある。

## Goal

ADR-002を実装可能な詳細へ完成させ、0128〜0129のacceptanceを固定する。

## Scope

- 現行mutation pathを列挙し、state/event/JSONL/Evidenceのwrite orderを図示する。
- failure pointをcommit前、commit後、projector前後、file rename前後に分類する。
- SQLiteとJSONLの権威、rebuild direction、retentionを決める。
- outbox schema、event sequence、idempotency key、retry/backoff、poison record処理を決める。
- legacy events.jsonlと既存events tableを対応付ける移行案を決める。
- hash chainをproduct guaranteeに含めるか決める。
- concurrency、migration lock、busy timeoutの契約を明文化する。

## Proposed implementation

- 実コードの全`append_event` callerとcommit ownershipを調査する。
- 「DB commit済みだがJSONL pending」はvalid recoverable stateとして定義する。
- 「JSONLにあるがDBにない」legacy anomalyの扱いを明示する。
- Evidence content-addressed stagingはoutboxと同じtransactionでは完全原子化できないため、PENDING/READY reconciliationを設計する。
- operational commandsとexit codeを先に設計する。

## Likely affected surfaces

- `docs/adr/ADR-002-transactional-audit-outbox.md`
- `src/pcl/events.py` caller inventory
- `src/pcl/evidence.py` write path
- migration/recovery docs

## Invariants

- 設計taskでproduction behaviorを変えない。
- 「append-only」と「tamper-evident」を混同しない。
- repair不能なcaseを自動修復できると書かない。

## Non-goals

- outbox code実装。
- CLI repair実装。
- cloud replication。

## Acceptance criteria

- ADRにsource of truth、transaction boundary、state machine、failure matrix、legacy plan、rollbackがある。
- 全mutation pathがinventory化され、未調査callerがない。
- 0127と0128のschema/CLI acceptanceがADRから導ける。
- Maintainerと少なくとも1名のreviewerがAcceptedまたは明示的な修正要求を記録する。

## Required tests

- No runtime tests required; validate design with executable pseudo-tests or sequence diagrams.
- Prototype SQL transaction/outbox query if needed.
- Review existing fixture DB and JSONL anomaly examples.

## Evidence required to close

- caller inventory。
- failure matrix。
- ADR decision log。
- prototype output。

## Rollout and rollback

- Accepted ADRをmerge gateにする。
- 未決のhash chain等はexplicit deferred decisionにする。

## Open questions

- JSONLからDB完全rebuildをv1で保証するか。
- event hash chainを今入れるか。
- projectorを同期flushとbackground retryのどちらで起動するか。

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
