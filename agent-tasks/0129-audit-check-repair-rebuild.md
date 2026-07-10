# 0129: Add audit integrity check, repair, and rebuild commands

- **Status:** Proposed
- **Milestone:** M1 / Trust Foundation
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** `0128`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

outboxがあっても、利用者が不整合を検出・説明・修復できなければ運用上の信頼は得られない。silent repairは危険であり、dry-runとmachine-readable reportが必要。

**既存実装に注意:** `pcl validate --strict` には既に audit-log integrity check
（`src/pcl/validators.py` の `_validate_audit_log_integrity`、SQLite events と
JSONL の突合）が存在する。本タスクは新規発明ではなく、この既存 check を
characterize した上で `pcl audit check` として拡張・整理し、repair / rebuild
を新設するもの。既存 `validate --strict` の検出範囲と挙動を退行させない。

## Goal

DB、outbox、JSONL、Evidence metadata/filesの整合性を検査し、サポート対象の不整合を安全に修復できるCLIを提供する。

## Scope

- `pcl audit check [--json]`をread-onlyで実装する。
- `pcl audit repair --dry-run`を既定または必須preview付きで実装する。
- `pcl audit rebuild-jsonl --from-sqlite`を実装する。
- pending/failed outbox、missing/duplicate JSONL event、sequence gap、orphan temp evidence、metadata/file mismatchを分類する。
- 修復可能、human review、unsupportedの3分類を返す。
- repair action自身をaudit eventとして記録する。
- backup path、artifact hashes、repair summaryを出力する。

## Proposed implementation

- checkはstateを一切変更せず、projector flushもしない。
- repairはplanを生成し、`--apply`または明示confirmationで実行する。
- JSONL rebuildはtemp fileへ生成・検証し、atomic replaceする。
- legacy unknown lineを削除せず、unsupported anomalyとして隔離/報告する。
- Evidence orphan cleanupはこのtaskではdeleteせず、quarantineまたはreportを優先する。
- large project向けにstreaming scanとprogress on stderrを検討する。

## Likely affected surfaces

- new audit application/CLI module
- outbox/projector
- Evidence store
- recovery docs
- JSON output fixtures

## Invariants

- `audit check`はread-only。
- repair前に対象と理由を表示。
- unknown dataを黙って破棄しない。
- repairでhistoryを捏造しない。

## Non-goals

- JSONL-onlyから全domain stateを完全再構築。
- arbitrary corrupt SQLite repair。
- automatic secret cleanup。

## Acceptance criteria

- Clean projectで`audit check`がOKとcounts/hashesを返す。
- Pending outboxでcheckがrecoverable issueを返し、repair apply後にJSONLへ1回だけ投影される。
- Corrupt/duplicate/missing line fixtureでissue typeとsupported actionが正しく分類される。
- Rebuild後のJSONLがDB event count/orderと一致し、旧file backupが残る。
- `--json`出力がstable schemaでstdout purityを守る。

## Required tests

- Clean/inconsistent fixture matrix.
- Dry-run causes zero mutation.
- Atomic rebuild interruption test.
- Unknown legacy line preservation test.
- Evidence missing/orphan cases.
- Exit code matrix.

## Evidence required to close

- before/after audit reports。
- repair plan fixture。
- backup and rebuilt hashes。
- negative/unsupported case results。

## Rollout and rollback

- 最初はsupport対象caseを狭くする。
- repair不能caseはmanual playbookへ案内。
- docsで保証範囲を明示。

## Open questions

- `audit repair`の既定をdry-runにするか。
- JSONLからDB importを別taskで提供するか。

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
