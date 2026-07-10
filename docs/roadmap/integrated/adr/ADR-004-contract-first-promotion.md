# ADR-004: 外部契約を先に固定し、内部Entityは利用実績から昇格する

- Status: Proposed
- Date: 2026-07-09
- Owners: Architecture / Maintainers

## Context

PLHは既に多くのentityとCLI surfaceを持つ。新しい概念をtableから始めると、migration、CRUD、validation、dashboard、MCP、docsが一度に増え、初回価値が遠ざかる。

## Decision

新概念は次の順で導入する。

1. JSON Schema付きartifact。
2. generic Evidenceとして保存。
3. eventとlinkで利用履歴を観測。
4. 複数repoで不足が確認された場合だけ専用tableへ昇格。

external packet contractは内部DB rowをそのまま公開しない。producer/consumer fixtureで互換性を検証する。

## Consequences

- 初期実装が小さく、外部adapterが使いやすい。
- artifact queryのUXを整える必要がある。
- entity promotion判断を感覚ではなく利用データで行える。
