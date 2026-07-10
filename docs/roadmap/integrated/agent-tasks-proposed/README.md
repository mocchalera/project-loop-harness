# Agent Task Backlog — Integrated Roadmap

**Status:** Proposed  
**Task range:** `0123`–`0152`  
**Baseline:** `main` at v0.3.1-equivalent, tasks through `0122` completed

このbacklogは、既存`agent-tasks`へそのまま追加する前の提案版である。task ID、release番号、migration番号は実装branchで再確認する。

## Dispatch rules

1. `deps`がmerge済みでないtaskを実装開始しない。ただし設計reviewとprototypeは可能。
2. 一つのagentへ同時に複数のstate/migration taskを渡さない。
3. agentへ対象commit SHA、allowed paths、test budget、known failuresを必ず渡す。
4. scope外変更が必要なら勝手に拡張せず、Decision/Replan proposalを返す。
5. 完了報告にはtest command、exit code、diff、Evidence、未確認事項を含める。
6. 「tests should pass」「looks correct」だけを完了証拠にしない。

## Recommended waves

- **Wave A — M0/M1:** `0123`–`0130`
- **Wave B — M2:** `0131`–`0134`
- **Wave C — M3/M4:** `0135`–`0141`
- **Wave D — M5/M6:** `0142`–`0145`
- **Wave E — M7/M8:** `0146`–`0152`

## Task index

| ID | Title | Milestone | Priority | Size | Dependencies |
|---|---|---|---|---|---|
| [0123](0123-release-v0-3-1-baseline.md) | Release v0.3.1 and freeze the implementation baseline | M0 / proposed v0.3.1 | P0 | S | — |
| [0124](0124-mcp-stdio-framing-negotiation.md) | Make MCP stdio transport and protocol negotiation specification-compliant | M1 / Trust Foundation | P0 | M | 0123 |
| [0125](0125-mcp-external-conformance.md) | Add MCP external conformance fixtures and compatibility matrix | M1 / Trust Foundation | P0 | M | 0124 |
| [0126](0126-transactional-audit-outbox-design.md) | Finalize transactional audit outbox ADR and failure model | M1 / Trust Foundation | P0 | M | 0123 |
| [0127](0127-event-outbox-jsonl-projector.md) | Implement transactional event outbox and idempotent JSONL projector | M1 / Trust Foundation | P0 | XL | 0126 |
| [0128](0128-audit-check-repair-rebuild.md) | Add audit integrity check, repair, and rebuild commands | M1 / Trust Foundation | P0 | L | 0127 |
| [0129](0129-crash-concurrency-test-suite.md) | Build crash-injection and concurrent-writer reliability suite | M1 / Trust Foundation | P0 | L | 0127, 0128 |
| [0130](0130-guarded-executor-hardening.md) | Rename and harden the guarded executor surface | M1 / Trust Foundation | P1 | M | 0123 |
| [0131](0131-completion-packet-v1-contract.md) | Define and package completion-packet/v1 contract | M2 / Product Wedge | P0 | M | 0123 |
| [0132](0132-finish-emits-completion-packet.md) | Extend existing pcl finish to generate a completion packet | M2 / Product Wedge | P0 | XL | 0128, 0131 |
| [0133](0133-lite-pcl-start.md) | Add Lite pcl start entry point | M2 / Product Wedge | P0 | L | 0131 |
| [0134](0134-handoff-packet-pcl-resume.md) | Implement handoff-packet/v1 and read-only pcl resume | M2 / Product Wedge | P0 | L | 0132 |
| [0135](0135-work-brief-v1-evidence.md) | Introduce work-brief/v1 as an Evidence-backed contract | M3 / Adaptive Entry | P0 | M | 0131 |
| [0136](0136-deterministic-route-recommendation.md) | Add deterministic Direct/Discover/Assure route recommendation | M3 / Adaptive Entry | P0 | L | 0135 |
| [0137](0137-adaptive-policy-explain-override.md) | Implement multi-axis adaptive policy, explanation, and explicit override | M3 / Adaptive Entry | P0 | XL | 0136 |
| [0138](0138-work-brief-revision-replan.md) | Add immutable Work Brief revisions and pcl replan | M4 / Replan & Assurance | P0 | L | 0128, 0135 |
| [0139](0139-stale-invalidation-propagation.md) | Propagate constraints, stale state, and invalidation after replan | M4 / Replan & Assurance | P0 | XL | 0138 |
| [0140](0140-verifier-provenance-separation.md) | Record producer/verifier provenance and separation level | M4 / Replan & Assurance | P0 | M | 0131 |
| [0141](0141-risk-based-verification-policy.md) | Enforce risk-based verification and human-gate policy | M4 / Replan & Assurance | P0 | L | 0137, 0140 |
| [0142](0142-profile-contract-boundary.md) | Define a non-executable Profile contract and plugin boundary | M5 / Discovery Profile | P0 | L | 0135, 0137 |
| [0143](0143-discovery-reference-profile.md) | Ship an AI-PLC-inspired Discovery reference Profile | M5 / Discovery Profile | P0 | L | 0142 |
| [0144](0144-decision-proposal-human-selection.md) | Implement decision-proposal/v0 ingestion and human selection flow | M5 / Discovery Profile | P0 | L | 0143 |
| [0145](0145-master-trace-handoff-integration.md) | Integrate Master Trace intent-index as an optional handoff section | M6 / Trace & Efficient Handoff | P1 | L | 0134 |
| [0146](0146-capability-profile-v0.md) | Add capability-profile/v0 for model-agnostic adaptation | M7 / Adaptive Cost & Learning | P1 | M | 0137 |
| [0147](0147-budget-profile-incomplete-packet.md) | Implement budget profiles and explicit budget-exhaustion outcomes | M7 / Adaptive Cost & Learning | P1 | L | 0131, 0146 |
| [0148](0148-context-cache-delta-handoff.md) | Add content-addressed context cache and delta handoff | M7 / Adaptive Cost & Learning | P1 | XL | 0134, 0146 |
| [0149](0149-knowledge-proposal-experiment.md) | Run knowledge-proposal/v0 as an Evidence-backed experiment | M7 / Adaptive Cost & Learning | P2 | M | 0135, 0142 |
| [0150](0150-cross-model-evaluation-harness.md) | Build a reproducible cross-model evaluation harness | M8 / External Evidence | P0 | XL | 0134, 0137, 0141, 0144 |
| [0151](0151-design-partner-operations.md) | Run external dogfood and design-partner operations | M8 / External Evidence | P0 | L | 0150 |
| [0152](0152-adoption-stability-release.md) | Publish adoption path, compatibility matrix, and contract stability policy | M8 / External Evidence | P0 | L | 0151 |

## Parallelization guidance

- `0124`と`0126`は`0123`後に並列可能。
- `0130`はoutbox implementationと並列可能だが、Evidence output contractの衝突をreviewする。
- `0131`のcontract reviewはM1中に並列可能だが、`0132` mergeはM1 gate後。
- `0138`と`0140`は前提task完了後に並列可能。
- `0142`設計と`0145`設計は並列可能だが、Profile outputとhandoff contractを共通reviewする。
- `0146`、`0149`は実験的。M2〜M4の利用データなしに優先度を上げない。

## Stop conditions

次の場合は後続taskを止め、PdM/architecture decisionへ戻す。

- M1でDB/JSONLのsource of truthに合意できない。
- M2のDirect pathが10分/3操作の目標を満たさない。
- Direct overheadが継続して10%を超える。
- Discoveryが曖昧taskのreworkを改善しない。
- Profile boundaryを破り、coreがagent固有promptまたはLLMを必須にし始める。
- packet contractがreleaseごとに破壊変更される。
