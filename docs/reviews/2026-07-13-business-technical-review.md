# Business and technical review — 2026-07-13

- Source: AGI Cockpit task `524a3d14`
- Reviewer: Claude
- Reviewed state: Project Loop Harness v0.4.3 and the repository state visible on 2026-07-13
- Original request: 「このプロジェクトをビジネス的視点と技術的な視点からレビューしてください」
- Captured by: Codex, without changing the review's recommendations

## Overall assessment

**技術的には異例の完成度、ビジネス的にはまだ「ユーザー1人の製品」。**

リポジトリ作成から短期間で v0.1.6 から v0.4.3 まで進み、厚いテスト、
依存ゼロ、trusted publishing、複数PythonバージョンとWindowsを含むCIという
規律は、alpha段階の個人OSSとして突出している。一方、GitHubのstarとforkは
0で、実ユーザーはオーナー自身と、そのエージェント経由の限定的なdogfoodに
留まる。投資の多くが信頼性・整合性・契約という内向きの品質に向き、発見性と
「初見3分で価値が分かる」外向きの体験が未整備であることが最大のリスクである。

## Business review

### Strengths

1. **モデル性能向上が価値を毀損しにくい戦略。** 生成がコモディティ化するほど
   信頼、Evidence、検証、引き継ぎが希少になるというテーゼに立ち、coreはLLMを
   呼ばず、モデル出力をfactではなくclaimとして扱う。ベンダーのエージェント機能と
   正面衝突しない。
2. **ポジショニングが明確。** AI coding agentに、忘れず、暴走せず、証拠を残し、
   次の行動を判断させるlocal control planeである。忘却、暴走、証拠不足、コスト、
   終端処理の負荷という実際の痛みから設計されている。
3. **dogfoodの学習ループが本物。** PLH自身と外部プロジェクトでの利用から摩擦を
   抽出し、複数リリースで修正している。human gateを弱める要求が出ていないことは
   コア価値仮説の初期検証として意味がある。

### Risks

1. **配布と発見性がほぼゼロ。** READMEは長く、3分で価値を理解する入口としては
   重い。理想ユーザーがいる場所への一次発信もまだない。技術的完成度と認知の差が
   最大の負債である。
2. **ベンダー内製化リスク。** Claude CodeやCodex自身がcheckpoint、task list、
   session memory、subagent統制を取り込んでいる。差別化であるクロスエージェント、
   監査可能、ローカル、モデル中立を、複数エージェントを指揮するユーザー向けに
   もっと鮮明に示す必要がある。
3. **将来の収益経路は未定義。** 現時点では問題ではないが、Council runnerをcoreと
   別パッケージにする境界は、将来のサポート、企業監査、runner提供などの選択肢を
   残す意味でも妥当である。
4. **概念が多く、オンボーディングが重い。** Goal、Feature、Task、Workflow、
   Evidence、Receipt、Context Pack、Work Brief、Council Profileなどの語彙を、
   最初の価値体験では見せすぎないgolden pathが必要である。

### Business recommendations, in priority order

1. **v0.5.0 AdoptionをCouncilと同格以上に扱う。** READMEを「30秒の価値説明」
   「5分quick start」「深掘り」に分け、asciinemaまたはGIFでgolden pathを示す。
2. **一次発信を1本出す。** 日本語ならZenn、英語ならHNまたはRedditを候補とし、
   フィードバック母数を増やす。
3. **乗り換えコストゼロの入口を示す。** 既存プロジェクトへ`pcl init`しても
   `CLAUDE.md`や`AGENTS.md`と共存できることをAdoption Guide冒頭で保証する。

## Technical review

### Strengths

1. **アーキテクチャ境界が強い。** Skillは指示、CLIはruntime、SQLiteは正、JSONLは
   投影、HTMLは人間向けビューという責務分離が、ADRだけでなくテストで強制される。
   transactional outboxを含む整合性設計もこの規模の個人ツールとして非常に堅い。
2. **epistemic vocabularyが競争力になっている。** `ready_for_handoff`などの
   過剰な断定を契約へ入れず、不在をテストする。AIツールが確信を装う問題に対する
   構造的な回答になっている。
3. **回帰からの学習が制度化されている。** 同型回帰を不変条件、fixture、release
   checklistへ落とし、失敗をプロセスに焼き込んでいる。
4. **runtime依存ゼロと決定論。** 配布、監査、長期保守に有利な選択である。

### Risks

1. **`cli.py`、`commands.py`、`context.py`が大きい。** テストが厚いうちに、
   サブコマンド単位の段階的な純リファクタを検討すべきである。
2. **alphaに対して機能表面積が巨大。** 安定契約の範囲が未宣言であるため、JSON
   出力、typed error code、schema migration経路など、何を互換契約として守るかを
   stability policyで明示する必要がある。
3. **人間側のバス係数が1。** editable installの参照先、worktree、`PYTHONPATH`など
   の運用上の罠を、開発環境チェックとして機械化する余地がある。
4. **性能・スケールは未検証。** 大規模リポジトリ、長期肥大した`events.jsonl`、
   dashboard描画の目安とrotation/compaction方針がない。
5. **Council Profileは複雑性の分水嶺。** 境界設計は正しいが、基本ループの新規
   ユーザー価値を検証する前に高度機能を深掘りすると、誰も使わない機能が増える。

### Technical recommendations, in priority order

1. **stability policyを宣言する。** 安定契約としてJSON出力、typed error code、
   schema migration経路などを明示する。
2. **`cli.py`と`commands.py`を段階分割する。** テスト無変更greenを条件にした
   純リファクタとして進める。
3. **性能の目安とevent logのrotation/compaction方針を文書化する。** 実装は需要が
   出てからでよい。
4. **dev-envの罠を機械化する。** editable installの参照先確認などをdoctorまたは
   開発用checkへ追加する。

## Reviewer conclusion

技術的な下地は非常に強く、戦略テーゼも時流に対して順張りである。現在の
ボトルネックは技術ではなく、誰にも知られていないこと。次の1〜2週間はCouncilの
追加開発よりも、Adoption、README分割、3分体験、一次発信を優先し、ユーザー母数を
増やすべきである。

## Repository-owner interpretation boundary

このレビューは助言であり、公開、外部投稿、telemetry、provider実行、課金、
デフォルト変更の承認ではない。外部に見える操作は別途、人間の明示承認を要する。
