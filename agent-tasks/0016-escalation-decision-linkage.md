# Task 0016: Escalation / Decision Linkage

## Goal / Why now

0014 で human escalation、0015 で durable human decision が入ったが、現状は `escalations` と `decisions` が並列の人間判断キューになっている。

このタスクでは、`needs_human` verification から発生した escalation と、その判断結果として残す decision を明示的に関連付ける。目的は、`pcl next`、dashboard、reports 上で「何が人間判断を要求し、その判断はどの decision として記録されたか」を追跡可能にすること。

ただし、最初の実装では schema migration は避ける。既存の `decisions.blocks_json` と event payload を使い、リンクを deterministic に復元できる形にする。

## 推奨 scope

実装すること:

- `pcl decision open` から escalation を参照できるようにする。
- `pcl escalation resolve` から関連 decision を参照できるようにする。
- `pcl next` の open escalation 解決コマンドを、可能なら decision 作成へ誘導する。
- dashboard の escalation / decision rows に関連 ID を表示する。
- workflow run report / goal report に関連 escalation / decision を含める。
- event payload にリンク情報を残す。
- 既存の open escalation 優先、open decision 次点、strict validation 最優先の順序は維持する。

実装しないこと:

- 新しい join table や FK カラム追加。
- migration。
- escalation resolve 時の decision 自動作成。
- decision resolve 時の escalation 自動 resolve。
- 外部通知、GitHub/Slack/email 連携。
- generated dashboard HTML の直接編集。

## 具体的な CLI/API 変更案

### 1. `pcl decision open`

追加オプション:

```bash
pcl decision open \
  --question "..." \
  --recommendation "..." \
  [--blocks-json '[...]'] \
  [--escalation ESC-0001]
```

挙動:

- `--escalation` が指定されたら、対象 escalation が存在することを検証する。
- 対象 escalation は `open` であることを推奨。最初の実装では closed escalation への decision 作成を禁止してよい。
- `blocks_json` に以下を追加する。

```json
{
  "type": "escalation",
  "id": "ESC-0001"
}
```

- 既に同じ object が `blocks_json` にある場合は重複追加しない。
- `decision_opened` event payload に `escalation_id` を入れる。
- JSON output にも `escalation_id` を含める。

API 変更:

```python
open_decision(
    paths,
    question=...,
    recommendation=...,
    blocks_json="[]",
    escalation_id=None,
)
```

### 2. `pcl escalation resolve`

追加オプション:

```bash
pcl escalation resolve ESC-0001 \
  --summary "..." \
  [--decision DEC-0001]
```

挙動:

- `--decision` が指定されたら、対象 decision が存在することを検証する。
- できれば対象 decision の `blocks_json` に `{"type":"escalation","id":"ESC-0001"}` が含まれることを要求する。
- 含まれない場合は typed error にする。これにより曖昧な後付けリンクを防ぐ。
- `escalation_resolved` event payload に `decision_id` を入れる。
- JSON output にも `decision_id` を含める。

API 変更:

```python
resolve_escalation(
    paths,
    escalation_id=...,
    summary=...,
    decision_id=None,
)
```

`cancel_escalation` には `--decision` は不要。

## `pcl next` への接続方針

現状の優先順位は維持する:

1. `pcl next --strict` の validation failure
2. open escalation
3. open decision
4. needs_human verification から escalation open 提案
5. active workflow / defect / goal

変更案:

open escalation があるときの action は引き続き `resolve_escalation` だが、command は decision linkage を促す形にする。

推奨 command:

```bash
pcl decision open --escalation ESC-0001 --question 'Record the human decision for ESC-0001' --recommendation 'Choose the safe next step'
```

理由:

- escalation は「人間判断が必要」を表す。
- decision は「人間が何を選んだか」を durable に残す。
- 先に decision を作り、その後 `pcl escalation resolve ESC-0001 --decision DEC-0001 --summary ...` で escalation を閉じる流れが追跡しやすい。

`pcl next --json` の target には以下を含める:

```json
{
  "id": "ESC-0001",
  "workflow_run_id": "WR-0001",
  "linked_decision_ids": []
}
```

open escalation に既に linked open decision がある場合:

- `pcl next` は `resolve_decision` を返すより、まだ escalation が open なので `resolve_escalation` を優先してよい。
- ただし command は既存 linked decision を使う。

```bash
pcl escalation resolve ESC-0001 --decision DEC-0001 --summary 'Record the outcome'
```

この方が「open escalation が最優先」という 0015 の契約を壊さない。

## dashboard への接続方針

`renderer.py` で DB から dashboard-data を作る時に、以下を追加する。

### decisions rows

既存 fields に加えて `linked_escalation_ids` を追加する。

取得方法:

- `decisions.blocks_json` を JSON parse。
- `{"type":"escalation","id":"ESC-...."}` を抽出。
- deterministic のため ID 昇順、重複除去。

dashboard table の columns に追加:

```python
["id", "status", "question", "recommendation", "linked_escalation_ids", "selected_option", "reason", "blocks_json", "created_at"]
```

### escalations rows

既存 fields に加えて `linked_decision_ids` を追加する。

取得方法:

- decisions の `blocks_json` から escalation ID を逆引きする。
- 加えて `events.payload_json` の `decision_id` / `escalation_id` からも復元できるとよいが、最初は `blocks_json` 逆引きを canonical にする。
- deterministic のため ID 昇順、重複除去。

dashboard table の columns に追加:

```python
["id", "workflow_run_id", "severity", "question", "recommendation", "linked_decision_ids", "status", "created_at"]
```

## reports への接続方針

最初に入れる対象:

- `pcl report run WR-0001`
- `pcl report goal G-0001`

追加する情報:

- run に紐づく escalations
- その escalations に紐づく decisions
- 関連 events

`report_run`:

- `workflow_run_id` に直接紐づく escalations を取得。
- その escalation IDs を `decisions.blocks_json` から逆引きして decisions を取得。
- report data に `escalations`, `decisions` を追加。
- markdown に `## Escalations` と `## Decisions` を追加。

`report_goal`:

- goal に紐づく workflow runs を取得済み。
- その run IDs に紐づく escalations を取得。
- その escalation IDs から decisions を取得。
- markdown に同じく `## Escalations` / `## Decisions` を追加。

`report_defect` は out of initial scope でもよいが、defect repair run に紐づく escalation があるため、余裕があれば同じ helper を使って含める。

## tests の観点

追加/更新するテスト:

### `tests/test_decisions.py`

- `decision open --escalation ESC-0001` が `blocks_json` に escalation reference を追加する。
- JSON output に `escalation_id` が含まれる。
- 存在しない escalation ID は typed JSON error。
- closed/cancelled escalation への `decision open --escalation` は typed JSON error。
- 既存 `--blocks-json` と `--escalation` を併用しても JSON array が deterministic になる。
- 同じ escalation reference が重複しない。

### `tests/test_escalations.py`

- `escalation resolve ESC-0001 --decision DEC-0001` が成功し、JSON output と event payload に `decision_id` が入る。
- 存在しない decision ID は typed JSON error。
- escalation とリンクしていない decision ID を指定すると typed JSON error。
- `pcl next --json` が open escalation に対して `decision open --escalation ESC-0001 ...` を提案する。
- linked open decision がある open escalation に対して、`pcl next --json` が `escalation resolve ESC-0001 --decision DEC-0001 ...` を提案する。

### `tests/test_dashboard.py` or existing lifecycle tests

- dashboard-data の escalation row に `linked_decision_ids` が含まれる。
- dashboard-data の decision row に `linked_escalation_ids` が含まれる。
- rendered HTML に linked IDs が表示される。
- render は deterministic。

### `tests/test_reports.py`

- run report に linked escalation / decision が出る。
- goal report に linked escalation / decision が出る。
- repeated report generation が deterministic。
- report events に `decision_opened` と `escalation_resolved` が含まれる。

## 変更対象ファイル

主な変更:

- `src/pcl/decisions.py`
- `src/pcl/escalations.py`
- `src/pcl/cli.py`
- `src/pcl/commands.py`
- `src/pcl/renderer.py`
- `src/pcl/reports.py`
- `tests/test_decisions.py`
- `tests/test_escalations.py`
- `tests/test_dashboard.py`
- `tests/test_reports.py`

必要に応じて:

- `docs/implementation-plan.md`
- `TASKS.md`

ただし、このタスク実装では `src/pcl/db/schema.sql` と `src/pcl/db/migrations/*` は変更しない方針。

## migration が必要かどうか

不要。

理由:

- `decisions.blocks_json` は既に汎用的な blocking target array として存在する。
- escalation -> decision の逆引きは `blocks_json` から deterministic に復元できる。
- resolve 時の `decision_id` は `events.payload_json` に残せる。
- dashboard/reports 用には既存 DB と event payload で十分。

将来的に検索性能や referential integrity が問題になった場合のみ、別 task で `decision_links` table か `escalation_decision_links` table を検討する。

## Do not / out of scope

- schema migration を追加しない。
- agents に SQLite を直接編集させない。
- `.project-loop/project.db` を直接編集しない。
- `.project-loop/dashboard/dashboard.html` を直接編集しない。
- generated HTML を source of truth にしない。
- decision resolve で escalation を自動 resolve しない。
- escalation resolve で decision を自動作成しない。
- hosted backend、cloud sync、外部通知、GitHub writes は実装しない。
- paid service dependency や telemetry は追加しない。
- MCP/plugin distribution には進まない。

## acceptance criteria

- `pcl decision open --escalation ESC-0001 ...` が linked decision を作成する。
- linked decision の `blocks_json` に `{"type":"escalation","id":"ESC-0001"}` が deterministic に保存される。
- `decision_opened` event payload に `escalation_id` が含まれる。
- `pcl escalation resolve ESC-0001 --decision DEC-0001 --summary ...` が linked decision を要求・検証して escalation を resolve できる。
- `escalation_resolved` event payload に `decision_id` が含まれる。
- invalid escalation / decision / unlinked decision は typed JSON error になる。
- `pcl next --json` は open escalation に対して decision 作成または linked decision を使った escalation resolve を提案する。
- `pcl next --strict --json` は validation failure を最優先し続ける。
- dashboard-data と dashboard HTML に linked escalation / decision IDs が表示される。
- run / goal reports に linked escalations / decisions が表示される。
- すべての state mutation は event を append する。
- `pytest` が通る。
- `pcl --help` が通る。
- schema migration は追加されていない。

## 実装順序

1. `decisions.py` に `escalation_id` optional parameter を追加する。
2. `decision open --escalation` の CLI parser と dispatch を追加する。
3. escalation 存在/status 検証 helper を追加する。
4. `blocks_json` に escalation reference を merge する helper を追加する。
5. `decision_opened` payload / JSON output に `escalation_id` を追加する。
6. decision linkage の unit/CLI tests を追加して通す。
7. `escalations.py` に `decision_id` optional parameter を追加する。
8. `escalation resolve --decision` の CLI parser と dispatch を追加する。
9. decision 存在検証と `blocks_json` linkage 検証 helper を追加する。
10. `escalation_resolved` payload / JSON output に `decision_id` を追加する。
11. escalation resolve linkage tests を追加して通す。
12. `commands.py` の `next_action` helper を更新し、open escalation に linked decision 情報を付与する。
13. linked decision がない open escalation では `pcl decision open --escalation ...` を提案する。
14. linked decision がある open escalation では `pcl escalation resolve ... --decision ...` を提案する。
15. dashboard-data enrichment helper を `renderer.py` に追加する。
16. dashboard table に linked ID columns を追加する。
17. reports に escalation / decision sections を追加する。
18. dashboard/report deterministic tests を追加する。
19. `pytest` を実行する。
20. `pcl --help` を実行する。
21. 必要なら `/tmp/pcl-demo` で `pcl init`, `pcl doctor`, `pcl validate`, `pcl render` を確認する。
