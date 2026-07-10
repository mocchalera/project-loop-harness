# 統合版エグゼクティブ・ロードマップ

## 1. 経営・製品判断

PLHは「汎用AIエージェント」や「新しいIDE」を目指さない。狙うべきカテゴリーは次である。

> **coding agentが出した「完了」を、再現可能な証拠、残存リスク、次の安全な一手、別agentへ渡せるhandoffへ変換する、モデル非依存・ローカルファーストの制御層。**

AI-PLCからは、Collection、発散と収束、Backtrack、maker≠checker、Adaptive Depth、Knowledge Propagationを取り入れる。ただし、PLH coreへ新しい業務エンティティを大量追加しない。上流思考はオプションのDiscovery Profileとして実装し、coreは状態・監査・Evidence・Verification・Policy・Completion・Handoffに集中する。

## 2. 対象ユーザー

### 最初のターゲット

同じリポジトリでClaude Code、Codex、Copilot、Aider、ローカルモデルなどを使い分ける個人開発者と小規模チーム。

主な痛みは次である。

- agentの「完了」が、本当にテスト済みか分からない。
- sessionが切れると、意思決定、未検証事項、次の一手が消える。
- 別モデルへ渡すたびに、同じコードと会話を再読させてコストが増える。
- 弱いモデルではスコープ逸脱・検証漏れが増え、強いモデルだけに頼ると費用が高い。
- AI生成PRをレビューするとき、生成コードより「何を確認したか」が分からない。

### 後続ターゲット

- AI生成PRをレビューするmaintainer。
- 複数agentを運用するチームリード。
- 監査・再現性が必要な内製開発チーム。

### 今は狙わない範囲

- 汎用agent runtime。
- hosted cloud execution platform。
- IDE、チャットUI、タスク管理SaaSの置き換え。
- 本格的なOS isolation sandbox。
- あらゆる職種向けの汎用AI-PM。

実装は横断的に保ちつつ、売り方と初期テンプレートはcoding agentへ絞る。

## 3. 製品の3本柱

### Prove Done

変更、実行したcheck、exit code、artifact、証拠hash、検証済みclaim、未検証claim、残存riskをcompletion packetにする。

### Resume Anywhere

会話履歴全体を送らず、目的、現在状態、意思決定、証拠、blocker、次の安全な一手をhandoff packetにする。

### Adapt Control

変更リスク、要求の曖昧さ、モデル能力、予算に応じ、計画の深さ、検証の深さ、実行粒度、checkpoint頻度、context budgetを変える。

## 4. 統合原則

1. **モデルなしでもcoreが機能する。** LLM呼び出しはadapterまたはProfile側に置く。
2. **モデル出力はclaimでありfactではない。** Evidenceとdeterministic checkが別に必要。
3. **変更riskが検証深度を決め、モデル能力が手順の細かさを決める。** 強いモデルだから検証を省かない。
4. **明確な仕事ではPLHが見えなくなる。** 初回導線は`start → finish → resume`。
5. **曖昧な仕事にだけDiscoveryを挿入する。** 全タスクへ4段階工程を強制しない。
6. **契約を先に試し、エンティティは後から昇格する。** Artifact → Event → Tableの順。
7. **状態変更は明示的、inspectionはread-only。** fallback、override、budget exhaustionを黙って処理しない。
8. **疑似精度を避ける。** Optionの1〜10点を事実扱いせず、前提、根拠、不確実性、可逆性を記録する。
9. **source of truthを一つにする。** SQLiteとJSONLの役割を明文化し、クラッシュ後にreconcileできる。
10. **外部相互運用性は宣言ではなく適合試験で証明する。** MCP等は実クライアントで確認する。

## 5. マイルストーン

バージョン番号は提案であり、承認時にリリース責任者が最終決定する。マイルストーンのExit条件をバージョン番号より優先する。

| ID | 提案リリース | 目的 | 主な成果 | Exit条件 |
|---|---|---|---|---|
| M0 | v0.3.1 | 現在地を固定 | `0122`までをrelease、contract fixtureとbaselineをtag | mainとpackage/release notesが一致し、以後の比較基準が固定 |
| M1 | v0.3.2 | Trust Foundation | MCP適合、transactional outbox、audit check/repair、crash test、executor安全化 | 外部MCP client smoke成功。強制終了後もDB/JSONL/Evidenceを検出・修復可能 |
| M2 | v0.4.0 | Three-command Wedge + Integrity Gate | completion packet v1、`pcl start`、既存`pcl finish`拡張、`pcl resume`、Evidence-backed terminal guards | 10分以内・3操作で有用packetを得て、Story/Test/Goal不整合とfail-open checkを完了扱いにできない |
| M2.1 | v0.4.1 | Integrity Migration | idle routing修復、lifecycle repair/link、structured diagnostics、Skill provenance | 既存projectを意味判断の自動承認なしにenforced lifecycleへ移行できる |
| M3 | v0.4.2 | Adaptive Entry | work brief v1、route recommendation、multi-axis policy、explain/override | LLMなしでrouteと理由を再現。明確なタスクへのoverheadが目標内 |
| M4 | v0.4.3 | Replan & Assurance | brief revision、stale/invalidation、verifier provenance、risk policy | 前提変更から安全に戻れ、高risk変更を自己承認だけで閉じられない |
| M5 | v0.5.0 | Discovery Profile | profile contract、AI-PLC-inspired discovery、decision proposal、人間checkpoint | coreにOption tableを増やさず、曖昧タスクの手戻り低減を実測 |
| M6 | v0.5.1 | Trace & Efficient Handoff | Master Trace/intent-index統合、claim-bound handoff | transcript全文なしで別session/modelが再開。出典のないclaimをfact化しない |
| M7 | v0.6.x | Adaptive Cost & Learning | capability/budget profile、budget exhaustion packet、context cache、knowledge proposal実験 | 安いworker→deterministic check→必要時だけescalationが説明可能に動作 |
| M8 | v0.7.x | External Evidence | benchmark、design partner、互換matrix、contract stability | 外部利用者の成果と失敗を公開可能な形式で示す |
| G1 | v1.0 gate | Stable product contract | supported surfaces、deprecation policy、recovery contract | 下記v1 gateを満たす |

## 6. v1 gate

以下は目標であり、現時点の実績ではない。

- 最初の有用なcompletion packetまで10分以内。
- 初心者のcore操作は`start / finish / resume`の3つで説明できる。
- 低riskかつ強いモデルの作業におけるPLH overheadが5%以下。
- 弱いモデル条件で、Agent単独よりtask successを15ポイント改善、または人間介入を30%削減。
- 別session・別modelへのresume成功率80%以上。
- packetからのcheck再現率90%以上。
- false completion率がAgent単独より統計的または実務的に明確に低い。
- crash injection後の状態不整合を100%検出し、サポート対象ケースを自動修復できる。
- supported MCP clientsとの互換matrixを公開できる。

## 7. North Starと補助指標

North Starは次とする。

> **Verified Resumable Completions per active repository**

単なるcommand実行数やtoken削減率をNorth Starにしない。補助指標は次である。

- false completion rate。
- unverified critical claims。
- resume success rate。
- human review time。
- context bytes / task。
- deterministic check coverage。
- budget exhausted時の安全停止率。
- route override率とoverride後の成果。

## 8. 明示的にやらないこと

少なくともM5の評価完了までは、次を実装しない。

- `intent`、`option`、`knowledge`を一括でfirst-class table化。
- 全タスクへのCollection→Inception→Construction→Operation強制。
- 全タスクへの第二モデル検証。
- 自動生成Knowledgeの自動注入。
- full transcriptのhandoff packetへの既定同梱。
- cloud backend、fleet daemon、multi-user権限、rich dashboard。
- lexical/context baselineで不足が立証される前のembedding基盤。
- 本物のOS隔離がない機能を「sandbox」と表現すること。
- 実測前の「何% token削減」「品質が何倍」等の宣伝。

## 9. 最大リスク

### PLHを使うこと自体が仕事になる

対策はLite pathとadaptive policy。DirectではDiscovery概念を見せない。

### 契約と内部schemaが同時に変わり続ける

対策は外部packetのversioningとfixture。DB schemaは内部実装として分離する。

### 独立agentレビューを過信する

対策はverifier separationとevidence classを別軸で記録する。別モデルの承認だけではproof levelを上げない。

### AI-PLC統合が製品範囲を拡散させる

対策はProfile境界。上流生成物はEvidenceとしてcoreへ取り込み、Product/UX固有機能はpluginに置く。

### 監査を売りながらdual-writeが壊れる

対策はM1を最優先し、transactional outboxとrecoveryをproduct contractにする。

## 10. 意思決定の優先順位

1. Trust Foundationを完了する。
2. `finish`をpacket生成の主力にし、`start/resume`を追加する。
3. Work BriefとAdaptive Routeをartifact contractとして試す。
4. ReplanとAssuranceを固める。
5. 外部Discovery ProfileでAI-PLC思想を検証する。
6. 評価で必要性が確認された概念だけDB entityへ昇格する。
