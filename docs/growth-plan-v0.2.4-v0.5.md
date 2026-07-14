# Project Loop Harness 成長計画 v0.2.4 → v0.5.0

**作成日:** 2026-07-08
**作成者:** Fable 5（orchestrator）
**入力:** docs/project-loop-harness-v0.2.3-third-party-review.md（第三者レビュー提言書）+ 実コード検証 + ax1-moc1 実使用フィードバック + 引き継ぎ履歴
**ステータス:** APPROVED — 坂本承認済み（2026-07-08）

---

## 0. 第三者レビューの精査結果

レビューは「ローカル clone・テスト実行なし」と明記しているため、事実主張を実コード（v0.2.3 = main HEAD 0a6c1c2）で検証した。

| レビュー主張 | 検証結果 |
|---|---|
| P1-1: `source_drifted` が warning codes に含まれず health が `ok` のまま | **事実**。`src/pcl/evidence.py:36` の `ADHOC_WARNING_FINDING_CODES` に `source_drifted` がない。findings は生成される（evidence.py:577-597）が `_adhoc_assessment` は ok を返す |
| P1-2: SECURITY.md が `0.1.x` のまま | **事実**。SECURITY.md:8 |
| P2-1: CI が Python 3.11 単独 vs classifiers 3.10–3.13 | **事実**。ci.yml:14 vs pyproject.toml:22-25 |
| P2-3: code context receipt が target-bound でない | **事実**（0078 実装は latest receipt 解決。binding metadata なし） |
| 提案タスク採番 PLH-0101〜0110 | **衝突**。agent-tasks/0100・0101 は既に使用済み → 本計画では 0102〜 に再採番 |

レビューの方向性判断（local control plane 特化、hosted/telemetry/LLM-in-core の回避、Trust Patch 最優先）は、既存の承認済み方針（2026-07-04 方向性決定、0097 設計、epistemic 語彙規律）と整合しており採用する。

**採用しない/修正する点:**

1. **ユーザー満足度の軸が弱い。** レビューは trust / context binding に集中しており、実ユーザー（ax1-moc1）から出た摩擦 F4/F5/F7、坂本の「人間判断の日本語化・わかりやすい escalation」要望（Milestone 13）に触れていない。本計画では Operator Experience リリースを Master Trace 形式化より前に挿入する。
2. **Master Trace は「新規構想」ではない。** docs/master-trace-handoff.md（M0）が既に存在し、既存コマンドだけで動く。v0.3.x での作業は発明ではなく契約の形式化 + context pack への optional section 追加に縮小できる。
3. **コスト計測の解像度。** レビューの成功指標（§13）にコスト軸を追加する（後述 §5）。charclass/v1 token 推定器・0090 の token_cost_estimate という既存資産を handoff 経済の計測に転用する。

---

## 1. 戦略テーゼ — なぜこの製品が「これからの世界」で効くか

前提とする世界観: **モデル性能は上がり続け、コスト管理は厳しくなり続ける。**

### テーゼ1: 生成はコモディティ化し、信頼が希少資源になる

モデルが賢くなるほど、agent が生み出す「主張」の量は増える。ボトルネックは生成ではなく **検証・監査・引き継ぎの信頼** に移る。PLH は生成の側に立たず（core は LLM を呼ばない）、claims-not-facts・evidence・receipt という検証の側に立つ。この設計はモデル進化に対して中立であり、worker が賢くなるほど pull-context 方式の効率が上がる — つまり **モデル性能向上がそのまま PLH の価値を増幅する**。

### テーゼ2: output token が最も高価な世界では、push 型長文指示書が最大の浪費

高性能 master agent に長文指示書を書かせるのは、最も高価な token（高性能モデルの output）の最も低付加価値な使い方である。PLH の pull 型 handoff（master transcript → evidence → intent-index → context pack → worker が pull）は、この支出を構造的に消す。さらに PLH 自体の限界トークンコストはゼロ（local / deterministic / dependency-light）。**コスト厳格化が進むほど、この差別化は強くなる。**

### テーゼ3: 検証支出にも予算規律が要る

「全部を毎回検証する」は賢いモデルの世界でもコスト的に成立しない。migration 005 の verification feedback loop（execution_rate / executed_pass_rate）は「どの検証提案が実行され、何が通ったか」を計測する基盤であり、検証支出の配分最適化に直結する。dogfood でこの数値を貯めることが v0.4 の本丸。

### テーゼ4: ユーザー満足度は「境界の賢さ」と「摩擦の少なさ」で決まる

実ユーザーの声が既にある: human gate（requires_human）は称賛され、epistemic 境界を弱める要望はゼロだった。一方で摩擦は「終端処理の認知負荷が実装より重い」（F7）、human-gate handoff 文面（F5）、オール英語表記。**満足度の最短経路は境界を緩めることではなく、境界の手前と後ろの体験を磨くこと**である。

### ターゲットペインの再確認

理想ユーザー = 複数 AI エージェントを指揮する AI 開発パワーユーザー / AI プロダクトオーナー（坂本さん自身）。ペインは:

```text
忘却     — agent が文脈・決定・却下案を忘れる / 拾い間違える
暴走     — 承認なき破壊的操作、スコープ逸脱
証拠不足 — 「done」の根拠が辿れない、レビュー不能
高コスト — master の長文指示書、無駄な再検証、handoff やり直し
終端負荷 — 完了処理・引き継ぎ処理の認知コストが人間に残る
```

PLH の一文: **AI coding agent に、忘れず・暴走せず・証拠を残して・次にやることを判断させるための local control plane。** — この定義（レビュー §4.1）を README / PyPI / 冒頭ピッチの正とする。

---

## 2. 品質 × コスト × 満足度のマッピング

| リリース | 品質 | コスト | 満足度 |
|---|---|---|---|
| v0.2.4 Trust Patch | evidence 意味論の正しさ、CI 実証範囲 | copy lock 観測（並列 agent の待ち時間削減の前提データ） | 「表示が嘘をつかない」信頼 |
| v0.3.0 Target-Bound Context | 誤 receipt による誤修正の防止 | handoff やり直しの削減 | worker への引き継ぎ不安の解消 |
| v0.3.1 Operator Experience | human gate 判断品質（why_blocked の ja 化） | 終端処理の master token 削減（F7） | **本丸**: F5/F7/ja、坂本の願いに直結 |
| v0.3.2 Master Trace / Intent Index | intent-index の claims-not-facts 契約、AI-PLC 的 Collection の最小翻訳 | **本丸**: master output token の構造的削減 | 長文指示書からの解放 |
| v0.4.0 Dogfood Operations | 実測に基づく信頼性実証、first-class Intent 化の判断材料 | コスト KPI の実測値（テーゼの証明） | 実運用 runbook |
| v0.4.1 Integrity Migration | 既存projectを強いlifecycle invariantへ移行 | false completionの修復往復を削減 | 具体的なrepair guidance |
| v0.4.2 Adaptive Entry | immutable briefと説明可能なroute/policy | 曖昧タスクの過剰workflowを抑制 | 推奨理由とoverride監査 |
| v0.4.3 Evidence Completeness | positive evidence cherry-pickと外部完成判定の不整合を防止 | 不完全成果の再レビューを削減 | skill間でpassing/completeの意味が一致 |
| v0.5.0 Council + Adoption | Councilのclaim/proof分離とhuman gate、別trackの契約安定性 | Council overheadとreview時間を実測 | 曖昧タスクの手戻り低減 + 初見3分で価値理解 |

---

## 3. ロードマップ

レビュー §8 を土台に、順序を 1 箇所変更（Operator Experience を Master Trace 形式化より前に挿入）し、実リポジトリの採番・既存資産に合わせて調整した。

### v0.2.4 Trust Patch（最優先・小粒）

目的: v0.2.3 の evidence durability を「表示が嘘をつかない」状態に固める。

| タスク | 内容 | 由来 | サイズ |
|---|---|---|---|
| 0102 | `source_drifted` health 修正 — 短期は `ADHOC_WARNING_FINDING_CODES` への追加 + missing / size_mismatch テスト固定。artifact_health / source_health 分離は論点として温存（§6 論点2） | レビュー P1-1（検証済み事実） | S |
| 0103 | SECURITY.md v0.2.x 更新 + copied evidence 機密リスク・commit policy・MCP exposure 明記 + release checklist に version check 追加 | レビュー P1-2（検証済み事実） | S |
| 0104 | Python 3.10–3.13 CI matrix（pytest + smoke: `pcl --version` / `init` / `validate --strict --json` / `render --json`。build/twine は 3.12 単独） | レビュー P2-1（検証済み事実） | S |
| 0105 | evidence copy observability — copy duration / copied bytes / member count を event metadata に、concurrent copy stress test。reserved-row / counter 方式への変更はしない（観測が先） | レビュー P2-2 | S-M |
| 0106 | `docs/release-checklist.md` — 既存リリース手順（trusted publishing / fresh venv smoke / sdist contract / editable 指し先確認の罠を含む）を契約化 | レビュー PLH-0108 | S |
| 0107 | `agent-tasks/README.md` — ID / status / milestone / priority の backlog index（orchestrator 執筆で可） | レビュー PLH-0109 | S |

成功条件: source drift が warning 表示 / SECURITY.md 整合 / 3.10–3.13 matrix green / checklist に沿って v0.2.4 をリリース。

### v0.3.0 Target-Bound Context

目的: context pack を agent handoff の信頼できる契約に進化させる。「便利な CLI」から「handoff の制御層」への転換点。

| タスク | 内容 | サイズ |
|---|---|---|
| 0108 | target-bound code context receipts — `pcl impact --diff --for-task T-XXXX / --for-job J-XXXX`、receipt に binding metadata（target_type / target_id / binding_strength）、`context pack --require-bound-receipt`、unbound latest fallback は warning | M-L |

設計上の注意: receipt 契約は `code-context-summary/v0` 絶縁層（0078 承認済み設計）を崩さず additive に拡張する。staleness（working_tree_changed_since_receipt / receipt_age_seconds）は 0082 の relevance / receipt_age 資産を再利用。

### v0.3.1 Operator Experience（レビューにない追加リリース）

目的: 実ユーザーが表明した摩擦と坂本の願い（人間に判りやすい escalation）を潰す。満足度の本丸であり、F7 は master token 削減というコスト施策でもある。

| タスク | 内容 | 由来 | サイズ |
|---|---|---|---|
| 0119 | `pcl context check` read-only preflight — target-bound receipt / supporting evidence の事前確認 | third-party review + v0.3.0 deferred item | M |
| 0120 | `pcl finish` terminal close-out planner — 終端処理を計画し、safe generation tail のみ実行 | ax1-moc1 F7（最重要摩擦） | M-L |
| 0121 | human-gate handoff 文面改善 + ja ガイダンス — `pcl next` の human decision branch を日本語補助 | ax1-moc1 F5 + Milestone 13 + 坂本要望 | M |
| 0122 | feature_coverage 既存カバレッジ検出で no-op | ax1-moc1 F4 | M |

状態: v0.3.1 として出荷済み。旧計画の 0109/0110/0111 予約は、実採番
0119〜0122 で置き換えた。

### v0.3.2 Master Trace / Intent Index v0 形式化

目的: 既存の M0 dogfood ワークフロー（docs/master-trace-handoff.md）を契約に昇格し、pull 型 handoff のコスト優位を製品機能にする。

| タスク | 内容 | サイズ |
|---|---|---|
| 0123 | `master-trace/v0` + `intent-index/v0` 契約 docs。M0 runbook を歴史的 dogfood として整理し、現在の `pcl evidence add --task --copy` / `pcl context pack` で実行できる command sequence と trust model を明文化する。LLM 呼び出しは core に入れない。raw transcript の inline 禁止 | S-M |
| 0124 候補 | context pack への optional `master_trace_context` section（trace_evidence_id / intent_index_evidence_id / trust_model: claims-not-facts / raw_transcript_inlined: false / source_paths）。0123 の契約受け入れ後に切る | M |

first-class trace entity 化と `pcl intent` / `pcl collect` は v0.4 dogfood の
結果を見てから判断する（レビュー論点4 と同意見 — 早すぎる抽象化を避ける）。

### v0.4.0 Dogfood Operations

目的: テーゼ 2・3 を実測で証明する。機能追加より計測を優先。

- PLH 自身 + 外部 repo（ax1-moc1 継続 or 新規）の 2 repo dogfood report（`docs/dogfood-report-v0.4.md`）
- **コスト KPI の実測**: master_brief_tokens_saved（pull 型 vs push 型の比較実測）、average_context_pack_tokens、finish による終端 round-trip 削減数
- verification feedback の実データ: execution_rate / executed_pass_rate / feedback_coverage_rate
- handoff KPI: worker_handoff_success_rate / handoff_confusion_count / bound_receipt_coverage
- AI-PLC upstream intake の dogfood: 2 repo で master-trace / intent-index を
  evidence-linked handoff として使い、`pcl intent` / `pcl collect` を
  first-class entity 化するだけの反復需要があるかを測る
- Codex / Claude Code handoff runbook
- **公開前RC2 Integrity Gate**: 実タスクdogfoodで確認されたfalse completionを
  release blockerとして修復する。Skill/CLI contract parity、Evidence ID first、
  Test/Feature/Goal terminal mutation guard、target-bound completed packetによる
  direct Goal closure、fail-open check rejectionをschema 8のまま実装する。

### v0.4.1 Integrity Migration

v0.4.0で新規false completionを作れなくした後、既存projectを安全に強い
invariantへ移行する。

- redundantなidle human gateを廃止し、明示intentは`pcl start`へ渡す（0141）;
- read-only lifecycle repair plannerとdedicated link repair command;
- structured validation findingと具体的repair command;
- Skill/runtime provenance receipt;
- lifecycle integrity findingをadvisoryからenforcedへ昇格する前のdogfood。

### v0.4.2 Adaptive Entry

従来v0.4.1に予定していたwork brief v1、deterministic route
recommendation、multi-axis policy、explain/overrideは、Integrity Migrationの
後に実施する。適応ルーティングより完了判定の信頼性を優先する。

2026-07-11にWave Cを活性化した。canonical実装順は、0146 immutable Work
Brief Evidence、0147 read-only route recommendation、0148 JSON policy
resolve/explain、0149 explicit audited override、0149a dogfood、0149b release
preparationとする。proposalのWork Brief必須`route`は入力/出力循環を作るため
採用せず、route recommendationを別artifactへ分離する。承認はimmutable briefの
本文を書き換えず、Evidence hashへ結びつくeventとして記録する。詳細は
`docs/plan-v0.4.2.md`を正とする。

2026-07-11に0146–0149を実装し、0149aの二repository dogfoodを人間が承認、
0149bでversion 0.4.2のlocal RC、release note、wheel/sdist、clean-install、
artifact hashを準備した。tag/push/GitHub Release/PyPI publicationは別の明示操作とする。

### v0.4.3 Evidence Completeness

Cockpit task `cb004add` のLP制作dogfoodでは、レスポンシブ/ページフロー等は
passした一方、厳密なカンプ座標比較は6/17（35.3%）で、外部スキルは成果を
`prototype`と判定した。しかしPCLでは選択されたpositive EvidenceだけでTest/
Featureが`passing`になり、`pcl next`もidleになり得た。これはEvidenceの耐久性
ではなく、Evidence集合の完全性とskill間の完成語彙の不整合である。観察記録は
`docs/dogfood/lp-production-cross-skill-review.md`を正とする。

v0.4.3は0150 evidence-set completeness、0151 generic completion-policy /
terminal preflight、0152 unfinished-work routing / approval provenance、0153
cross-skill dogfood / Skill parity / human review、0153b local release
preparationの順に完了した。coreは
`mockup-to-code`やWeb固有thresholdをhard-codeせず、明示work root・manifest・
JSON predicateに限定した汎用adapterを提供する。Motion Phase、crop pair、detail
inventory、visual line countは外部skill側の改善依存として分離する。詳細は
`docs/plan-v0.4.3.md`を正とする。2026-07-11にlocal RCを準備した。publicationは
別の明示操作とする。

### v0.5.0 Adoption / Distribution

- Council Profile: contract-first, built-in-only Discovery boundary with
  read-only request preparation, fail-closed bundle validation, atomic Evidence
  ingest, and existing human Decisions. The canonical dispatch is 0154–0162 in
  `docs/plan-v0.5.0-council-profile.md`.
- Provider/model execution remains a separate runner and separate approval;
  PLH Core does not gain SDKs, credentials, network calls, or model ranking.
- Council 0154–0162 is a feature track. The following Adoption/Distribution
  items form a separate release-readiness track with separately numbered tasks;
  both tracks must close before publication, but they do not share one Feature
  DoD.
- README split（レビュー PLH-0107 準拠: 30 秒ピッチ + 3 分 quickstart + docs/operator-manual.md / contracts.md / agent-handoff.md / internals.md へ分離）
- JSON contract stability policy（論点3 の決定を文書化）
- examples/ + Codex / Claude Code quickstart + `.project-loop` commit policy
- 上流設計レイヤーの採用判断: `pcl intent` / `pcl collect` / `pcl option`
  / `pcl replan` をどの milestone に切るかを、v0.4 dogfood 指標で決める
- **v0.4 の実測数値を README の訴求に使う**（「master の指示書 token を X% 削減」— 実測が最強のマーケティング）

---

## 4. やらないこと（レビュー §3.4 を承認済み方針として再確認）

hosted backend / cloud sync / marketplace / telemetry / multi-user collaboration / 複雑な自動 scheduler / dashboard の過剰リッチ化 / core からの LLM API 呼び出し。

追加: semantic search / embeddings の昇格は既存ゲート（eval fixture で lexical チューニング後も missing-critical-context が改善しない場合のみ）を維持。

---

## 5. 成功指標

レビュー §13 の 4 分類（handoff / evidence 信頼性 / context pack 品質 / release 品質）を採用し、コスト軸を追加する。

| コスト指標 | 意味 | 計測手段 |
|---|---|---|
| master_brief_tokens_saved | pull 型 handoff で master が書かずに済んだ output token | charclass/v1 推定器で transcript vs 従来指示書を比較 |
| average_context_pack_tokens | handoff 1 回あたりの入力コスト | pack の token 推定（既存） |
| finish_roundtrips_saved | `pcl finish` による終端コマンド往復削減数 | dogfood 実測 |
| verification_spend_efficiency | executed_pass_rate × execution_rate（実行された検証が意味を持った割合） | migration 005 stats |
| bound_receipt_coverage | 誤 context による手戻り（最も高価な失敗）の予防率 | v0.3.0 以降の pack 統計 |

---

## 6. 坂本の決定が必要な論点

1. **ロードマップ順序**: Operator Experience（v0.3.1）を Master Trace 形式化（v0.3.2）より前に挿入する変更を承認するか。（推奨: 承認。F7 は実ユーザー最重要摩擦かつ M0 ワークフローは形式化前でも dogfood 可能）
2. **evidence health の形**: 短期は `source_drifted` を warning codes に追加（0102）。中期の artifact_health / source_health 分離は additive contract 変更として v0.3.x で再検討。（推奨: 短期案のみ先行、分離は dogfood の source_drift_rate 実測後）
3. **ID gap 許容**（レビュー論点2）: 現状維持し、0105 の観測データで判断。（推奨: 現状維持）
4. **`.project-loop` commit policy**（レビュー論点5）: evidence/adhoc-files は commit しない現状を SECURITY.md（0103）に明文化。project.db / events.jsonl の扱いは v0.5.0 までに決定。
5. **v0.2.4 リリース範囲**: 0102–0107 の 6 本で切るか。

---

## 7. 実行計画（Cockpit 委譲）

実装は従来どおり codex worker（cockpit task、worktree 分離）へ委譲し、Fable が spec 起票と独立検収を行う。

```text
順序:
  0103 + 0104 + 0107   並行可（互いに独立、S サイズ）
  0102 → 0105          evidence.py を触るため直列
  0106                 リリース直前に Fable 執筆でも可
検収規律（確立済み）:
  - spec は worker 着手前に main へコミット（0078 の教訓）
  - 不変条件は「何を守るか」を正規経路・対象スコープ付きで書く（0087/0089/0090 の教訓）
  - 検収は PYTHONPATH=worktree/src、終了後 canonical repo で pip install -e '.[dev]' 復元
  - worker task complete 前に editable の指し先確認（v0.2.1 の罠）
```

v0.2.4 は全タスク S〜S-M のため、承認後 1〜2 セッションでリリース可能な見込み。

---

## 8. v0.3.0 スコープ確定（2026-07-08 追加承認）

v0.2.4 リリース後、第三者の v0.2.4 レビュー（v0.3 道筋提案）を実コードで検証し、
坂本が以下を承認した。§6 の論点1・2 に対する確定判断を含む。

**承認（v0.3.0 に入れる）:**

1. **migration 007 `evidence_links` を v0.3.0 で導入**（論点1の決着）。汎用
   `evidence_links(evidence_id, target_type, target_id, link_role, created_at)`
   テーブル + 既存 `linked_task_id` の backfill。判断根拠: v0.3.0 が `code_context`
   という2つ目の link role を導入し、v0.3.2 master-trace が3つ目を足すため、単一
   `linked_task_id` 列では role を表現できない。artifact-only にすると receipt 選択が
   artifact scan になり evidence_links 導入時に捨てるコードになる。近い将来の consumer
   が3つ（code_context / master-trace / v0.4 KPI）確実なため rework を回避する。→ **0113**
2. **0108 の no-migration invariant を撤回・改訂**。binding は `evidence_links`
   の `code_context` role 行（queryable）+ receipt artifact の `target_binding`
   （self-describing）に二重記録し、選択は SQL クエリにする。→ **0108 改訂済み**
3. **source-hash drift を default-on で修正**（論点2の決着）。`evidence.py:598` の
   size 一致時に source sha256 を `expected_sha256` と比較し `hash_mismatch` を出す。
   `--deep` は入れない（size gate + 10MB cap でコスト有界）。→ **0114**
4. **context pack contract fixtures を必須で入れる**。0108 が pack 契約を変えるため、
   6ケース（no-receipt / unscoped / task-bound / job-bound / stale / require-missing）
   を fixture で凍結。0087/0089/0090 の契約回帰3連発への恒久対策。→ **0115**

**保留（後続リリースへ）:**

- `pcl context check` preflight → **v0.3.1**（0119）として出荷済み。
- `pcl finish`（F7）→ **v0.3.1**（0120）、human-gate ja（F5）→ **v0.3.1**
  （0121）、feature_coverage no-op（F4）→ **v0.3.1**（0122）として出荷済み。
- master-trace / intent-index 形式化 → **v0.3.2**（0123）。first-class trace
  entity 化は v0.4 dogfood の結果を見てから。

**論点3（binding_strength 語彙）** は 0108 spec が既に `none` / `caller_asserted`
のみで実装しており（claims-not-facts、`safe_to_continue` 等禁止）、追加作業なし。

**dispatch 順:** 0113 + 0114 並行（独立、`evidence.py` の別関数面）→ 0108（0113
マージ後）→ 0115（0108 契約確定後）。検収規律は §7 と同一。migration 007 は
`require_human_approval: database_migration` を本承認で充足。

---

## 9. AI-PLC 上流設計思想の取り込み方（2026-07-09 追加）

AI-PLC の価値は、実装 executor ではなく Goal 前の Collection、Intent、
発散、収束、Backtrack、知見伝播にある。PLH に取り込む場合は、AI-PLC の
Markdown/スラッシュコマンドを移植せず、PLH の CLI、SQLite、JSONL、
Evidence、Validation、Context Pack に翻訳する。

取り込み順は以下で固定する。

1. **v0.3.2: Collection の最小翻訳。** `master-trace/v0` と
   `intent-index/v0` を evidence-backed contract として formalize する
   （0123）。これは `pcl intent` ではない。外部 agent が作った
   intent-index を claims-not-facts の navigation artifact として扱う。
2. **v0.4.0: Dogfood で反復需要を測る。** 2 repo 以上で
   master-trace / intent-index handoff を使い、handoff 成功率、混乱回数、
   master_brief_tokens_saved、bound_receipt_coverage を見る。
3. **v0.4.x: first-class Intent / Collection の設計判断。** dogfood で
   反復需要が出た場合だけ、`pcl intent create/show/approve` と
   `pcl collect receipt show` を設計する。DB migration を含む場合は
   human approval を再取得する。
4. **その後: Option / Replan / Knowledge。** `pcl option` は既存
   `pcl decision` lifecycle に接続し、独立した decision table を重複させない。
   `pcl replan` は `pcl next` の優先順位に入るため、Intent/Option の戻り先が
   できてから切る。Knowledge Ledger は DB source-of-truth + Markdown export の
   形に限定する。

maker != checker は Intent 系とは独立に進められるが、最初は
`validate --strict` または project config の policy として始める。自動で
human-gated verification を承認する挙動は入れない。

---

## 10. 統合ロードマップの採用（2026-07-10 追加 — Status: Active with integrated amendments）

`docs/roadmap/integrated/` の統合ロードマップ bundle（2026-07-09 基準）を
**Accept with modifications** で採用した（坂本承認 2026-07-10）。本計画は
supersede されず、以下の amendments 付きで Active を維持する。決定記録・
再採番マップ・最小合意 4 点の判断は `docs/roadmap/integrated/ADOPTION.md` を正とする。

**Amendments の要点:**

1. **v0.3.2 = Master Trace / Intent Index 契約形式化（0123）は変更なし**。
   bundle が M6 へ先送りする案は不採用（D-08）。Wave A と並行実行する。
2. **v0.3.3 = Trust Foundation（bundle M1）を新設**: MCP 仕様準拠
   （0125–0126）、transactional audit outbox（0127–0129）、crash/concurrency
   suite（0130）、guarded executor hardening（0131）。根拠は実コードで検証済み
   の 2 欠陥（`mcp_server.py` の Content-Length framing + version echo、
   `events.py` の非原子的 dual-write）。
3. **0124 = v0.3.1 baseline fixtures**（bundle 0123 の縮小版）を Wave A の
   起点にする。
4. コスト KPI 実測は v0.4.0 Dogfood Operations の位置を維持（テーゼ2 の
   証明を後退させない）。
5. Wave B 以降は
   `docs/roadmap/integrated/agent-tasks-proposed/` の proposal に留め、
   wave 承認ごとに再採番して活性化する。Three-command wedgeとadaptive
   policyはv0.4で完了し、Discovery Profileは2026-07-12にv0.5.0として
   0154–0162へ活性化した。後続proposalのversion labelはmilestone reviewで
   exit条件優先で決める。

## 11. v0.5.0 Adoption / Distribution 優先化（2026-07-13）

Cockpit task `524a3d14` のビジネス・技術レビューと、0162 の人間判断
`continue experiment` を受け、追加Council機能とv0.5.1 Traceより先に
Adoption / Distributionを進める。

1. **P0 0163:** READMEを30秒価値説明、5分セットアップ、詳細リファレンスの
   3層へ変更し、セットアップ後はroutine CLIをagentが担う導線を固定する。
2. **P0:** 既存`AGENTS.md`、`CLAUDE.md`、`.gitignore`、`pcl.yaml`との共存境界と
   alpha stability policyを公開契約として説明する。
3. **P0:** 日付依存テスト、Project Loop警告、task index、release surfaceを整流し、
   local v0.5.0 RCをsource/wheel/sdistで検証する。
4. **P1:** demoと一次発信原稿を準備する。公開は別の人間承認を要する。
5. **P1/P2:** CLI分割、dev-env check、scale/event-log方針は、Adoption evidenceに
   基づいて順番を決める。

Councilはopt-inのまま維持する。実provider、paid/network、telemetry、default
変更、公開は本優先化に含めない。正規の並びとexit条件は
`docs/roadmap/priority-reset-2026-07-13.md`を参照する。

2026-07-14に0173でlocal RCを準備し、別途承認された公開後、0174でrelease
commit、GitHub Release、Actions、PyPI artifacts、clean public installをread-only
再検証した。v0.5.0は公開済みであり、次は外部feedback launch packetである。
投稿、real-provider実行、telemetryは引き続き個別の人間承認を要する。
