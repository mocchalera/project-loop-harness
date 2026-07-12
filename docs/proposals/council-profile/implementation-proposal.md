# PLH Council Profile 実装提案・引継ぎ仕様

- **Status:** Proposed for implementation planning
- **作成日:** 2026-07-11
- **基準リポジトリ:** `mocchalera/project-loop-harness` の 2026-07-11 時点 `main`
- **確認済み到達点:** v0.4.3、タスク台帳 0153b まで完了
- **対象読者:** PLH maintainer、実装担当agent、外部Council runner担当
- **提案上の仮称:** `PLH Council Profile` / 外部runner `plh-council`

> この資料の結論は、**PLH CoreをSystem of Record兼Control Planeとして維持し、複数モデルの選択・協調・反証・統合は外部Profile runnerへ分離する**ことである。モデル名・モデル数は固定しない。PLHが受け取るのは会話ログではなく、versioned contractに適合したEvidence bundleである。

---

## 1. 実装判断の要約

### 採用する

1. `direct / discover / assure` のうち、主に `discover` と必要な `assure` を外部Councilへ渡す。
2. Councilはタスクごとに **1〜4モデル**を選び、役割と協調トポロジーを動的に決める。
3. モデルのプロバイダーSDK、認証情報、価格表、ランキング、プロンプト実装はPLH Coreへ入れない。
4. PLHはProfile manifest、read-only request生成、bundle検証・Evidence化、人間Decision、監査イベントを担当する。
5. Council出力は、少なくとも次の構造化Artifactを持つ。
   - `council-run/v0`
   - `claim-set/v0`
   - `verification-plan/v0`
   - 必要時のみ `decision-proposal/v0`（最大3件）
   - 必要時のみ改訂候補 `work-brief/v1`
6. 実装開始条件はCouncilの「合意」ではない。重大な未確認事項がEvidence、検証計画、人間Decisionのいずれかへ明示的に着地していることを条件にする。
7. MVPでは新規DBテーブルを作らない。**Artifact → Event → Table**の順を守り、運用上の検索需要が確認されるまでEvidence bundleとして保持する。

### 採用しない

- Sol、Fableなど特定モデルへの固定。
- 常に2モデル、常に4モデルという固定編成。
- PLH CLIから暗黙に外部モデルを起動すること。
- モデル出力をfactとして扱うこと。
- 全思考過程やhidden chain-of-thoughtの収集・保存。
- Councilの提案コマンドを自動実行すること。
- 外部runnerからSQLiteを直接変更すること。
- Council専用の独立した状態DB、Decision UI、Evidence管理を重複実装すること。

---

## 2. 現行PLHとの適合性

現行PLHには、この提案を受けるための基盤がすでにある。

| 必要能力 | 現行PLHで再利用するもの | 本提案で追加するもの |
|---|---|---|
| 目的・制約・非目標 | immutable `work-brief/v1` Evidence | Profile requestへのhash-bound同梱 |
| ルート選択 | route recommendation / adaptive policy / audited override | Profileのsupported route検査 |
| コンテキスト引継ぎ | `context-pack/v1`、code-context receipt | Profile用request envelope |
| 外部agent境界 | Agent Adapter、`generic_shell`、Evidence ingest | Profile-specific prepare/ingest契約 |
| 主張と事実の分離 | Evidence / Verification | `claim-set/v0` |
| 実証計画 | deterministic checks / completion policy | `verification-plan/v0`（提案のみ） |
| 人間判断 | Decision / Escalation / approval provenance | `decision-proposal/v0`とのhash binding |
| 監査 | transactional outbox / JSONL projector | Profile ingest/selection event |
| 実装後の証明 | completion-packet / handoff-packet | Council refsのadditive packet参照（後続） |

### 重要な再利用方針

- Work Briefの承認状態・actor-kind・source-refは既存のapproval provenanceを使う。
- Evidenceのcopy、hash、path guard、target linkは既存Evidence serviceを使う。
- `pcl next`のopen Decision優先順位を使い、別のhuman queueを作らない。
- route mismatchをProfile commandの`--force`で逃がさない。必要なら既存`pcl route override`を先に記録する。
- Councilの改訂Work Briefは自動でcurrent contractにしない。既存の`brief add → review → human approve`を通す。

---

## 3. 解く問題

高性能モデルは、実装前に設計上の失敗条件や手戻り要因を広く潰せる。一方、人間が複数モデルの長大な議論を逐語的に追うと、認知負荷がボトルネックになる。また、複数モデルが整合的な誤りへ収束する危険もある。

したがって必要なのは「AI会議画面」ではなく、以下を行う制御面である。

1. タスクのrisk、曖昧さ、予算に応じて適切なモデルチームを編成する。
2. 独立提案と反証を行い、同調バイアスを減らす。
3. 出力を事実、仮定、推論、選好、riskへ構造化する。
4. 現実検証が必要な論点を最小プローブへ変換する。
5. 人間にしか決められない選択だけを最大3件へ圧縮する。
6. 結論と少数意見、Evidence、停止理由、コストを監査可能にする。
7. 承認済みWork Briefへ戻し、通常のPLH実装・検証ループへ接続する。

---

## 4. 目的と非目的

### 4.1 目的

- PLHをモデル非依存のまま、外部の単体モデル・複数モデル・Fusion型・Fugu型runnerと接続可能にする。
- clear/low-riskタスクでは従来のDirect pathを壊さず、Councilを見えなくする。
- ambiguous/high-riskタスクで、人間の読む量を「判断パケット」へ圧縮する。
- モデル選択、役割、バージョン、予算、停止理由を再現可能なrun manifestへ残す。
- invalid/partial/budget-exhaustedな出力を、成功として扱わず安全にEvidence化する。
- 外部runnerを実モデルなしのfixtureでPLH CIから検証可能にする。

### 4.2 非目的

- PLH内でOpenAI、Anthropic、OpenRouter、Sakana等のSDKを管理する。
- PLHが外部モデルの品質ランキングを提供する。
- hosted orchestration SaaSを作る。
- 自由形式の任意agent graphをMVPで扱う。
- repository変更、依存追加、migration、外部通信をCouncil提案から自動実行する。
- Councilを通さないとPLHを使えない設計にする。
- モデル同士の全文会話をPLHのcanonical stateにする。

---

## 5. アーキテクチャ決定

```text
┌──────────────────────────────────────────────────────────────┐
│ External models / services                                   │
│ single frontier model / heterogeneous panel / Fusion / Fugu │
└───────────────────────────┬──────────────────────────────────┘
                            │ provider-specific APIs
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ plh-council (separate package / process)                      │
│ - capability registry                                         │
│ - 1..4 participant selection                                  │
│ - topology selection                                          │
│ - prompts / tools / budget / credentials                      │
│ - independent proposals / critique / synthesis                │
│ - typed output bundle                                         │
└───────────────────────────┬──────────────────────────────────┘
                            │ profile-run-request/v1
                            │ profile-output-bundle/v1
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ Project Loop Harness Core                                     │
│ - profile manifest validation                                 │
│ - deterministic request preparation                           │
│ - bundle/schema/hash/path validation                          │
│ - immutable Evidence + target link                            │
│ - Decision / provenance / next action                         │
│ - audit / completion / handoff                                │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
                Repository / checks / human owner
```

### 5.1 リポジトリ境界

推奨構成は次である。

```text
mocchalera/project-loop-harness    # Core / contracts / Evidence / Decisions
mocchalera/project-loop-council    # optional external runner
```

同一monorepoへ入れるより、別package/repositoryがよい。理由は以下。

- PLHのzero-runtime-dependency方針を守れる。
- provider SDK更新とCore release cadenceを切り離せる。
- 認証情報とnetwork権限をCoreから隔離できる。
- runnerを他実装へ差し替えられる。
- PLH test suiteが外部APIなしで完結する。

ただし利用者体験とcontractは一つのエコシステムとして設計する。完全に別製品としてEvidence、Decision、監査を再実装しない。

### 5.2 先行bootstrap

正式なProfile API実装前でも、既存`generic_shell` Agent Adapterと`pcl ingest-agent-run`で最小dogfoodは可能。ただし、それだけではCouncil内部のparticipant、budget、claims、decision proposalをPLHが型付きで理解できない。よってこれは**Stage 0の検証経路**であり、最終境界ではない。

---

## 6. 責務分離

### 6.1 PLH Coreが担う

- manifest discovery、trust区分、schema validation。
- target、Work Brief、route、policy、Evidence、contextの決定論的解決。
- read-only `profile-run-request/v1`生成。
- bundleとlisted artifactsのpath、symlink、size、hash、schema、cross-reference検査。
- immutable Evidence copyとtarget link。
- open Decisionの作成、human selection、provenance、audit event。
- `pcl next`でのhuman gate、Work Brief改訂、verificationへの誘導。
- rejected inputでゼロmutationを保証。

### 6.2 外部Council runnerが担う

- API key、provider SDK、endpoint、retry、rate limit。
- モデル能力レジストリ、価格、latency、実績。
- タスクごとのparticipant数、役割、モデル、topology選択。
- repositoryの追加読取とproviderへ送るcontextの最小化。
- secret scanning、data policy enforcement。
- 独立提案、反証、統合、停止判定。
- token/cost/latency計測。
- typed artifact生成。

### 6.3 人間が担う

- 有料サービス・network・data policyの許可。
- 製品意味論、不可逆な選択、risk acceptance。
- 非推奨候補を選ぶ場合のoverride理由。
- 改訂Work Briefの最終承認。
- migration、dependency、production data等、既存AGENTS.md上のhuman gate。

---

## 7. End-to-endフロー

### 7.1 Routeと事前条件

```text
pcl start / brief add
  → route recommend
  → policy resolve
  → effective route = discover または assure
  → profile prepare
```

`council.discovery`の事前条件:

- targetが存在する。
- targetへWork Brief Evidenceが一意に解決できる。
- Work Briefはunapprovedでもよい。Discoveryは承認前に内容を精緻化するためである。
- Work Briefのreview/approval stateをrequestへ明示する。
- effective routeがmanifestの`supported_routes`に含まれる。
- route mismatch時はread-only commandを失敗させ、既存`pcl route override`を案内する。
- networkやpaid serviceを許可するrequestでは、設定または明示provenanceにより人間承認済みであることを要求する。

### 7.2 Request生成

```bash
pcl profile prepare council.discovery \
  --target task:T-0001 \
  --brief E-0007 \
  --output /tmp/council-request.json \
  --json
```

性質:

- inspection/read-only。SQLite、events.jsonl、Evidenceを変更しない。
- `--output`を省略した場合はstdoutへcontract本体を出す。
- `--json`のstdoutは機械可読JSONのみ。説明はstderr。
- requestはWork Brief hash、route recommendation hash、override hash、resolved policy、context pack、linked Evidence hashesを含む。
- request digestは`request_digest`フィールドを除くcanonical JSONへSHA-256を適用する。
- rootの絶対pathは外部へ出さず、basenameとfingerprintを使う。

### 7.3 外部runner実行

PLHはこのコマンドを自動実行しない。

```bash
plh-council run \
  --request /tmp/council-request.json \
  --output-dir /tmp/council-output
```

外部runnerは`/tmp/council-output/profile-output-bundle.json`とlisted artifactsを生成する。実モデルを使わないfixture runnerも同じcontractを出す。

### 7.4 Bundle planとingest

```bash
pcl profile ingest \
  --request /tmp/council-request.json \
  --bundle /tmp/council-output/profile-output-bundle.json \
  --dry-run --json

pcl profile ingest \
  --request /tmp/council-request.json \
  --bundle /tmp/council-output/profile-output-bundle.json \
  --summary "Council discovery result" \
  --json
```

検証順:

1. request schemaとdigest。
2. manifest ID/version/hash。
3. targetと現行project fingerprint。
4. output bundle schema、request binding、status整合性。
5. listed artifact pathがbundle directory配下であること。
6. symlink、path traversal、duplicate path/ID、case-fold collision。
7. file size、aggregate size、SHA-256。
8. artifact contract schema。
9. cross-reference（participant、claim、verification、proposal、recommended candidate）。
10. decision proposal数がrequest limit以下。
11. status/next_action/decision proposalの整合性。

成功時:

- bundle全体を既存Evidence durability/copy serviceでimmutable保存。
- Evidence kindは`profile_output_bundle`。
- targetへgeneric evidence link。
- metadataにprofile ID/version、request digest、bundle ID/digest、statusを保存。
- `profile_output_ingested` eventを同一mutation boundaryで追加。
- proposalごとに既存Decisionを`open`で作成し、bundle Evidence + artifact hashへbinding。
- next actionを返す。

失敗時:

- Evidence、link、Decision、eventを一切残さない。
- staging fileはcleanupする。
- machine-readable error codeとrepair commandを返す。

### 7.5 Human Decision

`needs_human` bundleは1〜3件のDecisionをopenにする。`pcl next`は既存優先順位によりopen Decisionを返す。

```bash
pcl decision proposal show DEC-0004 --json

pcl decision proposal select DEC-0004 \
  --candidate OPT-A \
  --actor "human:owner" --actor-kind human \
  --recorded-by "agent:codex" --recorder-kind agent \
  --source-kind conversation \
  --source-ref "conversation:<approval-reference>" \
  --reason "認証境界ではデータ分離を優先する" \
  --json
```

規則:

- `actor-kind=human`以外は選択を確定できない。
- recorded-byがagentでも、human actor/source provenanceが必要。
- 非推奨候補を選ぶ場合は`--override-reason`必須。
- proposalのEvidence ID、relative path、artifact hash、selected/rejected IDsをeventへ固定する。
- 選択後も元Artifactを書き換えない。
- 全Decision解決後、revised Work Briefがあれば`brief add/review/approve`へ誘導する。

### 7.6 通常実装へ戻る

```text
all proposals resolved
  → revised work-brief/v1 add
  → human approve
  → direct/assure implementation workflow
  → deterministic verification
  → pcl finish / completion-packet
```

Councilの合意だけでexecution-readyにしない。承認済みWork Brief、必要なVerification、通常のterminal guardが引き続きauthoritativeである。

---

## 8. CLI仕様

### 8.1 `pcl profile list`

目的: built-inおよび許可済みexternal manifestを列挙する。

JSON出力の最低項目:

```json
{
  "ok": true,
  "profiles": [
    {
      "profile_id": "council.discovery",
      "profile_version": "0.1.0",
      "profile_kind": "discovery",
      "trust": "built_in",
      "valid": true,
      "supported_routes": ["discover", "assure"]
    }
  ]
}
```

### 8.2 `pcl profile show <profile-id>`

- manifest内容、source path、trust、manifest hash、capabilities、human approvals requiredを表示。
- external commandを実行しない。

### 8.3 `pcl profile validate <id-or-path>`

- schema、unknown keys、contract support、duplicate ID、package dataを検査。
- external pathはproject rootまたは明示allowlist配下だけ。
- symlink escapeはfail closed。

### 8.4 `pcl profile prepare`

主なerror code:

| Code | 意味 | 次の一手 |
|---|---|---|
| `profile_not_found` | manifest未発見 | `pcl profile list` |
| `profile_manifest_invalid` | manifest不正 | `pcl profile validate` |
| `profile_target_not_found` | target不在 | target ID確認 |
| `profile_work_brief_required` | Briefなし | `pcl brief add` |
| `profile_work_brief_ambiguous` | current Briefが一意でない | `--brief E-...` |
| `profile_route_mismatch` | effective route非対応 | `pcl route current` / override |
| `profile_paid_service_approval_required` | paid利用未承認 | human approval記録 |
| `profile_network_forbidden` | data policy不一致 | offline fixtureまたはpolicy変更 |
| `profile_context_budget_too_small` | 必須sectionが入らない | policyを明示変更 |

### 8.5 `pcl profile ingest`

主なerror code:

| Code | 意味 |
|---|---|
| `profile_request_digest_mismatch` | requestが改変された |
| `profile_bundle_request_mismatch` | 別requestの出力 |
| `profile_bundle_id_conflict` | 同じbundle IDで異なるdigest |
| `profile_bundle_path_escape` | `..`/absolute/symlink escape |
| `profile_bundle_hash_mismatch` | artifact改変 |
| `profile_bundle_size_exceeded` | request limit超過 |
| `profile_artifact_contract_unsupported` | 未知contract |
| `profile_artifact_schema_invalid` | schema不適合 |
| `profile_artifact_cross_reference_invalid` | 参照切れ |
| `profile_decision_limit_exceeded` | proposalが3件等のlimit超過 |
| `profile_status_inconsistent` | statusとnext actionが矛盾 |

Idempotency:

- 同一`bundle_id + bundle_digest`の再ingestは既存Evidenceを返し、`idempotent_replay: true`、ゼロmutation。
- 同一`bundle_id`でdigestが異なる場合はconflict。
- 検索はEvidence metadata/eventを利用し、MVPでは専用tableを作らない。

### 8.6 `pcl decision proposal show/select`

新しいコマンドは、既存Decisionのauthoritative状態を置き換えず、proposal Evidenceを読みやすく投影する薄いuse caseにする。

`show`は以下を返す。

- question、why human、impact。
- candidatesとtrade-off。
- recommendation。
- uncertaintyとreversibility。
- minority opinion。
- unresolved assumptions。
- bound Evidence/hash。
- factual provenance。

`select`は既存Decision resolve serviceを使い、proposal-specific validationとevent payloadを加える。

---

## 9. Contract設計

同梱`schemas/`をv0提案として使う。実装時は現行PLHのschema registry/package-data patternへ移し、canonical fixturesを凍結する。

### 9.1 `profile-manifest/v1`

目的: Profileの静的能力と入出力contractを宣言する。

重要点:

- data-only。Python import hookやarbitrary command executionを持たない。
- `external_runner.invocation_hint`は説明用で、PLHは実行しない。
- built-in/externalのtrustはmanifest自己申告ではなくloader側で付与する。
- `auto_execute`はMVPで常にfalse。

### 9.2 `profile-run-request/v1`

目的: 現行PLH stateから外部runnerへ渡す、再現可能でhash-boundな入力。

含める:

- target。
- immutable Work Brief本文、Evidence ID/hash、review/approval state。
- route recommendation、override、effective route。
- resolved adaptive policy。
- budget-aware context pack。
- linked EvidenceのID/kind/hash/summary。
- participant/output/cost/data policy limits。
- request digest。

含めない:

- API key。
- provider credential。
- dashboard HTML。
- full transcript。
- project.db。
- root absolute path。

### 9.3 `profile-output-bundle/v1`

目的: 外部runnerの結果を一つのatomic ingest単位へ束ねる。

- listed artifactだけがauthoritative。
- directory proximityで勝手に関連付けない。
- `needs_human`ならproposalが1件以上必要。
- `budget_exhausted/partial/failed`は`safe_to_run=false`。
- bundle digestは`bundle_digest`を除くcanonical bundle JSONを対象にし、listed artifactのhash/sizeを推移的に固定する。

### 9.4 `council-run/v0`

目的: 誰が、どの役割で、どのモデル設定、topology、budget、停止理由で処理したかを記録する。

必須の正直さ:

- requested modelとprovider-reported modelを分ける。
- exact revisionを得られないaliasは`pinning_status=provider_alias`とする。
- costが推定なら明示する。
- repository contentをどの粒度で外部送信したか記録する。
- hidden chain-of-thoughtは保存しない。保存するのは役割別出力のhash、要約、claims、critiqueだけ。

### 9.5 `claim-set/v0`

分類:

- `fact`: repository、公式仕様、deterministic check等で裏付け可能。
- `assumption`: 未確認前提。
- `inference`: Evidenceから導いた推論。
- `preference`: UX、事業、risk tolerance等の価値判断。
- `risk`: 失敗条件と影響。

モデルの発言だけをfactの裏付けにしない。`evidence_class=model_judgment`は存在しても、deterministic/observational/human evidenceの代替ではない。

### 9.6 `verification-plan/v0`

- すべてproposal-only。
- command文字列は自動実行しない。
- safety classとhuman approval requirementを明示する。
- pass conditionを観測可能にする。
- migration、dependency、network、production data、destructive operationは既存human gateを維持する。

### 9.7 `decision-proposal/v0`

- 1 artifact = 1 question。
- 2〜5候補。
- 1〜10点の擬似スコアは禁止。
- benefits、costs、risks、assumptions、Evidence、uncertainty band、reversibilityを記録。
- recommendationはあるが自動選択しない。
- unanswered behaviorは`block`。
- 少数意見を失わない。

---

## 10. Council runnerの編成ロジック

PLH Coreはこのロジックを実装しないが、互換runnerが満たすべきbehaviorとして定義する。

### 10.1 モデル数

| 状況 | 既定編成 |
|---|---|
| 明確・低risk・十分なEvidence | 1モデル |
| 通常の設計で独立checkが有効 | 2モデル |
| 曖昧な設計、複数trade-off | 3モデル |
| auth/migration/security/不可逆変更 | 最大4モデル |

多いほどよいとはしない。追加participantの期待改善がcost/latencyを上回る場合だけ増やす。

### 10.2 選択基準

モデルの総合ランキングではなく能力ベクトルと失敗相関を使う。

```yaml
capability_profile:
  architecture: high
  repository_navigation: high
  tool_reliability: medium
  adversarial_review: high
  structured_output: true
  context_capacity: 200000
  cost_class: high
  latency_class: medium
  provider_family: vendor-a
  observed_schema_failure_rate: 0.02
```

選択に含める:

- role適合度。
- 過去のschema adherence。
- repository/task categoryの実績。
- provider/lineage diversity。
- data policy。
- budget/latency。
- context limit。
- tool access。

同系列モデルを複数置く場合は、独立性が限定的であることをrun manifestへ残す。

### 10.3 MVPで許可するtopology

1. `single`
2. `parallel_synthesize`
3. `propose_critique_revise`
4. `specialist_pipeline`

任意graph、再帰的ensemble、ensembleの入れ子は非対象。

### 10.4 独立性

- 最初のproposal roundでは他participantの回答を見せない。
- critique roundで初めて相互出力を開示する。
- synthesis roleは不一致を消去せず、少数意見と未解決仮定へ保存する。
- makerとcheckerは可能なら別provider/lineage、最低でも別contextにする。

### 10.5 停止条件

以下のいずれかで明示的に停止する。

- 重大claimがEvidence、verification item、人間Decisionのいずれかへ着地し、連続roundで新規high-severity findingがない。
- 人間の価値判断が必要。
- token/cost/wall-time budget exhausted。
- runner error。
- policyによりCouncil不要と判定。

全員一致は停止条件にしない。budget exhaustedはcompletedではない。

---

## 11. 状態とstatus意味論

| Status | 意味 | PLHの扱い |
|---|---|---|
| `completed` | Council段階の目的を満たし、未解決human decisionなし | Evidence化。Work Brief改訂/verificationへ進めるが、自動実装しない |
| `needs_human` | 1〜3件の価値判断が必要 | open Decisionを作り、`pcl next`でhuman gate |
| `partial` | 有用な成果はあるが必要条件未達 | Evidence化するが実装開始をblock |
| `budget_exhausted` | budget内で収束しなかった | 明示的incomplete。残存claimと安全な次手を表示 |
| `failed` | runner/schema/tool error | 観測用Evidence化可。repair/retryへ誘導 |
| `skipped` | policy上Council不要 | 理由を記録。Direct pathへ戻す提案は可能 |

`failed`をEvidence化するかはoperatorの明示ingestによる。PLHが勝手に外部runの存在を推測しない。

---

## 12. 永続化と監査

### 12.1 MVPのDB方針

- DB schemaは現行のまま。
- Claims、ProfileRun、Option専用tableを作らない。
- Bundleは1件のEvidenceとして保存し、generic evidence linkでtargetへ結ぶ。
- Decisionは既存tableを使う。
- 検索や集計の反復需要がdogfoodで確認された場合だけtable昇格を提案する。
- migrationが必要になった時点で作業を止め、human approvalを得る。

### 12.2 推奨Evidence metadata

```json
{
  "contract_version": "profile-output-bundle/v1",
  "profile_id": "council.discovery",
  "profile_version": "0.1.0",
  "request_id": "PRR-...",
  "request_digest": "...",
  "bundle_id": "POB-...",
  "bundle_digest": "...",
  "status": "needs_human",
  "decision_count": 1
}
```

### 12.3 Event

`profile_output_ingested`:

```json
{
  "evidence_id": "E-0012",
  "target": {"type": "task", "id": "T-0001"},
  "profile_id": "council.discovery",
  "profile_version": "0.1.0",
  "manifest_sha256": "...",
  "request_id": "PRR-...",
  "request_digest": "...",
  "bundle_id": "POB-...",
  "bundle_digest": "...",
  "status": "needs_human",
  "artifact_count": 4,
  "decision_ids": ["DEC-0004"]
}
```

`decision_proposal_selected`:

```json
{
  "decision_id": "DEC-0004",
  "bundle_evidence_id": "E-0012",
  "proposal_id": "DP-0001",
  "proposal_artifact_path": "decision-proposal.json",
  "proposal_sha256": "...",
  "selected_candidate_id": "OPT-A",
  "rejected_candidate_ids": ["OPT-B"],
  "recommended_candidate_id": "OPT-A",
  "override_reason": null,
  "provenance": {
    "actor": "human:owner",
    "actor_kind": "human",
    "recorded_by": "agent:codex",
    "recorder_kind": "agent",
    "source_kind": "conversation",
    "source_ref": "conversation:..."
  }
}
```

既存outbox serviceを必ず使い、直接events.jsonlへappendしない。

---

## 13. Filesystemとsecurity

### 13.1 Bundle path guard

- bundle manifestの親directoryをrootとする。
- absolute path、`..` segment、NUL、drive prefix、UNC、case-fold duplicateをreject。
- listed artifactとその親componentがsymlinkならreject。
- manifestに列挙されない近接fileは無視する。
- aggregate bytesとfile countをrequest limitで制限。
- JSONはUTF-8、duplicate keyを拒否できるparser pathを使う。
- schema validation前にsize capを適用する。

### 13.2 外部Profile trust

MVP推奨:

- built-in manifest: package data、`trust=built_in`。
- external manifest: 明示pathまたは`.project-loop/profiles/`、`trust=external`。
- external profileはdefault無効。configまたはCLIで明示enable。
- manifestはdata-only。import path、shell hook、pre/post scriptは禁止。
- `invocation_hint`は表示するだけで実行しない。

### 13.3 Credentialと機密情報

- API keyをrequest、bundle、Evidence、eventsへ入れない。
- root absolute pathをrequestへ入れない。
- runnerは`.env`、secret pattern、sensitive pathを送信しない。
- providerへ送信した内容の粒度を`council-run/v0.privacy`へ記録する。
- prompt injection対策としてrepository内文書はuntrusted dataとして扱い、runnerのsystem policyやdata policyを変更できない。
- full transcriptやhidden reasoningを保存しない。

### 13.4 Human approval

現行AGENTS.mdに従い、以下は別途human approvalが必要。

- paid service dependency。
- 新規runtime dependency。
- hosted backend/cloud sync。
- production DB access。
- destructive operation。
- telemetry。

この提案書は、それらを自動承認しない。

---

## 14. 推奨コード境界

現行構造を全面リライトしない。新しいuse caseから薄いmoduleを追加し、既存serviceを再利用する。

```text
src/pcl/
  profiles.py                 # manifest discovery/list/show/validate
  profile_requests.py         # read-only request builder/digest
  profile_ingest.py           # bundle validation + Evidence ingestion
  decision_proposals.py       # projection/show/select validation
  contracts/                  # existing schema registry patternへ追加
  bundled_profiles/
    council.discovery/
      profile.json

tests/
  test_profile_manifest.py
  test_profile_prepare.py
  test_profile_ingest.py
  test_decision_proposals.py
  fixtures/profiles/
  fixtures/profile_runs/
```

命名は現行package conventionsへ合わせて調整してよい。ただし以下は守る。

- `cli.py`へ全ロジックを書かない。
- provider adapter/moduleを`src/pcl`へ作らない。
- direct SQLiteを行わない。
- canonical JSON/hash helperを重複実装しない。
- Evidence path guard/durabilityを複製しない。
- profile featureのための大規模directory refactorを同時に行わない。

---

## 15. 実装スライス

同梱`agent-tasks/0154`〜`0160`を提案backlogとする。番号は実装開始時にcurrent `main`を再確認し、衝突していたら再採番する。

| Task | 内容 | DB | Priority | 依存 |
|---|---|---:|---:|---|
| 0154 | Profile境界ADRとcontract schemas | 変更なし | P0 | 0153b |
| 0155 | manifest registry + read-only prepare | 変更なし | P0 | 0154 |
| 0156 | output bundle dry-run/ingest + security/idempotency | 変更なし | P0 | 0155 |
| 0157 | decision proposal projection + human selection | 変更なし | P0 | 0156 |
| 0158 | built-in Council Discovery profile + fixture runner | 変更なし | P1 | 0157 |
| 0159 | generic_shell/bootstrap dogfood + docs/parity | 変更なし | P1 | 0158 |
| 0160 | multi-model evaluation gate + adoption decision | 変更なし | P1 | 0159 |

### Dispatch

0154 → 0155 → 0156 → 0157は同じCLI/Evidence/validator surfaceへ触れるため、基本的に直列。0158のfixture runnerと外部`plh-council` repositoryの初期実装は、0156 contract freeze後に並列化できる。0159/0160は統合後。

---

## 16. テスト計画

### 16.1 Contract

- 各schemaのpositive/negative fixture。
- package wheel/sdistへschemaとbuilt-in manifestが含まれる。
- unknown keys、wrong version、duplicate IDs、cross-reference切れをreject。
- canonical exampleをsnapshot固定。

### 16.2 Read-only保証

`pcl profile prepare`前後で以下が不変。

- project.db content/hashまたはrow count。
- committed outbox/event count。
- events.jsonl。
- Evidence count/link count。
- dashboard/reports。

`--output`指定時に書くのは明示されたrequest fileだけ。

### 16.3 Zero-mutation failure

各失敗ケースでEvidence、link、Decision、eventが0件増加。

- malformed JSON。
- request digest mismatch。
- path/symlink escape。
- missing artifact。
- wrong hash/size。
- unsupported contract。
- status inconsistency。
- proposal count over limit。
- recommended candidate不在。
- same bundle ID/different digest。

### 16.4 Determinism

- unordered SQLite selectを逆順にしてもrequest bytes/digestが同じ。
- manifest discovery orderが同じ。
- bundle finding orderが同じ。
- JSON/text outputがsnapshot一致。
- time/IDは既存clock/ID injection patternでfixture化。

### 16.5 Human provenance

- agent actorはselectionを確定できない。
- human actor + agent recorderは可能。
- source-refなしをreject。
- 非推奨候補でoverride reasonなしをreject。
- proposal artifact hash driftをreject。
- selection replayはidempotent、別candidate replayはconflict。

### 16.6 Status safety

- `budget_exhausted`はexecution-readyにならない。
- `partial`はexecution-readyにならない。
- `needs_human`でproposalなしはinvalid。
- `completed`でもWork Brief未承認なら実装契約として扱わない。
- Councilの`model_judgment`だけでdeterministic verificationを満たさない。

### 16.7 Distribution

- Python 3.10〜3.13。
- wheel/sdist smoke。
- runtime dependencyが増えていない。
- PLH CIはnetwork/API keyなしで通る。
- fixture runnerでend-to-end prepare → external fake run → dry-run → ingest → selectを実行。

---

## 17. Dogfoodと評価

### 17.1 比較対象

少なくとも10〜20件の実案件を、以下へ分ける。

- clear/low-risk（Councilを使わない対照）。
- ambiguous設計。
- migration/auth/security。
- repository調査が必要。
- 人間の製品判断が必要。

比較:

1. 単体モデルDirect。
2. Council profile。

### 17.2 計測

- human active review minutes。
- human decisions per task。
- first-pass CI rate。
- rework ratio。
- design drift count。
- escaped defect severity。
- model/token/cost per accepted change。
- Council skip rate。
- invalid schema/output rate。
- budget-exhausted safe-stop rate。
- prediction-to-outcome: 事前riskが実際に起きたか。

### 17.3 採用判断の暫定gate

Councilをdefault推奨へ進める条件は、ambiguous/high-risk cohortで以下のいずれかを満たし、品質を悪化させないこと。

- rework ratioを相対20%以上減らす。
- human active review minutesを相対25%以上減らす。
- first-pass CIまたはacceptance passを有意に改善する。

同時に:

- false completionを悪化させない。
- clear taskへCouncilを不要に挿入しない。
- budget-exhausted/invalid出力のsafe-stopを100%維持する。
- 費用増を定量表示し、改善がない場合は自動縮退する。

数値はdogfood開始時の仮説であり、事前にbaselineを凍結してから変更する。

---

## 18. Rollout

### Phase 0: No-core-change bootstrap

- `generic_shell` + `agent-output/v1`で一度Council相当を回す。
- 実際に必要なArtifactと判断数を確認。
- provider/モデル選択は手動でもよい。

### Phase 1: Contract first

- ADR、schemas、fixturesだけをmerge。
- human reviewで境界を承認。
- DB migrationなし。

### Phase 2: Core profile surface

- list/show/validate/prepare。
- dry-run/ingest。
- Decision binding。
- fake runner E2E。

### Phase 3: External runner

- 別repository/packageで`plh-council`。
- API key/configはPLH外。
- 1〜4モデル、4 topology。
- exact model/cost/privacy manifest。

### Phase 4: Dogfood

- 10〜20件。
- baseline比較。
- invalid/partial/budget casesを意図的に試験。

### Phase 5: Adoption

- 成果が確認できた場合のみREADME/adoption guideへ昇格。
- claims/profile runsの専用tableは検索需要を確認して別ADR。
- UIはDecision projectionがCLIで成立してから検討。

---

## 19. Definition of Done

MVPは以下をすべて満たした時点で完了。

1. PLH runtime dependencyを増やさずにProfile manifestをvalidateできる。
2. `profile prepare`が決定論的かつ完全read-onlyである。
3. 外部APIなしのfixture runnerでvalid bundleを作れる。
4. valid bundleを1件のimmutable Evidenceとしてtargetへingestできる。
5. invalid bundleは全ケースでzero mutation。
6. request/bundle/artifact hash bindingが監査できる。
7. `needs_human`から既存Decisionへopenし、human provenance付きで選択できる。
8. 非推奨選択にはoverride reasonが必要。
9. `partial/budget_exhausted/failed`がexecution-readyにならない。
10. Councilの結果から改訂Work Briefを作っても、自動承認されない。
11. wheel/sdistへschemas/profile fixtureが含まれる。
12. existing `start/finish/resume/next/brief/route/evidence-set/completion` snapshotsを壊さない。
13. docs/Skill/CLI parityが確認される。
14. 1件以上の実repository dogfoodをhuman reviewする。

---

## 20. 実装前に人間が決める項目

以下は実装担当が勝手に確定しない。

1. **Profile APIをv0.4.xへ入れるか、v0.5.0 Adoptionへ入れるか。**
2. **外部profile directoryをMVPで許可するか。** 最小ならbuilt-in manifestだけでもよい。
3. **ingest時にopen Decisionを自動作成するか。** 本提案は作成を推奨する。代替はEvidenceだけをingestし、別commandでopenする方式。
4. **paid/network approvalのauthoritative source。** project configだけか、hash-bound human provenanceを必須にするか。
5. **`failed` bundleをEvidence化するoperator UX。** 明示ingestは許可するが、通常next actionをどう表示するか。
6. **外部runner repositoryのowner/release cadence。**

本資料の推奨は次。

- v0.5.0 Adoptionのupstream-layerとしてcontract first。
- 最初はbuilt-in manifestのみ、external manifestは後続。
- ingest時に最大3件のopen Decisionを作る。
- paid/networkは明示human approvalをhash-boundで要求。
- failed bundleは明示ingest可、executionはblock。
- runnerは別repository。

---

## 21. 最初のPRで行うこと

最初のPRは**実行コードを入れない**。

1. この資料をPLH repositoryの`docs/proposals/`等へ移す。
2. ADRを採否決定する。
3. 0154 task specをcurrent numberingへ追加。
4. schemasとpositive/negative fixturesをpackage外のproposal areaへ置く。
5. 現行contract registry、Evidence service、approval provenance、route/current resolverとのfit gapを記録する。
6. DB schemaを変えないことを確認する。
7. human approval後に0155へ進む。

これにより、モデル統合の魅力に引っ張られてCore境界を崩すリスクを防ぐ。
