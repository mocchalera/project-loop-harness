# ADR-001: AI-PLC思想はProfileとして統合し、最初からEntity化しない

- Status: Proposed
- Date: 2026-07-09
- Owners: PdM / Architecture

## Context

AI-PLCはCollection、発散/収束、Backtrack、Adaptive Depth、maker≠checkerを提供する。一方PLHには既にGoal、Feature、Story、Task、Decision、Escalation、Evidence、Verificationがある。Intent、Option、Knowledge等を同時にtable化すると、概念重複、migration、validation、dashboard、MCP surfaceが急増する。

## Decision

AI-PLC由来の上流機能は、versioned artifactを生成するoptional Profileとして統合する。

- Work BriefはEvidence artifact。
- Decision ProposalはEvidence artifact。
- 選択結果は既存Decision lifecycle。
- ReplanはWork Brief revisionとeventから開始。
- Knowledgeはproposal artifactとして実験。
- ProfileはDBを直接変更しない。

## Consequences

### Positive

- Direct taskへ概念を露出しない。
- schema churnを抑える。
- AI-PLC以外のDiscovery手法も接続可能。
- artifact contractを外部adapterから利用できる。

### Negative

- 初期は高度なqueryが弱い。
- generic Evidence linkのUX改善が必要。
- artifact lifecycleの一部をapplication layerで解決する必要がある。

## Promotion trigger

独立lifecycle、複数repoでの反復利用、2 release以上のschema安定、generic query不足が揃ったときだけfirst-class entity化を再検討する。
