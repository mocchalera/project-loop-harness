# v0.4.0 Plan — Dogfood Operations + Three-command Wedge (Wave B)

- **Status:** Active
- **Date:** 2026-07-10
- **Decided by:** 坂本（PdM/オーナー）指示 2026-07-10「growth plan どおり
  v0.4.0 Dogfood Operations（コスト KPI 実測）。統合ロードマップ Wave B
  （pcl start / completion packet）の活性化判断着手」/ Fable 5 (orchestrator)
  が本計画として具体化
- **Basis:** `docs/growth-plan-v0.2.4-v0.5.md` §3 v0.4.0 + §10 amendment 5、
  `docs/roadmap/integrated/ADOPTION.md`（Wave B activation 節）、
  `docs/roadmap/integrated/00-executive-roadmap.md` M2

## 1. Version label の統合判断

growth plan は v0.4.0 = Dogfood Operations（計測優先）、bundle は
M2 = v0.4.0 = Three-command Wedge を提案していた。両者は矛盾ではなく相補で
ある: wedge の 3 command（`start` / 拡張 `finish` / `resume`）は dogfood で
計測する対象そのもの（finish_roundtrips_saved、handoff KPI、
time-to-first-value）であり、KPI 計測は wedge が emit する packet / receipt
を主要データ源にする。したがって **v0.4.0 = 両者を単一 milestone に統合**する。
これは ADOPTION.md 修正点 3「M2 以降の version label は milestone review 時に
exit 条件優先で決定」の適用である。

## 2. Scope

### 2a. Wave B — Three-command Wedge（コード成果）

活性化タスク（再採番は ADOPTION.md を正とする）:

| repo ID | 内容 | 依存 |
|---|---|---|
| 0134 | `completion-packet/v1` contract（schema package data、validator、fixtures、`pcl contract validate`） | 0123 (merged) |
| 0135 | 既存 `pcl finish` 拡張: check 実行 → validation → packet 生成 → state commit（後方互換、plan-only 既定は維持） | 0134 |
| 0136 | `pcl start "<intent>"` lite entry point（LLM なし、dry-run 完全列挙、重複 active work 禁止） | 0134 |
| 0137 | `handoff-packet/v1` + read-only `pcl resume` | 0135 |

bundle の schema/example（`docs/roadmap/integrated/schemas/`,
`examples/`）は参照素材（planning proposal 権威）であり、実装時の契約は
repo spec と実装コードレビューで確定する。

### 2b. Dogfood Operations — コスト KPI 実測（計測成果）

| repo ID | 内容 | 依存 |
|---|---|---|
| 0138 | KPI 集計 surface `pcl report kpi --json`: 既存記録データ（verification feedback stats、context pack token 推定、bound receipt coverage、finish/packet events）の read-only 集計。新規計測 hook は最小限 | なし（並行可） |

運用成果（コードでなく計測・文書）:

- `docs/dogfood-report-v0.4.md` — PLH 自身 + 外部 repo 1 つ（ax1-moc1 継続
  or 新規）の 2 repo dogfood report。
- **コスト KPI**（growth plan §5 の定義を正とする）:
  - `master_brief_tokens_saved` — pull 型 handoff で master が書かずに済んだ
    output token（charclass/v1 推定器で transcript vs 従来指示書を比較）
  - `average_context_pack_tokens` — handoff 1 回あたりの入力コスト
  - `finish_roundtrips_saved` — `pcl finish` / completion packet による終端
    round-trip 削減数
  - `verification_spend_efficiency` — executed_pass_rate × execution_rate
  - `bound_receipt_coverage` — 誤 context 手戻り予防率
- handoff KPI: worker_handoff_success_rate / handoff_confusion_count /
  bound_receipt_coverage。
- AI-PLC upstream intake dogfood: master-trace / intent-index を
  evidence-linked handoff として 2 repo で使い、`pcl intent` / `pcl collect`
  first-class 化の反復需要を測る（v0.5 判断材料）。
- Codex / Claude Code handoff runbook。

## 3. Exit 条件（version label より優先）

1. **M2 wedge exit（bundle M2 準拠）**: 新規利用者が ontology を知らずに
   10 分以内・3 操作（start → finish → resume）で有用な packet を得る。
   dogfood で time-to-first-value を手動計測して記録する。
2. **Dogfood exit（growth plan 準拠）**: 2 repo の dogfood report が
   `docs/dogfood-report-v0.4.md` に存在し、§2b の KPI 5 種すべてに実測値
   （または計測不能の明示的理由）が入っている。
3. 既存 suite green + `pcl finish` 既存 contract の後方互換維持
   （0135 の characterization test が証拠）。

## 4. 実施順序

```
0134 (contract)  ──┬─→ 0135 (finish 拡張) ──→ 0137 (resume)
                   └─→ 0136 (start)
0138 (KPI report) ── 並行・独立
dogfood 計測 ─────── wedge 出荷後〜継続（report は随時追記）
```

dispatch: 0134 + 0138 を並行起票 → 0135・0136 を 0134 merge 後に並行 →
0137 は 0135 merge 後。全タスク spec-first / worktree worker / orchestrator
独立検収（v0.3.3 と同じ運用）。

## 5. やらないこと（この milestone で）

- work brief / route recommendation / adaptive policy（M3 = Wave C。活性化
  判断は v0.4.0 exit review で行う）
- `pcl intent` / `pcl collect` の first-class table 化（dogfood 結果待ち）
- LLM 呼び出しの core 追加、agent process の自動起動、cloud/remote 連携
- README 導線の書き換え（M2 gate 後 = v0.5.0 の README split で実施）
