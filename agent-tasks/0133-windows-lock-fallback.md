# 0133: Windows advisory-lock fallback (msvcrt)

- **Status:** Accepted
- **Milestone:** v0.3.3 Trust Foundation (release blocker)
- **Priority:** P0
- **Estimated size:** S-M
- **Dependencies:** 0128 (merged)
- **Origin:** CI run 29070104876 — `MCP conformance (windows-latest)` failed:
  every `pcl init` returns exit 4 because `src/pcl/locks.py` requires `fcntl`
  and raises `DataStoreError(capability: fcntl.flock)` on Windows. Behavior is
  ADR-002 §4.3-conformant (explicit failure, no silent skip) but is a full
  Windows regression vs v0.3.1. 坂本 decision 2026-07-10: fix before tagging
  v0.3.3.

## Problem

0128 の project-operation lock / JSONL-projector lock は `fcntl.flock` 前提。
Windows には fcntl がなく、全 mutation（init 含む）が明示的エラーで失敗する。

## Goal

Windows で `msvcrt.locking` ベースの fallback を実装し、ADR-002 の lock 意味論
（migration は exclusive、mutation/projector は並行可、projector 同士は
exclusive、lock 省略禁止）を Windows でも成立させる。

## Scope

1. `src/pcl/locks.py` に platform 分岐を追加: POSIX = 現行 fcntl、Windows =
   `msvcrt.locking`。どちらも import 不能な platform では現行どおり明示的
   `DataStoreError`（silent skip 禁止）。
2. msvcrt は shared lock を提供しないため、Windows での意味論は次のいずれかを
   実装し、選択理由と挙動差を docs（`docs/event-outbox-compatibility.md` の
   platform 節）へ明記する:
   - (a) 全 lock を exclusive 化（mutation が直列化される。正しさ優先・並行性
     低下を明記）— 推奨のシンプル案。
   - (b) byte-range を使った shared/exclusive エミュレーション — 採用する場合
     は starvation と正しさの論証を docs に書く。
3. timeout / retry / errno 挙動を POSIX 側と揃える（30s、documented failure）。
4. 単体テスト: fallback 選択ロジック（platform を monkeypatch）、Windows 意味論
   の contract test（POSIX 上でも msvcrt を mock して分岐を検証）。
5. CI: 既存 `MCP conformance (windows-latest)` job が green になること。
   加えて Windows で最低限の smoke（init / goal create / validate --strict /
   audit check）を CI job として追加する。

## Invariants

- lock を黙って省略しない。非対応 platform は明示エラー（現行契約の維持）。
- POSIX 側の挙動・性能を変えない（fcntl 経路は現状維持）。
- ADR-002 の transaction / projector 契約を弱めない。
- schema / migration 変更なし。

## Non-goals

- Windows での crash/concurrency stress suite 対応（0130 の platform 制約は
  現状のまま。将来タスク）。
- network filesystem 対応。
- lock file format の変更。

## Acceptance criteria

- ruff + full pytest green（macOS/Linux）。
- monkeypatch/mock による fallback 分岐テストが追加されている。
- CI の windows-latest jobs（conformance + 新 smoke）が green。
- docs に Windows の lock 意味論（採用案と挙動差）が明記されている。

## Agent execution protocol

開始前: 対象 commit SHA、変更予定 path、characterization 結果、scope 外事項。
完了時: 変更概要、全 test command と exit code、採用した Windows 意味論と根拠、
Acceptance 別根拠、未確認事項（Windows 実機は CI でしか検証できない旨を含む）。
「テストは通るはず」では close しない。
