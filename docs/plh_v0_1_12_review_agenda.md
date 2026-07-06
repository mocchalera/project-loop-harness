# Project Loop Harness v0.1.12 レビュー & 改善議題

作成日: 2026-07-06  
対象: `mocchalera/project-loop-harness` v0.1.12 / PyPI `project-loop-harness==0.1.12`  
目的: v0.1.12の実装確認、リリース品質レビュー、v0.2に進む前の論点整理

---

## 0. 前提と検証範囲

このレビューは、公開GitHub / PyPI / GitHub Actionsの確認に加え、PyPI wheel / sdist を手元で展開して軽いスモーク検証を行った結果に基づく。

確認した主な事実:

- PyPI上では `project-loop-harness 0.1.12` が最新リリースとして表示され、リリース日は 2026-07-06。[S1]
- GitHub Actions の Publish Python Package run は `v0.1.12` として実行され、Status は Success。PyPI publish step も成功している。[S2]
- `pyproject.toml` は version `0.1.12`、Python `>=3.10`、runtime dependencies は空、CLI entry points は `pcl` と `pcl-mcp`。[S7]
- 手元のwheelスモークでは `pcl --version` が `pcl 0.1.12` を返し、`pcl --help` / `pcl-mcp --help` は正常に表示された。
- 手元のスクラッチプロジェクトで `pcl init`、`pcl index build`、`pcl impact --diff`、`pcl impact --diff --include-untracked`、`pcl receipt show --latest --json`、`pcl context pack --task ... --include-code-context` が成功した。
- 極小budgetの `pcl context pack --include-code-context --max-tokens 10 --json` は `context_pack_budget_too_small` を返し、required sections と推奨最小budgetを返した。これはv0.1.12の設計意図と一致している。

注意: GitHub上のCI成功とwheelの基本動作は確認できたが、ここでのレビューは完全なリポジトリCIの再実行ではない。PyPI sdistについては、下記の通り配布品質上の問題を別途検出した。

---

## 1. 結論

v0.1.12は、前回議論した **Context Pack Truthfulness Hardening** をかなり正しく実装したリリースである。

特に良い点は以下。

1. `source_commands` の虚偽attestation問題を修正し、`pcl impact --diff --json` を `suggested_refresh_commands` に分離した。
2. `machine_context_rules` と `code_context_safety` をrequired sectionとして扱い、小さすぎるbudgetでは黙って安全情報を落とさずtyped errorにした。
3. 最新receiptがtargetに紐づいていない事実を `unscoped_latest` / `binding_strength: none` として明示する方向へ進んだ。
4. `receipt_age` / `age_warning` によって、最新receiptの鮮度をgo/no-goではなく事実ラベルとして渡せるようにした。
5. v0.2設計ドラフトが、feedback table、dogfood-to-fixture、advisory-first regression gate、receipt-scoped suggestion IDという正しい方向に整理されている。

ただし、次に潰すべき論点も明確である。

最優先は、v0.2の実装に入る前に **配布品質とコマンド表面の整合** を直すこと。具体的には、PyPI sdistにtestsは入っているがdocsが入っておらず、sdist展開後に `pytest` を走らせると `docs/agent-adapter-contract.md` 不在で失敗する。これはruntime機能のバグではないが、「PyPIに出したsource artifactが自己完結していない」という配布品質の問題である。

また、v0.2設計ドラフトは `pcl verify feedback` を提案しているが、現行CLIのtop-level commandは `verification` であり、READMEでも `pcl verification record` が使われている。ここは `pcl verification feedback` に揃えるか、明示的に `verify` aliasを追加するか、実装前に決めるべきである。

---

## 2. v0.1.12で解決されたこと

### 2.1 source_commands の誠実性

v0.1.11では、Context Packが既存receiptを読むだけであるにもかかわらず、`source_commands` に `pcl impact --diff --json` を載せていた。これは「packの根拠を再取得する読取コマンド」と「artifactを生成し直す更新コマンド」を混同していた。

v0.1.12のdocsでは、`source_commands` はread-only re-fetch commandsであり、evidence rowやreceipt artifact等を作ってはいけないと定義されている。そのためcode-context packは `pcl impact --diff --json` を `source_commands` に載せず、代わりに `suggested_refresh_commands` を使う。[S4]

手元スモークでも、`pcl context pack --task T-0001 --include-code-context --json` の `source_commands` は `pcl task read ...`、`pcl task list --json`、`pcl validate --json` に留まり、`suggested_refresh_commands` に `pcl index build --json` / `pcl impact --diff --json` が出た。これは正しい。

### 2.2 required section invariant

v0.1.12のContext Pack docsでは、`machine_context_rules` は常にrequired、`--include-code-context` 時の `code_context_safety` もrequiredとされ、成功時には `required_sections_omitted` が空になる設計が明記されている。budgetが小さすぎる場合は `context_pack_budget_too_small` のtyped errorを返す。[S4]

手元スモークでも、`--max-tokens 10` は成功packではなく、`context_pack_budget_too_small` と `estimated_min_max_tokens` を返した。これはかなり重要である。AIエージェント向けの文脈packは、「安全警告が落ちたが成功したように見える」状態が最も危険だからである。

### 2.3 receipt relevance / age の事実ラベル

v0.1.12は、latest receiptの根本問題を「完全解決」したわけではない。Context Packは依然として最新の `context_receipt` evidence rowを読む。しかし、v0.1.12ではそれを隠さず、`scope: unscoped_latest` と `binding_strength: none` で明示する。さらに、将来の `target_bound` / `caller_asserted` は「PLHが意味的関連を証明したものではない」と予約語の意味を抑制している。[S4]

この判断は正しい。PLHは「関連している」と強く言うべきではない。今できるのは、「最新を使ったがtarget bindingはない」と正直に渡すこと。

### 2.4 Code Contextの境界維持

Code Context docsは、indexを「working treeの置き換えではないsnapshot」と定義し、working treeをsource of truthとしている。また、receiptはagent cognitionの証明ではなく、PLHの候補文脈・省略・staleness・検証提案を記録するevidence artifactであると整理している。[S5]

これは、PLHの信頼性ブランドに合っている。PLHは「AIが理解した」とは言わない。PLHは「何を候補として渡し、何を落とし、どんな警告があったか」を記録する。

---

## 3. 評価サマリー

| 領域 | 評価 | コメント |
|---|---:|---|
| Context Pack truthfulness | A | v0.1.11の主要リスクだったsource_commandsとrequired section問題は、かなり良く修正された。 |
| Code Context safety | A- | sensitive omission、staleness、untracked labels、receipt summary isolationは良い。次はscope fidelity。 |
| Token/budget behavior | A- | required section failureは正しい。今後は長期dogfoodで推奨budgetを観測すべき。 |
| UX / human readability | B+ | `pcl receipt show` とContext Pack sectionは実用的。dashboard連携はまだ薄い。 |
| Distribution quality | C+ | wheelは良いが、sdistにdocsがなく、同梱testsが自己完結しない。次回リリース前に直すべき。 |
| v0.2 readiness | B+ | 設計は良いが、CLI命名とmigration境界を実装前に詰める必要がある。 |

---

## 4. 新たに見つかった重要論点

### 4.1 P0: sdistが自己完結していない

PyPIから `project-loop-harness==0.1.12` のsdistを取得して展開すると、`tests/` は含まれるが `docs/` は含まれていなかった。`pytest -q -x` は `tests/test_agent_adapter_contract.py::test_agent_adapter_docs_match_contract` で `docs/agent-adapter-contract.md` が存在せず失敗した。

これはruntime機能の破損ではない。しかし、source distributionとしては良くない。

問題の本質:

```text
sdistにtestsを含めるなら、testsが参照するdocsも含めるべき。
または、sdistではdocs依存テストをskipする明示条件を入れるべき。
```

推奨は前者である。PLHはdocs-as-contractの性格が強いプロダクトなので、docsをsource artifactから外すのは思想と合わない。

提案タスク:

```text
0085-distribution-source-completeness
- MANIFEST.in または pyproject設定で docs/ と agent-tasks/ をsdistに含める
- sdist展開後に pytest が最低限のcontract/doc testsを通ることをCIで検証
- wheelにはdocsを入れる必要があるかを別判断する
- README / PyPI long description のGitHub docsリンクはtag固定ではなくlatest/mainでよいか再確認
```

### 4.2 P0: v0.2設計の `pcl verify feedback` 命名

v0.2設計ドラフトは `pcl verify feedback --suggestion ...` を提案している。[S6]

しかし、現行CLIのtop-level commandは `verification` であり、READMEでも `pcl verification record` が正式な操作例として使われている。[S3]

このまま `verify` を新設すると、利用者にとって次のような混乱が生じる。

```text
pcl verification record
pcl verify feedback
```

これはPLHらしくない。命名は制御盤のUXであり、将来のagent指示にも効く。

推奨判断:

```text
第一候補: pcl verification feedback
第二候補: pcl verification feedback を本命にし、pcl verify feedback は短縮aliasとして後から検討
非推奨: verify と verification を意味なく併存させる
```

### 4.3 P1: suggested_refresh_commands のscope fidelity

v0.1.12は `source_commands` を正直にした。これは正しい。

ただし、`suggested_refresh_commands` はまだ「前回receiptと同じscopeを再現するコマンド」とは限らない。たとえば最新receiptが `--include-untracked` や `--base main` で作られていても、refresh suggestionが単に `pcl impact --diff --json` だと、再生成時にdiff scopeが変わる。

これはsource_commandsほど重大ではないが、次に効いてくる。

提案:

```text
code_context.refresh_replay:
  fidelity: generic | scope_preserving | unavailable
  commands:
    - pcl impact --diff --include-untracked --json
  reason:
    - diff_source was worktree-vs-HEAD+untracked
```

最低限、`diff_source` から再現できる範囲だけでも `--include-untracked` / `--base <ref>` / `--staged` / `--unstaged` を反映した方がよい。

### 4.4 P1: latest receipt selectorの明示化

v0.1.12は `unscoped_latest` と表示できるようになった。これは真実性の改善である。

次の段階では、operatorが明示的にreceiptを選べるようにするべきである。

候補:

```bash
pcl context pack --task T-0001 --include-code-context --receipt E-0007 --json
pcl context pack --task T-0001 --include-code-context --receipt latest --json
pcl context pack --task T-0001 --include-code-context --require-receipt --json
```

ただし `--require-bound-receipt` はまだ早い。bindingの意味が固まる前に「bound」という語を使うと、また誤解を生む。

---

## 5. v0.2設計ドラフトへのレビュー

`docs/verification-feedback-design.md` は、前回議論した論点をかなり正しく反映している。特に次の点は承認でよい。

### 5.1 feedback tableはmigration 005でよい

v0.2設計は `verification_feedback` をappend-only event tableとして追加し、`UNIQUE(suggestion_id)` を置かず、`executed` では `result` と `supporting_evidence_id` を必須にする。また、PLHが観測できない `never_seen` はstatusにしない。[S6]

これは正しい。feedbackは「現在状態」ではなく、「誰かがこう記録した」という証跡イベントである。

### 5.2 suggestion IDは `E-0001/VS-01` でよい

receipt evidence IDをprefixに持ち、receipt内のordinalで決定でき、新規DB sequenceが不要である。さらに、receipt payloadには `status` を置かず、状態はfeedback tableに置く設計になっている。[S6]

これは正しい。receiptは不変の候補提示であり、状態は時間とともに変わる。

### 5.3 dogfood-to-fixtureをbaselineより先に置くのは正しい

設計ドラフトは、dogfood-to-fixture workflowをMilestone 12に追加し、baseline record/compareより前に置いている。理由は、dogfood実例からfixtureが増えないevalは信用できないからである。[S6]

これも正しい。synthetic fixtureだけで評価基盤を精密化すると、実際のAI開発ループではなく評価装置に最適化される。

### 5.4 regression gateはadvisory firstでよい

設計ドラフトでは、precision / recall / missing-critical-context / false-positive / token-cost のthresholdは、5-kind fixture setと実測分散が揃うまでadvisoryに留め、schema破損やeval command failureなどの計測基盤の破損だけをblockingにする。[S6]

これはかなり健全である。PLHは「測定できていないのに強いgateを作る」べきではない。

---

## 6. v0.2へ進むための修正版タスク順

現行TASKSは0084までで止まっており、CLI-firstで進める方針も明記されている。[S8]

v0.1.12後の推奨順は以下。

### 0085: distribution source completeness

目的: PyPI source artifactの自己完結性を保証する。

受け入れ条件:

```text
- sdistにdocs/が含まれる
- testsが参照するdocsファイルがsdist上で存在する
- CIで「sdist展開 → dev install → pytest doc/contract subset」が通る
- sdistとwheelの役割差がREADMEまたはrelease checklistに明記される
```

### 0086: command surface alignment before v0.2

目的: v0.2設計のCLI命名を現行CLIと揃える。

受け入れ条件:

```text
- `pcl verify feedback` を `pcl verification feedback` に変更するか、alias方針を明文化
- docs/verification-feedback-design.md を修正
- README / help / tests で `verification` namespaceに統一
```

### 0087: verification suggestion IDs

目的: `verification_suggestions` をstring-listからobject-listへ移行する。

注意:

```text
- old receiptのstring-listは受け続ける
- summary JSONには id を含める
- human displayは大きく変えない
- receiptに status は入れない
```

### 0088: migration 005 verification_feedback

目的: append-only feedback event tableとCLI記録。

注意:

```text
- `pcl verification feedback` はsuggestion IDがreceipt内に実在することを検証
- executedはsupporting evidence必須
- no feedback recorded は派生表示
- feedback insertはJSONL eventもappend
```

### 0089: dogfood-to-fixture propose

目的: 実receiptからunlabeled fixture候補を作る。

注意:

```text
- expected_files / expected_tests / critical_context は空
- labels_status: unlabeled
- fixtures/proposed/ に出す
- tests/fixtures/ への採用は人間ラベル後のmanual move
```

### 0090: baseline record / compare

目的: eval結果をevidence化し、advisory comparisonを作る。

注意:

```text
- fixture hashだけでなく git HEAD / index run / index detail hash / config hash / pcl version / eval contract versionを保存
- metric regressionはadvisory
- eval infrastructure failureはblocking
```

### 0091: refresh command scope fidelity

目的: `suggested_refresh_commands` を前回receiptのdiff scopeに近づける。

受け入れ条件:

```text
- diff_sourceごとの推奨refresh command mappingを定義
- --include-untracked / --all-changes / --staged / --unstaged / --base の再現可能範囲を整理
- 再現不能なprovided-diffは generic として明示
```

---

## 7. ソクラテス式に今問うべきこと

### 問い1: PyPI sdistは「動作配布物」か「検証可能なsource artifact」か？

PLHの性格から考えると後者である。であれば、testsだけ入れてdocsを抜くのは中途半端。source artifactとして出すなら、docs-as-contractも含めるべき。

### 問い2: `suggested_refresh_commands` は「便利な提案」か「前回条件の再現」か？

今は便利な提案である。しかし、Context Receiptの世界では再現性が重要になる。将来は `generic` と `scope_preserving` を分けた方がよい。

### 問い3: `unscoped_latest` をいつまで許すのか？

v0.1.12では許してよい。真実をラベル化したからである。だが、v0.2以降では operatorがreceiptを選べるUI/CLIが必要になる。

### 問い4: feedbackは「事実」か「申告」か？

申告である。`executed + passed` は、PLHがコマンド実行を検証した事実ではない。supporting evidenceに支えられた記録者の主張である。この境界を絶対に崩してはいけない。

### 問い5: v0.2の成功条件は何か？

機能が増えることではない。PLH自身が出した検証提案について、実行されたか、skipされたか、どんなevidenceが残ったか、fixtureがdogfoodから増えたかを測れるようになること。

---

## 8. 実装担当への返答案

```markdown
v0.1.12の方向性はかなり良いと思います。

特に、source_commandsからpcl impactを外してsuggested_refresh_commandsへ分離したこと、machine_context_rules/code_context_safetyをrequired sectionとして扱いbudget不足時にtyped errorへ倒すこと、latest receiptをunscoped_latest/binding_strength:noneとして正直に表示したことは、PLHの信頼性ブランドに合っています。

次に進む前に2点だけP0で挟みたいです。

1. PyPI sdistの自己完結性
   手元でproject-loop-harness==0.1.12のsdistを展開してpytest -q -xを走らせると、docs/agent-adapter-contract.mdが含まれておらずtest_agent_adapter_docs_match_contractで落ちました。testsをsdistに含めるならdocsも含めるべきです。PLHはdocs-as-contractの性格が強いので、これは次回PyPI publish前に直したいです。

2. v0.2設計のCLI命名
   docs/verification-feedback-design.mdはpcl verify feedbackを提案していますが、現行CLIはpcl verification recordです。ここはpcl verification feedbackに揃えるか、verify aliasを明示的に追加する方針を決めたいです。何となくverifyとverificationが併存するのは避けたいです。

その上で、v0.2の大枠は承認でよいです。
- 0087 suggestion IDs
- 0088 migration 005 verification_feedback append-only table
- 0089 dogfood-to-fixture propose
- 0090 baseline record/compare

追加で、v0.2中か直後に suggested_refresh_commands のscope fidelityを見たいです。latest receiptが--include-untrackedや--base mainで作られていても、refresh提案がpcl impact --diff --jsonだけだとscopeが変わる可能性があります。source_commandsほど重大ではありませんが、PLHの再現性思想からすると次の自然な改善点です。
```

---

## 9. 最終判断

v0.1.12は成功リリースである。

しかし、v0.2に進む前に「機能の追加」ではなく、以下の2つを整えるべきである。

```text
1. 配布物の誠実性: sdistがdocs/tests込みで自己完結しているか
2. コマンド表面の誠実性: verification namespaceを崩さずfeedbackを入れるか
```

その後で、v0.2のMeasurement and Feedbackへ進むのが正しい。

PLHの勝ち筋は、検索エンジンでも自動実行器でもない。  
**AI開発で発生した提案・判断・検証・省略・警告を、後から検査できる形で残すこと**である。

v0.1.12は、その思想をかなり強くした。次は、PLH自身が出した検証提案の結果を測る段階に入る。ただし、測定の前に、配布物とCLI命名の小さな嘘を潰すべきである。

---

## 参照ソース

[S1] PyPI project page: project-loop-harness 0.1.12, latest release, released Jul 6 2026  
https://pypi.org/project/project-loop-harness/

[S2] GitHub Actions run 28772831920: Publish Python Package v0.1.12, status success, PyPI publish job  
https://github.com/mocchalera/project-loop-harness/actions/runs/28772831920

[S3] README at v0.1.12: PLH as local control plane, runtime surface, Context Packs, Explainable Code Context  
https://github.com/mocchalera/project-loop-harness/tree/v0.1.12

[S4] docs/context-pack.md at v0.1.12: source_commands honesty, suggested_refresh_commands, relevance, age, required sections  
https://raw.githubusercontent.com/mocchalera/project-loop-harness/v0.1.12/docs/context-pack.md

[S5] docs/code-context.md at v0.1.12: index/search/impact/receipt/show contracts and diff modes  
https://raw.githubusercontent.com/mocchalera/project-loop-harness/v0.1.12/docs/code-context.md

[S6] docs/verification-feedback-design.md at v0.1.12: v0.2.x Measurement and Feedback design  
https://github.com/mocchalera/project-loop-harness/blob/v0.1.12/docs/verification-feedback-design.md

[S7] pyproject.toml at v0.1.12: package metadata, dependencies, scripts, package-data  
https://github.com/mocchalera/project-loop-harness/blob/v0.1.12/pyproject.toml

[S8] TASKS.md at v0.1.12: task order through 0084 and CLI-first policy  
https://github.com/mocchalera/project-loop-harness/blob/v0.1.12/TASKS.md
