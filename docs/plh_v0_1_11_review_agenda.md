# Project Loop Harness v0.1.11 レビューと次期改善論点

作成日: 2026-07-06  
対象: `mocchalera/project-loop-harness` v0.1.11  
レビュー種別: 公開GitHub上の静的レビュー。ローカルインストール、テスト再実行、実プロジェクト適用検証は未実施。

---

## 0. 結論

v0.1.11は、前回までの議論で合意した「検索エンジンではなく、説明可能な文脈の領収書を通常のagent handoffへ接続する」という方向をかなり正しく実装している。Release note上では、Context Pack x Code Context Bridge、shared `code-context-summary/v0`、`pcl receipt show`、advisory retrieval eval、`pcl impact` のdiff modesが入っており、no schema migration、no new runtime dependency、no automatic go/no-go verdict、372 tests passedとされている。[S1]

率直に言うと、v0.1.11は「やるべきことをやった」リリースである。v0.1.9で生まれたContext Receipt、v0.1.10で固めたTrust/Safety、そしてv0.1.11で通常のContext Packへ接続した流れは、PLHを単なるCLI群から「AI開発ループの文脈制御盤」へ引き上げた。

ただし、ここから先の危険は別のところにある。次に検索精度やUIを足す前に、次の問いを潰す必要がある。

> Context Packに埋め込まれた最新receiptは、本当にそのjob/taskに関係しているのか？

現状の`--include-code-context`は「最新のcontext_receipt evidence」を読む。これは設計上は明快だが、作業対象とreceiptがズレる可能性がある。v0.1.12の中心は、semantic searchでもdashboard大型化でもなく、**receipt relevance / scope / safety invariantのhardening**にすべきである。

---

## 1. v0.1.11で実装された主要変更

| 領域 | 実装されたこと | 評価 |
|---|---|---|
| Context Pack Bridge | `pcl context pack --include-code-context` が最新receiptを読み、`code-context-summary/v0`として埋め込む | 良い。PLHの標準handoff面にCode Contextが入った |
| Summary isolation | `context-receipt/v0`本体をpackへ直埋めせず、summaryを挟む | 非常に良い。unstable receipt契約をstable pack契約から絶縁している |
| Human triage | `pcl receipt show` が evidence id / path / latest に対応し、同じsummary modelを表示 | 良い。人間・次エージェント・将来dashboardの三重定義を避けた |
| Eval | adversarial fixtureとCI advisory evidence。release blockerにはしない | 良い。現段階でthreshold gateにしない判断は健全 |
| Diff modes | `--staged`, `--unstaged`, `--include-untracked`, `--all-changes`, `--base auto` | 良い。AIが作る新規ファイルを扱えるようになった |
| Go/no-go | `safe_to_continue`等を入れない | 正しい。PLHは許可者ではなく判断材料の構造化者である |

`docs/code-context.md`では、PLHのCode Context Indexはdependency-freeなsnapshotであり、working treeの代替ではなく、candidate context、omission、staleness、suggested verificationを説明するためのものだと整理されている。[S3] これはPLHの既存定義、つまりcoding agentsのためのlocal control planeというREADME上の位置づけと整合している。[S2]

---

## 2. 重要な設計判断の評価

### 2.1 `code-context-summary/v0`を挟んだ判断は正しい

`context-pack/v1`は通常のhandoff面であり、今後も安定契約として扱われるべきである。一方で`context-receipt/v0`はまだ進化中のreceipt契約である。v0.1.11はreceipt本体をpackに入れず、`code-context-summary/v0`だけを埋める設計を採った。[S4]

これは非常に重要である。ここを間違えてreceipt本体をinliningしていたら、receipt側の実験的な項目変更がContext Packの安定契約へ伝播していた。今回のsummary layerは、単なる表示機能ではなく、**契約の防火壁**である。

### 2.2 `safe_to_continue`を入れなかった判断は正しい

`docs/code-context.md`とテストは、receiptやsummaryが「agentが理解した」「agentが読んだ」「安全に進めてよい」といった認知・許可の主張をしないようにしている。[S3][S9]

この判断はPLHの信頼性ブランドに直結する。AIエージェントは`ok`や`safe`という字段を過剰に実行許可として解釈しがちである。PLHはgo/no-goを出すのではなく、facts、warnings、omissions、staleness、verification suggestionsを落とさず残すべきである。

### 2.3 Diff modesの完成は地味だが大きい

`pcl impact`が`--staged`、`--unstaged`、`--include-untracked`、`--all-changes`、`--base auto`に対応したことは、AI開発では実用上かなり大きい。[S1][S3] AIエージェントは新規ファイルを頻繁に作る。これまでuntracked fileがreceiptの外に落ちる危険があったが、少なくとも明示的に含められるようになった。

`diff.py`ではGit由来のdiff source、provided diffのattestation、untracked provenanceを分けており、local-gitで取得したものとcaller-provided diffを混同しない設計になっている。[S7] ここはPLHらしい。

---

## 3. 総合評価

| 観点 | 評価 | コメント |
|---|---:|---|
| 方向性 | A | PLHの勝ち筋を「検索」ではなく「handoff / receipt / verification」へ置けている |
| 契約設計 | A- | summary isolationは良い。ただしlatest receiptのscopeが未解決 |
| 安全性 | A- | secret scannerにならない、go/no-goを出さない、sensitive omissionを明記。良い |
| 実装スコープ管理 | A | no schema migration / no new runtime dependencyを守りながら進めている |
| UX | B- | `receipt show`は良いが、Context Pack上で「なぜこのreceiptか」はまだ弱い |
| 評価基盤 | B | advisory evalは妥当。ただし実運用feedbackとの接続はこれから |
| プロダクト準備度 | B | local power user / dogfoodにはかなり使える。一般ユーザー向けには説明負荷が高い |

PLHはこの数リリースで、かなり良い方向に育っている。だが、v0.1.11で一段階上がったからこそ、次の欠陥はより深刻になる。単体CLIとしての欠陥ではなく、**制御盤として誤った文脈を正しそうに渡す欠陥**である。

---

## 4. 次に最優先で議論すべき不足

### 4.1 最新receiptが対象job/taskに紐づいていない

`docs/context-pack.md`では、`--include-code-context`は最新の`context_receipt` evidence rowを読み、そのsummaryを`context_pack.code_context`へ埋めると説明されている。[S4] `context.py`も、include flagがある場合にlatest receiptをsummary化する流れになっている。[S6]

これはv0.1.11としては正しい最小実装だが、次の実運用では穴になる。

```text
T-0100: dashboardの文言修正
最新receipt: src/pcl/diff.pyの変更receipt
context pack --task T-0100 --include-code-context
→ unrelated receiptが自然に混ざる可能性
```

これは検索精度以前の問題である。Context Packが「最新」を採用するのは便利だが、作業対象とreceiptの関係が明示されていないと、エージェントは無関係なdiffを現在タスクの文脈として扱う可能性がある。

提案:

```json
"code_context": {
  "contract_version": "code-context-summary/v0",
  "status": "from_receipt",
  "receipt_ref": {...},
  "relevance": {
    "scope": "unscoped_latest",
    "target_type": "task",
    "target_id": "T-0100",
    "binding_strength": "weak",
    "warning": "This is the latest receipt, not a receipt explicitly created for this target."
  }
}
```

さらに将来は、次のような明示bindingが欲しい。

```bash
pcl impact --diff --for-task T-0100 --json
pcl impact --diff --for-job J-0007 --json
pcl context pack --task T-0100 --include-code-context --require-bound-receipt
```

### 4.2 `source_commands`の意味がやや紛らわしい

`docs/context-pack.md`は、`--include-code-context`が`pcl index build`や`pcl impact`を実行しないと明記している。[S4] 一方でContext Packのsource commandsには、code contextを含む場合に`pcl impact --diff --json`が追加される実装が見える。[S6]

これは実装バグというより、契約語彙のリスクである。`source_commands`という字段名は「このpack生成で実行されたsource command」に見える。実際には「receiptを生成するために事前に走らせるべき/走らせた可能性のある関連command」である。

提案:

- v0.1.12では既存contractを壊さず、`code_context.receipt_ref.source_command`または`code_context.refresh_commands`を追加する。
- docs上で`source_commands`の意味を「reconstruct/follow-upに使うcommand」なのか「actual executed commands」なのか明確化する。
- 将来の`context-pack/v2`では`source_commands`、`suggested_refresh_commands`、`source_paths`を分ける。

### 4.3 safety sectionは「高優先度」と「必ず落ちない」を分けるべき

`context-pack.md`では、`machine_context_rules`と`code_context_safety`が最高priorityにpinされ、tight budgetでもordinary detailより先に選ばれるとされている。[S4] これは良い。しかし、priority-based selectionとnon-droppable invariantは同じではない。

極端に小さい`--max-tokens`でsafety sectionが入らない可能性があるなら、PLHは「安全情報が落ちたpack」を成功として返すべきではない。少なくとも次のどちらかが必要である。

```json
"required_sections": ["machine_context_rules", "code_context_safety"],
"required_sections_omitted": [],
"required_section_policy": "fail_if_omitted"
```

または、required sectionが入らない場合はtyped errorにする。

PLHは「安全情報が落ちたことをmetadataに書いたからOK」とすべきではない。AIエージェントは本文を主に読む。安全・omission・stalenessだけは本文から消えてはいけない。

### 4.4 untracked warningは事実ベースに近づけるべき

v0.1.11ではuntracked対応がかなり進んだ。だが、summary側の`untracked_omission_warning`はdiff sourceの種類から出るため、実際にuntracked filesが存在するかまではsummaryだけでは分かりにくい。[S6]

これは安全側に倒した実装として理解できる。ただし、常に警告が出るとwarning fatigueを生む。v0.1.12では、`untracked_excluded_count`または`untracked_detected_count`をreceipt payloadに残し、summaryが次の3段階を区別できるとよい。

```text
none: untrackedなし
warning: untrackedあり、receiptに未含有
included: untrackedを明示的に含めた
```

### 4.5 verification suggestionが実行結果へ接続されていない

v0.1.11はverification suggestionsをContext Packへ渡すところまで到達した。次は、suggestionが実際に実行されたのか、hit/miss/skippedだったのかを記録する段階である。

現状のsuggestionは「助言」で止まる。これをfeedback loopにしないと、PLHはいつまでも評価できない。

提案:

```json
"verification_suggestions": [
  {
    "id": "VS-0001",
    "command": "python3 -m pytest tests/test_context.py",
    "reason": "test_hint:path_token_match",
    "source_receipt": "E-0001"
  }
]
```

そのうえで、verification evidence側に以下を持たせる。

```json
"verification_feedback": {
  "suggestion_id": "VS-0001",
  "status": "executed",
  "result": "passed",
  "evidence_id": "E-0009"
}
```

これはv0.2.xでschema migrationが必要になる可能性が高い。急がなくてよいが、設計は今から始めるべきである。

---

## 5. v0.1.12の推奨テーマ

v0.1.12のテーマは、**Code Context Bridge Reliability**がよい。新機能の派手さではなく、v0.1.11で開いたhandoff面が誤解を生まないようにするリリースである。

### 0082: receipt relevance / scope guard

目的: Context Packに入るreceiptが「最新」なのか「対象にboundされている」のかを明示する。

最小スコープ:

- `code_context.relevance.scope = unscoped_latest | target_bound | missing_receipt`
- `target_type`, `target_id`, `binding_strength`
- unscoped latestの場合はnon-droppable safety sectionに警告
- `pcl context pack --include-code-context --require-bound-receipt`は将来optionとして検討

これはv0.1.12のP0である。

### 0083: required safety section invariant

目的: priorityではなくinvariantとして、safety factsが本文から落ちないことを保証する。

最小スコープ:

- `required_sections`と`required_sections_omitted`をmetadataへ追加
- `code_context_safety`が落ちる場合はtyped errorまたは`ok:false`
- budget極小ケースのテスト追加

ここはAIエージェント時代の制御盤として譲れない。

### 0084: source command semantics cleanup

目的: `source_commands`が「実行済み」なのか「再現/更新用」なのかを曖昧にしない。

最小スコープ:

- docsで現在の意味を明文化
- `code_context.refresh_commands`を追加
- `source_paths`にreceipt pathが含まれる場合、`source_commands`側は「pack生成時には実行されない」と明示

### 0085: untracked signal precision

目的: untracked warningを「常時一般警告」から「事実ベース警告」へ近づける。

最小スコープ:

- non-including modesでもuntracked countだけはdiff provenanceへ記録するか検討
- summaryに`untracked_status = none | omitted | included | unknown`を追加
- `--include-untracked`時はsample pathsを過剰に出さない。sensitiveやexcludedは必ず漏らさない

### 0086: receipt lifecycle / stale receipt handling

目的: 古いreceiptがlatestとして混ざる事故を減らす。

最小スコープ:

- `created_at`とcurrent HEAD / index HEADの差をsummaryで強調
- `receipt_age_warning`を追加
- `pcl receipt list --json`で最近のreceipt一覧を見られるようにする
- `pcl receipt show --latest`だけに頼らない導線を作る

---

## 6. v0.2.xの推奨テーマ

v0.2.xでは、Milestone 12にあるMeasurement and feedbackへ進むのがよい。実装計画でも、v0.2.xはretrieval eval suite hardening、precision / recall / missing-critical-context / false-positive / token-cost metrics、verification suggestion feedback loopが候補として挙げられている。[S5]

ただし、ここでやるべきは「評価指標をたくさん作ること」ではない。必要なのは、PLH自身のdogfoodから出た実例を評価fixtureへ変換する仕組みである。

### v0.2で欲しいもの

1. `pcl eval retrieval`のbaseline history
2. dogfood receiptからfixture候補を生成するcommand
3. suggestion idとverification evidenceの接続
4. missing-critical-contextの人間ラベル付け
5. false positive / token-costの軽量計測
6. eval結果をdashboard-dataに載せる。ただしHTMLは人間用、agentはJSONを見る

### v0.2でまだ不要なもの

- embedding index
- Tree-sitter必須化
- call graph全面実装
- hosted search
- content-based secret scanner
- 自動go/no-go判定

実装計画でも、embeddings、Tree-sitter、call graph、semantic retrievalは、Milestone 12の評価でmissing-critical-contextが改善しないと示されるまで昇格しない方針になっている。[S5] これは守るべきである。

---

## 7. 具体的な契約案

### 7.1 `code_context.relevance`

```json
{
  "code_context": {
    "contract_version": "code-context-summary/v0",
    "status": "from_receipt",
    "receipt_ref": {
      "evidence_id": "E-0001",
      "receipt_path": ".project-loop/evidence/context-receipts/e-0001-impact-v0.json",
      "created_at": "2026-07-06T00:00:00Z"
    },
    "relevance": {
      "target_type": "task",
      "target_id": "T-0007",
      "scope": "unscoped_latest",
      "binding_strength": "weak",
      "warning": "The latest receipt is included, but it was not explicitly created for this target."
    }
  }
}
```

### 7.2 required safety section metadata

```json
{
  "required_sections": [
    "machine_context_rules",
    "code_context_safety"
  ],
  "required_sections_omitted": [],
  "required_section_policy": "fail_if_omitted"
}
```

### 7.3 verification suggestion ID

```json
{
  "verification_suggestions": [
    {
      "id": "VS-0001",
      "command": "python3 -m pytest tests/test_context.py",
      "reason": "test_hint:path_token_match",
      "source_receipt_evidence_id": "E-0001",
      "status": "suggested"
    }
  ]
}
```

これらは一気に全部入れる必要はない。v0.1.12では`relevance`とrequired safetyだけで十分価値がある。

---

## 8. ソクラテス式の論点

### 問い1: 「latest receipt」とは、誰にとって最新なのか？

repo全体にとって最新なのか、jobにとって最新なのか、taskにとって最新なのか、現在のworking treeにとって最新なのか。この区別を曖昧にしたままContext Packに載せると、PLHは「正しそうな文脈」を誤って渡す可能性がある。

### 問い2: Context Packの読者は誰か？

v0.1.11のimplementation planでは、receipt audience priorityは「next agent first, human second, CI third」と整理されている。[S5] これは妥当である。ただし、next agent firstなら、曖昧な字段名は危険である。エージェントは字段を命令として読む。だから`source_commands`や`safe`系の語彙は特に慎重に扱うべきである。

### 問い3: PLHはいつ失敗すべきか？

PLHは「なるべく成功してmetadataで注意する」だけでは弱い。安全sectionが落ちる、receiptが壊れている、target-bound receiptを要求したのに存在しない、これらは成功扱いにすべきではない。

### 問い4: 評価は誰のためにあるのか？

評価は開発者の自己満足ではなく、semantic retrievalやcall graphを入れるかどうかの投資判断のためにある。だから、evalはまずadvisoryでよい。だが、dogfood実例からfixtureが増えないevalは信用できない。

### 問い5: 非エンジニアのAI開発パワーユーザーに何が刺さるか？

彼らが欲しいのは「高度な検索」ではない。欲しいのは、AIに任せた変更がどこまで見られ、何が見落とされ、次に何を確認すべきかが一目で分かることだ。PLHのUI/UXは、この判断摩擦を潰す方向に絞るべきである。

---

## 9. いまやらない方がよいこと

### 9.1 semantic embedding index

まだ早い。v0.1.11の橋渡しが正しく働くか、missing-critical-contextがどこで起きるか、dogfood実例が足りない。評価なしにembeddingを入れると、検索は賢く見えるが、トークンと保守コストが増える。

### 9.2 Tree-sitter必須化

将来は有力だが、今はdependency-freeの価値が高い。pyproject上でもruntime dependenciesは空で、PLHは軽量runtimeとして配布されている。[S10]

### 9.3 content-based secret scanner

PLHはsecret scannerではないとdocsに明記されている。[S3] これは守るべき。やるなら外部tool連携か明示opt-inであり、coreに中途半端なsecret scanningを入れるべきではない。

### 9.4 hosted UI / cloud sync

まだ早い。ローカル制御盤としてのtrust boundaryがPLHの強みである。外部同期を急ぐと、receipt、root path、evidence、ローカル作業内容の扱いが一気に重くなる。

### 9.5 自動go/no-go

いらない。PLHがやるべきなのは、許可ではなく、判断材料の構造化である。

---

## 10. 推奨ロードマップ

### v0.1.12: Bridge Reliability

- 0082 receipt relevance / scope guard
- 0083 required safety section invariant
- 0084 source command semantics cleanup
- 0085 untracked signal precision
- 0086 receipt lifecycle / stale receipt handling

このリリースはno new runtime dependencyを維持する。schema migrationも可能なら避ける。

### v0.2.0: Measurement and Feedback

- retrieval eval baseline history
- dogfood receipt to fixture workflow
- verification suggestion ID
- verification evidence feedback loop
- dashboard-dataへのeval summary追加

ここではschema migrationが必要になる可能性がある。事前に設計レビューを挟むべきである。

### v0.3.0: Thin Mission Control

- dashboard receipt card
- human decision cockpitの意味圧縮
- copy-ready `pcl` commands
- 「今止まっている理由」「安全上の注意」「次に検証すべきこと」を1画面に集約

ただし、HTMLは人間用、agentはJSON/evidence/Context Packを読むという境界は維持する。

---

## 11. 実装担当への返答案

```markdown
v0.1.11の方向性はかなり良いと思います。前回議論した shared receipt summary model、Context Pack Bridge、receipt show、advisory eval、diff modes がほぼそのまま形になっており、PLHが「receiptを作れるCLI」から「通常handoffにreceiptを渡すcontrol plane」へ進んだと評価しています。

次の最重要論点は検索精度ではなく、latest receiptのrelevance/scopeです。現状の `--include-code-context` は最新の context_receipt を読むため、対象task/jobとreceiptがズレる可能性があります。これはv0.1.11としては正しい最小実装ですが、v0.1.12では `code_context.relevance.scope = unscoped_latest | target_bound | missing_receipt` のような字段を追加し、unscoped latestの場合はsafety sectionで明示警告したいです。

また、code_context_safety はpriority 10000だけでなく required section invariant として扱いたいです。極小budgetでsafety factsが本文から落ちるなら、成功扱いではなくtyped errorまたは required_sections_omitted を明示すべきです。

v0.1.12の柱は Bridge Reliability とし、semantic retrievalやTree-sitter、hosted UIにはまだ進まない方針でよいと思います。v0.2ではverification suggestion feedback loopとdogfood fixture化に進むのが筋です。
```

---

## 12. 最終判断

v0.1.11は良いリリースである。特に、`code-context-summary/v0`を絶縁層にしたこと、`safe_to_continue`を入れなかったこと、receipt showとContext Packが同じsummary modelを使うこと、diff modesを整えたことは、PLHの思想と合っている。

次の盲点は、「文脈がある」ことではなく「その文脈が今の作業対象に関係している」ことをどう示すかである。

PLHはAIエージェントに大量の文脈を渡す道具ではない。AI開発における判断材料を、落とさず、歪めず、後から検査できる形で渡す道具である。v0.1.12では、その信頼性を一段上げるべきである。

---

## 参照ソース

- [S1] GitHub Release v0.1.11: https://github.com/mocchalera/project-loop-harness/releases/tag/v0.1.11
- [S2] README at v0.1.11: https://raw.githubusercontent.com/mocchalera/project-loop-harness/v0.1.11/README.md
- [S3] docs/code-context.md at v0.1.11: https://raw.githubusercontent.com/mocchalera/project-loop-harness/v0.1.11/docs/code-context.md
- [S4] docs/context-pack.md at v0.1.11: https://raw.githubusercontent.com/mocchalera/project-loop-harness/v0.1.11/docs/context-pack.md
- [S5] docs/implementation-plan.md at v0.1.11: https://raw.githubusercontent.com/mocchalera/project-loop-harness/v0.1.11/docs/implementation-plan.md
- [S6] src/pcl/code_context/summary.py at v0.1.11: https://raw.githubusercontent.com/mocchalera/project-loop-harness/v0.1.11/src/pcl/code_context/summary.py
- [S7] src/pcl/code_context/diff.py at v0.1.11: https://raw.githubusercontent.com/mocchalera/project-loop-harness/v0.1.11/src/pcl/code_context/diff.py
- [S8] tests/fixtures/retrieval_adversarial_v0.json at v0.1.11: https://raw.githubusercontent.com/mocchalera/project-loop-harness/v0.1.11/tests/fixtures/retrieval_adversarial_v0.json
- [S9] tests/test_code_context_summary.py at v0.1.11: https://raw.githubusercontent.com/mocchalera/project-loop-harness/v0.1.11/tests/test_code_context_summary.py
- [S10] pyproject.toml at v0.1.11: https://raw.githubusercontent.com/mocchalera/project-loop-harness/v0.1.11/pyproject.toml
