# 0143: Ship an AI-PLC-inspired Discovery reference Profile

- **Status:** Proposed
- **Milestone:** M5 / Discovery Profile
- **Priority:** P0
- **Estimated size:** L
- **Dependencies:** `0142`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

曖昧なgoalにDirectで入ると、間違った問題を正しく実装する。AI-PLCのCollection、発散、収束、Backtrackは有効だが、4段階すべてをcoreへ強制すべきではない。

## Goal

曖昧なwork targetについて、Context収集→問題整理→代替案→人間decision→approved Work Briefを作るagent-neutral reference Profileを提供する。

## Scope

- `profiles/discovery/`にmanifest、instructions、templates、example outputsを追加する。
- inputはWork Brief draft、target-bound context refs、policy、budget。
- Collectionでsource候補、出典、staleness、unknownを整理する。
- 最低2案の代替を発散し、trade-off、不確実性、可逆性、Evidence refsを出す。
- one human checkpointを必須とし、選択前にexecutionへ進めない。
- outputはWork Brief revision proposalとdecision-proposal/v0。
- 前提変更時のBacktrack/Replan instructionsを含める。
- Claude Code/Codex等への利用例をadapter-neutralに文書化する。

## Proposed implementation

- AI-PLCの概念を参考にするが、名称・ファイル構造・4段階commandをコピーしない。
- 数値scoreを必須にしない。ordinal ratingも根拠を要求する。
- 生成物はclaims-not-facts。出典なし断定をschema/validatorで抑える。
- budget内でCollectionを止めるtermination conditionを持つ。
- clear taskへprofileを適用した場合のexit/skip pathを作る。

## Likely affected surfaces

- built-in profile package
- templates/examples
- profile fixtures
- docs/adapters
- evaluation fixtures

## Invariants

- human selectionなしにcandidateをapproved Decisionにしない。
- Profileはcode/DBを直接変更しない。
- 出典とunknownを隠さない。
- Direct taskへ必須化しない。

## Non-goals

- Story/Spec/Wireframe全部。
- 自動market research。
- web browsing core integration。
- Option table。

## Acceptance criteria

- Ambiguous onboarding fixtureからsource-aware briefと2案以上のdecision proposalが得られる。
- Clear bug fix fixtureではDiscovery不要を返し、無駄な発散を止められる。
- Human selection前にexecution-ready stateへ進まない。
- Outputをprofile ingestでschema validationしEvidenceへlinkできる。
- Backtrack scenarioでreplan proposalを生成できる。

## Required tests

- Profile manifest/fixture validation.
- Ambiguous vs clear task.
- Missing sources/unknown handling.
- Budget termination.
- Human gate required.
- Replan scenario.

## Evidence required to close

- sample discovery bundle/output。
- human decision flow transcript。
- clear-task skip result。
- AI-PLC concept attribution in docs。

## Rollout and rollback

- experimental built-in profile。
- M5ではopt-in。
- 評価でrework改善がなければcoreへ近づけない。

## Open questions

- 最低candidate数。
- Collection source typesをどこまでsupport。
- profile instructionsの日本語/英語同梱。

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
