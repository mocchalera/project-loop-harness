---
title: "AIコーディングエージェントの『完了』を、ローカルで検証可能にする Project Loop Harness v0.5.0"
emoji: "🔁"
type: "tech"
topics: ["ai", "cli", "python", "codex", "claudecode"]
published: false
---

> 編集メモ: これは投稿前の下書きです。公開前に
> [launch-checklist.md](launch-checklist.md) を完了し、人間の承認を得てください。

AIコーディングエージェントは変更を作るのは得意です。一方で、セッションをまたいで
「何が終わったのか」「何を根拠に完了と言えるのか」「次に進むべきか、人間に判断を
求めるべきか」を保つのは、まだ運用側の仕事になりがちです。

この問題に対して、ローカルで動くCLI **Project Loop Harness (`pcl`)** を作っています。
2026年7月14日に v0.5.0 を GitHub Releases と PyPI で公開しました。

- GitHub: https://github.com/mocchalera/project-loop-harness
- v0.5.0 Release: https://github.com/mocchalera/project-loop-harness/releases/tag/v0.5.0
- PyPI: https://pypi.org/project/project-loop-harness/0.5.0/

## 何をするものか

`pcl` は、コーディングエージェントの作業を次のループとして記録・検証します。

```text
Goal -> Harness -> Workflow -> Agent Jobs -> Evidence -> Verification
     -> State -> Dashboard -> Stop / Retry / Escalate
```

中心にあるのはダッシュボードではなく、ガード付きの状態機械です。

- SQLiteを現在状態の system of record とする
- JSONLに監査可能なイベント投影を残す
- テスト、成果物、レビュー、completion packetをEvidenceとして結び付ける
- CLI経由の状態変更を検証し、人間にしか決められない判断では止まる
- HTMLダッシュボードは状態から生成する人間向けビューに限定する

ランタイム自体はLLMを呼びません。Codex、Claude Codeなど特定のモデルや
エージェントベンダーに状態管理を預けず、同じローカル状態を引き継ぐための
コントロールプレーンです。

## 5分で試す

まず `pipx` でCLIを入れ、既存リポジトリに何が追加されるかをdry-runで確認します。

```bash
pipx install project-loop-harness
cd /path/to/your-project
pcl init --dry-run --json
pcl init
pcl doctor
pcl validate --strict
pcl render --json
```

空でないリポジトリでは、最初に `pcl init --dry-run --json` を実行する設計です。
通常の初期化は既存の `AGENTS.md`、`CLAUDE.md`、`.gitignore` の内容を保持し、
Project Loop用のマーク付きブロックを一度だけ追記します。既存の `pcl.yaml` も
デフォルトでは置き換えません。`--force` は生成テンプレートを置き換える明示的な
境界なので、dry-runを確認したうえで人間が判断する想定です。

初期化後は、エージェントに次のように依頼できます。

```text
AGENTS.md、CLAUDE.md（存在する場合）、pcl.yamlを読み、Project Control Loopを
使ってください。目標は <実現したい結果> です。安全な次の操作、設定済みチェック、
Evidenceの保存、completion packetの生成、goalのcloseまで続けてください。
人間の判断または外部の障害が本当に必要な場合だけ止まってください。
```

人間が各CLI操作を手動で進めるのではなく、エージェントが通常のループを担当し、
権限、破壊的操作、プロダクト判断、外部サービスなどの境界で人間に戻します。

詳しい導入範囲とコミット対象は
[Adoption Guide](https://github.com/mocchalera/project-loop-harness/blob/main/docs/adoption-guide.md)
にまとめています。

## ローカル、依存を増やしにくい、状態が残る

Coreはローカル専用で、Python標準ライブラリを優先しています。v0.5.0の
ランタイム依存は空で、Python 3.10以上を対象としています。初期化によって
telemetry、cloud sync、provider call、自動GitHub書き込みが有効になることは
ありません。

状態変更は `pcl` コマンドまたは内部サービス関数を通し、イベントを追記します。
エージェントがSQLiteや生成HTMLを直接編集する運用にはしません。これにより、
「完了した」という会話上の主張ではなく、後から確認できるEvidenceと状態遷移を
引き継げるようにしています。

## v0.5.0で変わったこと

今回のリリースは Adoption / Distribution と、実験的な Council Profile が中心です。

- READMEを30秒の価値説明、5分セットアップ、詳細説明の順に再構成
- 既存リポジトリとのinspect-firstな共存手順を明文化
- 日本語ダッシュボードの先頭を「今 / 完了 / 次 / あなたの判断 / 注意点」に整理
- `pcl finish` の不足Evidenceや回復手順の診断を改善
- `pcl guide` に目的別の開始・完了・回復ルートを追加
- ローカルの摩擦を集計するread-onlyな `pcl report skill-usage` を追加

## CouncilはCoreのデフォルトではない

Council Profileは、曖昧または高リスクな仕事のための **opt-in / experimental** な
外部助言境界です。モデルプロバイダーでも、実行器でも、検証者でも、承認者でも
ありません。明確な仕事ではDirectがデフォルトのままです。

Coreが行うのは、決定論的なrequestの準備と、返されたbytesの検証・Evidence化です。
選択と承認は人間のDecisionに残ります。実ネットワークや有料providerの実行は
Coreの外側で、別のhash-boundな人間承認を必要とします。v0.5.0での位置付けは
「デフォルト採用」ではなく「実験を続ける」です。

## いま知りたいこと

完成した製品だと主張するためではなく、初見の人がCoreの価値と境界を正しく理解し、
既存プロジェクトへ安全に導入できるかを確かめるために公開しています。特に次の
フィードバックを求めています。

1. 30秒で「誰の、どの問題を解くCLIか」を説明できたか
2. `pcl init --dry-run --json` を見て、既存ファイルへの影響を判断できたか
3. 最初に価値を感じた箇所と、最初に止まった箇所はどこか
4. agent-safeな操作とhuman gateの境界は期待どおりか
5. SQLite / JSONL / dashboard の役割分担は理解しやすいか

IssueやDiscussionを作る前段階の短い感想でも構いません。再現手順を公開できる場合は
GitHub Issuesへお願いします。機密情報、認証情報、プロジェクトの生データは添付しないで
ください。

- Issues: https://github.com/mocchalera/project-loop-harness/issues
- README: https://github.com/mocchalera/project-loop-harness#readme

まずは小さなリポジトリでdry-runし、「自分のエージェント運用で何が足りないか」を
教えてもらえると助かります。
