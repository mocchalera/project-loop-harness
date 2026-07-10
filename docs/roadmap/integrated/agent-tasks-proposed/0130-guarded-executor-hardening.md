# 0130: Rename and harden the guarded executor surface

- **Status:** Proposed
- **Milestone:** M1 / Trust Foundation
- **Priority:** P1
- **Estimated size:** M
- **Dependencies:** `0123`
- **Owner:** TBD
- **Reviewer:** At least one maintainer not implementing the task

## Problem

ホスト上の`subprocess`実行を「sandbox」と呼ぶとOS isolationを連想させ、保証を過大に見せる。さらにstdout/stderrの無制限captureやsecret-shaped output保存は安定性・privacy riskになる。

## Goal

実態を`guarded executor`として正確に表現し、output cap、streaming Evidence、redaction metadata、明示的permission contractを追加する。

## Scope

- docs、help、status outputの「sandbox」を保証に合う用語へ変更する。
- 既存public command/API名がある場合はdeprecation aliasを設計する。
- stdout/stderrをstreaming fileへ保存し、memory capture上限を設ける。
- 最大bytes、timeout、truncation reason、original byte countをEvidence metadataに記録する。
- 環境変数継承、working directory、allowed command、network/FS非隔離を明示する。
- configurable redaction filterをEvidence保存前に適用し、redacted=trueを記録する。
- 「secret scannerではない」ことをdocsで明記する。

## Proposed implementation

- commandはlist形式、`shell=False`の既存contractを維持する。
- redaction patternは保守的にし、raw outputを別所へ黙って保存しない。
- truncated outputでもexit codeとtail/head strategyを再現可能に記録する。
- large binary outputをtext decodeで壊さずbinary/encoding metadataを扱う。
- actual container backendはextension pointだけ定義し、このtaskで実装しない。

## Likely affected surfaces

- `src/pcl/workflow_sandbox.py` or successor
- Evidence output capture
- security docs
- CLI help
- deprecation tests

## Invariants

- OS isolation、network isolation、secret detectionを保証しない。
- output cap超過をsuccess logとして偽装しない。
- redaction有無をpacketから識別できる。

## Non-goals

- Docker/devcontainer backend。
- malware/secret scanning。
- arbitrary shell script support。

## Acceptance criteria

- Large output commandがmemoryを無制限消費せず、artifactにtruncation metadataを残す。
- Secret fixtureがconfigured patternでredactされ、raw valueがEvidenceへ残らない。
- Help/docsがguarded executorの保証と非保証を説明する。
- Existing safe command workflowが互換aliasまたはmigration note付きで動く。

## Required tests

- Large stdout/stderr streaming.
- Timeout and process termination.
- Redaction positive/negative fixtures.
- Binary/invalid UTF-8 output.
- Deprecated naming behavior.
- Environment allow/deny tests.

## Evidence required to close

- peak memory comparison。
- redaction fixture result。
- help/doc diff。
- security review checklist。

## Rollout and rollback

- 用語変更はrelease noteへ。
- 旧名称を一release残す場合はwarningをstderrへ。
- redaction defaultによるfalse positiveをdogfoodで観測。

## Open questions

- default output cap。
- 環境変数allowlistの互換影響。
- raw outputを明示opt-inで保存可能にするか。

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
