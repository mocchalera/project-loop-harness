# Contracts and Data Model

## 1. 規範語

この文書のMUST、MUST NOT、SHOULD、MAYは実装契約を示す。個別タスクがこの文書と衝突する場合、Acceptedになった本契約を優先する。

## 2. source of truth

採用案:

- SQLite: current state、commit済みevent、outbox、artifact metadataのsource of truth。
- JSONL: commit済みeventのappend-only投影。SQLite transaction commit前には外部へ出さない。
- Evidence files: content-addressed storage。metadata状態は`PENDING`、`READY`、`MISSING`等で管理。
- HTML、Markdown report、wiki export: 派生review surface。source of truthではない。

JSONLとSQLiteの両方を同時に権威と呼ばない。JSONLからrebuildをサポートする場合も、それはrecovery capabilityとして明文化し、通常時の権威はSQLiteとする。

## 3. contract versioning

- contract IDは`name/vN`形式。
- additiveであってもconsumerが拒否する可能性があるため、各schemaはfixtureとcompatibility testを持つ。
- v1内の必須field削除、意味変更、enum削除は禁止。
- 新しいoptional field追加はminor package releaseで可能。
- breaking changeは`v2`を作り、移行期間中は両方をread可能にする。
- DB schema version、package version、contract versionを一致させる必要はない。

## 4. `work-brief/v1`

schema: `schemas/work-brief-v1.schema.json`

### semantics

- 仕事の「なぜ、何を成功とするか、何をしないか」を固定するexecution input。
- Evidence artifactとして保存する。
- revisionはimmutable。
- `status=approved`の最新revisionだけがcurrent execution contract。
- assumptionsは`unverified / supported / contradicted / retired`を明記する。
- constraintに可能な限りEvidence sourceを結ぶ。
- route recommendationは決定論的policy resultであり、最終判断ではない。

## 5. `route-decision/v1`

schema: `schemas/route-decision-v1.schema.json`

### semantics

- 同じ入力とpolicy versionから同じ結果を返す。
- `profile`はUX preset。authoritativeなのはresolved axes。
- reason codeはstable enumまたはnamespaced string。
- overrideは元recommendationを削除せず、actor、理由、timestampを別eventに残す。
- model self-assessmentだけをroute理由にしない。

推奨reason codes:

```text
clear_acceptance
missing_acceptance
broad_goal
unverified_root_cause
high_risk_path
public_api_change
dependency_change
migration_change
auth_or_permission_change
no_deterministic_check
large_change_surface
weak_tool_reliability
low_budget
manual_override
```

## 6. `decision-proposal/v0`

schema: `schemas/decision-proposal-v0.schema.json`

### semantics

- Discovery Profileが生成する候補比較artifact。
- candidateごとにhypothesis、trade-offs、evidence refs、uncertainty、reversibilityを持つ。
- 数値scoreはoptionalな表示補助であり、PLHがfactとして扱わない。
- 選択は既存Decision lifecycleまたはhuman gateで行う。
- rejected candidateを削除しない。

v0なのは、外部利用で必要fieldが変わる可能性が高いためである。

## 7. `completion-packet/v1`

schema: `schemas/completion-packet-v1.schema.json`

### MUST

- producer version、contract version。
- work target。
- base/head revisionとdiff hash。
- changed paths。
- check command、exit code、artifact ref、reproducibility。
- claimごとのproof levelとEvidence refs。
- unverified claims。
- residual risks。
- terminal outcome。
- next actionまたはnull。

### MUST NOT

- 実行していないtestをpassedと記録。
- 別モデルが承認しただけでL2以上へ昇格。
- exit codeやartifactなしにdeterministic check成功と記録。
- budget exhaustionをcompletedに変換。

## 8. `handoff-packet/v1`

schema: `schemas/handoff-packet-v1.schema.json`

### MUST

- source work targetとbrief revision。
- current state。
- verified/unverifiedの分離。
- blocker、risk、human decision。
- next safe action。
- context refsとfreshness。
- generation timestampとproducer version。

full transcript、全ファイル、全Evidence本文は既定で含めない。参照と選択理由を渡す。

## 9. `knowledge-proposal/v0`

schema: `schemas/knowledge-proposal-v0.schema.json`

- default statusは`proposed`。
- provenanceがない提案はaccept不可。
- scopeは`task / repository / organization / environment`。
- revision rangeまたはexpiryを持てる。
- contradictionが見つかった場合は自動で勝者を決めず、`needs_review`にする。
- accepted Knowledgeだけがcontext候補。

## 10. Proof Level

proof levelはclaim単位で算出する。

| Level | 意味 | 例 |
|---|---|---|
| L0 | assertionのみ | agentが「直した」と述べた |
| L1 | artifact capture | diff、log、screenshot、receiptが存在 |
| L2 | deterministic verification | test、typecheck、lint、schema validationが成功 |
| L3 | independent acceptance/observation | 独立環境、acceptance scenario、実観測が成功 |
| L4 | 指定human approval | 権限のある人がEvidenceを見て承認 |

packet全体のsummary levelは重要claimの最低値をルールで計算する。平均や最大値を使わない。

## 11. verifier provenance

Verification recordへ少なくとも次を追加または関連artifactで保持する。

```json
{
  "producer": {
    "agent_id": "A-1",
    "session_id": "S-1",
    "model": "optional"
  },
  "verifier": {
    "agent_id": "A-2",
    "session_id": "S-2",
    "model": "optional"
  },
  "separation": "separate_agent",
  "evidence_classes": ["model_judgment", "deterministic_check"],
  "fallback_used": false
}
```

model名はoptional。agent/session separationとEvidence classを必須判断材料にする。

## 12. staleとinvalidation

Replanまたはrepository revision変更で、artifactは次の状態を取る。

- `current`: 現在contractに適用可能。
- `stale`: 基準revisionや前提が変わり、再評価が必要。
- `invalidated`: 明示的に使えないと判断。
- `superseded`: 新revisionに置き換えられたが履歴として有効。

staleを削除しない。`finish`はcritical stale artifactがある場合、policyに従い停止またはhuman gateへ送る。

## 13. event contract

すべてのstate mutationは、同一SQLite transaction内でdomain eventとoutbox recordを作る。

最低field:

```text
event_id
sequence
occurred_at
event_type
actor
entity_type
entity_id
payload_json
previous_event_hash (optional)
event_hash (optional)
projector_status
```

JSONL projectorはevent IDまたはsequenceで冪等にする。二重出力してもconsumerが重複判定できる。

## 14. CLI contract

### 共通

- `--json`はstdoutへJSON以外を出さない。
- diagnosticsはstderr。
- mutation commandは`--dry-run`を持つか、preview/planを返す。
- exit codeを文書化する。
- read-only commandは暗黙にstateを変更しない。
- fallback、override、partial completionは明示的なfieldを持つ。

### 提案exit codes

| code | 意味 |
|---:|---|
| 0 | requested operation completed |
| 2 | usage/contract error |
| 3 | validation or policy blocked |
| 4 | human decision required |
| 5 | budget exhausted |
| 6 | recoverable integrity issue detected |
| 7 | unsupported protocol/compatibility |
| 8 | internal failure |

既存契約と衝突する場合は、互換性調査を先に行い、既存exit codeを優先する。

## 15. エンティティ昇格条件

Artifactをtableへ昇格するには、次の全条件を満たす。

1. 独立したlifecycleと状態遷移が複数use caseで必要。
2. generic Evidence queryでは不足する検索・制約がある。
3. 少なくとも2つの外部dogfood projectで反復利用された。
4. contract fieldが2 release以上安定した。
5. migration、recovery、dashboard、MCP surfaceを増やす費用に見合う。

Work Brief、Decision Proposal、Knowledge Proposalはこの条件を満たすまで専用tableにしない。
