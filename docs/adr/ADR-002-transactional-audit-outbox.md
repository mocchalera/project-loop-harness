# ADR-002: SQLite transaction を権威とし、JSONL は transactional outbox から投影する

- Status: Proposed
- Date: 2026-07-10
- Owners: Architecture / Reliability
- Decision gate: Maintainer と、実装担当ではない reviewer 1 名以上
- Supersedes on acceptance: `docs/adr/0001-hybrid-state.md` の SQLite/JSONL 整合性に関する dual-write 前提
- Origin: `docs/roadmap/integrated/adr/ADR-002-transactional-audit-outbox.md`

## 1. Context

Project Loop Harness (PLH) は normalized current state を SQLite に、監査表示を
`.project-loop/events.jsonl` に保存している。現行 `append_event` は次の順で動く。

```text
caller: domain row INSERT/UPDATE
  -> append_event: events.jsonl を append
  -> append_event: SQLite events row を INSERT
  -> caller: conn.commit()
```

`append_event` は transaction を開始せず、commit も rollback も行わない。このため
JSONL append 後、SQLite commit 前の exception、process kill、disk error、caller の
rollback により「JSONL にあるが DB にない」孤児行が残る。逆方向の failure も、将来
write order だけを入れ替えれば解消するものではない。filesystem と SQLite の atomic
commit はできないため、現在の dual-write を維持して両方を同時に権威とする設計は
採用しない。

本 ADR は設計のみを固定する。schema migration、runtime、projector、CLI の実装は
0128 以降の scope とする。

### 1.1 Goal, scope, and success conditions

Goal は、1 回の mutation の authoritative commit point と、commit 前後の全 failure の
検出・復旧契約を、0128 が追加判断なしで実装できる粒度に固定することである。

In scope:

- authority、transaction/projector boundary、schema、ordering、idempotency、retention;
- current caller/commit ownership、legacy mapping、Evidence reconciliation;
- crash/concurrency/migration failure semantics、operations、rollout/rollback;
- 0128 implementation handoff と 0129--0130 の責務境界。

Non-goals:

- outbox/migration/CLI の production implementation;
- JSONL-only から arbitrary domain DB の完全 rebuild;
- cloud replication、background daemon、unknown/corrupt data の自動破棄;
- cryptographic tamper-evidence の v1 implementation。

本設計の成功条件は、source of truth、transaction boundary、outbox state machine、failure
matrix、legacy plan、rollback が矛盾なく定義され、全 production caller が inventory 化され、
0128 の schema/runtime/test acceptance と 0129 の CLI acceptance が本文から導けることである。
ADR 自体の acceptance は maintainer と independent reviewer の記録を必要とする。

## 2. Decision summary

この ADR が Accepted になった場合、次を契約とする。

1. SQLite の domain state、`events`、`outbox_records` を source of truth とする。
2. 1 回の domain mutation、対応する event row、JSONL sink 用 outbox row を同一の
   explicit SQLite transaction で commit する。
3. JSONL は commit 済み event の append-only projection とし、DB の rebuild source
   にはしない。
4. projector は DB commit 後に `events.sequence` 順で outbox を処理する。投影失敗で
   commit 済み domain mutation を rollback しない。
5. mutation command は commit 後に bounded synchronous projection を 1 回試行する。
   background daemon は v1 では導入しない。明示 flush と、後続の mutation による
   retry を可能にする。
6. JSONL append は event ID、sequence、canonical record の一致確認によって冪等に
   する。DB commit 済みだが JSONL pending は valid recoverable state である。
7. SQLite から JSONL 全体を rebuild できる。JSONL から arbitrary domain DB を完全
   rebuild する保証は v1 に含めない。
8. v1 は append-only/rebuildable audit を保証するが、tamper-evident audit は保証しない。
   hash chain は deferred とすることを推奨し、最終判断は本 ADR の human gate に残す。

## 3. Authority, durability, and retention

| Surface | Role | Authority | v1 retention |
|---|---|---|---|
| SQLite domain tables | current normalized state | authoritative | project lifetime |
| SQLite `events` | committed event history and total order | authoritative | project lifetime; automatic purge 禁止 |
| SQLite `outbox_records` | projection delivery state | authoritative | delivered row も project lifetime; compaction は別 ADR |
| `events.jsonl` | human/tool-readable append-only projection | derived | rebuild 時は backup 後に置換可能 |
| Evidence metadata | Evidence lifecycle/state | authoritative in SQLite | owning record の policy に従う |
| Evidence files | content bytes | filesystem object; SQLite metadata と reconciliation | unknown/orphan を自動削除しない |
| dashboard/reports | review view | derived | 再生成可能 |

「append-only」は通常の projector が既存 logical event を変更・削除しないという運用契約
であり、「改ざんを検知できる」という意味ではない。SQLite が破損または失われた場合の
recovery は SQLite backup/WAL recovery の範囲であり、JSONL だけから domain tables を
復元できるとは主張しない。

## 4. Transaction boundary

### 4.1 Mutation unit of work

すべての state-changing public operation は、次の explicit boundary を所有する。

```text
acquire shared project-operation lock
connect (foreign_keys=ON, busy_timeout=30_000 ms)
BEGIN IMMEDIATE
  validate state used by mutation
  mutate domain rows
  INSERT events (..., sequence)
  INSERT outbox_records (..., event_id, sink='jsonl', status='pending')
COMMIT                         <-- authoritative commit point
best-effort synchronous projector attempt
release lock
```

- transaction coordinator/public operation が begin/commit/rollback を所有する。
- `append_event` は event/outbox insert だけを行い、commit、JSONL I/O、retry を行わない。
- helper は connection を受け取り、外側の unit of work に参加する。nested commit は禁止する。
- sequence allocation と competing writer の stale read を避けるため `BEGIN IMMEDIATE` を
  domain read より前に行う。
- 現行 `SQLITE_BUSY_TIMEOUT_MS = 30_000` を維持する。timeout は recoverable contention と
  して structured error を返し、暗黙の無制限 retry はしない。
- projector failure 後に mutation を再実行してはならない。結果には
  `committed: true`, `projection: pending`, event ID/sequence を含める。

### 4.2 Projector boundary

projector は mutation transaction と別 boundary で動く。

```text
acquire shared project-operation lock
acquire exclusive JSONL-projector lock
read next deliverable outbox row by events.sequence
compare JSONL prefix/tail with event ID + sequence + canonical bytes
append one canonical UTF-8 JSON line using one write
flush + fsync file                         <-- durable projection point
BEGIN IMMEDIATE
  mark matching outbox row delivered
COMMIT
release locks
```

JSONL の同時 writer は 1 process に直列化する。projector retry 時:

- line が存在し canonical record と一致するなら、再 append せず delivered を記録する。
- line が存在しないなら append する。
- 同じ sequence/event ID で内容が異なる、途中 line、gap、unknown line がある場合は自動で
  上書き・truncate せず `failed_needs_review` にする。

`flush()` だけでなく `fsync()` 成功後にのみ delivered とする。fsync 非対応 platform は
silent downgrade せず capability error とし、0128 の platform contract/test に記録する。

### 4.3 Locks and concurrency

- migration は project-operation lock を exclusive で取得する。
- normal mutation と projector は同 lock を shared で取得し、migration と並行しない。
- JSONL-projector lock は projector/rebuild 同士を exclusive にする。
- lock は `.project-loop/project.lock` と `.project-loop/events-jsonl.lock` に対する OS advisory
  lock とする。取得 timeout は SQLite と同じ 30 秒。support しない platform では lock を
  省略せず明示的に失敗する。lock file の内容は state/source of truth として読まない。
- SQLite の `BEGIN IMMEDIATE` が event sequence と domain writes の writer serialization を
  担う。filesystem lock だけを DB correctness の根拠にしない。
- migration は transaction 内で schema statement、backfill、`schema_migrations`、metadata、
  migration event/outbox をまとめる。現行の bare `executescript` による statement 単位の
  partial apply を残さない。

## 5. Proposed schema for 0128

次の空き migration（現時点では `008`）で、最終形として最低限次を満たす。実際の
SQLite migration は table rebuild を使ってよいが、完了後の schema contract は同一とする。

```sql
CREATE TABLE events (
  id           TEXT PRIMARY KEY,
  sequence     INTEGER NOT NULL UNIQUE CHECK(sequence > 0),
  event_type   TEXT NOT NULL,
  entity_type  TEXT NOT NULL,
  entity_id    TEXT,
  payload_json TEXT NOT NULL,
  created_at   TEXT NOT NULL
);

CREATE TABLE outbox_records (
  id              TEXT PRIMARY KEY,
  event_id        TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
  sink            TEXT NOT NULL CHECK(sink IN ('jsonl')),
  idempotency_key TEXT NOT NULL UNIQUE,
  status          TEXT NOT NULL CHECK(status IN (
                    'pending', 'retry_wait', 'delivered', 'failed_needs_review'
                  )),
  attempts        INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
  next_attempt_at TEXT,
  last_error      TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  delivered_at    TEXT,
  UNIQUE(event_id, sink)
);

CREATE INDEX idx_outbox_delivery
  ON outbox_records(sink, status, next_attempt_at, event_id);
```

`idempotency_key` は v1 では `jsonl:<event-id>` とする。projector は join した
`events.sequence` で処理し、outbox `id` や timestamp で ordering しない。新 event の
sequence は同じ `BEGIN IMMEDIATE` transaction 内で現在の最大値 + 1 として確保し、
UNIQUE constraint を最終防衛線とする。sequence は project 内で単調増加し、欠番は
許容しない。rollback した allocation は event として存在しないため gap に数えない。

投影する additive JSONL envelope は既存 reader 互換の field 名を維持する。

```json
{
  "created_at": "2026-07-10T00:00:00Z",
  "entity_id": "G-0001",
  "entity_type": "goal",
  "event_type": "goal_created",
  "id": "EV-...",
  "payload": {},
  "sequence": 123
}
```

canonical bytes は UTF-8、1 object/line、`ensure_ascii=False`、key sort、compact separators、
末尾 LF とする。legacy line は parsed object の field equality で対応付け、空白や key order
の違いを content mismatch としない。new line は canonical bytes でも照合する。projector の
delivery query は `outbox_records JOIN events` を使い `ORDER BY events.sequence` とする。

### 5.1 Outbox state machine

```text
                   transient I/O error
PENDING ---------------------------------> RETRY_WAIT
   |                                            |
   | append/fsync + delivered commit            | next_attempt_at reached
   v                                            v
DELIVERED <----------------------------------- PENDING

PENDING/RETRY_WAIT -- mismatch, malformed tail, or attempt limit --> FAILED_NEEDS_REVIEW
FAILED_NEEDS_REVIEW -- explicit reviewed repair ------------------> PENDING or DELIVERED
```

- attempt を開始する時点で `attempts` を増やす。
- retry delay は `min(2^(attempts-1), 300)` 秒、最大 5 attempts とする。test を決定論的に
  するため v1 は jitter を入れない。
- process crash により attempt の記録だけが失われても correctness は変わらない。JSONL
  tail comparison が idempotency を担う。
- attempt limit、content mismatch、malformed/unknown tail は poison record として
  `failed_needs_review` に置く。domain state は保持し、normal projection はその sequence
  以降を追い越さない。

## 6. Current caller and commit-ownership inventory

2026-07-10、base `c9ebd327fd03c6243191ed618d9cff18ecc83783` で production code を
静的調査した。`append_event` 定義を除き 21 module、68 call site であり、未調査 caller は
ない。全 call site で `append_event` 自身ではなく caller/outer operation が commit する。

| Module | Calls | Functions containing calls | Current commit owner |
|---|---:|---|---|
| `agents.py` | 1 | `ingest_agent_run` | same public function |
| `checkpoints.py` | 1 | `record_checkpoint` | same public function |
| `code_context/eval.py` | 2 | `propose_retrieval_fixture`, `record_retrieval_baseline` | same function; explicit rollback handlers |
| `code_context/receipts.py` | 1 | `_record_context_receipt` | same function; explicit rollback handler |
| `code_context/store.py` | 1 | `build_code_index` | same function; explicit rollback handler |
| `commands.py` | 4 | `create_goal`, `add_feature`, `set_feature_status`, `open_defect` | same public function |
| `decisions.py` | 3 | `open_decision`, `resolve_decision`, `waive_decision` | same public function |
| `dispatch.py` | 7 | `assign_job`, `lease_job`, `heartbeat_job`, `release_job`, `reap_expired_leases`, `_start_workflow_run_if_needed` | public function; helper joins `lease_job`; reap opens escalations later in separate transactions |
| `escalations.py` | 2 | `open_escalation`, `_close_escalation` | same operation |
| `evidence.py` | 1 | `record_adhoc_evidence` | same function; explicit rollback/partial file cleanup |
| `init_project.py` | 1 | `init_project` | same function |
| `lifecycle.py` | 19 | public job/run/goal/defect transitions; `_cancel_active_jobs_for_failed_run`, `_run_started_update`, `_refresh_feature_status_for_defect` | outer public lifecycle operation; helpers do not commit |
| `migrations.py` | 2 | `apply_migrations` (`migration_applied`, `schema_metadata_repaired`) | migration loop/repair branch after `executescript` |
| `registry.py` | 3 | `register_agent`, `update_agent`, `retire_agent` | same public function |
| `stories.py` | 5 | `draft_story`, `plan_test_case`, `_transition_story`, `_transition_test_case`, `_set_feature_status` | outer transition; `_set_feature_status` does not commit |
| `tasks.py` | 4 | `create_task`, `set_task_status`, `add_dependency`, `remove_dependency` | same public function |
| `verification_feedback.py` | 1 | `record_verification_feedback` | same function; explicit rollback handler |
| `workflow_executor.py` | 3 | `_mark_execution_started`, `_mark_execution_resumed`, `_mark_execution_finished` | same helper function |
| `workflow_proposals.py` | 3 | `propose_workflow`, `approve_workflow_proposal`, `cancel_workflow_proposal` | same operation |
| `workflow_sandbox.py` | 1 | `_record_sandbox_evidence` | same function; explicit rollback handler |
| `workflows.py` | 3 | `run_workflow` (run, retry, and per-job events) | one commit after all events/jobs |
| **Total** | **68** | | |

### 6.1 Current mutation/file write order

| Path class | Current order before 0128 | Consequence |
|---|---|---|
| ordinary DB mutation | domain DB write -> JSONL append -> events INSERT -> caller commit | rollback/crash can leave JSONL-only line |
| multi-event helper | several domain writes and JSONL appends -> several events INSERTs -> one outer commit | failure can leave an arbitrary JSONL suffix for a fully rolled-back DB transaction |
| migration | `executescript` statements -> metadata -> JSONL append -> events INSERT -> commit | statement-between crash may partially apply DDL; audit event may become orphan |
| `record_adhoc_evidence` | optional copies -> temp manifest write -> rename -> evidence metadata/link -> JSONL -> event INSERT -> commit | crash can leave READY-looking file/copy without metadata; caught errors try cleanup but kill cannot |
| receipt/sandbox/proposal/workflow prompt artifacts | file creation/replace and DB metadata/event are separate filesystem/DB steps | orphan file or metadata-to-missing-file is possible depending crash point |

`reap_expired_leases` は lease state/events を 1 transaction で commit した後、blocked item
ごとに escalation を別 transaction で作る。したがって outbox 導入後も command 全体を
単一 transaction と誤って説明してはならない。それぞれの committed mutation は event と
outbox を持つが、後段 escalation の failure は再実行/検出可能な workflow-level partial
completion として扱う。

## 7. Failure model and recovery matrix

`C` は authoritative SQLite transaction commit、`F` は JSONL file fsync、`D` は
outbox delivered commit を表す。

| Crash/failure point | Durable result | Detection | Recovery |
|---|---|---|---|
| domain/event/outbox INSERT 前 | 何も commit されない | command error; audit は clean | retry command is safe |
| INSERT 中、`C` 前 | transaction 全体 rollback。JSONL 未変更 | DB に event/outbox がない | retry command is safe |
| `C` 直前 | old state または transaction 全体のどちらか。SQLite atomicity に従う | event/outbox/domain の同一 transaction presence | event がなければ retry、あれば mutation を再実行せず projection のみ |
| `C` 直後、projector 前 | domain/event/outbox pending、JSONL は旧 prefix | pending outbox + DB/JSONL count difference | projector flush; valid recoverable state |
| JSONL append 前 | outbox pending/retry_wait、JSONL は旧 prefix | pending row | backoff 後 retry |
| JSONL append/write 中、`F` 前 | line 不在または partial tail | JSON parser/tail canonical comparison | stop ordering; backup and reviewed repair/rebuild。自動 truncate 禁止 |
| `F` 直後、`D` 前 | canonical line は存在、outbox は pending | tail event ID/sequence/content が DB と一致 | retry は append せず delivered を commit |
| `D` 直後 | DB と JSONL が一致 | audit check clean | no-op |
| projector record N 実行中 | N より前は delivered、N は上記 append point のいずれか、N+1 以降は untouched | 最初の non-delivered sequence と JSONL tail | N から再開。後続を追い越さない |
| retry limit 到達 | domain/event 保持、outbox failed_needs_review | poison count/status | human-reviewed repair; silent skip 禁止 |
| migration statement 間、migration commit 前 | explicit migration transaction 全体 rollback | schema version/table/columns は pre-migration のまま | same binary で migration retry |
| migration commit 直後 | schema/backfill/migration event/outbox が全て present | `schema_migrations`, metadata, schema inspection | no DDL retry; projection retry only |
| Evidence temp write 前/中 | temp absent または incomplete | Evidence scan by expected hash/size | temp quarantine; metadata を READY にしない |
| Evidence rename 前 | verified temp + PENDING metadata、final absent | metadata state + temp/final paths | hash 再検証後 rename retry |
| Evidence rename 直後、READY commit 前 | final file exists、metadata PENDING | reconciliation scan | hash 一致なら READY transition; 不一致なら MISSING/ORPHANED review |
| Evidence READY commit 直後 | metadata/file pair ready; its event may be pending projection | audit check | event projector retry |
| JSONL rebuild temp write/rename 前 | old JSONL intact、temp may exist | temp marker/hash | discard/quarantine temp after review; rebuild retry |
| JSONL rebuild rename 直後、repair event commit 前 | new verified JSONL installed、repair metadata/event absent | backup + before/after hash + DB comparison | record recovery outcome through reviewed repair path; do not rebuild DB from log |

### 7.1 Detection commands and exit semantics

0129 は次を実装する。0128 は少なくとも structured projector result と pending status を
内部/public mutation result へ返し、read-only command が暗黙 flush しないことを保証する。

| Command/result | Mutation | Exit 0 | Exit 6 | Exit 7 | Exit 8 |
|---|---|---|---|---|---|
| `pcl audit check [--json]` | none | clean | supported recoverable or review-required issue | unknown/unsupported format | internal failure |
| `pcl audit flush [--json]` | pending delivery state + JSONL | all eligible rows delivered/no-op | pending/backoff/poison remains | unsupported format/platform | internal failure |
| `pcl audit repair --dry-run [--json]` | none | complete supported plan or clean no-op | issue exists but only partial/no safe plan | unsupported anomaly | internal failure |
| `pcl audit repair --apply [--json]` | backup + reviewed repair | applied/no-op | still pending or needs review | refused unsupported anomaly | internal failure |
| `pcl audit rebuild-jsonl --from-sqlite [--output P] [--apply]` | output only unless `--apply` | verified output/apply | recoverable I/O/interruption | DB/event contract unsupported | internal failure |
| mutation whose commit succeeds but projection fails | committed DB; outbox pending | projection delivered | `committed: true` and do-not-retry-mutation guidance | unsupported sink/format | internal failure only if commit outcome is known and reportable |

既存 `pcl validate --strict` の `_validate_audit_log_integrity` は DB/JSONL の ID set、rowid
order、field/payload equality、duplicate/malformed line を既に検出する。0129 はこれを退行
させず、sequence/outbox/Evidence classification を加える。現在は DB event 欠落も JSONL
event 欠落も同じ error だが、以後は source of truth に基づき「projectable DB event」と
「unsupported JSONL-only anomaly」を区別する。

## 8. Legacy JSONL and migration plan

migration は既存 `events` row に `rowid` 昇順で 1 から contiguous sequence を割り当てる。
legacy JSONL は sequence/hash がなくても直ちに不正とはしない。migration 前に read-only
preflight を行い、次の順で対応付ける。

1. JSONL `id` と DB `events.id` を一致させる。
2. `event_type`, `entity_type`, `entity_id`, parsed payload, `created_at` の完全一致を確認する。
3. JSONL order が DB `rowid` order と一致することを確認する。
4. 一致した legacy prefix には migration が backfill した sequence を論理的に対応付け、
   outbox row を `delivered` として作る。既存 JSONL line は migration では書き換えない。
5. DB-only event が一致済み prefix の末尾にだけ存在する場合は `pending` とし、sequence 順に
   投影できる。JSONL file 自体がない場合も空 prefix として同じ扱いにする。
6. JSONL-only ID、duplicate ID、field mismatch、malformed line、order mismatch、DB-only
   interior gap は migration を exit 6/7 で止める。unknown line を import/delete/reorder しない。

ID すら持たない historical line は自動 import しない。診断上の deterministic correlation
key として `legacy-sha256:<SHA-256(canonical parsed object)>` を生成できるが、同じ content
の duplicate line は line number も併記して ambiguity を保持する。この key は DB event ID
ではない。将来 explicit import を設計する場合も、human-reviewed mapping artifact と original
file backup を必須にする。

`rebuild-jsonl --from-sqlite` は legacy row も current canonical event envelope（sequence を含む）
で書き出すため、apply 時には legacy text が変わり得る。必ず original file を backup し、
before/after SHA-256、event count、first/last sequence を report する。通常 migration は
legacy file を非破壊で維持する。

## 9. Evidence file reconciliation

filesystem と SQLite は同じ transaction に入らないため、Evidence bytes の完全原子性は
保証しない。0128 以降の Evidence write は次の lifecycle を採る。

```text
TEMP_WRITTEN -> PENDING -> atomic rename -> READY
      |            |              |
      +------------+--------------+-> MISSING / ORPHANED / NEEDS_REVIEW
```

- temp/final file は content hash と size を持つ。
- metadata PENDING/READY transition と対応 event/outbox は各 SQLite transaction で atomic。
- rename 前後の crash は §7 の reconciliation で収束させる。
- content-addressed final path の同一 hash は idempotent no-op として扱える。
- unknown orphan、hash mismatch、external path は自動 delete しない。0129 は report または
  quarantine を優先する。
- 既存 `record_adhoc_evidence` の caught-error cleanup は best effort であり、crash guarantee
  ではない。0128 は metadata state を導入するまで、その限界を明示する。

## 10. Hash-chain open decision and recommendation

### Recommendation: v1 guarantee から defer

本 ADR の human gate には、hash chain を v1 product guarantee に含めない案を推奨する。

根拠:

1. transactional outbox が解決するのは commit/projection の欠落・重複・順序であり、
   tamper evidence は別 threat model である。
2. local attacker が SQLite と JSONL の両方を書き換えられるなら、unkeyed chain は全体を
   再計算できる。外部 anchor、署名鍵、checkpoint retention なしでは強い改ざん保証にならない。
3. legacy canonicalization、rebuild 時の hash preservation、redaction/compaction policy を先に
   固定せず hash fields を v1 必須にすると、互換性を早期に凍結する。
4. sequence + canonical comparison + backup hash で、今回必要な crash recovery と accidental
   corruption detection は実現できる。

したがって v1 documentation は **append-only, ordered, rebuildable, and consistency-checked**
と表現し、**tamper-evident** と表現しない。後続 ADR で attacker model、canonical event bytes、
`previous_hash/event_hash`、trusted checkpoint/signature、key rotation、legacy genesis marker を
まとめて決める。本 ADR が Proposed の間、この項目も human open decision である。遅くとも
本 ADR の acceptance review で defer/include を記録し、未解決のまま 0128 を開始しない。

## 11. Projector start policy

v1 は「各 mutation commit 後に synchronous bounded attempt + explicit flush」を推奨する。

- normal success では利用者が従来どおり直後に JSONL を読める可能性が高い。
- daemon、scheduler、liveness management を追加しない。
- commit と projection の failure semantics を CLI result で直ちに伝えられる。
- backoff 中または poison record を超えて busy loop しない。
- read-only commands (`validate`, `audit check`, context packaging 等) は flush しない。
- explicit retry surface は `pcl audit flush [--json]` とし、0128 で projector contract と共に
  実装する。repair/rebuild UI は 0129 に残す。

fsync は default on とする。監査 projection を durable と報告する以上、OS page cache への write
だけを delivered と呼ばない。performance data により relaxed mode が必要になった場合は、
別名の durability mode と result field を設計し、default guarantee を silently 弱めない。

## 12. 0128 implementation handoff gate

0128 は本 ADR が maintainer + independent reviewer に Accepted されるまで merge しない。
実装完了には最低限次を要求する。

1. schema version/`schema.sql`/package migration を更新し、supported fixture version 全てから
   `events.sequence` と `outbox_records` へ upgrade できる。
2. migration preflight が §8 の exact legacy、missing JSONL、DB-only suffix、unsupported anomaly
   を区別し、legacy JSONL を migration 中に書き換えない。
3. current `executescript` path を explicit atomic migration transaction に置き換え、statement
   間 failure で partial schema/metadata/event が残らない。
4. common transaction coordinator が `BEGIN IMMEDIATE`/commit/rollback を所有し、68 current
   call site を新契約へ移行する。helper の nested commit と二重 projection がない。
5. `append_event` は event + outbox insert のみを行い、DB commit 前に JSONL を触らない。
6. projector は sequence ordering、exclusive writer、canonical line、flush/fsync、retry after
   append-before-delivered crash、duplicate suppression、poison stop を実装する。
7. commit 後 projector failure は domain/event/outbox を保持し、structured result に
   `committed: true`, pending count, first pending sequence, safe next action を返す。
8. read-only command は outbox stateを変更しない。background daemon と full repair UI は入れない。
   `pcl audit flush [--json]` だけを明示的な projection mutation surface とする。
9. rollback、post-commit projector failure、duplicate retry、sequential/concurrent ordering、legacy
   fixture、fsync policy、migration artifact inclusion の tests を追加する。
10. old binary で新 schema に mutation できないことを明示し、read-only inspection の実測範囲を
    compatibility note と test evidence で示す。

0129 は audit check/repair/rebuild と backup/report UX、0130 は subprocess kill と 8--16 writer
stress を所有する。ただし 0128 は unit-level failure injection と最低限の concurrency correctness
を先送りしてはならない。

## 13. Executable pseudo-tests

```python
def test_rollback_has_no_projection():
    fault("before_sqlite_commit")
    run_mutation()
    assert domain_row_absent()
    assert event_absent()
    assert outbox_absent()
    assert jsonl_unchanged()

def test_commit_then_projector_failure_is_recoverable():
    fault("before_jsonl_append")
    result = run_mutation()
    assert result == {"committed": True, "projection": "pending", ...}
    assert domain_event_outbox_present()
    assert jsonl_missing_new_event()
    flush_projector()
    assert logical_jsonl_count(event_id) == 1

def test_crash_after_fsync_before_delivered_is_idempotent():
    fault("after_jsonl_fsync_before_delivered_commit")
    run_projector_in_subprocess()
    assert logical_jsonl_count(event_id) == 1
    flush_projector()
    assert logical_jsonl_count(event_id) == 1
    assert outbox_status(event_id) == "delivered"

def test_legacy_exact_mapping_is_non_destructive():
    before = sha256(events_jsonl)
    migrate()
    assert sha256(events_jsonl) == before
    assert sequences() == range(1, event_count() + 1)
    assert all_legacy_outbox_delivered()

def test_migration_statement_crash_rolls_back_everything():
    fault("between_migration_statements")
    migrate_in_subprocess()
    assert schema_is_pre_migration()
    assert no_schema_migration_row()
    assert no_migration_event_or_outbox()
```

## 14. Rollout and rollback

Before migration:

- stop concurrent PLH writers;
- acquire exclusive project-operation lock;
- create and report hashes for DB, WAL/SHM when present, and JSONL backup;
- run legacy preflight; unsupported anomaly blocks migration without mutation.

After migration, package downgrade is read-only at best: old `append_event` cannot satisfy
`events.sequence NOT NULL` and must not be used for mutation. If no post-migration mutation occurred,
rollback may restore the complete pre-migration DB + WAL/SHM + JSONL backup set. Once a new sequence/event
has committed, file-by-file downgrade or reverse migration is unsafe; preserve artifacts and roll forward.
Projector can be disabled while keeping pending outbox rows, but committed domain/event rows must not be
deleted merely to make JSONL look current.

## 15. Consequences and rejected alternatives

### Consequences

- JSONL may lag SQLite and CLI/API must expose that state.
- schema migration、transaction coordinator、projector、locks、legacy preflight が必要になる。
- delivered outbox retention increases DB size; compaction is intentionally deferred.
- filesystem corruption and Evidence crash states become detectable/reconcilable, not magically atomic.

### Rejected: JSONL first, then DB

現行の orphan JSONL failure を残す。

### Rejected: DB first without outbox

process kill で projection intent が失われ、missing JSONL event を確実に retry できない。

### Rejected: JSONL as sole source of truth

constraint、join、migration、current state query を複雑化し、既存 architecture と互換でない。

### Rejected: filesystem/SQLite distributed transaction

local dependency-light CLI に現実的な 2PC participant がなく、crash guarantee を単純化しない。

### Rejected: background projector daemon in v1

lifecycle/installation/locking/observability の surface を増やす。bounded synchronous attempt と
explicit retry で必要な guarantee を満たせる。

## 16. Decision log and acceptance checklist

| Item | Proposed resolution | Gate state |
|---|---|---|
| Source of truth | SQLite domain/events/outbox | proposed; human acceptance required |
| JSONL rebuild direction | SQLite -> JSONL supported | proposed; human acceptance required |
| JSONL -> DB rebuild | not a v1 guarantee | proposed; human acceptance required |
| Hash chain | defer; do not claim tamper evidence | recommendation; open until human decision |
| Projector trigger | post-commit synchronous bounded attempt + explicit flush | proposed; human acceptance required |
| fsync | default on | proposed; platform verification required |
| Legacy migration | ID/full-content/order mapping; non-destructive; anomalies block | proposed; fixture verification required |
| Review | maintainer + independent reviewer | **pending** |

この文書の Status は Proposed のままとする。作成者は Accepted を自己記録しない。
