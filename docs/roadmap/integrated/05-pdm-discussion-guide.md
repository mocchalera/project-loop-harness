# PdM Discussion Guide

## 1. この会議で決めること

最初の90分で、詳細機能より次の境界を決める。

1. PLHの最初の顧客は誰か。
2. `start → finish → resume`を主導線にするか。
3. AI-PLC思想をProfileとして扱うか、core entityへ入れるか。
4. M1 Trust Foundationを新機能より優先するか。
5. v1で何を保証し、何を保証しないか。

## 2. 推奨アジェンダ

| 時間 | 議題 | 出力 |
|---:|---|---|
| 0–10分 | 現在のユーザー痛み | 最優先painを1つに限定 |
| 10–25分 | 製品ポジション | 1文のcategory statement |
| 25–40分 | core/Profile境界 | ADR-001のAccept/Reject |
| 40–55分 | Trust Foundation | M1のscopeとrelease判断 |
| 55–70分 | 3-command UX | success pathと非対象 |
| 70–80分 | 評価方法 | North Starとgo/no-go |
| 80–90分 | ownerと次のPR | task 0123–0126の担当 |

## 3. 承認が必要な決定

### D-01: 製品のwedge

推奨:

> Agentの完了を証拠付きにし、どのagentにも再開可能にする。

代替:

- generic project orchestration。
- AI-PM/requirements platform。
- agent runtime。

後二者を今選ぶと、既存大手製品との競争と概念過多が増える。

### D-02: AI-PLC統合方式

推奨: Profile-not-Entity。Work Brief、Decision ProposalをEvidence artifactとして試す。

反対案: Intent/Option/Replan/Knowledgeを最初からtable化。

判断基準: 初回UX、migration費用、既存Goal/Decisionとの重複、外部利用実績。

### D-03: JSONLの役割

推奨: SQLite commit後の投影。transactional outboxで再送可能にする。

要確認: JSONLから完全rebuildをv1 guaranteeに含めるか。含めるならlegacy/import/hash chainの追加設計が必要。

### D-04: MCP

選択肢:

1. 仕様準拠をM1で直し、supported clientを明示。
2. `pcl-mcp`をexperimentalと明記し、既定surfaceから下げる。

宣言versionとtransportが一致しない状態の放置は選択肢にしない。

### D-05: Route preset

推奨: `direct / discover / assure`はUX preset、resolved policy axesをauthoritativeにする。

要確認: `assure`を独立presetにするか、verification modeとしてUI上だけ表現するか。

### D-06: human gate

決めること:

- どのriskで必須か。
- override権限と記録。
- non-interactive agentでの応答形式。
- timeout時にfail closedか。

### D-07: pricing/positioningの前提

この計画はOSS local-first coreを前提にする。monetizationを考える場合も、現時点ではcloud executionより、team policy、compliance export、hosted coordination等を仮説に留める。

## 4. ユーザーインタビュー質問

機能名を説明せず、実際の行動を聞く。

- 最近、coding agentが「完了」と言ったのに未完了だった具体例は何か。
- そのとき何を確認し、何分かかったか。
- 別モデルや別sessionへ作業を渡したとき、何をもう一度説明したか。
- 安いモデルを使わない理由は品質か、管理コストか。
- PR reviewで最も不足する情報は何か。
- 自動実行させたくない変更は何か。
- どの時点で人間承認が必要か。
- transcript、README、issue、test logのどれを現在handoffに使うか。
- PLHを使わない方が早い仕事は何か。
- completion packetを誰に、どの画面で見せたいか。

## 5. Opportunity scoring

各candidateを次で評価する。点数は意思決定補助であり事実ではない。

| 軸 | 問い |
|---|---|
| Pain frequency | 週に何回起きるか |
| Pain severity | 誤り・時間・費用・riskはどれほどか |
| Existing workaround | 現在の代替は十分か |
| PLH advantage | local evidence/stateが本当に優位か |
| Time to value | 10分以内に価値を示せるか |
| Integration cost | agent/toolごとのadapter負担は何か |
| Lock-in resilience | モデル性能向上後も残る価値か |
| Evidenceability | 効果を測れるか |

## 6. 主要な反論と回答

### 「強いモデルならPLHはいらない」

強いモデルにはplanning scaffoldingを減らす。ただし、外部check、残存risk、handoff、監査はモデル能力と別問題。overheadが価値を上回るならDirectでほぼ消える設計にする。

### 「CIだけでよい」

CIはcommitのcheckには強いが、依頼意図、却下案、未検証claim、次の安全な一手を保持しない。PLHはCIを置き換えず、その結果をclaimへbindingする。

### 「AGENTS.mdやhooksで十分」

指示とevent triggerは実行証拠や共通packetではない。PLHは異なるruntimeをまたぐ契約を提供する。

### 「工程が重い」

正しい反論。だから全工程を強制せず、Directを既定にし、曖昧さとriskがある場合だけ深くする。評価でoverhead上限を設ける。

### 「AI-PLCをそのまま使えばよい」

AI-PLCは上流の進行設計に強い。PLHは永続状態、Evidence、Verification、Recoveryに強い。置き換えではなく、Profile adapterとして接続する方が双方の長所を残す。

## 7. Decision record template

```markdown
# Decision: <title>

- ID: D-xxxx
- Date:
- Owner:
- Status: proposed | accepted | rejected | superseded
- Scope:

## Context

## Options considered

## Decision

## Why

## Evidence

## Consequences

## Revisit trigger

## Supersedes / Superseded by
```

## 8. Milestone review template

```markdown
# Milestone Review: Mx

## Exit criteria
- [ ] ...

## Evidence
- tests:
- packets:
- benchmark:
- user feedback:

## Regressions and known limits

## Metrics versus baseline

## Decision
- ship
- extend
- rollback
- stop

## Next hypothesis
```

## 9. 次に承認すべき実装範囲

最初の承認単位は`0123`〜`0130`。ここではAI-PLC機能を増やさず、現行の信頼境界と外部互換性を修復する。次の承認単位`0131`〜`0134`で初めて3-command UXを製品化する。
