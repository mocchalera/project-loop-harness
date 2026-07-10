# 0129: Build crash-injection and concurrent-writer reliability suite

- **Status:** Proposed
- **Milestone:** M1 / Trust Foundation
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** `0127`, `0128`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

通常のexception testだけでは、kill、commit境界、partial file write、複数writer競合を検証できない。outbox設計が本当にrecovery contractを満たすか、process boundaryで証明する必要がある。

## Goal

主要crash pointとconcurrency conditionを再現可能に注入し、整合性検出・修復・event orderingをCIで検査する。

## Scope

- test-only fault injection pointをtransaction、commit、projector、Evidence staging、atomic renameへ追加する。
- subprocessを強制終了するharnessを作る。
- 8〜16 writer processで同projectへmutationするtestを作る。
- migration lock中のwriter behaviorを検査する。
- busy timeout、retry/backoff、max attemptsを検査する。
- crash後に`audit check/repair`を実行し、expected stateへ収束することを検査する。
- Linux必須、macOS/Windowsで可能なsubsetを定義する。
- failure matrixと平均runtimeを文書化する。

## Proposed implementation

- fault injectionは明示env/test hookがないproductionでは無効。
- `SIGKILL`相当がないWindowsではterminate/abrupt exitの差を記録する。
- concurrency testはflaky sleepに依存せずbarrier/file lockで同期する。
- event uniqueness、sequence、domain row count、JSONL logical countを検査する。
- CI時間が長い場合はfast subsetとnightly/fullを分ける。

## Likely affected surfaces

- test fault hook
- subprocess harness
- CI matrix
- reliability docs
- audit commands

## Invariants

- test hookが通常実行で有効にならない。
- flaky testをretryだけで隠さない。
- failure後に手動DB編集を前提としない。

## Non-goals

- distributed/network filesystem support。
- database corruption recovery beyond SQLite guarantees。
- performance benchmark全般。

## Acceptance criteria

- 各supported crash pointで、結果がclean commitまたはdetectable recoverable stateのどちらかになる。
- concurrent writersでlost update、duplicate logical event、foreign-key violationがない。
- projector retryがevent orderを保持する。
- CI failure時にどのfault pointで何が壊れたか分かるartifactが残る。

## Required tests

- Crash matrix for pre/post commit, pre/post append, pre/post rename.
- Concurrent mutation stress repeated N times.
- Migration exclusivity.
- Disk/permission error simulation where portable.
- Audit repair convergence.

## Evidence required to close

- failure matrix report。
- stress counts and timings。
- CI artifacts containing DB/JSONL audit summary。

## Rollout and rollback

- fast suiteをrequired gate。
- full stressをscheduledまたはpre-release gate。
- platform limitationをcompatibility docsへ記録。

## Open questions

- required CIのruntime上限。
- Windowsで保証するatomicity subset。

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
