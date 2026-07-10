# Project Loop Harness 統合ロードマップ・実装計画

**文書ステータス:** Proposed for discussion  
**基準日:** 2026-07-09  
**対象リポジトリ:** `mocchalera/project-loop-harness`  
**基準ブランチ:** `main`  
**基準実装:** v0.3.1相当、タスク`0122`まで完了済み  
**目的:** Project Loop Harness（以下PLH）を、モデル性能・予算・利用エージェントが変わっても機能する「証拠・完了・引き継ぎ・適応制御」のローカル基盤へ発展させる。

この一式は、PdM、テックリード、実装担当エージェントが同じ前提で議論し、合意後にそのまま実装タスクへ移れる粒度で構成している。AI-PLCの上流設計思想は採用するが、そのファイル中心の4段階工程をPLH coreへ直接移植しない。曖昧な仕事にだけ有効化できるProfileとして統合する。

## 最初に読む順番

| 読者 | 推奨順序 |
|---|---|
| PdM・プロダクト責任者 | `docs/00-executive-roadmap.md` → `docs/05-pdm-discussion-guide.md` → `docs/04-evaluation-and-rollout.md` |
| テックリード・設計者 | `docs/01-adaptive-loop-architecture.md` → `docs/02-contracts-and-data-model.md` → `docs/03-implementation-plan.md` → `docs/adr/` |
| 実装担当エージェント | `agent-tasks/README.md` → 指定された個別タスク → 関連ADR・schema |
| 検証担当 | `docs/02-contracts-and-data-model.md` → `docs/04-evaluation-and-rollout.md` → 個別タスクの受け入れ条件 |

## 文書一覧

### 主要文書

- `docs/00-executive-roadmap.md` — 製品戦略、対象ユーザー、統合原則、段階別ロードマップ、やらないこと。
- `docs/01-adaptive-loop-architecture.md` — coreとProfileの境界、Direct/Discover/Assure、Replan、maker/checker、モデル・予算適応。
- `docs/02-contracts-and-data-model.md` — 外部契約、証拠レベル、永続化方針、互換性ルール。
- `docs/03-implementation-plan.md` — 依存関係、リリースゲート、変更対象、テスト戦略、ロールバック。
- `docs/04-evaluation-and-rollout.md` — 比較実験、成功指標、dogfood、design partner、公開可能な主張。
- `docs/05-pdm-discussion-guide.md` — 未決定事項、会議アジェンダ、インタビュー、意思決定テンプレート。
- `docs/06-cli-contract-draft.md` — `start/finish/resume/replan/audit/profile`の暫定CLI契約。
- `docs/07-state-machines-and-events.md` — Work Brief、Replan、Evidence、Outbox等の論理状態遷移。
- `docs/08-repository-integration.md` — planning PR、task activation、既存計画との統合手順。
- `docs/09-ai-plc-integration-mapping.md` — AI-PLC/提供案の採用・変更・延期・拒否の対応表。

### ADR

- `docs/adr/ADR-001-profile-not-entity.md`
- `docs/adr/ADR-002-transactional-audit-outbox.md`
- `docs/adr/ADR-003-adaptive-policy-axes.md`
- `docs/adr/ADR-004-contract-first-promotion.md`

### 契約案

- `schemas/work-brief-v1.schema.json`
- `schemas/completion-packet-v1.schema.json`
- `schemas/handoff-packet-v1.schema.json`
- `schemas/route-decision-v1.schema.json`
- `schemas/decision-proposal-v0.schema.json`
- `schemas/knowledge-proposal-v0.schema.json`
- `config/pcl-policy.example.yaml`

### レビュー・引き継ぎ用

- `handoff/PDM_REVIEW_PROMPT.md`
- `handoff/ARCHITECTURE_REVIEW_PROMPT.md`
- `handoff/IMPLEMENTATION_AGENT_PROMPT.md`
- `examples/` — contractの具体例。

### 実装バックログ

- `agent-tasks/README.md` — `0123`以降の順序、依存、並列化可能範囲。
- `agent-tasks/0123-*.md`〜`0152-*.md` — 実装エージェントへ渡せる個別仕様。

## この計画の権威順位

実装中に記述が衝突した場合は次の順で判断する。

1. 現在のリポジトリコードとテストが示す実際の互換契約
2. AcceptedになったADR
3. AcceptedになったJSON SchemaとCLI契約
4. マイルストーン文書
5. 個別タスク仕様
6. 会議メモ、エージェント出力、作業中の仮説

この一式を配置しただけでは既存計画を自動的に破棄しない。PdMとテックリードが承認した時点で、現行のgrowth planに「この計画が後継である」旨を明記する。

## 実装開始前の最小合意

次の4点を決めるまで、`0127`以降の状態モデル変更を開始しない。

1. SQLiteを現在状態のsource of truthとし、JSONLをcommit済みイベントの投影とするか。
2. `work-brief/v1`をまずEvidence artifactとして扱い、専用テーブルを作らない方針を採用するか。
3. `direct / discover / assure`をUX presetとし、最終的な制御は複数のpolicy axisで行うか。
4. `pcl start → pcl finish → pcl resume`を初心者向けの主導線にするか。

## 完了の定義

この計画全体は、機能数ではなく次の状態で完了と判断する。

> 任意のcoding agentが行った変更について、PLHが何を検証したかを決定論的に残し、別のagentまたは人間が小さいhandoff packetから安全に再開できる。明確な仕事では儀式を増やさず、曖昧・高リスク・低能力モデルの仕事だけ制御を強められる。
