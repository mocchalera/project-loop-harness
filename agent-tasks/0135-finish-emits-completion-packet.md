# 0135: 既存 pcl finish を completion packet 生成へ拡張（後方互換）

- **Status:** Approved（Wave B activation、DEC-0003 / `docs/plan-v0.4.0.md`）
- **Milestone:** v0.4.0 Dogfood Operations + Three-command Wedge
- **Priority:** P0
- **Estimated size:** XL — 必要なら contract 層 / 実行層の 2 PR に分割してよい
- **Dependencies:** 0134 (contract merged 前提)、0128/0131 (merged)
- **Origin:** bundle 0132 の repo 再採番。ADOPTION.md 最小合意 4「既存
  `pcl finish`（0120）を置き換えず拡張する」を前提とする。

## Problem

現行 `pcl finish` は plan-only（`finish_plan`、`src/pcl/commands.py:721`）+
`--execute`（残 step なしのときだけ validate/render を実行する tail、
`src/pcl/cli.py:1059`）。外部利用可能な packet、diff 固定、check Evidence、
terminal outcome を一つの冪等 use case で生成する surface がない。

## Goal

既存 finish contract（help / JSON / exit code）を後方互換に保ちながら、
safe plan → check 実行 → validation → completion packet 生成 → state commit
までを opt-in で実行できるよう拡張する。

## Scope

1. **最初に現行 `pcl finish` を characterize する**（help / JSON / exit code /
   既存 tests）。既定挙動は plan-only のまま変えない。
2. 実行 mode は明示 opt-in（例: `--apply` / `--emit-packet`。`--execute` の
   既存意味は維持し、migration 設計を返す）。`--dry-run` / `--json` /
   non-interactive 確認 semantics を定義する。
3. active target、base/head revision、dirty state、changed paths を解決する。
   git diff hash は packet 生成時 snapshot と一致させ、finish 実行中の repo
   変更を検出する。
4. check plan は project config / policy から作り、実行前に表示する。
   preconfigured check 以外の任意 command を暗黙実行しない。
5. check 実行は guarded executor（0131 の `workflow guard` 実行基盤 /
   `guarded_process.py`）を再利用し、stdout/stderr/exit code を Evidence 化
   する（出力上限・redaction は 0131 contract に従う）。
6. claim–Evidence binding、strict validation、human gate、budget 状態を確認
   し、`completion-packet/v1`（0134）を content-addressed artifact として
   Evidence store に保存する。
7. packet ref / terminal state / event を**同一 transaction**で commit する
   （0128 outbox 経由。raw SQL 禁止）。packet 生成後に state commit が失敗
   した場合、orphan artifact を `pcl audit check` で検出可能にする（0129 の
   anomaly 分類へ additive 追加）。
8. 冪等性: 同一 state での再実行は既存 packet を返すか明示的 no-op。
   NO_CHANGES / check 失敗（INCOMPLETE_VALIDATION）/ budget・human gate
   block の各 outcome semantics を定義する。

## Invariants

- check 未実行を passed にしない。critical blocker を黙って override しない。
- 同じ packet を重複して別完了として数えない。
- 既存 finish の plan-only 既定・JSON contract・exit code を壊さない
  （characterization test が証拠）。
- LLM 呼び出しなし。自動 PR 作成なし。

## Non-goals

- handoff packet / resume（0137）。profile discovery（Wave C+）。cloud upload。

## Acceptance criteria

- clean success: checks + packet が Evidence 化され terminal outcome が
  COMPLETED_VERIFIED になる。
- check failure: INCOMPLETE_VALIDATION packet が残り、task/goal を completed
  にしない。
- budget / human gate block: 対応する incomplete outcome と next action。
- no changes: NO_CHANGES を説明し、acceptance Evidence 不足なら active 維持。
- unchanged completed state の再実行が重複完了を作らない（idempotency test）。
- finish 実行中の repo 変更 race test。outbox/projector 失敗 path test。
- 既存 finish regression suite green + ruff + full pytest green。

## Agent execution protocol

開始前: 対象 commit SHA と 0134 merge 済みの証拠、変更予定 path、現行 finish
の characterization 結果、scope 外事項。
完了時: 変更概要と設計判断（opt-in flag 設計、outcome semantics）、全 test
command と exit code、各 outcome の example packet（Evidence ref）、CLI 互換
性への影響、Acceptance 別根拠、未確認事項と rollback 方法。
「テストは通るはず」では close しない。
