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

### 実装進捗

| Slice | 状態 | 実装 / Evidence |
| --- | --- | --- |
| P0-1 C0 verification input manifest | implemented | `ceb9748`, `docs/evidence/0213-finish-input-manifest-validation.md` |
| P0-1 C1 isolated finish workspace | implemented | `19b7c0b`, `docs/evidence/0214-finish-isolated-workspace-validation.md` |
| P0-2 result and stability contract | implemented | `92346bb`, `E-0599`〜`E-0601`, `docs/evidence/0215-finish-result-stability-validation.md` |
| P0-3 shared terminal readiness | implemented | `f946277`, `63457ec`, `E-0602`, `docs/evidence/0216-shared-terminal-readiness-validation.md` |
| P0-4 start and router targeting | implemented | `3c6c019`, `E-0604`, `docs/evidence/0217-target-attach-routing-validation.md` |
| P0-5a scoped audit | implemented | `6794ce9`, `E-0606`, `docs/evidence/0218-scoped-audit-validation.md` |
| P0-5b check reuse 以降 | planned | P0-5a の scoped output contract 後に継続 |

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

- `finish-check-result/v2`: completion-check Evidence の加算的 contract。completion-packet/v1 の check shape は変更しない
- `runner-result/v1`: spawn、timeout、signal、exit、artifact collection
- `assertion-result/v1`: passed / failed / not_evaluated / unknown
- `failure_phase`: prepare / spawn / execute / assert / collect / commit
- `failure_kind`: configuration / dependency / timeout / crash / assertion / mutation / race / infrastructure / unknown

`verification-attempt-identity/v1` は input manifest、実行 argv / scope、PCL・Python・Python module version、実行ファイル identity、OS / arch、environment digest、worker / shard / seed digest、timeout、cache mode / manifest、lock digest、finish policy digest を含む。全 CLI に共通する安全な version probe はこの slice で追加せず、version を解決できない外部 tool は executable path / stat と `null` version で過大主張を避ける。

`reproducible: true` は単発 exit 0 から設定しない。cold / warm strata、最小連続 pass 数、最大 attempt 数、混在結果を `stability-evaluation/v1` に保持し、評価状態を `stable` / `stability_required` / `incomplete_flaky` / `incompatible_attempts` とする。

P0-2 の後方互換境界:

- isolated finish の現在の1回実行は `cold` 1 attempt として記録し、必ず `reproducible: false` とする。
- `resume` は PCL が生成した非 reproducible check を「権威ある再現済み結果」には昇格させず、次回 stability Evidence を得る replay command として保持する。
- completion-packet/v1 に未定義の outcome は追加しない。`STABILITY_REQUIRED` / `INCOMPLETE_FLAKY` に相当する terminal enforcement は、P0-3 の shared readiness evaluator へ接続する。
- compatible attempt の履歴参照・重複実行回避は P0-5 で実装する。P0-2 は deterministic identity と純粋 evaluation contract を先に固定する。

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

実装境界（2026-07-28）:

- `terminal-readiness/v1` は副作用なし・決定論的な加算contractとして実装済み。
- `next`、`finish`、Feature / Goal lifecycle guardが共有判定を使用する。
- linked Taskは`task read`で完全な判定、`task list`でcompactな`derived_status`を返す。
- P0-2の単発stabilityはP0-5のcompatible history/reuse実装まではrecord-only advisoryを維持する。

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

実装は次の依存順で分割する。

1. **P0-5a scoped audit**: bare Task / Goal target を既存
   `routing-target/v1` で fail-closed に解決し、event ID または ISO-8601
   time の provenance anchor 境界、compact summary、flag 未指定時の
   `audit-check/v1` 後方互換を固定する。audit は常に read-only とする。
2. **P0-5b immutable check reuse**: P0-2 の
   `verification-attempt-identity/v1` と P0-5a の scope を用いて compatible
   result を参照し、provenance / policy 不一致時は再利用しない。真の
   before / after finding-set delta はこの immutable result 間で計算する。
3. **P0-5c output / retry friction**: finish dry-run の summary / pagination /
   machine-state exclusion と、active Task への start attach retry
   idempotency を個別の後方互換 contract として扱う。

P0-5a は DB migration、依存追加、audit mutation を行わない。Story
`US-0072` の意味承認は実装許可から推測せず、Tests `TC-0155`〜`TC-0158`
とともに非 terminal のまま保持する。

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
| Result / stability | `src/pcl/verification_results.py`, `finish_execution.py`, `guarded_process.py`, `resume.py` | finish contract / timeout / signal / mixed outcome / replay tests |
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

## 10. 継続監視ログ

### 2026-07-27: P0-1 実装 dogfood

| 観測 | 対応先 | 状態 |
| --- | --- | --- |
| `pcl start --new` で `G-0067 / T-0141` を作成した直後も、`next_actions` が対象を block していない `DEC-0014` の resolve command を返した | `F4`, P0-4 | 再現済み |
| `work_started` と start receipt が記録されても `T-0141.status` は `todo` のままだった | `F6`, P0-4 | 再現済み。明示 `pcl task status ... in_progress` で補正 |
| target-bound dry-run は正しい `T-0141` を選べたが、既存 agent state を含む 1,749 input と大量の `changes` を無制限 JSON で返した | `F7`, P0-5 | audit だけでなく finish dry-run にも `--summary` / pagination / machine-state exclusion policy が必要 |
| C1 の package-manager compatibility では root `node_modules` の独立 copy までは決定的に扱えるが、workspace ごとの dependency tree は typed config がない | `F10`, P0-6 / P1 backend | residual risk として Evidence に記録 |
| Story は user の意味承認を代行せず `US-0068` を draft に保持したため、実装 Evidence が green でも Test terminal transition は行っていない | `F9`, P0-7 | 権限境界どおり。implementation authorization と Story semantic approval の表示分離が必要 |

### 2026-07-28: P0-2 実装 dogfood

| 観測 | 対応先 | 状態 |
| --- | --- | --- |
| `next --target T-0141` が今回の target を block しない外部キャンペーン Decision `DEC-0014` を再び返した | `F4`, P0-4 | 再現継続。Decision は変更せず、明示されたローカル実装だけを継続 |
| Story draft を保存した直後の `feature status ... specified` が reviewer-checkable Evidence 必須で拒否された | `F5`, `F9`, P0-3 / P0-7 | state は誤って進めず discovered のまま保持。Story specification と implementation Evidence の必要条件を command guidance で分離する余地 |
| 単発成功を `reproducible: false` に直すと、`resume` が安全な再実行 command まで削除した | `FD`, P0-2 | 回帰テストで検出。PCL 生成 check に限り stability Evidence 用 replay command を保持するよう修正 |
| P0-2 の record-only stability と現行 terminal transition の間に一時的な不一致が残る | `F2`, `F5`, P0-3 | completion-packet/v1 を壊さず、shared readiness 接続まで明示的 residual gap とする |
| 同じ検証文書の Evidence `E-0599` を3つの Testへ共有しようとすると `conflicting acceptance target` で拒否され、Testごとに `E-0600` / `E-0601` の重複登録が必要だった | `F8`, P0-5 | Evidence bytesと検証実行は同じ。immutable resultの複数acceptance target linkまたはbundle参照を検討する |

### 2026-07-28: adopter task `81812d6f` 継続監視

| 観測 | 対応先 | 状態 |
| --- | --- | --- |
| 同一Node laneがGitHub runnerの実空き容量12GBと既定timeoutの影響で失敗し、機能不一致・fixture不備・resource不足の切り分けに長時間を要した | `FB`, `FD`, `F10`, P0-2 / P0-6 | attempt identityとは別に、disk / memory / CPU / runner limitのresource envelopeを観測provenanceへ追加し、正規化したcapacity classだけをcompatibility判断へ使う |
| PCL Evidenceのproducer commandに省略表記が保存でき、後からexact path入りEvidenceへ差し替える必要があった | `F9`, P0-7 | claimed commandにplaceholder / ellipsis警告を追加し、可能ならguarded executor receiptのexact argvを参照する |
| 正常な耐久コピーEvidence追加後にaudit異常数が220→223へ増えたが、target / since / delta scopeがなく原因切り分けが難しかった | `F7`, P0-5 | `audit check --target --since --summary`と「今回mutationが増やしたfinding」の差分表示を受け入れ条件へ追加する |
| integration worktreeのPCL照会は`not_initialized`で停止し、canonical checkoutへ手動で戻って状態確認した | `F10`, P0-6 | canonical DBを増殖させず、worktree実行からcanonical state rootとexecution rootをtyped bindingする |
| 最新reportは旧SHA `c5ef0ba9` のaccepted結果を補強証拠として分離し、最終SHA `d9eab21f` のreview task `7242f774` と全緑CI `30291783362` を正式根拠として明記した | `F10`, P0-6 | exact SHA / review task / CI runをtyped execution bindingへ保持する必要性を再確認。監視側からadopter stateは変更していない |
| `81812d6f` は `completed / latestSeq 13` 確認後、同じIDの incremental wait が「タスクが見つかりません」へ変わった | `F10`, P0-6 / Cockpit retention | 完了タスクがcontrol planeから消えても、PCL側progress receiptにtask ID、last sequence、terminal report ref、確認時刻を保持し、監視再開時に「新規reportなし」と「履歴消失」を区別する |

### 2026-07-28: P0-3 実装 dogfood

| 観測 | 対応先 | 状態 |
| --- | --- | --- |
| `next --target T-0142` が今回のtargetをblockしない `DEC-0014` を返した | `F4`, P0-4 | 3 slice連続で再現。shared readinessではなくrouting scopeの問題として分離 |
| 既存`completion_blockers`へStory/Test/Defect理由を混ぜるとDefect lifecycleの公開shapeを壊した | `F2`, P0-3 | 従来fieldはcompletion-policy専用に維持し、全理由を加算`terminal_readiness`へ分離 |
| linked Taskへ完全readinessを一覧表示すると大量Task projectでJSONを増幅する | `F7`, P0-5 | `task list`はcompactな`derived_status`のみ、`task read` / `next` / `finish`は完全contractへ分離 |
| baseline snapshotが加算`terminal_readiness`を意図変更として記録しておらず全体回帰で検出された | `F2`, P0-3 | snapshotとfixture READMEを同時更新し、既存action command/fieldは維持 |

### 2026-07-28: P0-4 実装 dogfood

| 観測 | 対応先 | 状態 |
| --- | --- | --- |
| `next --target T-0144` は対象外 `DEC-0014` を除外し、`pcl context pack --task T-0144 --json` を返した | `F4`, P0-4 | 修正確認。`routing_scope=target` と明示 `target_binding` を保持 |
| `start --task T-0144` は既存 `G-0067 / T-0144` を再利用し、`created_ids` は `E-0603` と `EV-1B43DE29826E` のみだった | `F3`, `F6`, P0-4 | 修正確認。Taskは `in_progress`、Goal / Task重複なし |
| `finish --emit-packet --dry-run --task T-0144` は同じTask/Goal bindingと既存`terminal-readiness/v1`を返した | `F2`, `F4`, P0-4 | 修正確認。finish独自のterminal判定は追加していない |
| 同finish dry-runは無関係なlocal agent stateを含む261件の`changes`を返した | `F7`, P0-5 | 再現継続。summary / pagination / machine-state exclusionをP0-5で扱う |
| 既に`in_progress`の同じTaskへ`start --task`を再実行すると、新しいstart receipt / eventを追加できる | `F8`, P0-5 | attach retry用idempotency keyまたは既存receipt再利用契約を検討 |

### 2026-07-28: P0-5a 実装 dogfood

| 観測 | 対応先 | 状態 |
| --- | --- | --- |
| `audit check --target T-0145 --since EV-F70052078EA9 --summary` は全体77件をscanし、対象0件 / excluded 77件をcompactに返した | `F7`, P0-5a | 修正確認。明示targetとprovenance anchorを保持 |
| flag未指定のauditは従来6-key `audit-check/v1` shapeとexit 6を維持した | `F7`, P0-5a | 後方互換確認 |
| `--target T-9999` は `audit_target_not_found` / exit 2で停止した | `F7`, P0-5a | fail-closed確認。別target/rootを推測しない |
| scoped auditは全scan後にfilterするため、出力量は減るがscan costは減らない | `F7`, P0-5b / scale | compatible immutable result reuseまで残存 |
| `--since` はEvidence / event作成anchorであり、mutable source driftの発生時刻は推測しない | `F7`, P0-5b | true before/after deltaは保存済みresult比較で実装する |
