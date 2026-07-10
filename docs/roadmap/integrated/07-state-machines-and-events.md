# State Machines and Event Draft

## 1. Status

この文書は論理状態を示す。既存PLHのDB enumやstatus名を直ちに置き換えるものではない。実装時は既存state machineへmappingし、不要な新statusを増やさない。

## 2. Work Brief lifecycle

```text
DRAFT ──approve──> APPROVED ──replan──> SUPERSEDED
  │                    │
  └──retire────────────┴──────────────> RETIRED
```

Rules:

- artifact本文はimmutable。
- 同一targetでcurrent approvedは高々1つ。
- replanは新revisionを作り、oldをSUPERSEDEDにする。
- SUPERSEDEDは削除せず、過去packetの解釈に使う。

Provisional events:

- `work_brief.created`
- `work_brief.approved`
- `work_brief.superseded`
- `work_brief.retired`

## 3. Work execution lifecycle

既存Goal/Task/Workflow stateへ次のapplication outcomeをmappingする。

```text
OPEN → ACTIVE → FINISH_PLANNED
                    │
                    ├─ validation fail ─> ACTIVE / BLOCKED
                    ├─ budget exhausted → ACTIVE / PAUSED
                    ├─ human required ──> WAITING_HUMAN
                    └─ checks complete ─> COMPLETED
```

`INCOMPLETE_*`は必ずしも新DB statusではなくcompletion packet outcomeとして表せる。既存state enumを増やす前にmappingを決める。

Provisional events:

- `work.started`
- `finish.planned`
- `check.recorded`
- `completion_packet.created`
- `work.completed`
- `work.blocked`
- `budget.exhausted`

## 4. Route and policy lifecycle

```text
RECOMMENDED ──override──> OVERRIDDEN
      │
      └──policy/input changed──> STALE → RECOMPUTED
```

- recommendationを上書き削除しない。
- overrideはactor/reason必須。
- historical packetは当時のpolicy hashを保持。

Events:

- `route.recommended`
- `route.overridden`
- `route.recomputed`

## 5. Replan lifecycle

```text
PROPOSED ──approve/apply──> APPLIED
    │                         │
    └──reject/cancel──> CLOSED│
                              └─ creates new Work Brief revision
```

Apply transaction logically includes:

1. new brief artifact metadata。
2. old/new revision relation。
3. replan event。
4. initial invalidation plan。

Full stale propagation may run in the same or following transaction according to scale, but partial state must be detectable and resumable.

Events:

- `work.replan_proposed`
- `work.replanned`
- `work.replan_rejected`
- `artifact.validity_changed`

## 6. Artifact validity lifecycle

```text
CURRENT ──premise/revision changed──> STALE
   │                                   │
   ├──explicit contradiction────────> INVALIDATED
   │                                   │
   └──new revision replaces─────────> SUPERSEDED
                                       │
STALE ──revalidate───────────────────> CURRENT
```

- `STALE`は「誤り」ではなく再評価が必要。
- `INVALIDATED`は明示理由必須。
- `SUPERSEDED`は過去には有効だった可能性を保持。

## 7. Verification lifecycle

```text
REQUESTED → IN_PROGRESS → RECORDED
                              │
                              ├─ unmet policy → NEEDS_MORE_EVIDENCE
                              ├─ human gate   → NEEDS_HUMAN
                              └─ accepted     → SATISFIED
```

Verification result、policy satisfaction、proof levelを同じbooleanへ畳み込まない。

Events:

- `verification.requested`
- `verification.recorded`
- `verification.policy_satisfied`
- `verification.human_approved`

## 8. Evidence file lifecycle

```text
TEMP_WRITTEN → PENDING_METADATA → READY
      │                │           │
      └─failure────────┴──────────> MISSING/ORPHANED
                                      │
                                      └─ audit repair/quarantine
```

理想的な順序:

1. temp/content-addressed pathへwrite。
2. hash/sizeを検証。
3. transaction内でmetadataをPENDING登録。
4. atomic rename。
5. metadataをREADYへ。
6. failureはaudit checkで検出。

filesystemとSQLiteの完全原子性は主張しない。reconciliationを保証する。

## 9. Outbox lifecycle

```text
PENDING → DELIVERING → DELIVERED
   │           │
   └──────────> FAILED_RETRYABLE → PENDING
                   │
                   └─attempt limit→ FAILED_NEEDS_REVIEW
```

- domain transactionはPENDING作成まで。
- JSONL append後にDELIVERED。
- retryはevent ID/sequenceでidempotent。
- FAILEDでもdomain stateをrollbackしない。

Events for repair may include:

- `audit.repair_planned`
- `audit.repair_applied`
- `audit.jsonl_rebuilt`

Repair events自身が同じoutboxを通るため、rebuild時の再帰/orderingを設計する。

## 10. Decision Proposal lifecycle

```text
PROPOSED → HUMAN_REQUIRED → SELECTED
     │             │
     └────────────> REJECTED / EXPIRED
```

Proposal artifactと最終Decision recordを分離する。推薦candidateと選択candidateが異なる場合はoverride reasonを残す。

## 11. Knowledge Proposal lifecycle

```text
PROPOSED → ACCEPTED → SUPERSEDED / EXPIRED
     │          │
     └────────> REJECTED
                │
conflict ─────> NEEDS_REVIEW
```

ACCEPTED以外をcontextへ自動注入しない。

## 12. Event envelope draft

既存event schemaへadditive mappingする。

```json
{
  "event_id": "EV-...",
  "sequence": 123,
  "occurred_at": "2026-07-09T12:00:00Z",
  "event_type": "work.replanned",
  "actor": {"kind": "human", "id": "local:takuma"},
  "entity": {"type": "goal", "id": "G-0001"},
  "payload": {},
  "correlation_id": "RUN-...",
  "causation_id": "EV-...",
  "schema_version": "event/v1"
}
```

`sequence`はproject内単調増加。timestampだけでorderingしない。event payloadのbreaking changeはevent type versionまたはschema versionで扱う。

## 13. Atomicity boundaries

### Must be one SQLite transaction

- domain state mutation。
- event row。
- outbox row。
- packet/Evidence metadata link（fileがREADYである前提またはPENDING state）。

### May occur after commit and must be recoverable

- JSONL projection。
- filesystem atomic renameのfinalization。
- derived HTML/Markdown rendering。
- external adapter notification。

## 14. Read-only operations

次は既定でeventを発生させない。

- `pcl resume`表示。
- `pcl audit check`。
- `pcl explain`。
- `pcl profile prepare`。
- `pcl context pack`生成が現在read-only contractならその方針を維持。

利用統計を取りたい場合も、read-only semanticを壊すaudit eventではなく明示opt-in metrics exportを使う。
