# 0145: Integrate Master Trace intent-index as an optional handoff section

- **Status:** Proposed
- **Milestone:** M6 / Trace & Efficient Handoff
- **Priority:** P1
- **Estimated size:** L
- **Dependencies:** `0134`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

長いsessionでは、なぜ判断したか、どのclaimがどの発言・Evidenceに基づくかがhandoffから抜ける。一方、full transcriptは大きく、モデル生成summaryをfact化すると危険。

## Goal

既存Master Trace/intent-index構想をhandoff packetへoptional refとして統合し、出典付きclaims-not-factsの履歴を小さく渡す。

## Scope

- 既存`intent-index/v0`計画と実装済みEvidence linksを再確認する。
- raw transcriptとexternal model indexをEvidenceとして別々にcaptureする。
- index entryにsource line/message refs、claim type、decision/rejection/open questionを持たせる。
- `pcl trace ingest/check/show`または既存surfaceをhandoffへ接続する。
- handoff packetはindex本文を全inlineせずref、high-priority items、omission metadataを含める。
- source refが解決できないentryをunverified/invalidとして扱う。
- coreはLLMを呼ばず、external agentがindexを生成する。

## Proposed implementation

- indexはMaster Trace first-class tableにしない。
- line numbering/normalizationを固定し、transcript hashとbindingする。
- モデルの「決定された」claimはsourceと既存Decision recordを照合する。
- privacy上、transcript本文をpacketへ既定同梱しない。
- context budgetに応じたselection理由を記録する。

## Likely affected surfaces

- trace/index contracts
- Evidence capture/link
- handoff/context selector
- CLI/profile adapter
- docs

## Invariants

- source refsなしのindex claimをfactとして扱わない。
- core LLM dependencyなし。
- raw transcriptとindexを混同しない。
- full transcriptをdefault handoffにしない。

## Non-goals

- 会話UI。
- 全agentのtranscript自動収集。
- semantic embedding search。
- first-class trace entity。

## Acceptance criteria

- Bound transcript+index fixtureがvalidationを通りhandoffへrefされる。
- Broken source ref、hash mismatch、unsupported schemaが検出される。
- Handoff consumerがdecision/rejected option/open questionのsourceへ辿れる。
- Indexなしprojectも従来resumeできる。
- Context budget超過時にomitted itemsと理由が記録される。

## Required tests

- Source binding/hash.
- Broken/ambiguous refs.
- No-index backward compatibility.
- Budget selection determinism.
- Claims vs Decision record mismatch.
- Privacy/full transcript omission.

## Evidence required to close

- sample transcript/index/handoff。
- binding validation output。
- size comparison。
- external model generation instructions。

## Rollout and rollback

- opt-inから開始。
- 外部adapterごとにtranscript formatを追加。
- 利用価値が低ければfirst-class化しない。

## Open questions

- intent-index/v0をv1へ上げる時期。
- どのmessage formatをcanonicalにするか。

## Agent execution protocol

実装担当エージェントは開始前に次を返す。

1. 対象commit SHAと、依存taskがmerge済みである証拠。
2. 変更予定path。
3. 既存contractをcharacterizeするtestまたは確認結果。
4. scope外に見える問題と、今回は触れない理由。

完了時は次を返す。

1. 変更概要と設計判断。
2. 実行した全test command、exit code、失敗・skip。
3. schema/migration/CLI互換性への影響。
4. 生成したEvidenceまたはpacket refs。
5. 未確認事項、残存risk、rollback方法。
6. Acceptance criteriaを一項目ずつ満たした根拠。

「実装した」「テストは通るはず」「レビュー済み」という主張だけではcloseしない。
