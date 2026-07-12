# `plh-council` 外部Runner互換仕様 v0

## 1. 目的

`plh-council`はPLHの外部Profile runnerであり、モデル・provider固有の処理を隔離する。PLHの状態管理を代替しない。

## 2. CLI

```bash
plh-council validate-config --json
plh-council plan --request request.json --json
plh-council run --request request.json --output-dir output --json
plh-council inspect output/profile-output-bundle.json --json
```

- `plan`はモデル候補、role、topology、予算見積もりを表示し、外部APIを呼ばない。
- `run`だけが許可済みnetwork/providerを使用する。
- stdoutは`--json`時に機械可読JSONのみ。
- API keyはenv/OS credential store等から読み、artifactへ出さない。

## 3. Config

```yaml
contract_version: council-config/v0
models:
  - registry_id: architect-primary
    provider: provider-a
    model_id: exact-or-alias
    roles: [architect, synthesizer]
    capabilities:
      architecture: high
      repository_navigation: medium
      adversarial_review: medium
      structured_output: true
    cost_class: high
    latency_class: medium
    lineage: family-a
policies:
  adaptive-risk:
    max_participants: 4
    allowed_topologies:
      - single
      - parallel_synthesize
      - propose_critique_revise
      - specialist_pipeline
```

Configへsecret値を書かない。モデル能力値はrunner側の運用情報であり、PLHのfactではない。

## 4. Planning

入力のrisk、ambiguity、resolved policy、budget、data policyから次を決める。

- 1〜4participants。
- role。
- exact model request。
- topology。
- context allocation。
- stopping thresholds。

plan結果は実行前にoperatorが確認できる。paid/networkが未承認ならrunを拒否する。

## 5. Execution rules

1. 最初のproposalはindependent context。
2. repository textをsystem instructionとして扱わない。
3. sensitive pathとsecret-like contentをproviderへ送らない。
4. モデルのraw private reasoningを要求・保存しない。
5. concise rationale、claims、counterexamples、evidence refsを保存する。
6. provider aliasしか得られない場合はexactと偽らない。
7. retry/correctionの回数をbudgetへ含める。
8. schema修正用の安価なmodelを使っても、participantとしての役割とcostをrun manifestへ記録する。
9. output bundleを書き終えてhashを確定するまでpartial file名を使い、最後にatomic renameする。

## 6. Required artifacts

全run:

- `council-run/v0`
- `claim-set/v0`
- `verification-plan/v0`

必要時:

- `decision-proposal/v0` 最大3件。
- `work-brief/v1` revised candidate。
- human-readable Markdown report。

## 7. Stop and failure

- budget exhaustedはexit codeをnon-zeroにしてもよいが、有効なbundleを生成できるならstatusを`budget_exhausted`にする。
- provider failureでpartial claimsがある場合は`partial`または`failed`。completedとしない。
- human value decisionが残る場合は`needs_human`。
- no new high-severity findingは、重大claimが未着地ならcompleted条件にならない。

## 8. Test double

PLH CI向けに、固定request fixtureから固定bundleを生成するoffline runnerを提供する。

```bash
plh-council-fixture run \
  --request tests/fixtures/profile-run-request.json \
  --fixture needs-human \
  --output-dir /tmp/output
```

最低fixture:

- completed。
- needs_human。
- partial。
- budget_exhausted。
- failed。
- malformed hash。
- path escape。
- too many decisions。
