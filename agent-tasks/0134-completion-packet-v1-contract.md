# 0134: completion-packet/v1 contract + validator + fixtures

- **Status:** Approved（Wave B activation、DEC-0003 / `docs/plan-v0.4.0.md`）
- **Milestone:** v0.4.0 Dogfood Operations + Three-command Wedge
- **Priority:** P0
- **Estimated size:** M
- **Dependencies:** 0123 (merged — master-trace/v0 契約と同じ claims-not-facts 方針)
- **Origin:** integrated roadmap bundle 0131（`docs/roadmap/integrated/agent-tasks-proposed/0131-completion-packet-v1-contract.md`）の repo 再採番。bundle の `schemas/completion-packet-v1.schema.json` と `examples/completion-packet-*.json` は**参照素材（planning proposal 権威）**であり、本 spec と実装レビューが契約の正。

## Problem

`pcl finish`（0120、plan-only）は close-out plan を作れるが、agent/runtime を
またいで利用できる安定した完了 artifact がない。内部 DB row をそのまま公開
すると schema migration と外部互換性が結合する。

## Goal

claim / check / diff / risk / outcome を表現する versioned completion packet
contract、canonical serializer、validator、fixtures を実装する。runtime
統合（finish からの emit）は 0135 で行い、本タスクは契約層のみ。

## Scope

1. `completion-packet/v1` JSON Schema を package data として追加する
   （`pyproject.toml` の `[tool.setuptools.package-data]` に登録し、wheel から
   読めることをテストする）。bundle schema の top-level fields
   （contract_version / packet_id / producer / generated_at / outcome / target
   / repository / changes / checks / claims / unverified_claims / risks /
   human_decisions / next_action / verifier_provenance(optional)）を出発点に、
   現行 PLH の entity model（Goal/Task/Evidence ID 形式）へ合わせて確定する。
2. positive（minimal / full）+ negative fixtures。negative は期待 reason 付き。
3. canonical serializer（deterministic ordering）+ schema validator。JSON
   Schema library を新規依存に入れる場合は最小構成にし、入れない場合は既存
   validation 方針（手書き validator）に合わせる — どちらを選んだか根拠を返す。
4. claim-scoped proof level の決定論的計算 rule を pure module として定義する。
5. packet ID / timestamp / diff hash の canonicalization を決める
   （packet ID は content hash か random ID か — 選択と根拠を返す）。
6. read-only 検証 surface: `pcl contract validate --type completion-packet/v1
   <file>`（`--json` あり、stdout purity 維持、exit code contract 明記）。
7. contract docs（versioning / field semantics / non-guarantees /
   compatibility policy）。`docs/master-trace-intent-index.md` と同じ
   claims-not-facts の trust model を明記する。

## Invariants

- 別モデル review だけで proof level L2 以上にしない。
- 実行していない check を passed にしない（passed/failed/skipped/not_run/
  timed_out を区別）。
- budget exhaustion を completed outcome にしない。
- packet generation はモデル（LLM）を呼ばない。
- Evidence は本文でなく ref を既定にする。内部 DB primary key や private path
  を必須 field にしない。
- 既存 CLI / schema / migration に破壊的変更なし（本タスクは純追加）。

## Non-goals

- `pcl finish` runtime 統合（0135）。handoff packet（0137）。remote upload。
  UI rendering。

## Acceptance criteria

- minimal/full fixtures が validator を通り、各 negative fixture が期待
  reason で失敗する。
- wheel を build し、install した環境から schema package data を読める。
- proof calculator が claim/Evidence class から決定論的に同じ level を返す
  （table test）。
- outcome と critical claim proof の整合性 validator が negative を弾く。
- `pcl contract validate` の stdout/exit code contract test がある。
- ruff + full pytest green。

## Agent execution protocol

開始前: 対象 commit SHA、変更予定 path、既存 contract 群（context-pack/v1、
master-trace/v0）の characterization 結果、scope 外事項。
完了時: 変更概要と設計判断（schema library 採否、packet ID 方式、bundle
schema からの差分）、全 test command と exit code、Acceptance 別根拠、
未確認事項。「テストは通るはず」では close しない。
