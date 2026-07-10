# 0124: Freeze the v0.3.1 implementation baseline (fixtures + baseline doc)

- **Status:** Accepted
- **Milestone:** M0 / v0.3.1 baseline (integrated roadmap Wave A)
- **Priority:** P0
- **Estimated size:** S
- **Dependencies:** None
- **Origin:** `docs/roadmap/integrated/agent-tasks-proposed/0123-release-v0-3-1-baseline.md`,
  reduced in scope because v0.3.1 was already released before the bundle was
  adopted (commits `eb69824` → `73f2290`, pyproject `0.3.1`, tag `v0.3.1`).
  Only the baseline-freezing portion of that proposal remains.

## Problem

v0.3.1 は既に出荷済みだが、統合ロードマップ Wave A（MCP 仕様準拠化、
transactional outbox）は挙動を意図的に変更する。比較基準となる snapshot
fixture と baseline document がないと、後続タスクで意図した差分と回帰を
区別できない。

## Goal

現在の挙動を「正しい」と無条件に認定するのではなく、再現可能な baseline
として固定し、後続タスクが差分と互換性を測れる状態にする。リリース作業は
行わない（済んでいる）。

## Scope

1. `pcl --help` と主要 subcommand help、主要 `--json` 出力の snapshot fixture
   を保存する。最低限の対象: `pcl --version`, `pcl --help`,
   `pcl validate --strict --json`, `pcl render --json`, `pcl next --json`,
   `pcl context check --json`（空 project と代表 fixture project の両方）。
2. snapshot は timestamp、absolute path、UUID、hash 等の不安定値を normalizer
   で除外し、2 回連続生成して diff ゼロであることをテストで保証する。
3. 代表的な fixture DB（v0.3.0 相当 schema）から現行 schema へ migrate する
   smoke test を追加する。fixture DB に個人情報や実 project content を
   入れない。
4. `docs/releases/v0.3.1-baseline.md` を作成し、baseline commit SHA、schema
   version、migration list、supported Python versions、known limitations、
   実行した test commands を記録する。
5. 後続 schema contract test が参照する fixture directory を 1 つに決めて
   fixture 配置の README に明記する。

## Invariants

- 既存 runtime behavior をこのタスクで変更しない（fixture とテストの追加のみ）。
- 既存テストを削除・弱体化しない。
- fixture に機密・個人情報・実 project 内容を含めない。
- 生成された snapshot を手で編集しない（不安定値は normalizer で対処する）。
- `.project-loop/` 配下（canonical repo の dogfood 状態）を変更しない。

## Non-goals

- リリース作業、version bump、PyPI 公開（v0.3.1 は出荷済み）。
- MCP framing 修正（0125）。
- event outbox 実装（0128）。
- README 再構成。

## Acceptance criteria

- Snapshot fixture 生成を 2 回実行して diff が空であることをテストが保証する。
- 代表 fixture DB からの migration smoke がローカルで成功する。
- `docs/releases/v0.3.1-baseline.md` に commit SHA、schema version、known
  limitations、実行した test command と exit code が記録されている。
- `ruff check .` と full `pytest` が green。
- `pcl init /tmp/pcl-demo` smoke が成功する。

## Evidence required to close

- test command と exit code。
- baseline commit SHA。
- snapshot fixture の 2 回生成 diff が空である証拠。

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
