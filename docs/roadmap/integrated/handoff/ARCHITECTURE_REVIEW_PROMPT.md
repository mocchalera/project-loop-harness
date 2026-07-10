# Architecture Review Prompt

```text
Project Loop Harnessの統合ロードマップをarchitecture/reliability reviewerとしてレビューしてください。

読む文書:
- docs/01-adaptive-loop-architecture.md
- docs/02-contracts-and-data-model.md
- docs/03-implementation-plan.md
- docs/06-cli-contract-draft.md
- docs/07-state-machines-and-events.md
- docs/adr/*.md
- schemas/*.json

実コードのmain branchも照合してください。計画文書を正しい前提とみなさないでください。

重点確認:
1. SQLite transaction、event、outbox、JSONL、Evidence fileのatomicityとcrash recovery。
2. MCP宣言version、stdio framing、version negotiation、stdout purity。
3. packet contractと内部DB schemaの結合。
4. Work Brief/Decision Proposal/Knowledge ProposalをEvidence artifactで始める妥当性。
5. policy axisのdeterminism、override、historical reproducibility。
6. stale/invalidation graphのcycle、fan-out、partial failure。
7. producer/verifier separationとproof levelの混同。
8. Windows/macOS/Linuxのfile locking、rename、subprocess差異。
9. runtime dependencyゼロ方針との衝突。
10. 各taskの依存関係と、より小さいPR分割案。

出力:
- P0/P1/P2 findings
- 破綻するfailure sequence
- 変更すべきADR
- 追加すべきnegative/crash tests
- migration/rollback risk
- task順序の修正版
- Accept / Accept with changes / Reject
```
