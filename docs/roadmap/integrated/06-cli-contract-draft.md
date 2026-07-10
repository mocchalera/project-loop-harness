# CLI Contract Draft

## 1. Status

この文書はM1〜M5の議論用draftである。実装前に現行CLIのhelp、exit code、`--json` fixtureをcharacterizeし、既存のstable behaviorを不用意に壊さない。

## 2. 共通ルール

- `--json`指定時、stdoutは一つのvalid JSON documentまたはdocumented JSONLだけにする。
- diagnostics、progress、confirmation promptはstderrへ出す。
- mutation commandは`--dry-run`、plan、または明示的apply semanticsを持つ。
- read-only commandはDB、event、outboxを変更しない。
- targetが曖昧なら勝手に選ばず、candidateとselection-requiredを返す。
- fallback、override、partial completion、truncation、stalenessを隠さない。
- pathはproject root基準でcanonical化し、JSONではplatform-independent表記を優先する。
- non-interactive modeでhuman inputが必要なら、待ち続けずexit code 4とnext actionを返す。

提案する共通result要素。既存JSON contractと衝突する場合はadditive wrapperまたはcommand-specific mappingをADRで決める。

```json
{
  "command": "start",
  "status": "ok",
  "mutated": true,
  "result": {},
  "warnings": [],
  "next_actions": [
    {"text": "...", "command": "..."}
  ]
}
```

## 3. `pcl start`

```text
pcl start <intent>
  [--profile auto|direct|discover|assure]
  [--new]
  [--no-init]
  [--dry-run]
  [--json]
```

### Behavior

1. project rootを解決する。
2. 未初期化なら、`--no-init`時は停止。それ以外はstart操作の一部として最小初期化をplanする。
3. active workを検索する。
4. active workが一つある場合は、`--new`なしではduplicateを作らずresumeを案内する。
5. intent textを既存Goal/Task modelへ最小マッピングする。
6. M3以降はWork Brief draftとroute recommendationを追加する。
7. created IDs、profile、next actionを返す。

### Example JSON

```json
{
  "command": "start",
  "status": "ok",
  "mutated": true,
  "result": {
    "project_initialized": true,
    "target": {"type": "task", "id": "T-0001"},
    "intent": "Fix login timeout",
    "profile": "direct",
    "work_brief_ref": null
  },
  "warnings": [],
  "next_actions": [
    {"text": "Implement the scoped change", "command": null},
    {"text": "Inspect finish plan", "command": "pcl finish --dry-run --target T-0001"}
  ]
}
```

## 4. `pcl finish`

既存commandを拡張する。正確なflag名は現行contract characterization後に決める。

```text
pcl finish
  [--target <id>]
  [--dry-run | --apply]
  [--check <configured-check-id> ...]
  [--packet-output <path>]
  [--json]
```

### Plan phase

返すもの:

- target。
- base/head revision。
- changed paths。
- resolved risk/policy。
- required and optional checks。
- unmet Evidence/human gates。
- estimated budget。
- planned state transition。

### Apply phase

1. plan fingerprintを再確認。
2. allowed checksを実行。
3. check Evidenceを保存。
4. claim bindingとstrict validation。
5. completion packetを生成。
6. state/event/outboxをtransaction commit。
7. projector statusを返す。

### Outcome mapping

| Outcome | Exit intention | State effect |
|---|---|---|
| `COMPLETED_VERIFIED` | success | terminal complete |
| `COMPLETED_WITH_RISK` | success with explicit warning | terminal if policy permits |
| `INCOMPLETE_VALIDATION` | blocked | active/incomplete |
| `INCOMPLETE_BUDGET_EXHAUSTED` | budget exit | active/incomplete |
| `INCOMPLETE_HUMAN_DECISION_REQUIRED` | human gate exit | waiting |
| `NO_CHANGES` | no-op | do not invent completion |

## 5. `pcl resume`

```text
pcl resume
  [--target <id>]
  [--format json|markdown]
  [--output <path>]
  [--include <optional-section>]
  [--json]
```

- read-only。
- target不明時はcandidate list。
- full transcriptは既定で含めない。
- optional section: `intent-index`, `context-summary`, `recent-events`等。
- output fileを書いてもproject stateは変更しない。

## 6. `pcl brief`

```text
pcl brief create --target <id> --from <file> [--dry-run]
pcl brief add --target <id> --file <file>
pcl brief show --target <id> [--revision <n>]
pcl brief approve --target <id> --ref <evidence-ref> --actor <id>
```

- JSON artifactをschema validationしてからEvidence化。
- approved briefが複数なら曖昧として停止。
- in-place editなし。

## 7. `pcl route` / `pcl explain`

```text
pcl route recommend --target <id> [--json]
pcl route override --target <id> --profile <preset> --reason <text> --actor <id>
pcl explain route --target <id> [--json]
```

`explain`はprofileだけでなく、各policy axisのsource ruleとnon-overridable floorを返す。

## 8. `pcl replan`

```text
pcl replan --target <id>
  --reason <text>
  --brief <new-work-brief.json>
  [--invalidate <entity-id> ...]
  [--dry-run | --apply]
  [--json]
```

Dry-run result:

- old/new brief refs。
- structural diff。
- impact candidates。
- predicted stale/invalidation set。
- required human gate。
- next action。

Applyはold briefを削除せず、revision chainとeventを作る。

## 9. `pcl audit`

```text
pcl audit check [--json]
pcl audit repair [--dry-run | --apply] [--json]
pcl audit rebuild-jsonl --from-sqlite [--output <path>] [--apply]
```

- checkはread-only。
- repair/rebuildはbackup、plan、unsupported anomaliesを返す。
- unknown line/dataを黙って消さない。

## 10. `pcl profile`

```text
pcl profile list
pcl profile show <profile-id>
pcl profile validate <path-or-id>
pcl profile prepare <profile-id> --target <id> --output <dir>
pcl profile ingest <profile-id> --target <id> --from <dir> [--dry-run]
```

初期Profileはdata-only。`prepare`はcontextとinstructionを生成するだけで、外部agentを起動しない。`ingest`はschema validation後にEvidence化する。

## 11. `pcl budget`

```text
pcl budget status --target <id>
pcl budget explain --target <id>
pcl budget top-up --target <id> --dimension <name> --amount <n> --reason <text> --actor <id>
```

provider実token/costとPLH推定を別fieldで返す。

## 12. Exit code proposal

既存contractと照合して確定する。

| Code | Meaning |
|---:|---|
| 0 | completed/no-op as documented |
| 2 | usage or contract error |
| 3 | validation/policy blocked |
| 4 | human decision required |
| 5 | budget exhausted |
| 6 | recoverable integrity issue |
| 7 | protocol/compatibility unsupported |
| 8 | internal failure |

## 13. Backward compatibility

- 既存flag削除はdeprecation periodを設ける。
- 新しいJSON fieldはadditiveを優先する。
- stdout textはstable APIとみなさない場合も、documented parsingを促さない。
- script向けには`--json`とschema versionを提供する。
- packet contractをDB schemaと同時breaking changeしない。
