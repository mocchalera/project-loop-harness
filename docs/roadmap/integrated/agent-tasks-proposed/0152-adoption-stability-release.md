# 0152: Publish adoption path, compatibility matrix, and contract stability policy

- **Status:** Proposed
- **Milestone:** M8 / External Evidence
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** `0151`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

PLHの内部能力が高くても、READMEがarchitecture-firstで概念が多く、supported/experimentalの境界が不明なら採用されない。評価結果と実互換性を正直に反映した導線が必要。

## Goal

痛み→3-command demo→証拠packet→advanced featuresの順へdocsを再構成し、互換性・安定性・限界を公開する。

## Scope

- README冒頭をProve Done/Resume Anywhere中心に書き直す。
- `pcl start`→agent work→`pcl finish`→`pcl resume`の10分golden pathを載せる。
- Direct/Discover/Assureを必要時だけ説明する。
- MCP/agent/OS/Python compatibility matrixを公開する。
- packet contract stability、deprecation、migration、support policyを文書化する。
- AGENTS.md、hooks、CI、transcriptとの違いを説明する。
- benchmark methodologyと実測結果を条件付きで掲載する。
- known limitations、security non-guarantees、recovery contractを明記する。

## Proposed implementation

- 機能一覧をREADME最上部に置かない。
- 未測定のtoken/品質claimを書かない。
- supportedとexperimentalをbadge/tableで分ける。
- copy/paste exampleをCIで実行するdocs testを作る。
- 日本語/英語docsのsource of truthと更新方法を決める。

## Likely affected surfaces

- README
- quickstart/golden path
- compatibility docs
- contract/deprecation policy
- examples/docs tests
- release notes

## Invariants

- 実測条件なしの性能claimなし。
- 未確認clientをsupported扱いしない。
- security/OS isolationを誇張しない。
- advanced ontologyを初回必須にしない。

## Non-goals

- website全面制作。
- hosted demo。
- commercial pricing。

## Acceptance criteria

- 新規環境でREADMEのcopy/paste pathが10分以内にvalid packetを生成する。
- Compatibility matrixがtested version/date/platformを持つ。
- Stable/experimental/deprecated surfaceが一覧化される。
- Docs testがcommand driftを検出する。
- Evaluation結果のsample size、condition、limitationsが併記される。

## Required tests

- Docs code blocks/golden path.
- Fresh wheel install.
- Link/schema fixture checks.
- Compatibility matrix linter.
- English/Japanese drift check if bilingual.

## Evidence required to close

- new-user usability result。
- docs test run。
- compatibility matrix。
- stability policy review。

## Rollout and rollback

- public beta release candidateでdocs freeze。
- known issueを隠さず更新。
- v1 gate未達ならv0.xとして継続。

## Open questions

- README主要言語。
- v1でstableにするcommand/contract一覧。
- public benchmarkの掲載場所。

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
