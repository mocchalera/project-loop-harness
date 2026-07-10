# 0132: Optional `master_trace_context` section in context-pack/v1

- **Status:** Accepted
- **Milestone:** v0.3.2 Master Trace / Intent Index
- **Priority:** P1
- **Estimated size:** M
- **Dependencies:** 0123 (contract accepted 2026-07-10, pcl decision DEC-0002)
- **Origin:** growth plan v0.3.2 の「0124 候補」項（実採番 0132）。契約は
  `docs/master-trace-intent-index.md` の `master-trace-context/v0` 節が正。

## Problem

master-trace / intent-index 契約（0123）は受け入れられたが、worker への配送は
手動のまま: operator が evidence id と stored path を口頭・prompt で伝えている。
`pcl context pack --task` が optional section として trace/index への参照を
運べば、pull 型 handoff の主導線が 1 コマンドに閉じる。

## Goal

`context-pack/v1` に optional な `master_trace_context` section を additive に
追加する。契約文書の payload 例と boundary をそのまま実装境界とする。

## Scope

1. `pcl context pack --task T-XXXX` に opt-in フラグ（例:
   `--master-trace-context`。正確な flag 名は既存 CLI 慣行に合わせる）を追加し、
   指定時のみ section を emit する。既定では emit しない。
2. section 内容は契約の `master-trace-context/v0` payload 例に従う:
   evidence_id / manifest_path / member_paths / stored_paths（master_trace と
   intent_index の両方）、`trust_model: "claims-not-facts"`、
   `source_ref_discipline`、`raw_transcript_inlined: false`。
3. trace / index evidence の解決は、対象 task に link された evidence
   （`evidence_links`）から行う。該当 evidence が特定できない場合は section を
   捏造せず、明示的な absence（または candidate 提示 + selection-required）を
   返す。曖昧なら勝手に選ばない。
4. `pcl context check` に同 section の preflight（trace/index evidence の存在・
   stored_path 解決可否）を additive に追加する。
5. 0115/0119 の contract fixture 群に、section あり / なし / evidence 不在 /
   曖昧（複数候補）のケースを追加して契約を凍結する。
6. `docs/master-trace-intent-index.md` の「current pcl does not emit it」の
   記述を実装後の状態に更新する。

## Invariants

- **契約文書の boundary をすべて維持する**: raw trace / index 本文を context
  pack・dashboard data へ inline しない。evidence id と path 参照のみ。
- 既存 `linked_evidence` の挙動を変更・再解釈しない。section は additive。
- 外部モデル出力（intent index）を semantically validated と主張しない。
  禁止語彙（`safe_to_continue` / `verified_relevant` / `agent_read` /
  `ready_for_handoff` 等）を出力・コード・docs に導入しない。
- context pack 生成は read-only のまま（DB/event/outbox を変更しない）。
- schema migration なし。既存 `context-pack/v1` の既存 field を壊さない
  （0115 fixture が回帰ゲート）。
- flag 未指定時の出力は byte 単位で従来と同一（v0.3.1 baseline fixture と
  0115 fixture で確認）。

## Non-goals

- `pcl intent` / `pcl collect` / `pcl option` / `pcl replan` / knowledge
  ledger（future promotion gates。別 human approval が必要）。
- first-class trace entity / 専用テーブル。
- intent-index 内容の検証・採点・要約。
- dashboard への trace 表示。

## Acceptance criteria

- opt-in フラグ指定 + link 済み trace/index evidence がある task で、契約
  payload 例に適合する `master_trace_context` section が emit される。
- flag 未指定時の `context pack` 出力が従来と一致する（fixture diff 空）。
- trace/index evidence が不在・曖昧な場合に、捏造せず documented な
  absence / selection-required になる。
- `pcl context check` が section の preflight を報告する。
- 新規 fixture（あり / なし / 不在 / 曖昧）が追加され、`ruff check .` と
  full `pytest` が green。
- 契約文書の該当記述が実装状態へ更新されている。

## Evidence required to close

- test command と exit code。
- section あり / なしの実出力例（fixture として commit）。
- flag 未指定時の従来出力一致の証拠。

## Agent execution protocol

実装担当エージェントは開始前に次を返す。

1. 対象 commit SHA。
2. 変更予定 path。
3. 既存 contract を characterize する test または確認結果。
4. scope 外に見える問題と、今回は触れない理由。

完了時は次を返す。

1. 変更概要と設計判断。
2. 実行した全 test command、exit code、失敗・skip。
3. schema/migration/CLI 互換性への影響。
4. 未確認事項、残存 risk、rollback 方法。
5. Acceptance criteria を一項目ずつ満たした根拠。

「実装した」「テストは通るはず」だけでは close しない。
