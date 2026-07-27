# PCL 実利用摩擦の修正計画

## 0. 文書の位置づけ

本書は、実利用タスクの継続監視と修正方針レビューで確認した PCL の不具合・摩擦を、実装可能な依存順へ固定する計画である。

- 保存日: 2026-07-27
- 入力:
  - Cockpit task `07634a9e`「PCL実利用摩擦の修正方針レビュー」
  - adopter task `81812d6f` の PCL 利用ログと完了時点の状態
- レビュー結果: 12件 confirmed、2件 partially confirmed、0件 rejected
- 実装開始点: P0-1「finish safety substrate」
- 承認不要の初期境界: Python 標準ライブラリ、既存 Evidence・event・content-addressed JSON を使用し、DB migration と依存追加を行わない

本書は実装順を定める。各 Story の意味承認、DB migration、依存追加、外部自動書き込み、過去状態の自動再オープンは、別途明示的な人間判断を必要とする。

## 1. 成功条件

P0 完了時に、次をすべて満たす。

1. `pcl finish --emit-packet` の検証は、検証対象の入力と副作用を説明でき、正規作業ツリーの意図しない変化を成功証拠として採用しない。
2. check のプロセス成功、assertion 成功、失敗フェーズ、失敗種別を分離し、exit code 0 だけで再現可能な成功と判定しない。
3. `next`、`finish`、lifecycle の terminal readiness が同じ計算結果を使う。
4. 既存 Goal / Task に実行を attach でき、対象未指定時に無関係な Defect や Decision へ誤誘導しない。
5. Feature / Test / Task の派生状態と、作業開始時の Task 状態が利用者に一貫して見える。
6. audit と finish check は対象・期間・要約で絞れ、同一 check を役割別に重複実行しない。
7. PCL 状態変更、リポジトリ書き込み、外部変更の権限境界と terminal prerequisites が guide で分離される。
8. worktree / Cockpit / CI を含む canonical root binding と、マイルストーン進捗を構造化して観測できる。

## 2. 非交渉条件

- SQLite、JSONL、生成 HTML を agent が直接変更しない。
- すべての PCL 状態変更は service / CLI を通し event を追加する。
- dashboard HTML を機械状態として読まない。
- Evidence の存在と成功 claim を分離する。失敗・矛盾・timeout を成功 receipt で上書きしない。
- `finish` 実行中に正規作業ツリーを自動復元しない。入力変化は fail closed に分類する。
- 同じ入力・policy・check plan に対する結果は決定的に識別できる。
- 初期 P0 で OS sandbox、network isolation、強い認証済み actor independence を主張しない。
- 後方互換を壊す packet schema 変更は行わず、P0 の追加情報は Evidence artifact と additive JSON field で運ぶ。

## 3. 修正対象

| ID | 状態 | 問題 | P0 の解決方向 |
| --- | --- | --- | --- |
| F1 | confirmed | strict warning が terminal success を不必要に妨げる | low risk として `COMPLETED_WITH_RISK` へ統一 |
| F2 | confirmed | `next` と `finish/close` の terminal readiness が別計算 | shared readiness evaluator |
| F3 | confirmed | `pcl start` が既存 Goal / Task に attach できない | explicit attach target |
| F4 | confirmed | unbound `next` が複数 Goal 選択より無関係 Defect を優先 | target binding / ambiguity route |
| F5 | confirmed | Feature done / Test passing から Task ready_to_close が派生しない | readiness projection |
| F6 | confirmed | `start` 後も Task は `todo` のまま work_started だけ記録 | visible started state / derived status |
| F7 | confirmed | audit に target / since / summary scope がない | scoped audit read surface |
| F8 | confirmed | 同一 finish check を role ごとに二重実行する | shared immutable check result |
| F9 | confirmed | guide が PCL state mutation と repo/file write を混同 | operator permission matrix |
| F10 | partial | canonical root はあるが worktree / Cockpit / CI binding が弱い | typed execution binding |
| FA | confirmed | マイルストーン進捗を横断観測できない | progress receipt / projection |
| FB | partial | exit-only failure taxonomy が原因を潰す | structured result taxonomy |
| FC | confirmed | finish check が canonical root を変更でき、証拠を汚染する | input manifest + isolated execution |
| FD | confirmed | 単発 exit 0 を reproducible と表現し、cold/warm 混在を保持しない | attempt identity + stability result |

`FB` の worker 固有原因と `F10` の実行系 binding の完全形は、追加 fixture で確定する。未確定部分を推測で正常化しない。

## 4. 実装順

### P0-1: Finish safety substrate

対象: `FC`

#### Slice C0: verification input manifest

`verification-input-manifest/v1` を content-addressed JSON として生成できる純粋な runtime module を追加する。

記録対象:

- resolved canonical root、Git base / HEAD
- tracked / untracked / ignored の分類
- path、kind (`file` / `directory` / `symlink`)、mode、size、SHA-256 または symlink target
- `.project-loop/**` の除外理由
- manifest digest と収集時刻
- 収集失敗・読み取り競合の typed failure

比較結果:

- `read_only`
- `declared_outputs`
- `mutates_inputs`
- `unknown`

受け入れテスト:

- tracked source の内容・mode・symlink target の変更を検出する。
- untracked file の追加・変更・削除を検出する。
- ignored cache の追加は policy 上の declared output として分離できる。
- 読み取り中の消失、permission error、特殊 file は `unknown` へ fail closed する。
- 同じ入力から同じ canonical digest を生成する。
- `.project-loop/**` は入力 claim に混ぜない。

#### Slice C1: isolated finish workspace

- 正規 Git metadata を共有しない一時実行 workspace を作る。
- base checkout に dirty tracked / untracked 入力を materialize する。
- check は一時 workspace で実行し、stdout / stderr / result は既存 stage Evidence へ戻す。
- 実行前後 manifest を比較し、effect classification を check Evidence に記録する。
- `mutates_inputs` / `unknown` は `finish-attempt/v1` を残して `INCOMPLETE_VALIDATION` とし、terminal packet を生成しない。
- 正規作業ツリーの concurrent edit は race として検出し、自動復元しない。

受け入れテスト:

- tracked source、untracked temp、symlink、mode を変更する check は正規 root を変更しない。
- timeout / crash 後も正規 root は変わらない。
- isolated workspace の ignored cache 生成は policy に従い分類される。
- check 中の正規 root concurrent edit は completion を拒否する。

### P0-2: Result and stability contract

対象: `FB`, `FD`

check result を次へ分離する。

- `runner_result`: spawn、timeout、signal、exit、artifact collection
- `assertion_result`: passed / failed / not_evaluated / unknown
- `failure_phase`: prepare / spawn / execute / assert / collect / commit
- `failure_kind`: configuration / dependency / timeout / crash / assertion / mutation / race / infrastructure / unknown

attempt identity は input manifest、argv / scope、tool versions、OS / arch、environment digest、worker / shard / seed、timeout、cache mode / manifest、lock digest、finish policy digest を含む。

`reproducible: true` は単発 exit 0 から設定しない。cold / warm strata、最小連続 pass 数、最大 attempt 数、混在結果を `stability-evaluation/v1` に保持し、未達は `INCOMPLETE_FLAKY` または `STABILITY_REQUIRED` とする。

### P0-3: Shared terminal readiness

対象: `F1`, `F2`, `F5`

`src/pcl/terminal_readiness.py` に side-effect-free evaluator を追加し、`action_routing`、`finish_execution`、`lifecycle` から共有する。

入力:

- target と子 entity の current state
- required Story approval / Test result / Evidence validity
- strict finding severity
- open Decision / Escalation / budget
- latest valid completion attempt

出力:

- `ready`
- `ready_with_risk`
- `blocked`
- `incomplete`
- ordered reasons と exact next commands

Feature / Story / Test の完了から Task の `ready_to_close` を派生表示する。low strict warning は risk として残し terminal success を許可するが、error / unknown / invalid Evidence は許可しない。

### P0-4: Start and router targeting

対象: `F3`, `F4`, `F6`

- `pcl start --goal G-XXXX` / `--task T-XXXX` を追加する。
- attach は既存 target を再利用し、重複 Goal / Task を作らない。
- work_started event と Task の visible active state を同一 transaction で整合させる。
- target 未指定で複数の active Goal がある場合は、無関係な global blocker を選ばず `select_target` を返す。
- target-bound `next` はその target を block する Decision / Defect だけを優先する。

### P0-5: Check reuse and scoped audit

対象: `F7`, `F8`

- `pcl audit check --target <ref> --since <time|event> --summary --json`
- check attempt identity が同一なら、role ごとに再実行せず immutable result を参照する。
- reuse 時も provenance と policy compatibility を検証する。
- summary は active / historical、severity、failure kind、target を分離する。

### P0-6: Cross-system progress and execution binding

対象: `F10`, `FA`

- `execution-binding/v1`: canonical root、worktree root、Git common dir、branch / detached state、Cockpit task ID、CI run identity を typed optional fieldsで記録する。
- `progress-receipt/v1`: milestone、started / completed / blocked、target refs、latest valid Evidence、residual blockers を記録する。
- `resume` と context pack は progress receipt を優先し、古い `updated_at` や空の `verified` 配列だけに依存しない。

### P0-7: Operator contract

対象: `F9`

guide を次の権限面に分離する。

1. read-only inspection
2. PCL local-state mutation
3. repository / file write
4. external / production write
5. terminal transition

各 terminal command に prerequisites、必要 Evidence、human semantic decision、失敗時の exact recovery を記載する。

## 5. P1

P0 の Evidence-first 実装を壊さず、次を別判断で行う。

- OS sandbox / filesystem overlay / network policy backend
- `completion-packet/v2` と incomplete attempt の正規 contract
- runner ごとの structured reporter
- Cockpit の progress / attempt 自動 ingest
- historical Evidence の superseded / contradicted projection
- flake quarantine と再実行 budget
- normalized attempt / manifest table（DB migration の人間承認後）

## 6. 変更予定領域

| Slice | 主な実装候補 | 主なテスト |
| --- | --- | --- |
| C0 | `src/pcl/verification_manifest.py` | `tests/test_verification_manifest.py` |
| C1 | `src/pcl/finish_execution.py`, `src/pcl/workflow_sandbox.py` | `tests/test_finish.py`, `tests/test_guarded_process.py` |
| Result / stability | `src/pcl/finish_execution.py`, contracts | finish contract / timeout / mixed outcome tests |
| Readiness | `src/pcl/terminal_readiness.py`, `action_routing.py`, `lifecycle.py` | routing / finish / lifecycle parity tests |
| Start / router | start command service、routing | attach / multi-goal / visible state tests |
| Audit / reuse | audit command service、Evidence lookup | scoped read / no duplicate execution tests |
| Progress / binding | Evidence contracts、resume / context | worktree / Cockpit / CI fixture tests |
| Guide | command guide、skill | permission / prerequisite snapshot tests |

実際のファイル境界は既存責務を読んでから最小化し、CLI handler へ domain logic を戻さない。

## 7. リリース・検証ゲート

各 slice で:

1. Story draft と Test plan を PCL に記録する。
2. failing test で問題を再現する。
3. targeted test と `ruff check` を通す。
4. `PYTHONPATH=src pytest` を通す。
5. `PYTHONPATH=src python -m pcl --root . --json validate` を通す。
6. meaningful PCL state mutation 後に render する。
7. Evidence は write-once path から `pcl evidence add --copy` で登録する。
8. commit と PCL Evidence / Test / Task を対応づける。

P0 全体の release gate:

- existing `pcl finish` plan-only contract と completion-packet/v1 fixture が後方互換。
- canonical root contamination test が全対象ケースで green。
- target-bound `next` / `finish` / lifecycle readiness parity が green。
- live scratch project で init、doctor、validate、render、start attach、scoped audit、finish incomplete / terminal の双方を確認。
- 監視中 adopter task で得た空 `verified`、stale `updated_at`、`last_run_id: null`、unscoped finding flood、成功 Evidence のみ残る問題を regression fixture 化。

## 8. 停止・判断ゲート

次では実装を止め、人間判断を要求する。

- DB migration または新規 runtime dependency が必要になった。
- packet v1 の破壊的変更なしに安全性を表現できない。
- ignored dependency を隔離 workspace に materialize する policy が project 間で両立しない。
- PCL が外部サービスや Cockpit state を自動変更する必要が生じた。
- 過去の成功 packet / passing Test を自動で invalid / reopen する必要が生じた。

## 9. 最初の実装マイルストーン

最初の commit は Slice C0 とする。

完了条件:

- `verification-input-manifest/v1` の deterministic collector と comparator が追加されている。
- tracked / untracked / ignored output / symlink / mode / unknown の targeted tests が通る。
- finish 本体への接続前であることを明記し、collector 単体を完成させる。
- DB migration、依存追加、外部変更がない。

続く Slice C1 で finish execution に接続するまでは、現行 `pcl finish --emit-packet` が canonical root で check を実行する既知リスクは残る。C0 完了だけを finish safety 完了とは扱わない。
