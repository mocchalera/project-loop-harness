# Adaptive Loop Architecture

## 1. 目的

この設計は、PLHを「複雑な工程を利用者へ強制する管理ツール」ではなく、仕事の不確実性とriskに応じて必要な制御だけを挿入する基盤にする。

## 2. 論理アーキテクチャ

```text
┌─────────────────────────────────────────────────────────┐
│ Interfaces                                               │
│ CLI / MCP / Hooks / Agent adapters / Profile adapters    │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│ Application use cases                                    │
│ start / finish / resume / replan / verify / explain      │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│ PLH Core                                                 │
│ State / Audit / Evidence / Verification / Policy         │
│ Completion / Handoff / Recovery                          │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│ Infrastructure                                           │
│ SQLite / transactional outbox / JSONL projector          │
│ filesystem artifacts / guarded executor / git            │
└─────────────────────────────────────────────────────────┘

Optional Profiles
  Direct preset     ─┐
  Discovery profile ├── produce/consume versioned artifacts
  Assurance preset ─┘
```

既存コードを一度にこのディレクトリ構造へ移す必要はない。新規use caseから境界を守り、既存`cli.py`、`commands.py`、`context.py`等から段階的に抽出する。

## 3. CoreとProfileの責務

### PLH Core

- project状態とID。
- state transitionとvalidation。
- commit済みeventとaudit recovery。
- Evidence artifactとhash。
- deterministic checkの実行・記録。
- Verificationとproof level。
- completion/handoff packet。
- risk/capability/budget policyの解決。
- 明示的なhuman gate、override、escalation。

### Profile

- 曖昧な問題の問い直し。
- Context収集候補の提示。
- 代替案の発散。
- trade-offと不確実性の整理。
- Story/Spec/Wireframe等の領域固有生成。
- 外部モデルやagentの呼び出し。

ProfileはSQLiteを直接変更しない。versioned artifactを生成し、PLH CLI経由でEvidenceとして取り込む。

## 4. UX presetとpolicy axis

### UX preset

| preset | 主目的 | 既定動作 |
|---|---|---|
| `direct` | 目的・scope・checkが明確 | 軽いplanning、通常verification、少ないcheckpoint |
| `discover` | 問題や解法が曖昧 | Work Brief、Context収集、代替案、人間decision |
| `assure` | 変更riskが高い | 小さい実行単位、独立verification、必要に応じhuman gate |

presetは説明用の入口であり、最終制御ではない。たとえば曖昧かつ高riskな仕事は`discover` presetでも`verification_depth=human`になり得る。

### authoritative policy axis

```yaml
planning_depth: none | light | full
verification_depth: basic | standard | independent | human
execution_chunk_size: large | medium | small
checkpoint_frequency: low | medium | high
context_budget_bytes: integer
tool_call_budget: integer | null
wall_time_budget_seconds: integer | null
strong_model_escalations: integer
```

## 5. Golden paths

### Direct

```text
pcl start "Fix login timeout"
  └─ route: direct
      └─ task/work brief最小生成
          └─ agent実装
              └─ pcl finish
                  ├─ checks
                  ├─ completion-packet/v1
                  └─ terminal stateまたは明示的incomplete
                      └─ pcl resume（必要時）
```

### Discover

```text
pcl start "Improve onboarding"
  └─ route recommendation: discover
      ├─ work-brief/v1 draft
      ├─ Discovery Profileへhandoff
      ├─ context/alternatives/uncertaintyをEvidence化
      ├─ human decisionを既存Decisionへ記録
      ├─ work brief revisionをapprove
      └─ Direct executionへ移行
```

### Assure

```text
pcl start "Change auth migration"
  └─ route preset: assure
      ├─ high-risk reason codes
      ├─ small chunks
      ├─ deterministic checks
      ├─ producer/verifier separation
      ├─ human gate（policy次第）
      └─ completion packetに残存riskを明示
```

## 6. `pcl start`

`start`は初心者向けの集約use caseであり、既存の細かいGoal/Task/Workflow APIを削除しない。

### 責務

- 未初期化projectなら、`--dry-run`で作成物を説明し、明示的な`start`実行で最小初期化する。
- input textからWork Brief draftを作る。LLMによる意味解釈はしない。
- deterministic signalsからroute recommendationを作る。
- recommendation、reason codes、resolved policyを表示する。
- 利用者overrideを受け付け、Decision/Eventとして残す。
- 一つのactive work targetを返す。

### 非責務

- 自動でコードを変更する。
- 暗黙に外部モデルを呼ぶ。
- 曖昧な依頼を勝手に確定する。
- human gateを自動承認する。

## 7. `pcl finish`

既存のterminal close-out plannerを置き換えず、packet生成へ拡張する。

### 処理順

1. active targetとscopeを解決。
2. strict validationと未解決blockerを確認。
3. git base/head/diffを固定。
4. policyに従うcheck planを作成し、実行前に説明。
5. 許可されたcheckを実行し、streaming artifactとして保存。
6. claimとEvidenceのbindingを検査。
7. proof levelを決定論的に算出。
8. completion packetを生成。
9. 状態変更、event、packet参照を一つのtransaction boundaryでcommit。
10. JSONL projectorを冪等に追従。

### terminal outcome

- `COMPLETED_VERIFIED`
- `COMPLETED_WITH_RISK`
- `INCOMPLETE_VALIDATION`
- `INCOMPLETE_BUDGET_EXHAUSTED`
- `INCOMPLETE_HUMAN_DECISION_REQUIRED`
- `NO_CHANGES`

「checkを実行していないのにcompleted」としない。

## 8. `pcl resume`

read-onlyが既定。handoff packetを表示またはexportする。

含める情報:

- 原目的とcurrent revision。
- 現在状態。
- 変更ファイルとbase/head。
- verified claimsとEvidence。
- unverified claims、blocker、risk。
- DecisionとReplanの要約。
- 次の安全な一手。
- context artifact refsとbudget。

既定ではfull transcriptを含めない。Master Trace/intent-indexはoptional sectionとして参照する。

## 9. Work Brief

`work-brief/v1`は最初から専用tableにしない。Evidence artifactとして保存し、Goal/Taskへgeneric linkで結ぶ。

revisionはimmutable。変更時は新artifactを作り、`supersedes`を設定する。承認済みrevisionだけが現在のexecution contractになる。

### 最小内容

- problem。
- desired outcome。
- target user。
- acceptance criteria。
- constraintsとsource refs。
- non-goals。
- assumptionsとstatus。
- route/policy recommendation。
- decision refs。

## 10. Replan

Replanは「失敗したからretry」ではなく、「前提が変わったためexecution contractを改訂する」操作。

### trigger

- success condition変更。
- 制約追加・撤回。
- assumptionを反証するEvidence。
- scopeが閾値を超えた。
- risk class上昇。
- budget exhaustion。
- 人間が選択を変更。

### state effect

1. 旧Work Briefを保持。
2. 新revisionを作成。
3. `work.replanned` eventを記録。
4. 影響を受けるTask、Evidence、Verification、packetを`stale`または`needs_review`へ。
5. 何が自動invalidatedされ、何が人間確認かを説明。

stale artifactを削除しない。履歴と根拠を保持する。


## 11. Context Cascade and constraint inheritance

大きなGoalをchild Goal/Taskへ分ける際、制約本文を複製しない。親Work Briefのconstraintへrefを持ち、childのeffective setを決定論的に解決する。

| strength | child behavior |
|---|---|
| `invariant` | 原則上書き不可。変更には親briefのReplanまたは明示policy exceptionが必要 |
| `inherited_default` | Decision、actor、理由を記録すればchildでoverride可能 |
| `local` | 定義されたtarget内だけで有効 |

child artifactには、参照したparent revision、resolved constraint hash、local overrideを記録する。親制約が変わった場合、childへ黙って反映せず`stale`にして再評価を要求する。

## 12. maker≠checker

2つの軸を混同しない。

### verifier separation

- `same_run`
- `separate_context`
- `separate_session`
- `separate_agent`
- `human`

### evidence class

- `model_judgment`
- `deterministic_check`
- `observational_artifact`
- `human_judgment`

別モデルのレビューは独立性を上げるが、deterministic evidenceの代わりにはならない。

## 13. リスク判定

まずdeterministic signalを使う。

- migration、auth、permission、secret関連path。
- dependency manifest/lockfile。
- CI、infra、deployment。
- public API signature。
- changed files/lines/modulesの閾値。
- failing baseline test。
- test不在。
- generated fileやbinary。
- destructive command候補。

LLMによるsemantic risk判定は補助claimとしてのみ扱う。

## 14. capabilityとbudget

model名ではなく能力と実績を記録する。

```yaml
capability_profile:
  planning_reliability: high
  tool_reliability: medium
  structured_output: true
  context_budget: 32000
  latency_class: medium
  cost_class: high
  observed_schema_failure_rate: 0.02
```

budget切れはterminal completionではない。実行済みcheck、未確認事項、次の安全な一手を`INCOMPLETE_BUDGET_EXHAUSTED` packetへ残す。

## 15. Knowledge

KnowledgeはM7まで実験扱い。

```text
proposed → accepted → superseded/rejected/expired
```

`accepted`だけを将来context候補にする。最初は`knowledge-proposal/v0` Evidenceで試し、独立検索・矛盾解決・有効期限管理が繰り返し必要と確認されてからtableへ昇格する。

## 16. 段階的なコード境界

全面リライトは行わない。新規use caseから次の境界を作る。

```text
src/pcl/application/start.py
src/pcl/application/finish.py
src/pcl/application/resume.py
src/pcl/application/replan.py
src/pcl/domain/contracts/
src/pcl/domain/policy/
src/pcl/infrastructure/outbox.py
src/pcl/infrastructure/jsonl_projector.py
src/pcl/interfaces/cli/
src/pcl/interfaces/mcp/
```

既存public importsやCLIを壊さず、strangler patternで抽出する。構造変更だけの大規模PRと機能変更を同時に行わない。
