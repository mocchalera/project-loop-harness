# 0138: コスト KPI 集計 surface（`pcl report kpi`）

- **Status:** Approved（v0.4.0 Dogfood Operations / `docs/plan-v0.4.0.md` §2b）
- **Milestone:** v0.4.0 Dogfood Operations + Three-command Wedge
- **Priority:** P1
- **Estimated size:** M
- **Dependencies:** なし（0134–0137 と並行可。packet 系指標は「未計測」表示で
  先行実装し、0135/0137 merge 後に additive に埋まる設計にする）
- **Origin:** growth plan v0.4.0（`docs/growth-plan-v0.2.4-v0.5.md` §3/§5）
  由来。bundle 由来ではない。

## Problem

growth plan §5 のコスト KPI（テーゼ2 の証明）を dogfood report に書くための
集計 surface がない。verification feedback stats
（`src/pcl/verification_feedback.py:145` `verification_feedback_stats`、
migration 005）は CLI から取れるが、context pack の token 推定は生成時に
表示されるだけで**永続記録されない**（`src/pcl/context.py` は event を emit
しない read-only 設計）ため、average_context_pack_tokens を後から集計できない。

## Goal

既存記録データの read-only 集計 command `pcl report kpi --json` と、集計に
必要な最小の usage 記録を追加し、`docs/dogfood-report-v0.4.md` の実測値を
機械的に再現可能にする。

## Scope

1. `pcl report kpi [--json] [--since <ISO date>]`（read-only）。growth plan
   §5 の指標を section 化して返す:
   - `verification_spend_efficiency`: execution_rate / executed_pass_rate /
     feedback_coverage_rate（既存 `verification_feedback_stats` の再利用 +
     executed_pass_rate × execution_rate の合成値）
   - `context_pack`: 生成回数 / average_context_pack_tokens /
     bound_receipt_coverage（bound receipt 付き生成の割合）
   - `finish`: finish 実行回数 / packet outcome 分布 /
     finish_roundtrips_saved の算出材料（0135 未 merge の間は
     `not_yet_measured` を明示）
   - `handoff`: resume/packet 生成回数（0137 未 merge の間は同上）
   - 各指標に `data_source`（event type / table）と `window` を明記する。
2. **context pack usage の最小記録**: `pcl context pack` 成功時に
   `context_pack_generated` event（estimated_token_count / token_estimator /
   target / bound_receipt 有無 / truncated 有無）を 0128 outbox 経由で emit
   する。これは context pack の「project state を変えない」性質のうち
   **成果物 selection には影響しない**追加であり、audit trail への操作記録と
   して位置づける。契約影響（0115 fixtures、read-only を assert している既存
   test）を characterize し、変更点を docs / fixture README（`tests/fixtures/
   v0.3.1-baseline/README.md` の Intended changes 節）に記録する。
   ※ event 追加が既存 read-only contract test と両立不能な場合は、opt-out
   （`--no-usage-event`）ではなく**設計相談として halt して報告**する。
3. 未計測値の扱い: データが無い指標は `null` + `reason`（`not_yet_measured` /
   `no_data_in_window`）を返す。**擬似精度禁止** — 推定値を実測値のように
   出さない。master_brief_tokens_saved は transcript 比較の手動計測（dogfood
   report 側）とし、この command では算出しない旨を docs に明記する。
4. `docs/dogfood-report-v0.4.md` の**雛形**を追加する（KPI 表、計測手順、
   2 repo 分の記入欄。実測値の記入は運用作業であり本タスクの scope 外）。

## Invariants

- report は read-only（DB/event count 不変 assertion）。
- raw SQL を CLI 外へ公開しない。既存 stats API を再利用する。
- LLM 呼び出しなし。telemetry / 外部送信なし（計測はすべて local）。
- 既存 command の JSON contract を壊さない（event 追加は additive）。

## Non-goals

- master_brief_tokens_saved の自動算出。dashboards の過剰リッチ化。
  KPI の閾値 gate 化（計測が先、判断は v0.4.0 exit review）。

## Acceptance criteria

- `pcl report kpi --json` が上記 section を stable schema で返す（fixture）。
- verification 指標が `verification_feedback_stats` と一致する（同一 DB での
  equality test）。
- `context_pack_generated` event が pack 成功時に記録され、平均 token 集計が
  event から再現できる（統合 test）。
- 未計測指標が null + reason で返る（0135/0137 前の状態を fixture 化）。
- dogfood report 雛形が存在し、KPI 表の各行に計測手段が書かれている。
- ruff + full pytest green。baseline fixture への影響があれば Intended
  changes 節へ記録されている。

## Agent execution protocol

開始前: 対象 commit SHA、変更予定 path、context pack read-only test と
verification stats の characterization 結果、scope 外事項。
完了時: 変更概要と設計判断（event 追加の契約影響評価を含む）、全 test
command と exit code、Acceptance 別根拠、未確認事項。
「テストは通るはず」では close しない。
