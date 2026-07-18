# 議論の土台: 「エージェントの目」と Project Loop Harness

| 項目 | 値 |
| --- | --- |
| 対象URL | https://x.com/akihiro_genai/status/2078360043729354955 |
| 取得手段 | Grok X thread fetch（post_id `2078360043729354955`） |
| 取得日時（作業） | 2026-07-18（セッション内） |
| 文書種別 | 議論用分析メモ（実装仕様ではない） |
| 変更境界 | 本ファイルのみ。コード・`.project-loop`・pcl状態は変更しない |

## 1. 取得できた投稿要旨

**投稿者:** 中村彰宏（`@akihiro_genai`）— bio上「Codexではじめるエージェンティックコーディング」共著、Freelance Android Developer 等
**投稿日時:** 2026-07-18 06:03:43 GMT
**engagement（取得時点）:** Likes=10, Reposts=3, Quotes=1, Replies=1, Bookmarks=3, Views=702

**本文要旨（短い引用 + 要約）:**

> 「エージェントの目をどう構築するか」

ゲーム制作では、個々の3Dオブジェクトを確認する仕組みや、動きを連続画像として閲覧する基盤を構築し、それをハーネスへ組み込むことが絵作りの品質につながる、という主張。

**自己引用（Quoted Post）:**

| 項目 | 値 |
| --- | --- |
| ID | `2076994160968814867` |
| 同一投稿者 | `@akihiro_genai` |
| 日時 | 2026-07-14 11:36:11 GMT |
| 本文 | 「FableとGPT-5.6 solに作らせたゲームが普通に楽しいし脳トレになる」 |
| メディア | 動画あり（約16.3秒、URL取得済み）。**映像内容のフレーム単位転写・音声書き起こしは本メモでは未実施** |

**会話スレッド（取得できた返信）:**

| 項目 | 値 |
| --- | --- |
| 返信ID | `2078383673637003351` |
| 投稿者 | NAO \| AI新規事業（`@nao_aifounder`） |
| 日時 | 2026-07-18 07:37:36 GMT |
| 要旨 | 「目を作るのが本体」という同じ結論。UI側では実装後に実画面スクショを撮らせて見比べさせる。ログだけだと崩れていても「できました」で終わる。作らせる仕組みより確かめさせる仕組みの方が時間がかかった。 |

**取得不能 / 未確認（推測で埋めない）:**

- 引用元動画のコマ送り内容・ゲームのジャンル・操作感・「脳トレ」の具体的意味
- 投稿者が言う「ハーネス」が特定OSS・社内ツール・一般名詞のいずれを指すか（PLHとは**名指しされていない**）
- 対象ポストへの他の引用ポスト本文の網羅（Quotes=1 はカウント取得済みだが、引用側本文は本 fetch 結果に含まれない）
- 投稿者の他スレッド・DM・Zenn記事との対応関係
- エンゲージメント数値のその後の変動

---

## 2. 出典事実 / Grok解釈 / 提案の区別

本メモは三層を混ぜない。

| 層 | 意味 | 本メモでの扱い |
| --- | --- | --- |
| **出典事実** | X取得結果、またはリポジトリ文書の記述 | そのまま引用・参照 |
| **Grok解釈** | PLH文脈への写像・類似点の読み | 仮説として明示。確定事実にしない |
| **提案** | 議論・調査の次アクション | 実装コミットではなく問いと作業案 |

**重要な境界:** Xポスト単独を「PLHがこうあるべき」の確定要件として扱わない。投稿はゲーム制作の経験談・主張であり、PLHロードマップの承認済み仕様ではない。

---

## 3. リポジトリ照合（PLH側の既存思想）

照合した主な文書:

- `AGENTS.md` / `CLAUDE.md` / `README.md` / `docs/architecture.md`
- `docs/council-profile.md`
- `docs/adaptive-policy-v1.md`
- `docs/completion-policy-v1.md`
- `docs/approval-provenance-v1.md`
- `docs/master-trace-intent-index.md`
- 補助: `docs/evidence-set-v1.md`, `docs/verification-rubric.md`

### 3.1 すでに明文化されている中核

**出典事実（リポジトリ）:**

- 中核ループ:
  `Goal -> Harness -> Workflow -> Agent Jobs -> Evidence -> Verification -> State -> Dashboard -> Stop/Retry/Escalate`
- コア製品は「きれいなダッシュボード」ではなく、**証拠に裏打ちされた状態遷移を持つガード付き状態機械**
- エージェントは SQLite / 生成HTMLを直接いじらない。変異は `pcl` 経由
- 「done」は completion packet・evidence set・verification で再レビュー可能にする
- Evidence Set は「何を知っていて、何を含み、何を外し、必須レポートが通ったか」を答える
- Completion Policy は外部レポート JSON を決定論的に評価する。**レポートの真偽そのものは外部クレーム**
- Adaptive Policy は verification depth / checkpoint / escalation 等の軸を持つ
- Council Profile は外部 runner 境界。合意は証明ではない
- Intent Index の claim は**未検証のモデル出力**であり、line-bound pointer にすぎない
- Dashboard HTML は human view。機械の状態源ではない

### 3.2 投稿と響き合う既存表現

**Grok解釈:**

- 投稿の「ログだけで『できました』」批判は、PLHが README で言う「Turn a coding agent's “done” into reviewable evidence」と同じ問題意識に見える。
- 返信の「確かめさせる仕組みの方が時間がかかった」は、PLHが harness / completion / evidence に投資してきた理由と整合する。
- `evidence-set/v1` の例に `visual_check` kind が既にある。視覚系レポートを**ドメイン固有実装なしに**受け皿として持てる設計は存在する。
- `completion-policy/v1` は「必須レポートが pass でなければ terminal にしない」ため、ログ自己申告だけで pass する経路を狭める。
- ただし PLH はゲームエンジンや 30fps キャプチャを内蔵しない。**観測パイプライン本体は外部ツール / エージェント側**であり、PLHはそれを hash-bound に記録・ゲートする側である。

---

## 4. ループ写像（投稿主張 → PLH レイヤ）

| PLHレイヤ | 投稿・返信が刺す点（Grok解釈） | 既存PLHでの近いもの |
| --- | --- | --- |
| **Goal** | 「迫力ある絵」「楽しいゲーム」など成果の質 | `pcl start` の outcome / Goal・Story としての受け入れ条件 |
| **Harness** | 「環境を構築しハーネスに組み込む」 | `pcl` runtime + policy + guarded executor。ただし投稿の「目」は runtime 拡張より**観測アダプタ**に近い |
| **Workflow** | 作る → 見る → 直すの反復を型にする | workflow templates / adaptive route（verification depth 等） |
| **Agent Jobs** | エージェントに「生成」だけでなく「確認ジョブ」を与える | agent jobs / prompts / context pack。Job に verification 手順を載せる設計 |
| **Evidence** | 3Dオブジェクト単位の確認画像、30fps連写、実画面スクショ | adhoc evidence / evidence-set / ハッシュ付き artifact。**中身のセンサは外部** |
| **Verification** | ログ判定ではなく観察可能な成果物での判定 | verification record / rubric / completion-policy predicates |
| **State** | 「できました」を状態に載せない | evidence-backed transitions、イベント追記 |
| **Dashboard** | 人が見るための一覧・進捗 | 生成HTML。**エージェントの目ではない**（明示分離） |
| **Stop/Retry/Escalate** | 観察不能・崩れているのに完了できない | incomplete evidence set / policy fail / human gate / escalate |

**一行要約（解釈）:**
投稿が言う「エージェントの目」は、PLH用語では主に **Evidence 収集基盤 + Verification ゲート** であり、Dashboard や「より賢いモデル」そのものではない。

---

## 5. 分析の切り分け

### 5.1 すでに存在する考え（PLH）

1. **自己申告完了の不信** — 証拠なし status 変更を拒否する思想が中核。
2. **生成と検証の分離** — Skill/Agent が作る、CLI が状態と検証境界を握る。
3. **観測は artifact 化し、真偽は外部クレーム** — completion-policy / evidence-set の epistemic 境界。
4. **視覚・UI検証をレポート kind として受けられる器** — 例: `visual_check`。
5. **確認コストを想定した verification depth / risk floor** — adaptive-policy。
6. **人間ゲートと provenance** — approval-provenance（誰が何の bytes を承認したか）。
7. **Dashboard を source of truth にしない** — 「見る仕組み」を人間用と機械用で分ける。

### 5.2 不足している考え（PLHが明示的に持っていない／薄い）

1. **ドメイン知覚パイプラインの標準カタログ**
   3Dオブジェクト単位インスペクト、30fps 連写→画像列、ゲームループ観測など。PLHは kind をハードコードしないが、「目の作り方」のパターンライブラリは薄い。
2. **「エージェントが自分で見て比較する」手順の一等市民化**
   返信の「スクショを撮らせて自分で見比べ」は、単なる evidence 添付を超えた **observation loop inside the job**。PLHは evidence を要求できるが、「比較プロトコル」そのものは主に Skill/Workflow 文面側。
3. **時間軸・モーション証拠**
   静止スクショ中心の UI 検証と、フレーム列による動きの検証は別クラス。contracts は拡張可能だが、モーション証拠の推奨形状は未整備。
4. **「目の構築コスト」を product metric として測る枠**
   返信の「確かめさせる仕組みの方が時間がかかった」は、採用証明や dogfood では部分的に触れるが、「observation harness の構築時間 vs 生成時間」を第一級 KPI にはしていない。
5. **ゲーム/クリエイティブ成果物向け Goal 表現**
   コーディングエージェント向けの test/story は厚いが、「絵の迫力」「楽しさ」を検証可能 claim に落とすガイドは別問題として未整理。

### 5.3 組み込むなら最小でどんな形か（提案・非実装）

実装コミット前提ではなく、**思想を壊さず足すなら**の最小候補:

| 最小形 | 内容 | なぜ最小か |
| --- | --- | --- |
| A. **Observation パターンの文書だけ** | 「目 = 外部観測コマンド + report kind + evidence-set required kind + completion predicate」の cookbook を docs に1本 | コア runtime 非変更。既存 evidence-set / completion-policy の上に乗る |
| B. **report kind 慣例の例示拡張** | `visual_check` に加え `frame_sequence_check` / `object_inspect_check` を**例**としてドキュメント化（schema 固定はしない） | ハードコード回避のまま命名共有ができる |
| C. **Job プロンプト規約** | Agent Job に「生成後の必須観測ステップ」テンプレ（capture → compare → attach → only then claim done） | Skill/workflow 文面レベル。DB migration 不要 |
| D. **Verification depth との対応表** | R2/R3/R4 で「ログのみ / 静的スクショ / 独立視覚 / 人間観察」などの推奨を adaptive-policy 解説に足す | 既存軸の説明強化。新コマンド不要 |

**PLH原則との整合チェック（解釈）:**

- 「目」を LLM 内蔵ビジョンに閉じない（vendor lock 回避）
- 観測結果は必ず copied evidence + hash
- Dashboard をエージェントの観測面にしない
- ドメインツール実行は allowlisted executor / 外部 runner。コアにゲームエンジンを入れない

### 5.4 採用しない方がよい解釈

1. **「ハーネス = より強力なモデルを積むこと」**
   投稿は環境・確認基盤の話。PLHも runtime は model-neutral。
2. **「Dashboard をエージェントに読ませて目にする」**
   リポジトリは明示的に禁止・非推奨。HTML は human-only view。
3. **「30fps 連写機能を `pcl` コアに実装すべき」**
   投稿の具体例をコア機能化すると、local / dependency-light / domain-agnostic の境界を破る。
4. **「X投稿は PLH がゲーム制作ツールになると宣言している」**
   投稿は PLH を名指ししていない。ゲーム制作は応用領域の一例。
5. **「スクショがあれば完了」**
   画像の存在 ≠ 受け入れ条件充足。completion-policy が言う通り、レポート真偽は別問題。比較プロトコルと predicate が要る。
6. **「Council の多数決が視覚品質の証明になる」**
   council-profile 自身が agreement ≠ proof と明記。

### 5.5 検証すべき仮説

| ID | 仮説 | 検証の仕方（実装なし） |
| --- | --- | --- |
| H1 | 投稿の「ハーネス」は一般的 agent harness 概念であり、特定製品（PLH含む）の機能要求ではない | 投稿者の周辺ポスト・記事で「ハーネス」用法を追加収集 |
| H2 | 「エージェントの目」の本質はセンサー種類（3D/UI）ではなく、**完了ゲートを観察可能成果物に結びつけること** | UI dogfood（スクショ必須）とゲーム観測の失敗モードを比較 |
| H3 | PLH の evidence-set + completion-policy だけで、外部の frame-sequence レポートを terminal gate に使える | フィクスチャ JSON と read-only `completion evaluate` の机上/オフライン検証 |
| H4 | 現場コストの大半は観測基盤構築に移る（返信の主張の一般化） | dogfood / adoption-observation の時間内訳を再分類して観察 |
| H5 | エージェント自己比較は、独立 verification や human review を代替しない | adaptive risk floor（R2+）との関係をポリシー文章で collate |

### 5.6 議論で決める問い

1. PLH は「目」を **コア責務**（観測パイプライン提供）と見るか、**アダプタ責務**（外部観測の記録・ゲート）と見るか？
2. 視覚/モーション証拠を first-class にするなら、契約はどこまで？（kind 慣例のみ / 軽量 schema / Profile pack）
3. 「エージェント自身の見比べ」を verification に数える条件は何か？（self-check vs independent check）
4. ゲーム/クリエイティブ Goal の受け入れ条件を Story/Test に落とす標準ガイドを作るか？
5. 採用証明や dogfood で「observation harness 構築時間」を測る指標を追加するか？
6. 投稿・返信を外部フィードバックとして `docs/feedback/` に正規保存するか、research メモのままで足りるか？

---

## 6. 中心結論（議論用・非確定）

1. **出典事実:** 投稿はゲーム制作における「エージェントの目（観察可能な確認基盤）をハーネスに組み込む」ことの重要性を主張し、返信は UI でも「確かめさせる仕組み」が本体だと同調している。
2. **Grok解釈:** これは PLH の Evidence → Verification → State の思想と強く共鳴する。投稿の具体手段（3Dインスペクト、30fps連写）は **応用ドメインの観測アダプタ例** であり、PLHコア機能要求そのものではない。
3. **提案方向:** 次に議論すべきは新機能実装より、「目 = 外部観測 + hash-bound evidence + completion gate + job内比較手順」という最小パターンを文書・慣例として共有するか否か。

---

## 7. 推奨する次の一歩（実装を伴わない、最大3件）

1. **投稿者周辺の「ハーネス／目」用法の追加収集（調査）**
   同一アカウントの関連ポスト・引用・記事を数本読み、「ハーネス」が一般論か特定ツール論か、観測対象（3D/UI/ログ）の射程を確認する。成果は本メモへの追記か `docs/feedback/` への一次ソース整理。

2. **既存契約への机上マッピング（設計照合）**
   架空の `frame_sequence_check` / `object_inspect_check` レポートを、`evidence-report-manifest/v1` → `evidence-set/v1` → `completion-policy/v1` に通すシーケンスを1ページで書く。**コード変更なし**で「足りる / 足りない」を判定する。

3. **Observation Job テンプレの草案レビュー（設計議論）**
   「capture → self-compare → attach evidence → only then claim done → independent/human gate」を Skill/Workflow 文面レベルのチェックリスト草案にし、adaptive-policy の verification depth と対応づける。実装・コマンド追加はしない。

---

## 付録 A. 取得メタデータ（出典事実）

```text
main_post_id: 2078360043729354955
author: @akihiro_genai
created_utc: 2026-07-18T06:03:43Z
quoted_post_id: 2076994160968814867
quoted_created_utc: 2026-07-14T11:36:11Z
reply_post_id: 2078383673637003351
reply_author: @nao_aifounder
reply_created_utc: 2026-07-18T07:37:36Z
video_on_quoted_post: yes (duration ~16275 ms)
plh_named_in_posts: no (not observed in retrieved text)
```

## 付録 B. 用語の仮対応表（解釈・議論用）

| 投稿側の言い方 | PLH側の近い概念 | ずれる点 |
| --- | --- | --- |
| エージェントの目 | Evidence 収集 + 観測手順 | センサー実装は PLH 外 |
| ハーネスに組み込む | workflow/job/policy に観測ゲートを載せる | 投稿の「ハーネス」外延は未確定 |
| 3Dオブジェクト確認 / 30fps連写 | ドメイン別 report artifacts | コア非搭載が原則 |
| ログだけでできた | evidence なき done claim | PLHはこれを拒否する設計 |
| 確かめさせる仕組み | verification / completion-policy / human gate | 自前比較 vs 独立検証の区別が要る |
| 迫力ある絵作り | Goal/Story の受け入れ品質 | 主観品質の operationalization が未整備 |
