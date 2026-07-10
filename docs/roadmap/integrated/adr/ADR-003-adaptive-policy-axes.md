# ADR-003: Adaptive controlは単一のSimple/Standard/Complexではなく複数軸で解決する

- Status: Proposed
- Date: 2026-07-09
- Owners: PdM / Architecture

## Context

作業規模とriskは一致しない。1行のauth変更は小さくてもhigh riskであり、大規模docs変更はlow riskであり得る。モデル能力、予算、曖昧さも別の要因である。

## Decision

利用者には`direct / discover / assure` presetを示すが、runtimeは次の軸を解決する。

- planning depth。
- verification depth。
- execution chunk size。
- checkpoint frequency。
- context budget。
- tool/time/escalation budget。

routeはdeterministic signalとversioned policyで決め、理由を説明する。overrideは記録する。

## Consequences

- policy resolverとexplain surfaceが必要。
- presetだけより実装は複雑。
- 反面、強いモデルを過剰に縛らず、weak modelやhigh-risk changeへ細かい制御を適用できる。

## Invariant

model strengthはverificationを自動的に弱くしない。riskがverification depthを決める主要要因である。
