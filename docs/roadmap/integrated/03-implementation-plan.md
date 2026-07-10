# Implementation Plan

## 1. 基準と前提

- 現在の`main`はv0.3.1相当で、`pcl context check`、target-bound handoff agreement、`pcl finish` terminal planner等が入っている。
- 本計画は既存機能を再実装せず、`0123`から積み上げる。
- 既存CLI、DB、event、Evidence contractを壊す大規模rewriteはしない。
- タスクIDとmigration番号は、実装開始時に競合があれば次の空き番号へ変更する。
- LLM呼び出しはcore runtime dependencyにしない。

## 2. Waveと依存

```text
Wave A: Baseline / Trust
0123 ─┬─ 0124 ─ 0125
      ├─ 0126 ─ 0127 ─ 0128 ─ 0129
      └─ 0130

Wave B: Product Wedge
0131 ─ 0132 ─┬─ 0134
             └─ 0133

Wave C: Adaptive / Replan / Assurance
0135 ─ 0136 ─ 0137 ─┬─ 0141
       └─ 0138 ─ 0139│
0131 ─ 0140 ─────────┘

Wave D: Profile / Trace
0135 + 0137 ─ 0142 ─ 0143 ─ 0144
0134 ─ 0145

Wave E: Cost / Learning / Evidence
0137 ─ 0146 ─ 0147
0134 + 0146 ─ 0148
0135 + 0142 ─ 0149
0134 + 0137 + 0141 + 0144 ─ 0150 ─ 0151 ─ 0152
```

M1 gate前にWave Bを設計・schema reviewすることは可能だが、状態変更を伴うmergeはM1完了後を原則とする。

## 3. Task index

| ID | Title | Milestone | Size | Merge dependency |
|---|---|---|---|---|
| 0123 | Release v0.3.1 and freeze baseline | M0 | S | none |
| 0124 | MCP stdio framing and version negotiation | M1 | M | 0123 |
| 0125 | MCP external conformance fixtures | M1 | M | 0124 |
| 0126 | Transactional audit outbox ADR and failure model | M1 | M | 0123 |
| 0127 | Implement event outbox and JSONL projector | M1 | XL | 0126 |
| 0128 | Add audit check/repair/rebuild | M1 | L | 0127 |
| 0129 | Crash injection and concurrent writer suite | M1 | L | 0127,0128 |
| 0130 | Guarded executor terminology, caps, redaction | M1 | M | 0123 |
| 0131 | completion-packet/v1 contract and fixtures | M2 | M | 0123 |
| 0132 | Extend `pcl finish` to emit completion packet | M2 | XL | 0128,0131 |
| 0133 | Add Lite `pcl start` | M2 | L | 0131 |
| 0134 | handoff-packet/v1 and `pcl resume` | M2 | L | 0132 |
| 0135 | work-brief/v1 as Evidence contract | M3 | M | 0131 |
| 0136 | Deterministic route recommendation | M3 | L | 0135 |
| 0137 | Multi-axis policy, explain, override | M3 | XL | 0136 |
| 0138 | Immutable Work Brief revision and `pcl replan` | M4 | L | 0128,0135 |
| 0139 | constraint cascade and stale/invalidation propagation | M4 | XL | 0138 |
| 0140 | producer/verifier provenance | M4 | M | 0131 |
| 0141 | risk-based verification policy | M4 | L | 0137,0140 |
| 0142 | Profile contract and plugin boundary | M5 | L | 0135,0137 |
| 0143 | AI-PLC-inspired Discovery reference profile | M5 | L | 0142 |
| 0144 | decision-proposal/v0 and human selection flow | M5 | L | 0143 |
| 0145 | Master Trace/intent-index handoff integration | M6 | L | 0134 |
| 0146 | capability-profile/v0 | M7 | M | 0137 |
| 0147 | budget profile and incomplete-budget packet | M7 | L | 0131,0146 |
| 0148 | content-addressed context cache and delta handoff | M7 | XL | 0134,0146 |
| 0149 | knowledge-proposal/v0 experiment | M7 | M | 0135,0142 |
| 0150 | cross-model evaluation harness | M8 | XL | 0134,0137,0141,0144 |
| 0151 | external dogfood/design partner operations | M8 | L | 0150 |
| 0152 | adoption docs, compatibility matrix, stability policy | M8 | L | 0151 |

## 4. 変更対象の目安

実装時に実際のmodule構造を確認し、以下は固定パスではなく責務マップとして使う。

| 責務 | 既存/新規候補 |
|---|---|
| CLI registration | `src/pcl/cli.py`、将来`interfaces/cli/` |
| application use case | `src/pcl/commands.py`から`application/*.py`へ抽出 |
| DB connection/migration | `src/pcl/db.py`、`src/pcl/migrations.py` |
| event/outbox | `src/pcl/events.py`、新規`infrastructure/outbox.py` |
| Evidence/files | `src/pcl/evidence.py`、artifact store module |
| Validation | `src/pcl/validators.py`、domain policy validators |
| Context/handoff | `src/pcl/context.py`、new packet modules |
| MCP | `src/pcl/mcp_server.py`、protocol transport tests |
| Executor | `src/pcl/workflow_sandbox.py`、名称はguarded executorへ |
| JSON Schema | package dataとtop-level `schemas/` fixture |
| Docs | `docs/`、`agent-tasks/`、README golden path |

## 5. migration strategy

### 原則

- migrationはforward-onlyを既定とし、破壊前にbackup/checkpointを作る。
- SQL実行、schema version更新、migration eventを一つの明示transactionにする。
- migration中はexclusive project lockを取る。
- 各statement、commit直前、projector実行中へcrash injection pointを置く。
- 古いfixture DBを全supported versionからupgradeするtestを維持する。
- docsのschema versionはコードから生成し、CIでdriftを検出する。

### outbox migration

次の空きmigrationで最低限を追加する。

```text
events.sequence UNIQUE NOT NULL
outbox_records
  id
  event_id UNIQUE
  sink
  status
  attempts
  last_error
  created_at
  delivered_at
```

既存JSONL eventとの対応付け方法をADR-002で決める。hash/sequenceがないlegacy lineはimport時にdeterministic legacy IDを生成し、書き換えの有無を明示する。

## 6. PR strategy

- 一PR一主要責務。
- schema/contract PRとruntime implementation PRを分ける。
- refactorとbehavior changeを可能な限り分離。
- XL taskはdesign PR、storage PR、CLI PRへ分割してよいが、task acceptanceは統合後に閉じる。
- public CLI変更はhelp snapshot、JSON fixture、exit code testを必須にする。
- generated docs/schema fixtureをcommitし、再生成差分をCIで検査する。

## 7. test strategy

### Unit

- deterministic route/policy resolver。
- proof level calculation。
- packet serialization/validation。
- reason code stability。
- redaction、output cap、hash。

### Contract

- JSON Schema positive/negative fixtures。
- `--json` stdout purity。
- old packet reader compatibility。
- CLI help/exit code snapshots。

### Integration

- start→finish→resume golden path。
- discover profile artifact import→human decision→execution。
- replan→stale propagation→resume。
- producer/verifier separation。

### Failure injection

- JSONL append前後。
- SQLite commit前後。
- Evidence temp write/rename前後。
- migration statement間。
- projector retry/duplicate。
- disk full、permission error、process killを模擬。

### Concurrency

- 8〜16 writer process。
- migration lock中のwriter。
- projectorとmutation同時実行。
- busy timeout、retry/backoffの上限。

### Platform

- Linux、macOS、Windows。
- Python supported versions。
- path separator、file lock、atomic rename差異。

### External interoperability

- 公式または標準準拠MCP client。
- 少なくともClaude Code/Codex等、実際に対象とするadapter smoke。
- agent固有integrationが失敗してもcore packetをCLIで生成可能であること。

## 8. Definition of Done

個別taskは次をすべて満たして完了する。

- acceptance criteriaを満たす。
- regression testとnegative testがある。
- `--json` fixtureが必要なら更新済み。
- docs、help、schema fixtureが同期。
- migration/recovery impactが説明されている。
- security/privacy reviewが必要なsurfaceを確認。
- performance overheadを測定または「未測定」と明記。
- taskにEvidence refs、test commands、結果を記録。
- failure/rollback pathを試した。
- 「モデルがそう言った」だけの完了証拠を使わない。

## 9. Agent dispatch contract

実装エージェントへは個別taskだけでなく、必ず次を渡す。

1. 対象commit SHA。
2. 個別task file。
3. 関連ADRとschema。
4. allowed paths / forbidden paths。
5. test budgetとtime budget。
6. 既知のbaseline failures。
7. 完了時に返すEvidence形式。

agentはscope外の設計変更が必要になったら勝手に拡張せず、DecisionまたはReplan proposalを返す。

## 10. Rollback

- 新packet generationはfeature flagまたはadditive commandから開始。
- DB migration前に自動backup pathを表示。
- outbox projector停止時もSQLite mutationは保持し、delivery pendingを明示。
- profileはoptional package dataとして無効化可能。
- route recommendationはadvisoryから開始し、enforcementはM4以降。
- Knowledgeはv0実験であり、core completionをblockしない。
