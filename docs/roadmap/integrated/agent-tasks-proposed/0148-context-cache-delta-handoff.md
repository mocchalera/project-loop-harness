# 0148: Add content-addressed context cache and delta handoff

- **Status:** Proposed
- **Milestone:** M7 / Adaptive Cost & Learning
- **Priority:** P1
- **Estimated size:** XL
- **Dependencies:** `0134`, `0146`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

session/modelを変えるたびに同じrepo contextを再生成・再送すると、token、時間、latencyが増える。単純cacheはstale contextを再利用する危険がある。

## Goal

repository revision、target、policy、selected files等をkeyにcontext artifactを再利用し、前回からのdeltaだけをhandoffできるようにする。

## Scope

- cache key、content hash、producer version、selection policy、freshness contractを定義する。
- context packをcontent-addressed storeへ保存する。
- `pcl context cache inspect/list/gc`を追加する。
- previous packet/cache refからrepo/brief/decision/check deltaを生成する。
- handoffへbase context ref、delta ref、omitted/reused bytesを記録する。
- changed dependency neighborhoodやpolicy versionでinvalidatedする。
- disk quota、retention、manual purgeを実装する。
- secret/redaction metadataをcache key/eligibilityへ考慮する。

## Proposed implementation

- embeddingを使わず、既存deterministic context selectionから始める。
- cache hitでもfreshness checkを行う。
- partial cache corruptionをhashで検出し再生成する。
- platform-independent canonical pathを使う。
- cache本文をhandoff packetへinlineしない。

## Likely affected surfaces

- context pack builder
- artifact store/cache index
- delta generator
- handoff
- CLI GC
- policy

## Invariants

- stale cacheをcurrentとして使わない。
- hash mismatchを無視しない。
- cache削除でsource stateを失わない。
- secret-bearing cacheを無制限共有しない。

## Non-goals

- semantic vector database。
- cross-user cloud cache。
- full repo snapshot。

## Acceptance criteria

- 同じkeyでcontext再生成を避け、同じhash/refを返す。
- Repo/brief/policy変更でcache missまたはdeltaが正しく生成される。
- Hash corruptionで再生成し、silent reuseしない。
- Handoffがbase+deltaから同じselected contextを再構成できる。
- GCがdry-run、quota、pinned refを尊重する。

## Required tests

- Cache hit/miss/invalidation.
- Delta reconstruction.
- Corruption.
- Path normalization.
- GC pinned/active references.
- Secret/redaction eligibility.
- Size/time benchmark.

## Evidence required to close

- before/after bytes/time。
- cache/delta fixtures。
- corruption recovery。
- GC report。

## Rollout and rollback

- opt-in cacheから開始。
- dogfoodでhit rateとstale incidentを測る。
- cross-project共有は後回し。

## Open questions

- cache location/project scope。
- default quota。
- redacted contextのみ再利用するか。

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
