# 0137: handoff-packet/v1 + read-only `pcl resume`

- **Status:** Approved（Wave B activation、DEC-0003 / `docs/plan-v0.4.0.md`）
- **Milestone:** v0.4.0 Dogfood Operations + Three-command Wedge
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** 0135 (merged — latest completion/incomplete packet を選択
  対象に含むため)
- **Origin:** bundle 0134 の repo 再採番。bundle
  `schemas/handoff-packet-v1.schema.json` / `examples/handoff-packet.json` は
  参照素材、契約の正は本 spec と実装レビュー。

## Problem

session や model を変えると、利用者は会話履歴・diff・test 結果・decision を
再説明する。現行 context pack（target-bound、0115/0132）は有用だが、再開の
ための安定した外部 packet と単純な entry point がない。

## Goal

現在の work target を小さい handoff packet へ集約し、`pcl resume` で
read-only に取得できるようにする。

## Scope

1. `handoff-packet/v1` schema / fixtures / validator を 0134 と同じ方式で
   package 化する（`pcl contract validate --type handoff-packet/v1` に追加）。
   bundle top-level fields（target / current_state / summary / verified /
   unverified / decisions / blockers / risks / next_safe_action / context_refs
   / intent_index_ref(optional) / budget_remaining(optional)）を出発点にする。
2. `pcl resume [--target] [--format json|markdown] [--output]` を実装する。
3. 選択 logic: current Goal/Task、latest completion/incomplete packet（0135）、
   Decision、Evidence、blocker、risk。deterministic ordering と target-bound
   link（0113/0116 の links / binding agreement）を使い、superseded/stale
   判定（0114 drift、receipt freshness）を考慮する。
4. **verified と unverified を分離する**。verified に入れられるのは Evidence
   ref で裏づく claim のみ（claims-not-facts、DEC-0002 と同方針）。
5. context refs に freshness/hash を付け、本文全量は既定で inline しない
   （`master_trace_context` 0132 と同じ ref 方式）。packet size と omitted
   sections を記録する（`token_estimation.py` charclass/v1 を再利用）。
6. multiple active targets 時は勝手に選ばず candidate list を返す
   （`context_pack_target_selection_required` の既存 pattern に合わせる）。
7. read-only 保証: export file 以外の state を変更しない（DB hash / event
   count 不変 assertion を test に入れる）。Markdown renderer は JSON contract
   の派生であり source of truth にしない。`--json` stdout purity。

## Invariants

- resume は state を変更しない。full transcript を既定で含めない。
- unverified claim を verified 欄へ入れない。
- 複数 target を曖昧に自動選択しない。
- LLM 呼び出しなし。agent 自動起動なし。

## Non-goals

- Master Trace の生成（既存 0123 契約の消費のみ。bundle 0145 相当の統合深化
  は後続 wave）。remote sync。context embedding。agent-specific adapters。

## Acceptance criteria

- active / incomplete / completed target ごとに valid handoff packet を生成
  できる（fixture matrix）。
- **cross-session replay**: 別 session の test agent が packet だけから
  documented next check を再実行できる（integration test または dogfood
  Evidence）。
- multiple target で exit/JSON が selection required を明示する。
- packet 生成前後で DB/event count が変わらない（read-only assertion）。
- Markdown と JSON が同じ verified/unverified semantics を持つ。
- packet size / omission の記録 test。ruff + full pytest green。

## Agent execution protocol

開始前: 対象 commit SHA と 0135 merge 済みの証拠、変更予定 path、context
pack / links / drift の characterization 結果、scope 外事項。
完了時: 変更概要と設計判断（default target selection の扱い、Markdown
renderer の安定性を contract に含めたか）、全 test command と exit code、
sample handoff packets、Acceptance 別根拠、未確認事項。
「テストは通るはず」では close しない。
