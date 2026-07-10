# 0136: Lite `pcl start` entry point

- **Status:** Approved（Wave B activation、DEC-0003 / `docs/plan-v0.4.0.md`）
- **Milestone:** v0.4.0 Dogfood Operations + Three-command Wedge
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** 0134 (merged — start receipt が packet 語彙と整合するため)
- **Origin:** bundle 0133 の repo 再採番。

## Problem

初回利用者が Goal / Feature / Story / Task / Workflow の ontology を理解して
から価値へ到達する構造は重い。明確な仕事を一つ始めるだけの集約 command が
必要（M2 exit: 10 分以内・3 操作で有用 packet）。

## Goal

一つの自然言語 intent から、必要最小の project state と active work target
を作り、次の agent action を返す `pcl start` を提供する。

## Scope

1. contract 設計: `pcl start "<intent>"`、`--dry-run`、`--json`、`--no-init`、
   `--new`。`--profile` は Wave C（route/policy）導入前なので**受け付けない**
   （将来 additive に追加できる extension point だけ設計する）。
2. 未初期化 directory では、明示的な start 操作として最小 project 初期化を
   行う（既存 `init_project`（`src/pcl/init_project.py:243`）を再利用）。
   auto-init が作る files を dry-run で完全列挙する。
3. 既存 project では最小 target を作る。作る entity は **Goal + Task**
   （現行 model で task が goal に紐づくため）を推奨とするが、Task のみ案との
   比較根拠を返して確定する。既存 creation service（`create_goal`
   `src/pcl/commands.py:43`、`create_task` `src/pcl/tasks.py:37`）を再利用し、
   raw DB write を増やさない。
4. active work が既にある場合、重複作成せず resume / 明示 `--new` を案内する
   （`pcl next` / `loop_status` の active 判定を再利用）。
5. intent text / actor / repository revision / created IDs を start receipt
   として Evidence + event に残す（0128 outbox 経由）。
6. `--json` は confirmation 待ちをせず、created IDs / next action を stable
   schema で返す（stdout purity）。最初の next action は agent-neutral な
   text/JSON にする。

## Invariants

- 一回の start で重複 active work を作らない。
- LLM 呼び出しなし。意味的な acceptance criteria を勝手に生成しない。
- 既存 project files を暗黙上書きしない。dry-run は zero mutation
  （DB/event count 不変を test で証明）。
- 細かい既存 commands を廃止・変更しない（純追加）。
- intent string を shell command や path として解釈しない
  （escaping / unicode test 必須）。

## Non-goals

- Discovery questions / option 生成（Wave C+）。agent process 起動。
  acceptance criteria 自動生成。README 導線の書き換え（v0.5.0）。

## Acceptance criteria

- empty repo: start dry-run が予定 files/state を列挙し mutation しない。
- empty repo: start apply 後、active target と next safe action が返る。
- 既存 active work で再 start すると duplicate を作らず resume 案内になる。
  `--new` で明示的に追加できる。
- `--json` が created IDs / next action を stable schema で返す（fixture）。
- 3-command demo transcript（start → finish → resume の start 部分）と
  time-to-first-value の手動計測 note を Evidence として残す。
- uninitialized / initialized / active-work の matrix test、idempotency、
  Windows path、CLI help/JSON snapshot。ruff + full pytest green。

## Agent execution protocol

開始前: 対象 commit SHA と 0134 merge 済みの証拠、変更予定 path、既存 init /
goal / task creation service の characterization 結果、scope 外事項。
完了時: 変更概要と設計判断（最小 entity の選択根拠、auto-init 既定の判断）、
全 test command と exit code、created state/event audit、Acceptance 別根拠、
未確認事項。「テストは通るはず」では close しない。
