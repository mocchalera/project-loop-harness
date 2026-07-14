---
title: "AIコーディングエージェントの「完了」をSQLite・JSONL・Evidenceで検証可能にする"
emoji: "🔁"
type: "tech"
topics: ["ai", "python", "cli", "codex", "claudecode"]
published: false
---

AIコーディングエージェントは、コードを変更するところまでは速くなりました。
しかし実際に複数セッション、複数エージェントで開発を続けると、別の問題が残ります。

- 何をもって「完了」としたのか
- テストやレビューの証拠はどこにあるのか
- 次の操作はエージェントが進めてよいのか
- どこから人間の判断が必要なのか
- セッションが変わっても同じ状態から再開できるのか

私はこの運用をローカルで管理するCLI、
[Project Loop Harness](https://github.com/mocchalera/project-loop-harness)（`pcl`）を
開発しています。2026年7月14日に v0.5.0 を公開しました。

この記事では、単なるリリース紹介ではなく、次の3点を実装・dogfoodした結果をまとめます。

1. SQLite、JSONL、HTMLをどう役割分担したか
2. 会話上の「完了」を、ハッシュ固定Evidenceと状態遷移へどう変えたか
3. 公開PyPIパッケージだけを使う再現デモで、どこまで検証できたか

## ダッシュボードより先に、状態機械を作る

Project Loop Harnessの基本ループは次の形です。

```text
Goal -> Harness -> Workflow -> Agent Jobs -> Evidence -> Verification
     -> State -> Dashboard -> Stop / Retry / Escalate
```

ここで中心にあるのはダッシュボードではなく、ガード付きの状態機械です。
実装では、次の3つを意図的に分離しました。

### SQLite: 現在状態のsystem of record

Goal、Task、Feature、Test、Evidenceなどの現在状態はSQLiteに保存します。
エージェントがSQLを直接書くことは禁止し、状態変更は`pcl`コマンドまたは内部サービス関数を通します。

これにより、たとえばGoalを閉じる処理で「証拠があるか」「完了条件を満たすか」を
同じ経路で検査できます。

### JSONL: 追記型の監査投影

状態変更ごとにイベントを残します。SQLiteが現在状態、JSONLが追記型の監査投影です。
現在状態の問い合わせをイベント再生だけに依存させず、それでも「いつ何が変わったか」を
後から追えるようにしました。

### HTML: 人間向けの生成ビュー

HTMLダッシュボードはSQLiteの状態から生成します。人間には見やすい一方、
エージェントはHTMLを状態として読みません。機械向けにはCLIのJSON出力や
`dashboard-data.json`を使います。

この境界を決めた理由は、見た目を直接編集すると、表示と実状態が簡単にずれるからです。

## 「完了」をEvidence IDへ変える

会話だけなら、エージェントは「テストが通りました」「完了しました」と言えます。
しかし次のセッションから見ると、その主張を再確認できないことがあります。

`pcl`では、テスト出力や成果物をEvidenceとして登録し、必要ならファイルをコピーして
SHA-256を固定します。

```bash
pcl evidence add \
  --file artifacts/acceptance.txt \
  --summary "受け入れコマンドがPASSした出力" \
  --command "python -m unittest discover -s tests -v" \
  --copy \
  --task T-0001
```

Taskを完了させるときは、そのEvidence IDを理由として残します。
さらに`pcl finish --emit-packet`で、設定済みチェック、strict validation、
リポジトリ状態をcompletion packetへまとめます。

```bash
pcl finish --emit-packet --goal G-0001 --json
```

今回のデモでは、packetの結果が`COMPLETED_VERIFIED`になった後、
Goalをそのpacket Evidenceへ結び付けて閉じます。

人間の承認がないのに`story approve`や`verification approved`を記録することはしません。
機械的に確認できた事実と、人間にしか決められない判断を分けるためです。

## 公開PyPI版だけで再現した

リポジトリには、v0.5.0を固定インストールして一連の完了ループを再現する
[デモスクリプト](https://github.com/mocchalera/project-loop-harness/tree/main/examples/v0.5.0-adoption-demo)
を置きました。

```bash
git clone https://github.com/mocchalera/project-loop-harness.git
cd project-loop-harness/examples/v0.5.0-adoption-demo
./run-demo.sh --keep
```

スクリプトは新しい一時ディレクトリとvenvを作り、checkout内のPythonコードではなく、
PyPIから`project-loop-harness==0.5.0`をインストールします。

その後、次を実行します。

```text
init --dry-run
  -> init / doctor
  -> 自然言語intentからGoalとTaskを作成
  -> unittestを実行
  -> 出力をコピー・SHA固定Evidenceとして登録
  -> guarded finish check
  -> COMPLETED_VERIFIED packet
  -> Goal close
  -> strict validation
  -> 日本語dashboard render
  -> next: idle
```

2026年7月14日にmacOS・Python 3.13で統合後のスクリプトを実行した結果は次のとおりでした。
時間はその環境での参考値であり、ベンチマークではありません。

```text
Ran 1 test
OK

DEMO_OK=1
PCL_VERSION=0.5.0
ACCEPTANCE_EVIDENCE_ID=E-0002
PACKET_EVIDENCE_ID=E-0004
PACKET_OUTCOME=COMPLETED_VERIFIED
NEXT_TYPE=idle
ELAPSED_SECONDS=9
```

strict validationはエラー0・警告0でした。一時ディレクトリは所有マーカーと
パスprefixの両方を確認してから削除し、失敗時は診断用に保持します。

![完了後の日本語ダッシュボード](https://raw.githubusercontent.com/mocchalera/project-loop-harness/main/docs/assets/v0.5.0-demo/dashboard-ja.png)
*実際の公開PyPI版デモから生成した画面。詳細情報は折りたたみ、人間が最初に見る5項目を上部に表示しています。*

## 既存プロジェクトへの導入はinspect-first

まず試すだけなら`pipx`を使えます。

```bash
pipx install project-loop-harness
cd /path/to/your-project
pcl init --dry-run --json
```

空でないプロジェクトでは、先にdry-runして、作成・更新・skip対象を確認します。
内容が意図どおりなら初期化し、実プロジェクトのコマンドへ`pcl.yaml`を合わせます。

```bash
pcl init
pcl doctor
pcl validate --strict
pcl render --json
```

通常の初期化では既存の`AGENTS.md`、`CLAUDE.md`、`.gitignore`を保持し、
Project Loop用のマーカー付きブロックを追加します。既存の`pcl.yaml`も
デフォルトでは置き換えません。`--force`は別の明示的なレビュー境界です。

## dogfoodで分かった、誤解しやすい点

### 初期化しただけでは「完了」を検証できない

新規生成された`pcl.yaml`のチェックは、対象プロジェクトに合わせて設定する必要があります。
テストコマンドが空なら、`pcl finish`は十分な完了証拠を作れません。

これは自動推測で危険なコマンドを実行しないための設計ですが、初見では
「initしたのにfinishできない」と感じやすい箇所です。v0.5.0では`doctor`と
`finish`の診断を具体化しましたが、導入体験としてはまだ改善余地があります。

### `doctor --strict`と`validate --strict`は役割が違う

未調整の新規プロジェクトでは、`doctor --strict`がプロジェクト名や空のチェックを
問題として扱います。一方、ライフサイクル状態に矛盾がなければ
`validate --strict`は通ります。

環境・設定の健全性と、状態遷移の整合性を同じ「strict」で呼んでいるため、
ここも説明なしでは混同されやすいと分かりました。

### HTMLは便利だが、正にはしない

人間はダッシュボードを見たくなり、エージェントにも同じHTMLを読ませたくなります。
しかし生成物を状態として扱うと、更新漏れや表示都合が機械判断へ混ざります。

そのため、HTMLは最後までhuman-only viewにし、エージェントはJSON出力とEvidenceを使います。

## v0.5.0のCouncilは実験的なopt-in

v0.5.0には、曖昧または高リスクな仕事を複数観点で検討するCouncil Profileも含まれます。
ただし、これはデフォルト経路ではありません。

- 明確な仕事はDirectがデフォルト
- Council出力は助言Evidenceであり、承認ではない
- Coreはモデルproviderを呼ばない
- 実ネットワーク・有料provider実行はCore外
- 実行には別のhash-boundな人間承認が必要

現在の判断は「デフォルト採用」ではなく「実験を続ける」です。
基本ループの導入価値を検証する前に、Councilの機能を増やさない方針にしています。

## 今回知りたいこと

v0.5.0は公開しましたが、広く使われているとは主張できません。
まず3人の初見ユーザーで、次を観察する計画です。

1. 30秒で何をするツールか説明できるか
2. dry-runから既存ファイルへの影響を判断できるか
3. 最初に価値を感じる出力は何か
4. agent-safeとhuman gateの境界が期待どおりか
5. SQLite、JSONL、HTMLの役割を説明できるか

もし小さなscratch repositoryで試せる方がいれば、最初に詰まったコマンドと
期待していた結果を教えてもらえると助かります。機密情報、認証情報、
プロジェクトの生データはIssueへ添付しないでください。

- [GitHub](https://github.com/mocchalera/project-loop-harness)
- [PyPI v0.5.0](https://pypi.org/project/project-loop-harness/0.5.0/)
- [Adoption Guide](https://github.com/mocchalera/project-loop-harness/blob/main/docs/adoption-guide.md)
- [Issues](https://github.com/mocchalera/project-loop-harness/issues)
