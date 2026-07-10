# Integrated Roadmap — Adoption Record

- **Decision:** Accept with modifications
- **Date:** 2026-07-10
- **Approved by:** 坂本（PdM/オーナー）
- **Reviewed by:** Fable 5 (orchestrator) — レビューは実コード検証付き
  （MCP framing/negotiation 欠陥と events.py dual-write 欠陥を main で確認済み）
- **Source bundle:** `project-loop-harness-integrated-roadmap-2026-07-09.zip`
  （基準日 2026-07-09、この directory に planning proposal として収載）

## この directory の扱い

この配下は **planning proposal** であり、現行コード・Accepted ADR・Accepted
schema より権威が低い（bundle README の権威順位に従う）。実装 backlog として
active なのは `agent-tasks/`（repo 直下）へコピー・再採番されたタスクだけ。
`agent-tasks-proposed/` はここに参照用として残すが、活性化は wave 承認ごとに
行い、その時点の空き番号で再採番する。

## 採用時の修正点（レビュー指摘の反映）

1. **ベースライン更新**: bundle は「0122 まで完了」を前提にしていたが、
   採用時点で `agent-tasks/0123-master-trace-intent-index-contract.md`
   （承認済み・spec authored）が main に存在し、v0.3.1 も出荷済み。
2. **D-08（Master Trace の時期）**: 承認済み growth plan の
   **v0.3.2 = master-trace / intent-index 契約形式化（repo 0123）を維持**し、
   Wave A（Trust Foundation）と**並行実行**する。bundle の M6 まで先送りする
   案は不採用。bundle の 0145 相当（handoff packet への trace 統合）は repo
   0123 の契約を前提に後続で実施する。コスト KPI 実測（master_brief_tokens_saved
   等）は growth plan v0.4.0 Dogfood Operations の位置を維持する。
3. **version 割当**: v0.3.2 = Master Trace 契約（現行計画のまま）、
   **M1 Trust Foundation = v0.3.3**。M2 以降の version label は milestone
   review 時に exit 条件優先で決定する（bundle の原則どおり）。
4. **bundle 0123「Release v0.3.1」は縮小**: リリースは完了済みのため、
   baseline fixture 凍結部分のみ repo `0124` として起票。
5. **bundle 0128（audit）は既存実装参照へ修正**: `pcl validate --strict` の
   `_validate_audit_log_integrity`（`src/pcl/validators.py`）を characterize
   した上での拡張とする（repo `0129` に反映済み）。

## タスク再採番マップ（Wave A のみ活性化）

| bundle ID | repo ID | 内容 |
|---|---|---|
| 0123 | **0124**（縮小） | v0.3.1 baseline fixtures + baseline doc |
| 0124 | **0125** | MCP stdio framing / version negotiation |
| 0125 | **0126** | MCP external conformance fixtures |
| 0126 | **0127** | Transactional audit outbox ADR / failure model |
| 0127 | **0128** | Event outbox + JSONL projector 実装 |
| 0128 | **0129**（修正） | audit check / repair / rebuild |
| 0129 | **0130** | Crash injection / concurrent writer suite |
| 0130 | **0131** | Guarded executor hardening |
| 0131–0152 | 未採番 | Wave B–E。wave 承認時に空き番号で再採番 |

repo `0123`（master-trace 契約）は bundle 由来ではなく既存承認済みタスク。
Wave A と並行で実行する。

## Wave B activation（2026-07-10 追記）

坂本指示 2026-07-10（「growth plan どおり v0.4.0 Dogfood Operations。統合
ロードマップ Wave B（pcl start / completion packet）の活性化判断着手」）を
受け、Wave B（bundle M2 Three-command Wedge）を活性化する。決定の詳細と
version label の統合判断（v0.4.0 = Dogfood Operations + Wedge の単一
milestone）は `docs/plan-v0.4.0.md` を正とする。pcl 上の決定記録は DEC-0003。

Wave B 再採番マップ:

| bundle ID | repo ID | 内容 |
|---|---|---|
| 0131 | **0134** | completion-packet/v1 contract + validator + fixtures |
| 0132 | **0135** | 既存 `pcl finish` の packet 生成拡張（後方互換） |
| 0133 | **0136** | Lite `pcl start` entry point |
| 0134 | **0137** | handoff-packet/v1 + read-only `pcl resume` |

repo `0138`（`pcl report kpi` 集計 surface）は bundle 由来ではなく growth
plan v0.4.0 Dogfood Operations 由来のタスクとして併せて起票する。
`schemas/completion-packet-v1.schema.json` / `handoff-packet-v1.schema.json`
と `examples/` は planning proposal のまま参照素材とし、実装契約は repo spec
（0134 / 0137）側で確定する。Wave C 以降（0135–0152 bundle 相当）は引き続き
未採番。

## 実装開始前の最小合意（bundle README の 4 点）の判断

1. SQLite を source of truth、JSONL を commit 済み event の投影とする — **Yes**
   （`events.py:31-40` の dual-write 欠陥が実在するため必然。ADR-002 の
   Accepted 化は 0127 の human gate で確定）。
2. `work-brief/v1` は専用テーブルを作らず Evidence artifact から始める — **Yes**
   （ADR-001/004、growth plan §9 と整合）。
3. `direct / discover / assure` は UX preset、制御は複数 policy axis — **Yes**
   （ADR-003。実装は Wave C 活性化時に再確認）。
4. `pcl start → finish → resume` を初心者向け主導線にする — **Yes**
   （既存 `pcl finish`（0120）を置き換えず拡張する。Wave B 活性化時に
   既存 CLI contract の characterization を前提とする）。

## 現行 growth plan との関係

`docs/growth-plan-v0.2.4-v0.5.md` は **Active with integrated amendments**。
supersede ではない。amendments の要点は growth plan 末尾 §10 を参照。
