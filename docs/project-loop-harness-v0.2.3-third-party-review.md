# Project Loop Harness v0.2.3 第三者専門家レビュー提言書

**提出先:** Project Loop Harness 実装担当チーム
**作成者:** 第三者専門家レビューグループ
**対象バージョン:** `project-loop-harness` v0.2.3
**文書種別:** 実装・プロダクト進化に向けた外部提言書
**作成日:** 2026-07-08

---

## 0. この文書の目的

本書は、`project-loop-harness` v0.2.3 のリリース内容を前提に、第三者の専門家グループから実装担当チームへ提出する提言書である。

目的は単なるレビューではない。実装担当が次のリリース、設計判断、Issue 化、マイルストーン設計、議論設計にそのまま使えるように、以下を整理する。

- v0.2.3 時点のプロダクト価値の再定義
- 強みと構造的リスクの整理
- 優先度付きの改善提案
- 次に進むべきマイルストーン
- 実装タスク案と受け入れ条件
- チームで議論すべき論点
- 将来的な差別化テーマ

本書の結論は明確である。

> **Project Loop Harness は、単なる CLI ツールや dashboard ツールではなく、AI coding agent のための local control plane として進化すべきである。**

特に v0.2.3 で入った evidence durability / task linking / context pack linked evidence は、agent handoff の信頼性を高める方向に強く噛み合っている。ここを伸ばすべきであり、現段階で hosted backend、派手な UI、複雑な orchestration engine に逃げるべきではない。

---

## 1. レビュー体制

本書では、以下の専門視点を仮想的な第三者レビューグループとして統合した。

| 役割 | 主な観点 |
|---|---|
| Product Strategist | 市場での位置づけ、差別化、採用導線 |
| Agent Workflow Architect | Codex / Claude Code など coding agent 間の handoff 設計 |
| Systems Architect | CLI / SQLite / JSONL / file artifacts の責任分離 |
| Security Reviewer | local evidence、secret leakage、MCP exposure、security policy |
| Release Engineer | CI、package metadata、release checklist、version support |
| Developer Experience Reviewer | README、quickstart、docs、first-run experience |

---

## 2. 前提と参照範囲

本書は以下を主な参照対象とした。

- v0.2.3 release note
- README
- docs/architecture.md
- docs/context-pack.md
- SECURITY.md
- pyproject.toml
- .github/workflows/ci.yml
- evidence 関連実装の一部
- ID allocation / SQLite connection 周辺実装の一部

ローカル clone、全テスト実行、実リポジトリ dogfood は本書作成時点では実施していない。テスト通過数や smoke test は v0.2.3 release note の記載に基づく。

---

## 3. エグゼクティブサマリー

### 3.1 総評

v0.2.3 は、Project Loop Harness が「AI coding agent の作業を安全に進める local control plane」へ進化するための重要なリリースである。

特に以下が大きい。

1. `pcl evidence add --copy` により、adhoc evidence が workspace cleanup 後もローカルに残るようになった。
2. evidence ID allocation の concurrent collision 対策が入った。
3. `pcl evidence add --task T-XXXX` により、adhoc evidence を task に紐づけられるようになった。
4. task context pack に linked evidence metadata が出るようになった。
5. ただし artifact contents は inline しないという、正しい安全境界が維持されている。

この方向性は非常に良い。

ただし、次に進むべき方向は「機能追加」ではなく、**信頼性・対象束縛・証拠意味論・実運用導線の強化**である。

### 3.2 最重要提言

今後 2〜3 リリースの主軸は以下に置くべきである。

```text
v0.2.4: Trust Patch
v0.3.0: Target-Bound Context
v0.3.1: Master Trace / Intent Index v0
v0.4.0: Dogfood Operations
v0.5.0: Adoption / Distribution
```

### 3.3 今すぐやるべきこと

最優先は v0.2.4 Trust Patch である。

```text
1. source_drifted health 判定の修正
2. SECURITY.md の supported versions 更新
3. Python 3.10〜3.13 CI matrix
4. evidence copy lock / duration の観測
5. release checklist の明文化
```

v0.3.0 では、context pack を agent handoff の信頼できる契約に進化させるべきである。

```text
pcl impact --diff --for-task T-0001 --json
pcl impact --diff --for-job J-0001 --json
pcl context pack --task T-0001 --include-code-context --require-bound-receipt --json
```

### 3.4 やらない方がよいこと

現段階で以下に進むのは早い。

- hosted backend
- cloud sync
- marketplace
- telemetry
- multi-user collaboration
- 過度に複雑な自動 workflow scheduler
- dashboard の過剰リッチ化
- core からの LLM API 呼び出し

理由は単純である。Project Loop Harness の現時点の勝ち筋は「ローカルで証拠・文脈・状態・検証を支配すること」にある。早い段階で cloud や UI に寄せると、差別化がぼやける。

---

## 4. プロダクト定義の提案

### 4.1 現時点での最も強い定義

Project Loop Harness は、以下のように定義するのが最も強い。

> **Codex / Claude Code などの AI coding agent に、忘れず・暴走せず・証拠を残して・次にやることを判断させるための local control plane。**

さらに短く言うなら、次の定義がよい。

> **AI coding agent のための作業記憶・証拠管理・引き継ぎ装置。**

### 4.2 避けるべき定義

以下のように見せると弱い。

| 避けるべき定義 | なぜ弱いか |
|---|---|
| Workflow engine | 既存競合が多く、PLH の独自性が薄れる |
| Dashboard tool | dashboard は human view であり、source of truth ではない |
| Agent framework | 範囲が広すぎ、local control plane の強みがぼやける |
| MCP server | MCP は外部 tool bridge であって core ではない |
| Prompt management tool | PLH の価値は prompt ではなく state / evidence / verification にある |

### 4.3 Product North Star

PLH が目指すべき North Star は以下である。

> **複数の AI coding agent が関わる開発作業において、何を根拠に、何を行い、何が検証され、次に何をすべきかを、ローカルで再現可能に管理する。**

---

## 5. v0.2.3 の強み

### 5.1 CLI-first の境界設計が強い

`docs/architecture.md` では、Skill / CLI / SQLite / JSONL / HTML / Plugin / MCP の責任が分かれている。特に以下の考え方は正しい。

- Skill は agent に使い方を教える。
- CLI は state mutation、validation、render、read-only context packaging を担う。
- SQLite は current normalized state を保持する。
- JSONL は append-only audit trail を保持する。
- HTML は human-readable view であり、source of truth ではない。
- Plugin は CLI/runtime を置き換えない。
- MCP は local state logic を所有しない。

この境界設計は agentic system では非常に重要である。

多くの AI agent 系プロジェクトは、以下のような失敗をしやすい。

```text
agent が DB を直接読む
agent が dashboard HTML を読む
agent が events.jsonl を勝手に解釈する
agent が state file を直接編集する
plugin が runtime として肥大化する
```

PLH はこの失敗をかなり意識的に避けている。これは維持すべき中核原則である。

### 5.2 Context Pack が最も強いプロダクト核になっている

`pcl context pack` は、PLH の中心機能になり得る。

理由は、context pack が以下を同時に満たしているからである。

- agent handoff のための read-only packaging surface
- budget-aware な文脈生成
- source commands / source paths による再取得性
- canonical ordering
- additive `context-pack/v1` contract
- evidence contents を inline しない安全性

これは、agent 間 handoff における最も難しい問題、つまり「どの文脈を、どれだけ、どの根拠付きで渡すか」に正面から向き合っている。

PLH はここをさらに強化すべきである。

### 5.3 Evidence durability は v0.2.3 の中核価値

`pcl evidence add --copy` によって、adhoc evidence が元ファイルの削除や workspace cleanup に影響されにくくなった。これは証拠管理として重要である。

agent workflow では、以下が頻繁に発生する。

```text
一時ログが消える
worker output が上書きされる
テストログの所在が不明になる
master session transcript が保存されない
レビュー時に根拠を辿れない
```

`--copy` はこれらに対する重要な土台である。

ただし、後述する通り、copy 後の source drift の意味論は整理すべきである。

### 5.4 Task-linked evidence は正しい方向

`pcl evidence add --task T-XXXX` により、evidence が task と接続された。

これは非常に重要である。なぜなら agent handoff においては、単に evidence が存在するだけでは不十分だからである。

必要なのは、以下の問いに答えられることだ。

```text
この evidence は、どの task のために保存されたのか？
この worker は、どの evidence を根拠に作業したのか？
この task の完了判断に使える evidence はどれか？
```

v0.2.3 はこの方向に進んだ。次は code context も task/job に明示的に束縛すべきである。

### 5.5 Local-first / dependency-light は維持すべき差別化

`pyproject.toml` では runtime dependencies が空であり、PLH は local-first / dependency-light の思想を維持している。

これは非常に大事である。

PLH が扱うのは、開発者のローカルプロジェクト、agent output、test logs、evidence、dashboard、possibly sensitive な作業痕跡である。ここに早期の cloud dependency や telemetry を入れると、採用ハードルが跳ね上がる。

現段階では、ローカルで完結する制御層として尖らせる方が強い。

### 5.6 Release verification は良い

v0.2.3 release note では、以下が検証されている。

- editable install
- ruff
- pytest 457 tests
- `pcl validate --strict --json`
- dashboard render
- sdist/wheel build
- twine check
- sdist contract verification
- fresh wheel smoke

これは良い。AI agent 系プロダクトほど、このような「普通のリリース品質」が差別化になる。

ただし、CI matrix は package metadata と整合していない。これは後述する。

---

## 6. 重大な改善提案

## P1-1. `source_drifted` の health 判定を修正する

### 問題

v0.2.3 の evidence 実装では、copied evidence の元 source が消えた、または size mismatch した場合に `source_drifted` finding が追加される。

一方で、warning finding codes に `source_drifted` が含まれていないため、findings には `source_drifted` があるのに health が `ok` のままになる可能性がある。

### 影響

これは v0.2.3 の中核価値である evidence durability の意味論を曖昧にする。

copy artifact が intact であれば、artifact 自体は利用可能である。だが、元 source が drift しているなら provenance / freshness の観点では warning である。

これを `ok` と表現すると、agent や人間 reviewer が誤解する。

### 推奨対応

短期対応としては以下でよい。

```python
ADHOC_WARNING_FINDING_CODES = {
    ...,
    "source_drifted",
}
```

ただし、中期的には health を分離する方がよい。

```json
{
  "artifact_health": "ok",
  "source_health": "warning",
  "findings": [
    {
      "code": "source_drifted",
      "severity": "warning",
      "detail": "missing"
    }
  ]
}
```

### 受け入れ条件

- copied artifact が存在し、元 source が missing の場合、`source_health` または `health` が warning を示す。
- copied artifact が intact の場合、artifact usability は失われない。
- context pack / report / dashboard でも source drift が明示される。
- test で `source_drifted` の missing / size_mismatch ケースが固定される。

---

## P1-2. SECURITY.md の supported versions を v0.2.x に更新する

### 問題

v0.2.3 tag の SECURITY.md では、current public release line が `0.1.x` と記載されている。

これは v0.2.3 release と矛盾している。

### 影響

PLH は local evidence、agent output、dashboard、MCP server を扱う。セキュリティ境界が曖昧に見えると、ユーザーは安心して導入しにくい。

特に v0.2.3 で copied evidence が入ったため、`.project-loop/evidence/adhoc-files/` に sensitive file が残る可能性が上がった。security policy の更新は必須である。

### 推奨対応

`SECURITY.md` を以下のように更新する。

```md
## Supported Versions

| Version | Supported |
|---|---|
| 0.2.x | Yes |
| <0.2 | No |
```

さらに以下を明記する。

```text
- .project-loop/evidence/adhoc-files/ may contain copied sensitive source files.
- Do not commit copied evidence unless intentionally curated.
- Redaction is caller responsibility unless explicitly performed by pcl.
- MCP/read-only exposure must not reveal raw evidence contents by default.
- Dashboard HTML is not source of truth and must not be used as machine context.
```

### 受け入れ条件

- SECURITY.md が v0.2.x を supported line として示す。
- copied evidence の機密性リスクが明記される。
- release checklist に security policy version check が入る。

---

## P2-1. CI matrix を package metadata と整合させる

### 問題

`pyproject.toml` は `requires-python = ">=3.10"` とし、classifiers に Python 3.10 / 3.11 / 3.12 / 3.13 を掲げている。

一方、CI workflow は Python 3.11 単一で実行されている。

### 影響

これは「対応している」と表示している範囲と、実際に継続検証している範囲が一致していない状態である。

PLH は filesystem、SQLite、subprocess、packaging、CLI output contracts に依存するため、Python minor version 差の影響を完全には無視できない。

### 推奨対応

最低限、pytest と smoke は以下の matrix で実行する。

```yaml
strategy:
  matrix:
    python-version: ["3.10", "3.11", "3.12", "3.13"]
```

全バージョンで実行すべきもの。

```text
ruff check
pytest
pcl --version
pcl init
pcl validate --strict --json
pcl render --json
```

build / twine check / sdist contract は 3.11 または 3.12 の single canonical version でもよい。

### 受け入れ条件

- CI が Python 3.10〜3.13 で test を実行する。
- package classifiers と CI が整合する。
- release note に matrix 結果が記載される。

---

## P2-2. `evidence add --copy` の write lock 長時間保持を観測する

### 問題

`next_prefixed_id` は transaction 外では `BEGIN IMMEDIATE` を開始し、ID を scan して次 ID を決める。

v0.2.3 では concurrent `evidence add --copy` の collision race を解消するため、ID allocation が serialized になった。この判断自体は正しい。

ただし、file copy が SQLite write transaction 中に行われる場合、copy 対象が大きいと write lock を長く持つ可能性がある。

### 影響

複数 agent が同時に evidence を保存する運用になると、以下が起こり得る。

```text
write lock 待ちが増える
busy timeout に近づく
evidence add が遅い原因を診断できない
worker が途中で諦める
```

現時点では大改修の必要はないが、観測なしに判断すべきではない。

### 推奨対応

v0.2.4 ではまず observability を追加する。

```text
evidence_copy_duration_ms
db_write_lock_duration_ms
copied_total_bytes
member_count
busy_timeout_retry_or_failure
```

中期的には以下の設計を検討する。

#### 案A: reserved row 方式

```text
BEGIN IMMEDIATE
ID 予約 row を insert
commit
file copy
BEGIN
manifest / final status update
commit
```

利点は write lock が短いこと。欠点は failed / abandoned evidence row をどう扱うかという cleanup 設計が必要になること。

#### 案B: counter table 方式

```text
counter table で ID を increment
commit
file copy
insert final row
```

利点は単純。欠点は番号 gap を許容する必要があること。

### 受け入れ条件

- concurrent copy stress test がある。
- evidence copy duration と copied bytes が event metadata または debug output に出る。
- 現行 serialized ID allocation の安全性を維持する。

---

## P2-3. Code context receipt を task/job に明示的に束縛する

### 問題

v0.2.3 では evidence は task に紐づいたが、code context receipt はまだ target-bound ではない。

`context pack --include-code-context` は latest `context_receipt` evidence row を解決するが、この receipt が「この task のために作られたものか」は明示されない。

### 影響

worker handoff では、以下の曖昧さが致命的になる。

```text
この code context は T-0001 用か？
それとも直近の unrelated receipt か？
この diff scope は今の task に対応しているか？
```

agent が誤った code context を信じると、修正範囲を誤る。

### 推奨対応

v0.3.0 の中核として、target-bound code context receipts を導入する。

```bash
pcl impact --diff --for-task T-0001 --json
pcl impact --diff --for-job J-0001 --json
pcl context pack --task T-0001 --include-code-context --require-bound-receipt --json
```

JSON 例。

```json
{
  "code_context": {
    "contract_version": "code-context/v1",
    "binding": {
      "target_type": "task",
      "target_id": "T-0001",
      "binding_strength": "explicit"
    },
    "receipt": {
      "path": ".project-loop/code-context/T-0001.json",
      "git_head": "abc123",
      "created_at": "2026-07-08T00:00:00Z"
    },
    "staleness": {
      "working_tree_changed_since_receipt": false,
      "receipt_age_seconds": 120
    }
  }
}
```

### 受け入れ条件

- task/job に明示的に bound された code context receipt を生成できる。
- unbound latest receipt を使う場合は warning が出る。
- `--require-bound-receipt` では matching receipt がない場合に fail する。
- context pack 内で evidence と code context の target が一致する。

---

## P2-4. README / docs の導入導線を整理する

### 問題

README は情報量が多く、初見ユーザーには重い。

現時点で README は、product pitch、quickstart、command surface、architecture、runtime explanation、agent guidance、MCP、dashboard、context pack、evidence、workflow などを同時に背負っている。

### 影響

PLH は概念が多い。

```text
goal
task
job
workflow
evidence
context pack
code context
receipt
checkpoint
decision
escalation
report
dashboard
agent
lease
MCP
plugin
skill
```

この概念量を初回から全部見せると、強みが伝わる前にユーザーが離脱する。

### 推奨対応

README は導入に絞り、詳細は docs に分離する。

```text
README.md
  - 30秒で価値が分かる説明
  - 3分 quickstart
  - 代表ユースケース3つ
  - Codex / Claude Code 連携への入口
  - docs へのリンク

docs/operator-manual.md
  - command surface 全体

docs/contracts.md
  - context-pack/v1
  - evidence manifest
  - dashboard-data.json
  - CLI JSON output policy

docs/agent-handoff.md
  - Codex / Claude Code / Master Trace handoff flow

docs/internals.md
  - SQLite / JSONL / migrations / architecture
```

### 受け入れ条件

- README を読んだ初見ユーザーが 3 分で `pcl init` まで進める。
- README 冒頭で PLH の価値が一文で伝わる。
- 詳細仕様は docs に移され、失われない。

---

## P3-1. `agent-tasks` を backlog / roadmap として整理する

### 問題

`agent-tasks` が 100 件規模に増えており、design history、completed tasks、proposals、roadmap が混ざり始めている。

### 影響

PLH 自体が agent-driven workflow を掲げるなら、PLH 自身の task 管理が読みやすい必要がある。

### 推奨対応

以下のいずれかを導入する。

```text
agent-tasks/README.md
agent-tasks/_index.json
pcl roadmap command
pcl task archive
```

最小実装は `agent-tasks/README.md` でよい。

例。

```md
| ID | Title | Status | Milestone | Priority | Area |
|---|---|---|---|---|---|
| 0101 | Evidence source drift health | Proposed | v0.2.4 | P1 | evidence |
| 0105 | Target-bound code context receipts | Proposed | v0.3.0 | P2 | context-pack |
```

### 受け入れ条件

- active / proposed / completed tasks が一覧できる。
- milestone と priority が見える。
- 新規 contributor / agent が次に何を見ればよいか分かる。

---

## 7. アーキテクチャ原則

今後の実装判断では、以下を原則として維持するべきである。

### 原則1: CLI が唯一の mutation boundary

agent、plugin、MCP、dashboard、skill は state を直接変更してはならない。

```text
正: pcl command 経由で state mutation
誤: agent が project.db / events.jsonl を直接編集
```

### 原則2: SQLite は current state、JSONL は audit trail

SQLite と JSONL の二重構造は維持する。

```text
SQLite: queryable current normalized state
JSONL: append-only audit and reconstruction
```

JSONL を query engine にしてはいけない。SQLite を人間レビュー可能な audit trail の代替にしてはいけない。

### 原則3: Dashboard は human view であり source of truth ではない

dashboard HTML を agent context にしてはいけない。

agent には以下を渡すべきである。

```text
pcl JSON output
context pack
evidence paths
dashboard-data.json, if explicitly designed for machine use
```

### 原則4: Context pack は read-only handoff contract

`pcl context pack` は state を変更してはならない。

また、context pack は以下を満たすべきである。

- additive contract
- canonical ordering
- source_commands / source_paths による再現性
- required / omitted sections の明示
- budget-aware packaging
- artifacts の inline 回避

### 原則5: Evidence summary は claim-not-fact

特に model-derived artifact、intent index、agent summary は事実ではなく claim として扱うべきである。

```text
summary: caller/model claim
source_paths: inspection target
manifest/hash: verification material
```

### 原則6: Core から LLM API を呼ばない

PLH core は local-only / deterministic / dependency-light を保つべきである。

LLM による intent extraction や summarization が必要な場合でも、core はその結果を evidence として記録・参照するだけに留める。

### 原則7: Raw evidence contents はデフォルトで inline しない

安全上、context pack に raw transcript や copied file contents をデフォルト inline すべきではない。

必要なのは contents ではなく、検査可能な paths と metadata である。

---

## 8. 推奨ロードマップ

## v0.2.4: Trust Patch

### 目的

v0.2.3 の evidence durability を、信頼できる状態に固める。

### スコープ

```text
1. source_drifted health 修正
2. SECURITY.md v0.2.x 更新
3. Python 3.10〜3.13 CI matrix
4. evidence copy lock / duration observability
5. release checklist contract
```

### 成功条件

- copied evidence の source drift が warning として表現される。
- SECURITY.md が v0.2.x を正しく示す。
- Python 3.10 / 3.11 / 3.12 / 3.13 で pytest が通る。
- `pcl validate --strict --json` と `pcl render --json` が matrix smoke に含まれる。
- release checklist が docs に追加される。

### 非スコープ

- DB migration を伴う大きな schema 改修
- hosted backend
- LLM integration
- UI redesign

---

## v0.3.0: Target-Bound Context

### 目的

context pack を、agent handoff の信頼できる契約に進化させる。

### スコープ

```bash
pcl impact --diff --for-task T-0001 --json
pcl impact --diff --for-job J-0001 --json
pcl context pack --task T-0001 --include-code-context --require-bound-receipt --json
```

### 成功条件

- code context receipt が task/job target に明示的に bound される。
- context pack が matching receipt を優先する。
- `--require-bound-receipt` で不一致を fail にできる。
- unbound latest fallback は warning として扱われる。
- receipt staleness が pack 内で分かる。

### 非スコープ

- code index の大幅再設計
- 自動修正 agent の統合
- hosted code analysis

---

## v0.3.1: Master Trace / Intent Index v0

### 目的

マスター agent の作業ログを、worker agent が安全に pull context できる形で PLH に載せる。

これは、以下の運用を可能にするための土台である。

```text
Master agent が長文指示書を書かない
↓
Master transcript を evidence として残す
↓
安価な indexer が intent-index を作る
↓
Worker agent が context pack と source_paths を通じて読む
↓
Worker output を evidence として返す
↓
Master / human が review する
```

### スコープ

- `master-trace/v0` ガイドライン
- `intent-index/v0` ガイドライン
- context pack への optional `master_trace_context` section
- transcript 全文の inline 禁止
- source_ref / member_paths による原文参照
- LLM API 呼び出しは core に入れない

### intent-index/v0 例

```json
{
  "contract_version": "intent-index/v0",
  "source_evidence_id": "E-0012",
  "generated_by": "external-indexer",
  "items": [
    {
      "kind": "decision",
      "status": "final",
      "summary": "DB schema changes are out of scope for this worker task.",
      "source_ref": {
        "path": ".project-loop/evidence/adhoc-files/E-0012/session.md",
        "line_start": 42,
        "line_end": 51
      }
    },
    {
      "kind": "task_hint",
      "priority": "high",
      "summary": "Codex should implement the smallest safe validation fix.",
      "source_ref": {
        "path": ".project-loop/evidence/adhoc-files/E-0012/session.md",
        "line_start": 88,
        "line_end": 95
      }
    }
  ]
}
```

### 成功条件

- Master transcript を evidence として扱える。
- intent index は claim-not-fact として表現される。
- worker は source_paths から原文に戻れる。
- context pack に raw transcript 全文を inline しない。
- LLM API 依存が core に入らない。

---

## v0.4.0: Dogfood Operations

### 目的

PLH が実運用に耐えることを、PLH 自身または実リポジトリ上で示す。

### スコープ

- PLH 自身を PLH で運用した dogfood report
- もう 1 つの sample / external repo での運用 report
- Codex / Claude Code handoff runbook
- context pack token budget 実測
- evidence count / evidence health drift rate
- human gate 発生率
- loop completion metrics
- dashboard screenshot / report sample

### 成功条件

- `docs/dogfood-report-v0.4.md` が存在する。
- 少なくとも 1 つの実 handoff transcript が evidence として保存される。
- worker がどの context pack で作業したか追跡できる。
- 実運用で発生した混乱点と改善案が記録される。

---

## v0.5.0: Adoption / Distribution

### 目的

外部ユーザーが迷わず導入できる状態にする。

### スコープ

- README 再構成
- docs site または docs index
- examples/
- Codex / Claude Code quickstart
- plugin install guide
- `.project-loop` commit policy
- JSON contract stability policy
- issue templates / discussion templates

### 成功条件

- 初見ユーザーが 3 分で価値を理解し、10 分で最初の loop を作れる。
- README と docs の役割が分かれている。
- agent handoff use case が最初に見える。
- security warning が導入時に明確に伝わる。

---

## 9. 具体タスク案

以下は、そのまま GitHub Issue / agent-task として切れる粒度の提案である。

---

## PLH-0101: Evidence source drift health

### Goal

Copied evidence の元 source drift を `ok` と誤認させない。

### Scope

- `source_drifted` を warning classification に追加、または `artifact_health` / `source_health` を分離。
- missing source の test を追加。
- size mismatch source の test を追加。
- context pack / report / dashboard への表示方針を決める。

### Acceptance Criteria

- copied artifact が intact かつ source missing の場合、source warning が出る。
- copied artifact が corrupted の場合、artifact warning/error が出る。
- `pcl validate --strict --json` が通る。
- release note に意味論の変更が記載される。

---

## PLH-0102: Security policy v0.2.x update

### Goal

SECURITY.md を現在の release line と evidence copy の現実に合わせる。

### Scope

- Supported versions を v0.2.x に更新。
- copied evidence の機密性リスクを明記。
- `.project-loop` commit policy を明記。
- MCP exposure / raw evidence content policy を明記。

### Acceptance Criteria

- SECURITY.md が `0.2.x` を current supported line として示す。
- `.project-loop/evidence/adhoc-files/` の扱いが明記される。
- release checklist に security policy check が追加される。

---

## PLH-0103: Python version CI matrix

### Goal

Package metadata と CI coverage を整合させる。

### Scope

- Python 3.10 / 3.11 / 3.12 / 3.13 matrix を追加。
- 全 matrix で pytest を実行。
- smoke command を追加。
- build/twine/sdist contract は single canonical version に集約してよい。

### Acceptance Criteria

- CI matrix が全対応 Python version で通る。
- `pyproject.toml` classifiers と CI が一致する。
- release note に matrix 結果が載る。

---

## PLH-0104: Evidence copy lock observability

### Goal

`evidence add --copy` の並列運用リスクを観測可能にする。

### Scope

- copy duration を計測。
- copied total bytes / member count を記録。
- DB write lock duration を可能な範囲で計測。
- concurrent copy stress test を追加。

### Acceptance Criteria

- concurrent `evidence add --copy` が deterministic に成功する。
- slow copy の原因を event / debug output で把握できる。
- ID allocation safety を維持する。

---

## PLH-0105: Target-bound code context receipts

### Goal

Code context receipt を task/job に明示的に束縛する。

### Scope

- `pcl impact --diff --for-task T-XXXX`
- `pcl impact --diff --for-job J-XXXX`
- receipt に binding metadata を追加。
- `pcl context pack --require-bound-receipt` を追加。
- unbound fallback warning を実装。

### Acceptance Criteria

- task context pack は matching task-bound receipt を使う。
- job context pack は matching job-bound receipt を使う。
- mismatched receipt は warning または fail になる。
- source_commands / source_paths の再取得性が維持される。

---

## PLH-0106: Master trace evidence contract

### Goal

Master / orchestrator agent の session transcript を worker handoff に使える evidence として扱う。

### Scope

- `master-trace/v0` docs を追加。
- `intent-index/v0` docs を追加。
- model-derived index は claim-not-fact として扱う。
- context pack に optional `master_trace_context` section を追加。
- raw transcript 全文は inline しない。
- LLM API 呼び出しを core に入れない。

### Acceptance Criteria

- worker は task context pack から master trace evidence path を見つけられる。
- intent index item は source_ref を持つ。
- source_ref から copied evidence の原文に戻れる。
- docs に Fable / Claude Code / Codex handoff example がある。

---

## PLH-0107: README adoption split

### Goal

初見ユーザーが最初の 3 分で価値を理解できるようにする。

### Scope

- README 冒頭を product pitch / quickstart に絞る。
- command surface を `docs/operator-manual.md` へ移す。
- contracts を `docs/contracts.md` へ移す。
- agent handoff を `docs/agent-handoff.md` へ移す。

### Acceptance Criteria

- README が短くなり、導入に集中する。
- 詳細情報は docs に失われず残る。
- Codex / Claude Code use case が README 上部から辿れる。

---

## PLH-0108: Release checklist contract

### Goal

毎回の release を再現可能にする。

### Scope

`docs/release-checklist.md` を追加し、以下を含める。

- version bump
- changelog / release note
- ruff
- pytest matrix
- build
- twine check
- sdist contracts
- fresh wheel smoke
- `pcl validate --strict --json`
- `pcl render --json`
- SECURITY.md version check
- PyPI metadata check

### Acceptance Criteria

- v0.2.4 release がこの checklist に沿って実施できる。
- release note から checklist 結果が追跡できる。

---

## PLH-0109: Roadmap and agent-task index

### Goal

`agent-tasks` を透明な backlog / design history として管理する。

### Scope

- `agent-tasks/README.md` を追加。
- ID / title / status / milestone / priority / area を一覧化。
- active / proposed / completed を区別。

### Acceptance Criteria

- 実装担当者と agent が次の task を見つけやすい。
- completed design history と active backlog が混ざらない。

---

## PLH-0110: Two-repo dogfood report

### Goal

PLH が自身以外の repo でも機能することを示す。

### Scope

- PLH repo 自身で dogfood。
- もう 1 つ sample / external repo で dogfood。
- task creation から evidence / context pack / completion / review まで記録。
- metrics を収集。

### Acceptance Criteria

- `docs/dogfood-report-v0.4.md` が追加される。
- 2 repo の実行例がある。
- context pack と evidence の有用性 / 問題点が記録される。

---

## 10. Master Trace / Pull Context 構想の組み込み方

### 10.1 背景

AI agent 間 handoff では、従来以下の方式が主流である。

```text
Master agent が長文指示書を書く
↓
Worker agent が指示書を読む
↓
Worker が実装する
```

しかし output token は input token より高価であり、さらに長文指示書はマスター agent の認知リソースを消費する。

そこで、以下の方式が有望である。

```text
Master agent は作業ログ・判断・独り言を残す
↓
PLH が transcript / evidence / intent-index として保持する
↓
Worker agent は context pack から必要な文脈を pull する
↓
Worker が自律的に作業する
```

### 10.2 ただし生ログ丸投げは危険

raw transcript を worker に丸ごと渡すだけでは危険である。

理由は以下。

```text
仮説と決定が混ざる
撤回された案を拾う
雑談や古い方針を誤認する
責任境界が曖昧になる
secret が混入する可能性がある
```

したがって、PLH に組み込むべき形は以下である。

```text
raw transcript        = evidence artifact
intent index          = model-derived evidence artifact
context pack          = worker handoff contract
source_paths          = 原文に戻るための参照
worker output         = evidence
master review         = decision / checkpoint
```

### 10.3 推奨フロー

```bash
pcl evidence add \
  --file .work/fable/session-2026-07-08.md \
  --summary "Master planning session transcript" \
  --command "Recorded from Fable master session" \
  --copy \
  --task T-0001 \
  --json
```

```bash
pcl evidence add \
  --file .work/fable/intent-index-2026-07-08.json \
  --summary "Intent index derived from master transcript" \
  --command "external intent-indexer over master transcript" \
  --copy \
  --task T-0001 \
  --json
```

```bash
pcl context pack \
  --task T-0001 \
  --role implementer \
  --include-code-context \
  --include-master-trace \
  --max-tokens 12000 \
  --json
```

### 10.4 Context pack への追加例

```json
{
  "master_trace_context": {
    "contract_version": "master-trace-context/v0",
    "trace_evidence_id": "E-0012",
    "intent_index_evidence_id": "E-0013",
    "trust_model": "claims-not-facts",
    "raw_transcript_inlined": false,
    "source_paths": [
      ".project-loop/evidence/adhoc-files/E-0012/session-2026-07-08.md",
      ".project-loop/evidence/adhoc-files/E-0013/intent-index-2026-07-08.json"
    ],
    "warnings": [
      "Intent index is model-derived and must not be treated as source of truth.",
      "Inspect source_ref lines when task intent is ambiguous."
    ]
  }
}
```

### 10.5 実装時の禁止事項

```text
禁止: pcl core が LLM API を呼んで intent-index を生成する
禁止: raw transcript 全文を context pack にデフォルト inline する
禁止: dashboard HTML を worker context にする
禁止: events.jsonl を worker に直接読ませて推論させる
禁止: model-derived summary を fact として扱う
```

---

## 11. 会議アジェンダ案

### 11.1 90分レビュー会議

#### 0〜10分: 目的確認

- v0.2.3 の位置づけ確認
- 本会議で決めることの確認
- v0.2.4 / v0.3.0 の切り分け確認

#### 10〜25分: Evidence health 意味論

議題。

```text
copied artifact が intact なら health ok でよいか？
source drift は warning か？
artifact_health と source_health を分けるか？
```

決定事項。

```text
- v0.2.4 での最小修正方針
- 中期 schema / contract 変更の要否
```

#### 25〜35分: Security policy

議題。

```text
SECURITY.md の supported versions 更新
copied evidence の commit policy
MCP exposure policy
secret redaction の責任境界
```

決定事項。

```text
- v0.2.x supported line の表記
- .project-loop/evidence の扱い
```

#### 35〜50分: Target-bound context

議題。

```text
code context receipt は task/job に bound すべきか？
--require-bound-receipt をいつ導入するか？
unbound fallback は warning か failure か？
```

決定事項。

```text
- v0.3.0 の中核 scope
- JSON contract の方向性
```

#### 50〜65分: Master Trace / Intent Index

議題。

```text
master transcript を first-class entity にするか？
まず evidence pattern に留めるか？
intent-index/v0 の最小 contract は何か？
```

決定事項。

```text
- v0.3.1 の scope
- core に LLM を入れない方針の確認
```

#### 65〜75分: README / Adoption

議題。

```text
README の主対象は誰か？
初見ユーザーに何を最初に見せるか？
agent handoff use case をどこに置くか？
```

決定事項。

```text
- README split 方針
- docs 構造
```

#### 75〜85分: Roadmap 合意

議題。

```text
v0.2.4 / v0.3.0 / v0.3.1 / v0.4.0 の順番
v0.2.4 に入れる P1/P2
```

決定事項。

```text
- 次リリースに入れる Issue
- 担当者
- acceptance criteria
```

#### 85〜90分: Close

- 次 action 確認
- リリース目標確認
- unresolved decisions の記録

---

## 12. チームが決めるべき論点

### 論点1: Evidence health を単一値にするか、分離するか

推奨は分離である。

```json
{
  "artifact_health": "ok",
  "source_health": "warning"
}
```

単一の `health` では、artifact durability と source freshness が混ざる。

### 論点2: ID gap を許容するか

現状の sequential ID は見やすい。だが parallel agent usage を強めるなら、ID gap を許容する設計も検討すべきである。

```text
番号の美しさ
vs
parallel write の効率
```

短期は現状維持でよい。中期は観測結果で判断する。

### 論点3: Context pack の contract stability

`context-pack/v1` はどこまで後方互換を保証するのか。

決めるべきこと。

```text
additive field は patch/minor で許可するか？
required_sections の変更は breaking か？
JSON shape の安定範囲はどこか？
```

### 論点4: Master Trace を first-class entity にする時期

推奨は以下。

```text
v0.3.1: evidence pattern + docs + optional context section
v0.4以降: dogfood 結果に応じて first-class trace entity を検討
```

早すぎる抽象化は避けるべきである。

### 論点5: `.project-loop` を Git 管理する方針

決めるべきこと。

```text
.project-loop/project.db は commit するか？
.project-loop/events.jsonl は commit するか？
.project-loop/evidence/adhoc-files は commit しない方針か？
reports / dashboard はどう扱うか？
```

v0.2.3 で copied evidence が入ったため、この議題の重要度は上がった。

### 論点6: README の主対象

推奨する主対象は以下。

> AI coding agent を日常的に使う個人開発者 / 小規模開発者が、作業の暴走・忘却・証拠不足を防ぐための local control plane。

大企業向け workflow platform の方向に見せるのは、現段階では早い。

---

## 13. 成功指標

今後の PLH は、単なる機能数ではなく、以下の指標で評価するべきである。

### 13.1 Handoff 成功指標

| 指標 | 意味 |
|---|---|
| worker_handoff_success_rate | context pack を受けた worker が追加質問なしで作業を完了できた割合 |
| context_pack_reopen_rate | worker が source_paths を辿って原文を確認した割合 |
| handoff_confusion_count | worker が task intent を誤解した回数 |
| master_brief_tokens_saved | master が長文指示書を書かずに済んだ token 量の推定 |

### 13.2 Evidence 信頼性指標

| 指標 | 意味 |
|---|---|
| evidence_health_warning_rate | warning を持つ evidence の割合 |
| source_drift_rate | source_drifted が発生した割合 |
| copied_artifact_corruption_count | copied artifact の hash mismatch / missing 件数 |
| evidence_link_coverage | completed task のうち evidence linked なものの割合 |

### 13.3 Context Pack 品質指標

| 指標 | 意味 |
|---|---|
| average_context_pack_tokens | 平均 context pack size |
| required_sections_omitted_count | required section が budget で落ちた件数 |
| stale_code_context_warning_count | stale receipt warning 件数 |
| bound_receipt_coverage | task/job context pack のうち bound receipt を持つ割合 |

### 13.4 Release 品質指標

| 指標 | 意味 |
|---|---|
| ci_matrix_pass_rate | 対応 Python version matrix の通過率 |
| fresh_wheel_smoke_pass | fresh install smoke の通過 |
| release_checklist_completion | checklist 完了率 |
| migration_strict_validate_pass | migration 後 strict validate の通過 |

---

## 14. リスクと緩和策

### リスク1: Feature creep

PLH はすでに概念が多い。ここで機能を増やし続けると、新規ユーザーに伝わらなくなる。

緩和策。

```text
v0.2.4〜v0.3.1 は trust / target binding / handoff に集中する
README を導入に絞る
operator manual と internals を分離する
```

### リスク2: Dashboard が source of truth 化する

人間が dashboard を見るのはよい。だが agent が dashboard HTML を読むようになると危険である。

緩和策。

```text
machine context は pcl JSON / context pack / evidence paths に限定
dashboard HTML は human view と明記
```

### リスク3: Model-derived summary を fact として扱う

intent index や summary は便利だが、事実ではない。

緩和策。

```text
claims-not-facts vocabulary を徹底
source_ref / source_paths を必須に近づける
raw evidence contents は必要時に人間/agent が明示的に読む
```

### リスク4: copied evidence に secret が残る

`--copy` は durability を高めるが、secret retention risk も高める。

緩和策。

```text
SECURITY.md 更新
copy command の warning 強化
sensitive path detection の明示
.gitignore / commit policy 明記
```

### リスク5: Core が LLM-dependent になる

intent-index を core が LLM API で作り始めると、PLH の local-first / deterministic な強みが崩れる。

緩和策。

```text
LLM extraction は external agent / plugin 側
PLH core は artifact を evidence として記録・検証・参照するだけ
```

---

## 15. 実装担当への最終提言

v0.2.3 は良いリリースである。特に evidence durability / task linking / linked evidence context pack は、PLH が agent handoff control plane に進むための重要な土台になっている。

しかし、ここから先で重要なのは「広げること」ではない。

重要なのは、以下である。

```text
証拠の意味論を正しくする
context を task/job に束縛する
agent handoff の契約を強くする
Master Trace を安全に取り込む
実運用で dogfood する
導入導線を絞る
```

次のリリースでは、派手な機能よりも v0.2.4 Trust Patch を優先すべきである。

その後、v0.3.0 Target-Bound Context に進むべきである。ここが入ると PLH は「便利な CLI」から「agent handoff の制御層」に進化する。

さらに v0.3.1 で Master Trace / Intent Index を載せれば、以下の独自価値を持てる。

> **高性能 master agent に長文指示書を書かせず、worker agent が必要な文脈を安全に pull して作業する。**

この方向は、PLH の現在の設計思想と非常に相性がよい。

最後に、厳しめに言う。

PLH がここで hosted backend や派手な dashboard に向かうと、よくある agent workflow tool の一つに埋もれる可能性が高い。

勝ち筋はそこではない。

勝ち筋は、**エージェント間の申し送り・証拠・文脈・検証を、ローカルで再現可能に支配すること**である。

この一点に集中すれば、Project Loop Harness はかなり強いプロダクトになる。

---

## Appendix A. 参考リンク

1. v0.2.3 release note
   https://github.com/mocchalera/project-loop-harness/releases/tag/v0.2.3

2. README.md v0.2.3
   https://github.com/mocchalera/project-loop-harness/blob/v0.2.3/README.md

3. docs/architecture.md v0.2.3
   https://github.com/mocchalera/project-loop-harness/blob/v0.2.3/docs/architecture.md

4. docs/context-pack.md v0.2.3
   https://github.com/mocchalera/project-loop-harness/blob/v0.2.3/docs/context-pack.md

5. SECURITY.md v0.2.3
   https://github.com/mocchalera/project-loop-harness/blob/v0.2.3/SECURITY.md

6. pyproject.toml v0.2.3
   https://github.com/mocchalera/project-loop-harness/blob/v0.2.3/pyproject.toml

7. CI workflow v0.2.3
   https://github.com/mocchalera/project-loop-harness/blob/v0.2.3/.github/workflows/ci.yml

8. evidence.py v0.2.3
   https://github.com/mocchalera/project-loop-harness/blob/v0.2.3/src/pcl/evidence.py

9. ids.py v0.2.3
   https://github.com/mocchalera/project-loop-harness/blob/v0.2.3/src/pcl/ids.py

10. db.py v0.2.3
    https://github.com/mocchalera/project-loop-harness/blob/v0.2.3/src/pcl/db.py

---

## Appendix B. 実装担当向け短縮版

### 次にやる順番

```text
1. source_drifted health 修正
2. SECURITY.md v0.2.x 更新
3. Python CI matrix
4. evidence copy observability
5. release checklist
6. target-bound code context receipt
7. master-trace / intent-index v0
8. dogfood report
9. README / docs split
```

### 一番大事な方針

```text
CLI が mutation boundary
context pack が worker handoff contract
evidence は source_paths で原文に戻れる
model-derived summary は claim-not-fact
core は LLM API を呼ばない
raw evidence contents は inline しない
```

### 一番危険な方向

```text
hosted backend に早く行く
Dashboard を source of truth にする
MCP を runtime にする
LLM summary を事実扱いする
生ログを worker に丸投げする
```

### 最も強いプロダクト説明

> Project Loop Harness は、Codex / Claude Code などの AI coding agent に、忘れず・暴走せず・証拠を残して・次にやることを判断させるための local control plane である。
