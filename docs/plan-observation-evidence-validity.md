# Observation Evidence Validity 実装計画

## 0. 文書の位置づけ

本書は、Evidence の存在・SHA-256・来歴だけでは品質 claim の真実性を証明できない問題を埋めるための実装計画である。実装仕様を確定するものではなく、実装担当が Project Loop Harness の Story / Test へ分解できる粒度の計画と判断ゲートを示す。

- 改訂日: 2026-07-19
- 改訂根拠: 第三者 Codex review `c9538841` の P0–P2 findings
- 改訂状態: **GO WITH CHANGES の必須変更を反映済み。実装は Phase 1A から開始可能**
- 実装境界: 本書の更新は docs-only。DB migration、PCL state mutation、runtime 実装を含まない

根拠として、`AGENTS.md`、`CLAUDE.md`、`README.md`、`pcl.yaml`、`docs/architecture.md`、`docs/data-model.md`、`docs/evidence-set-v1.md`、`docs/completion-policy-v1.md`、`docs/approval-provenance-v1.md`、`docs/adaptive-policy-v1.md`、`docs/council-profile.md`、`docs/research/2026-07-18-akihiro-genai-post-interpretation.md`、Cockpit Talk Room `talk_e0b9f514`、`src/pcl`、`tests` を照合した。Talk Room の合意は次のとおりである。

1. ドメイン固有 capture は外部 adapter / profile の責務とする。
2. PCL コアは、凍結した target / cohort / artifact / policy、hash、完全性、actor provenance、決定論的 gate を扱う。
3. 生成担当の自己比較は診断であり、completion に寄与するのは別 actor の Reviewer Verdict または人間 Verdict だけとする。ただし、actor 名と source ref の差だけで認証済み独立性を主張しない。
4. hash は同一 bytes を示すだけであり、真実性、網羅性、美しさ、楽しさを示さない。
5. 外部 adapter の失敗や不明状態は `pass` に倒さず、`unknown` / `incomplete` / human review に倒す。

本文中の新しい契約名、CLI 名、event 名、設定名はすべて**提案名**であり、実装前に命名レビューを行う。

### 0.1 第三者 review の反映表

| Finding | 本計画での解消先 | 実装開始条件 |
| --- | --- | --- |
| P0: copied Evidence / Evidence Set が immutable event anchor と未照合 | C.3、D.5、Phase 1A | Phase 1A の受け入れ条件を満たすまで terminal gate へ接続しない |
| P0: actor/source は自己申告で、独立性を偽装不能にできない | A.2、D.4、J | v1 は `declared_separation` と表示し、認証済み独立性と呼ばない |
| P1: v1 evaluator は mutable work-root を再読込する | C.3、E.2、Phase 1B | v2 は predicate semantics だけを共有し、copy-only resolver を使う |
| P1: cohort の権威と集合不変条件が不足 | D.3、Phase 1B | resolved cohort と集合等式の fixture が通る |
| P1: Verdict revocation / current validity が未定義 | G.2、Phase 1C | sequence projection と明示 event ID の規則を固定する |
| P1: strict 実装後も dashboard が legacy と区別できない | G.3、Phase 1E | Phase 1 の一部として最小 trust class を出す |
| P2: subject / evaluator digest が自己申告 | D.5、Phase 1B | copied bytes または builtin evaluator ID から再構築する |
| P2: zero-mutation 観測範囲不足、Phase 1 過大 | Phase 1A–1E | slice ごとに独立受け入れ・rollback を持つ |

---

## A. 問題定義

### A.1 分離すべき5概念

| 概念 | 答える問い | PCL が機械的に確認できること | PCL が自動的に真実にできないこと |
| --- | --- | --- | --- |
| **Integrity** | 証拠は存在し、記録時と同じ bytes で、対象と来歴が結ばれているか | path 境界、hash、copy、Evidence ID、target link、policy / receipt hash、actor / recorder の申告 provenance | report の内容が現実を正しく表すか |
| **Relevance** | その証拠は当該 claim を実際に観測しているか | claim digest、subject/build digest、scope/cohort、baseline、rubric、対象 artifact の相互 binding | capture が意味上 claim に適切かという最終判断 |
| **Sufficiency** | claim を支持するのに観測量・範囲・評価が十分か | required cohort、観測済み・未観測範囲、必須 report、Verdict の明示結果、policy 閾値 | 全状態を観測したこと、未知の失敗がないこと |
| **Verdict** | 誰が、どの bytes と scope を見て、どの rubric で、何と判断したか | actor / recorder / source、対象 hash、rubric / evaluator / policy 版、claim ごとの判定、独立性ルール | actor の実世界の身元認証、実際に注意深く見たこと |
| **Residual Risk** | Verdict 後も何が未観測・未確定・許容済みか | 未観測 cohort、`unknown`、risk severity、理由、mitigation、human decision の保存 | 「リスクなし」の絶対証明 |

### A.2 保証境界と脅威モデル

最初の実装は、PCL の正規 CLI / service layer を使う actor に対して、取り違え、古い receipt の再利用、caller-declared scope の縮小、mutable source の差し替えを fail closed にする。次は保証しない。

- SQLite / event row / copied Evidence を直接改変できる特権 local actor への耐タンパー性。
- CLI 引数で申告された actor 名、Cockpit task ID、human identity の真正性。
- capture が現実を忠実に表すこと、reviewer が実際に注意深く閲覧したこと。

API / event / dashboard は actor assurance を次のように分離し、`declared_separation` を「偽装不能な独立評価」と表示してはならない。

| `independence_assurance` | 意味 | 初回 slice での扱い |
| --- | --- | --- |
| `none` | self assessment または同一 actor | completion-ineligible |
| `declared_separation` | producer と異なる namespaced actor / source が申告された | policy が明示許可する低・中リスクのみ候補。真正性は Residual Risk |
| `host_verified_session` | host 発行の検証可能 receipt が別 session を証明する | receipt contract 導入後のみ使用可。文字列 source ref だけでは付与禁止 |
| `human_origin` | human actor と mediated provenance が申告された | R4 の最低条件。ただし外部認証がなければ identity 自体は自己申告 |

### A.3 穴の中心

現行の Evidence Set は、caller が宣言した required kind と manifest に対して complete かを判定する。Completion Policy は hash-bound report の JSON predicate を決定論的に評価する。これは重要な Integrity 境界だが、次の laundering を単独では防げない。

- manifest の `status: pass` を、その report の真実性として扱う。
- caller が required kind を狭く宣言し、未観測 cohort を隠して `complete` にする。
- `--include KIND=E-XXXX:ROLE` に、report bytes と無関係な既存 Evidence ID を指定する。
- 生成担当が作った自己比較 report を `independent_verdict` 相当として扱う。
- build A の capture で build B の claim を承認する。
- policy / rubric / evaluator の版が変わった後に、古い Verdict を再利用する。
- hash 一致を、正しさ・網羅性・主観品質の証明として dashboard や completion 表示で誤読する。

したがって、Integrity を強化するだけでなく、claim と観測対象の binding、明示 scope、別 actor の Verdict、Residual Risk を terminal preflight に追加する必要がある。

---

## B. 現状監査

### B.1 すでに守られている境界

| 境界 | 現行実装 | 現行テスト / 文書 |
| --- | --- | --- |
| Evidence は state mutation と event を経由する | `src/pcl/evidence.py::record_adhoc_evidence`, `insert_evidence_link`, `require_healthy_terminal_evidence` | `tests/test_evidence_add.py`, `docs/data-model.md` の Adhoc Evidence Manifests |
| copied Evidence は保存 copy の bytes と hash を確認する | `src/pcl/evidence.py::record_adhoc_evidence`, `assess_adhoc_evidence`; copied member は `storage_mode` / `stored_path` を持つ | `docs/data-model.md` 236–266行相当、`tests/test_evidence_add.py` |
| superseded / missing / unhealthy Evidence は terminal proof にならない | `src/pcl/evidence.py::require_healthy_terminal_evidence` | `tests/test_lifecycle_integrity.py::test_drifted_evidence_is_rejected_before_mutation` |
| Evidence Set は exact target、明示 work root、manifest、known/included/excluded、全 report hash を固定する | `src/pcl/contracts/evidence_set.py::validate_evidence_set`; `src/pcl/evidence_sets.py::plan_evidence_set`, `record_evidence_set`, `_load_report_manifest`, `_safe_report_path` | `tests/test_evidence_sets.py::test_plan_is_read_only_and_required_exclusion_is_incomplete`, `test_record_creates_one_evidence_link_and_event_then_show_is_read_only`, `test_invalid_inputs_leave_zero_traces` |
| Evidence Set の complete は required report の存在・選択・`status=pass` と整合しなければならない | `src/pcl/contracts/evidence_set.py::_completeness`; `src/pcl/evidence_sets.py::_build_artifact` | `tests/test_evidence_sets.py::test_validator_rejects_semantically_false_complete_receipt`, `test_missing_required_kind_is_a_deterministic_incomplete_finding` |
| Completion Policy は任意コードを実行せず、制限 JSON path / operator のみを評価する | `src/pcl/contracts/completion_policy.py::validate_completion_policy`; `src/pcl/completion_policies.py::evaluate_completion_policy`, `_apply_operator` | `tests/test_completion_policy.py::test_completion_policy_fixture_validates_without_project_state` |
| Test の strict Evidence Set 経路は exact Test target、set complete、report hash、predicate を事前評価し、失敗時 zero mutation | `src/pcl/completion_policies.py::require_completion_policy`; `src/pcl/stories.py::_transition_test_case`, `reverify_test_case` | `tests/test_completion_policy.py::test_prototype_verdict_rejects_test_pass_with_zero_traces`, `test_incomplete_evidence_set_rejects_even_complete_verdict`, `test_missing_policy_report_and_drifted_report_reject_without_mutation` |
| 成功時は policy hash、Evidence Set hash、predicate results を terminal event に保存する | `src/pcl/completion_policies.py::evaluate_completion_policy`; `src/pcl/stories.py::_transition_test_case` の `completion_evaluation` | `tests/test_completion_policy.py::test_complete_verdict_passes_and_records_evaluation`, `test_passing_test_can_be_explicitly_reverified_without_replaying_pass` |
| human approval と agent recorder を区別し、review 対象 bytes を hash bind できる | `src/pcl/approval_provenance.py::approval_provenance`, `resolve_recording_provenance`; `src/pcl/work_briefs.py::approve_work_brief`, `review_work_brief` | `tests/test_work_briefs.py::test_brief_add_show_approve_and_idempotency`, `test_agent_review_is_hash_bound_but_cannot_approve_human_gate`; `docs/approval-provenance-v1.md` |
| adaptive policy は R2/R3 で independent、R4 で human verification の floor を宣言する | `src/pcl/adaptive_policy.py`; packaged `adaptive-policy-v1-default.json` | `tests/test_adaptive_policy.py::test_assure_resolution_applies_non_overridable_risk_floor`, `test_unknown_policy_fields_and_weak_risk_floor_are_rejected` |
| Council / model agreement は approval や proof にならない | `docs/council-profile.md`; Profile ingest / decision provenance 実装 | Council 関連 tests。今回の gate は Council 多数決を再利用しない |
| dashboard は SQLite / event から生成される human view であり source of truth ではない | `src/pcl/renderer.py::render_dashboard`; `docs/architecture.md` | `tests/test_dashboard_data_contract.py`, `docs/dashboard-data-contract.md` |

### B.2 現行 CLI と terminal 経路

- Evidence Set:
  - `pcl evidence-set plan|record|show`
  - parser / dispatch: `src/pcl/cli.py` の `p_evidence_set` と `plan_evidence_set` / `record_evidence_set` 呼び出し。
- Completion Policy:
  - `pcl completion evaluate --policy ... --evidence-set ... [--test ...]`
  - `pcl test pass|reverify ... --evidence-id E-... --completion-policy ...`
  - parser / dispatch: `src/pcl/cli.py` の `p_completion_evaluate`, `p_test_pass`, `p_test_reverify`。
- Workflow Verification:
  - `pcl verification record --run ... --result ... --verifier-role ... --rubric-json|--rubric-file ...`
  - mutation: `src/pcl/lifecycle.py::record_verification`
  - read: `src/pcl/verifications.py::list_verifications`, `read_verification`
  - terminal use: `complete_workflow_run`, `_approved_verification_id`, `_require_approved_goal_verification`, `_require_approved_defect_verification`。
- その他 terminal:
  - Test: `src/pcl/stories.py::_transition_test_case`, `reverify_test_case`
  - Feature done: `src/pcl/commands.py::set_feature_status`, `_guard_feature_done`
  - Task done: `src/pcl/tasks.py::set_task_status`; packet 自動遷移は `src/pcl/finish_execution.py::_apply_terminal_transition`
  - Goal close: `src/pcl/lifecycle.py::close_goal`, `_require_completed_goal_packet`
  - Defect: `fix_defect`, `verify_defect`, `close_defect`
  - Completion packet: `src/pcl/finish_execution.py::_completion_outcome`, `_build_packet`, `_commit_completion_packet`

### B.3 不足している runtime 契約

1. **Evidence ID と report bytes の exact binding がない。**
   `src/pcl/evidence_sets.py::_validate_selected_evidence` は Evidence ID の存在だけを確認し、`_build_artifact` は selection の ID / role を report metadata に結合する。選択した Evidence が同じ report bytes を保存しているかは確認しない。

2. **required kind の十分性は caller 宣言に依存する。**
   `evidence-set/v1` は caller-declared required kinds に対する completeness を正しく証明するが、必要な cohort / report kind の選び方自体は証明しない。これは `docs/evidence-set-v1.md` の明示済み epistemic boundary であり、既存機能の欠落ではない。

3. **manifest `status` は外部 claim である。**
   `_load_report_manifest` は `pass|fail|warning|unknown` の形と report hash を確認するが、report 内容から status を導出しない。これも `docs/completion-policy-v1.md` の境界どおりである。

4. **claim / subject / build / baseline / cohort / unobserved scope の共通 binding がない。**
   Completion Policy v1 predicate は個別 report の scalar を評価できるが、複数 report 間で同じ claim / subject / scope / rubric を見ているか、また未観測範囲が宣言されたかを検証しない。

5. **自己評価と独立 Verdict の actor 分離が terminal gate にない。**
   `approval-provenance/v1` は Work Brief 等で actor / recorder を分けられるが、Completion Policy v1 の評価には actor receipt がない。`record_verification` の `verifier_role` は文字列であり、actor identity、recorder、source、reviewed bytes、producer との差を固定しない。

6. **adaptive verification depth と Verdict actor の runtime enforcement が接続されていない。**
   adaptive policy は independent / human floor を解決するが、現在の `record_verification` や Test Completion Policy preflight がその actor provenance を検証する経路はない。

7. **policy hash は event に残るが、policy bytes の durable Evidence ref がない。**
   `completion_evaluation` は `policy_sha256` を残すが、後日 reviewer が同じ policy bytes を必ず開ける契約ではない。rubric / evaluator version も共通 binding に含まれない。

8. **dashboard は Integrity と Validity を分けて表示しない。**
   現行 dashboard は Evidence、Verification、approval provenance、evidence-backed done を表示するが、observed / unobserved、self / independent、Relevance / Sufficiency、Residual Risk を独立軸で示さない。`_approval_provenance_rows` も Work Brief event に限定される。

9. **terminal surface ごとに保証強度が異なる。**
   - direct Test は Evidence Set + Completion Policy の最も強い既存経路を持つ。
   - Feature done は Story / Test / Defect guard と健康な adhoc Evidence を要求するが、Evidence Set / independent Verdict を直接要求しない。
   - Task は `set_task_status` では reason のみで done にでき、`pcl finish --emit-packet` 経路は configured checks の成功を L2 claim として packet 化する。
   - Workflow / Goal / Defect は approved Verification を使えるが、その Verification の actor / reviewed bytes 独立性は強制しない。

10. **copied member と Evidence Set artifact が記録 event に再 anchor されない。**
    adhoc Evidence の event payload は記録時 member metadata を持つが、現行 health check は mutable manifest を読み、対応 event payload との一致を確認しない。Evidence Set も `evidence_set_recorded.artifact_sha256` を保存する一方、`inspect_evidence_set` は現在 artifact の canonical hash と event anchor を比較しない。`stored_path` の Evidence-ID canonical directory、regular non-symlink file、single-open file identity も strict invariant ではない。

11. **Completion Policy v1 evaluator は mutable work-root report を再読込する。**
    v1 の predicate operator は再利用可能だが、v2 が v1 evaluator をそのまま逐次呼び出すと、copy-only evaluation の保証を失う。

12. **Verdict の current validity / revocation projection がない。**
    明示 event ID は selection を決定的にするが、選択 event より後の revocation、Evidence supersession、過去 pass の現在 trust 表示を定義しなければ、失効済み Verdict を再利用できる。

13. **dashboard の evidence-backed done は proof class を区別しない。**
    passing Test は proof の種別にかかわらず同じ完了面へ載るため、strict gate の導入と同時に最低限の derived trust class が必要である。

最初から全 terminal surface を同時変更せず、既存の最強経路である **Test + Evidence Set + Completion Policy** に opt-in strict validity を追加する。

---

## C. 推奨する最小設計

### C.1 結論

推奨は、**Evidence Set v1 を Integrity receipt のまま変更せず、Completion Policy の versioned successor と event-based Verdict provenance を足す**ことである。

- DB entity は追加しない。
- schema migration は行わない。
- Evidence、Evidence Links、Events、Test terminal event を再利用する。
- ドメイン capture は外部 adapter / profile に残す。
- strict validity はまず Test 1件に明示 opt-in する。
- `completion-policy/v1`、legacy adhoc Evidence、既存 terminal flow は再解釈しない。
- v1 の predicate **operator semantics** は再利用してよいが、mutable report loader は v2 から呼ばない。
- v1 が実装するのは申告上の actor 分離であり、host 認証済み独立性ではない。

### C.2 提案する artifact / receipt

以下は提案名である。

1. **`observation-scope/v1`**
   - exact Test claim digest
   - subject/build digest と対象 artifact refs
   - baseline requirement と baseline refs
   - cohort / observation dimensions
   - observed ranges と unobserved ranges
   - selection method、seed、environment、adapter/tool version
   - evaluation rubric Evidence ref / hash / version
   - producer actor

2. **`observation-evaluation/v1`**
   - `evaluation_kind: self_assessment|reviewer_verdict`
   - `scope_sha256`, `claim_sha256`, `subject_sha256`, `rubric_sha256`, `policy_sha256`
   - reviewed Evidence refs と exact member hashes
   - claim ごとの `relevance`, `sufficiency`, `result`, reasons
   - residual risks と未観測範囲への判断
   - evaluator name / version
   - actor の申告と `independence_assurance`

3. **`observation_verdict_recorded` event**
   - `approval-provenance/v1` の actor / recorder / source を再利用
   - Verdict report Evidence ID と canonical artifact/member hash
   - Evidence Set ID / hash
   - policy Evidence ID / hash
   - scope / claim / subject / rubric hash
   - producer actor と verdict actor の分離結果、および assurance class
   - Verdict は「誰が何を見たと申告したか」の receipt であり、身元認証や注意深い閲覧の証明ではないことを維持

4. **`completion-policy/v2` の strict validity block**
   - v1 の predicate operator semantics を共有する versioned successor とする。v1 に field を直接追加せず、v1 の mutable work-root loader も呼ばない。
   - policy が required report kinds を宣言し、caller の `--required-kind` がその superset であることを確認する。
   - scope / self assessment / reviewer verdict / rubric / policy の report kind mapping を宣言する。
   - required actor class、最大許容 residual risk、baseline rule、copied Evidence requirement を宣言する。
   - self assessment の結果は diagnostic output にのみ載せ、completion eligibility の計算には使わない。

### C.3 strict evaluation の順序

1. Evidence Set ID に対応する authoritative `evidence_set_recorded` event row が**ちょうど1件**あることを確認する。
2. Evidence Set v1 の contract / target / completeness を確認し、現在 artifact の canonical hash と event の `artifact_sha256` を照合する。anchor の欠落・重複・不一致は completion-ineligible とする。
3. policy v2 が要求する report kind が required かつ included か確認する。
4. 各 report Evidence ID に対応する authoritative `adhoc_evidence_recorded` event row がちょうど1件あることを確認し、現在 manifest が anchored member metadata と canonical exact match することを確認する。
5. copied member の `stored_path` が `.project-loop/evidence/adhoc-files/<EVIDENCE-ID>/` 配下の canonical path で、regular non-symlink file であることを確認する。
6. file を no-follow / file-identity check 付きで1回だけ開き、同じ opened bytes を hash と JSON parse の両方に使う。hash 後の path 再読込は禁止する。
7. v2 predicate input は verified copied bytes resolver からだけ取得し、mutable work-root source を読まない。
8. scope、claim、subject/build、baseline、cohort、rubric、policy の binding digest を copied bytes または builtin evaluator identity から再計算・照合する。
9. self assessment と Reviewer Verdict を区別し、Verdict event の actor / recorder / source と reviewed bytes を照合する。
10. producer actor と Verdict actor の**申告上の分離**、`independence_assurance`、policy が要求する actor kind / assurance floor を確認する。
11. claim ごとの Relevance / Sufficiency / result と Residual Risk を評価する。
12. 選択 Verdict event より後に有効な revocation がないこと、contributing Evidence が superseded / unhealthy でないことを sequence projection で確認する。
13. missing / duplicate anchor / mismatch / unknown / inconclusive / adapter failure は completion-ineligible にする。
14. 成功時だけ `test_case_passed` / `test_case_reverified` event に既存 `completion_evaluation` と追加の `validity_evaluation` receipt を保存する。

### C.4 採用しない代替案

| 代替案 | 採用しない理由 |
| --- | --- |
| `verdicts` / `claims` / `observations` の新テーブルを最初から追加 | 現行 Evidence + link + event で最小 slice を表現できる。migration は人間承認が必要で、検索・一意性・revocation 要件が未確定 |
| `verifications` table を直接拡張して direct Test に流用 | 現行は `workflow_run_id NOT NULL` で workflow-bound。direct route に空 Workflow Run を作るのは既存方針と衝突し、意味変更または migration が必要 |
| Evidence Set v1 に scope / verdict fields を直接追加 | strict contract の `additionalProperties: false` と versioning を破る。Evidence Set の Integrity 境界も曖昧になる |
| manifest の `status: pass` を独立 Verdict とみなす | external self-claim のままで actor / claim / scope / rubric binding がない |
| self assessment を別 role 名にするだけで independent とみなす | 同一 actor が role 文字列を変える laundering を防げない |
| Council 多数決または単一 LLM judge を品質証明にする | agreement / model label は proof ではなく、provider lock と自己承認を招く |
| WEB / 映像 / ゲーム capture engine を `src/pcl` に実装 | domain-agnostic、dependency-light、model-neutral の境界を破る |
| dashboard の表示状態を terminal gate の入力にする | dashboard は human-only view であり source of truth ではない |
| 全 cohort / 全状態の観測を必須にする | 組合せ爆発し、観測コストを品質と誤認する。required floor + risk 上積みにする |

### C.5 非機能要件

- Python standard library first とし、Phase 1 で新 dependency、network、provider、subprocess 実行を追加しない。
- read-only evaluate は DB row、event、outbox、Evidence Link、file、ID allocationを変更しない。
- record / revoke は既存 mutation transaction と outbox 規則に従い、domain write と event row を同一 transaction に置く。
- canonical JSON、set ordering、finding ordering、event selection は同じ入力から byte-identical output を返す。
- strict resolver は既存 Evidence copy size/count limit を超えて無制限に memory/read cost を増やさない。各 member は1回だけ開き、hash と parse のために別読込しない。
- event lookup は `event_type + entity_id` で対象を限定する。既存 index で許容できない性能が実測された場合は、全scan fallbackを製品化せず migration proposal に戻す。
- typed error code と JSON top-level shape は compatibility fixture で固定し、human wording と machine result を分離する。
- current trust projection の失敗は `unknown` / `revoked_or_unhealthy` に倒し、過去の terminal event を暗黙に書き換えない。

---

## D. claim / evidence / scope / actor / version binding

### D.1 claim binding

最初の slice は新しい Claim entity を作らず、Test を acceptance claim とする。

- `claim_id`: `TC-XXXX`
- `claim_sha256`: Test の `id`, `feature_id`, `story_id`, `type`, `scenario`, `expected` を canonical JSON 化した hash
- `target`: `test_case:TC-XXXX`
- terminal 時に DB 上の現在値から digest を再計算する
- Verdict 作成後に scenario / expected が変わっていれば fail closed する

Feature / Goal / Task claim への一般化は後続 phase とし、Work Brief / Story / completion packet のどれを claim source にするかは別途決める。

### D.2 subject / build binding

scope artifact は最低限、次を持つ。

- repository base/head/diff hash または build artifact Evidence ref/hash
- build ID、environment、device/profile、fixture/seed/input
- capture artifact refs/hashes
- baseline refs/hashes、または `not_applicable` と理由

すべての capture / self assessment / Reviewer Verdict は同じ `subject_sha256` と `scope_sha256` を参照する。wrong build や cherry-picked capture は digest mismatch または reviewed set 不一致として拒否する。

### D.3 cohort と未観測範囲

コア schema に WEB viewport、映像 fps、ゲーム tick を固定しない。profile が domain dimensions を key/value として宣言し、コアは次だけを検証する。

- 初回 slice は明示列挙された静的 cohort を対象とし、各 entry は stable `cohort_entry_id` を持つ。
- policy が最低 required cohort を決め、profile はそれを上積みだけできる。`resolved_required = canonical_union(policy.required, profile.required)` とし、scope の required entries は resolved receipt と exact match しなければならない。
- profile を使わない場合も `scope.required ⊇ policy.required` を満たし、追加 entry は scope に明示する。
- required / observed / unobserved は重複なし・canonical order とし、`observed ∩ unobserved = ∅`、`observed ∪ unobserved = required` を必須とする。
- observed / unobserved の全 entry は required の部分集合であり、unknown entry、重複 ID、欠落 required entry を拒否する。
- selection は `algorithm_id`, `algorithm_version`, `seed`, `input_sha256`, `selected_entry_ids_sha256` を持ち、同じ入力から同じ canonical order を再現できる。
- unobserved entry が空でも、空配列として明示される。
- cohort 外を「問題なし」と表示しない。
- external adapter が `failed` / `unknown` / `partial` のとき、Verdict が勝手に `approved` へ上書きできない。

動的 sampling や domain-specific selection algorithm の自動実行は Phase 3 へ送り、Phase 1B では provider-free fixture による集合不変条件と digest の決定性だけを実装する。

### D.4 actor 分離

- `self_assessment.actor` は producer actor と一致してよいが、completion eligibility に寄与しない。
- `reviewer_verdict.actor` は producer actor と異ならなければならないが、文字列差だけで認証済み独立性とは呼ばない。
- agent Verdict は namespaced actor と distinct context/source ref を要求し、初回は `independence_assurance=declared_separation` と記録する。
- `host_verified_session` は host 発行 receipt の schema・検証器・replay guard が実装されるまで指定不可とする。
- R4 は `human_origin` を要求する。
- agent/system が human Verdict を記録する場合は、既存 `resolve_recording_provenance` と同じく `conversation|cockpit` source と non-empty source ref を要求する。
- PCL は identity provider ではないため、名前空間と human identity の真正性は Residual Risk として明示する。

「同一モデルの別 session を `declared_separation` として completion に許可するか」は Phase 1C 前の人間判断にする。Phase 1A / 1B の byte resolver と read-only contract evaluation はこの判断を待たず進めてよい。

### D.5 rubric / evaluator / policy / reviewed bytes の固定

- rubric と completion policy は `pcl evidence add --copy` で ordinary Evidence として保存し、Evidence Set に含める。
- Verdict report は `rubric_sha256`, `policy_sha256`, `evaluator_name`, `evaluator_version` を持つ。
- Verdict event は Verdict report の copied member hash、Evidence Set hash、policy Evidence hash を持つ。
- terminal event は上記に加え、再計算済み `claim_sha256`, `subject_sha256`, `scope_sha256` を保存する。
- `subject_sha256` / build digest は report の自己申告値を信頼せず、scope が参照する verified copied subject/build artifact bytes と canonical metadata から PCL が再構築する。これは同じ subject bytes への binding であり、その bytes が現実を忠実に表す証明ではない。
- external evaluator は copied evaluator artifact Evidence ID / SHA-256 を必須とし、policy allowlist と照合する。builtin evaluator は versioned builtin ID と PCL package / contract versionから固定 identity を生成する。任意の自己申告 `evaluator_version` だけでは completion に寄与させない。
- strict resolver は exactly one `adhoc_evidence_recorded` anchor を使い、manifest member metadata の exact match、Evidence-ID canonical directory、regular non-symlink file、single-open hash/parse を保証する。
- Evidence Set artifact は exactly one `evidence_set_recorded` anchor の `artifact_sha256` と再照合する。
- policy / rubric / evaluator mismatch は `inconclusive` ではなく typed preflight error とし、zero mutation を保証する。

---

## E. 既存契約の再利用とドメイン境界

### E.1 Evidence Set v1

- target-bound receipt、manifest、included/excluded、required kinds、report hashes、deterministic artifact をそのまま使う。
- `complete` の表示は「宣言された required report が揃った」という意味に限定する。
- strict validity evaluator が policy-required kinds、exact Evidence-to-report binding、`evidence_set_recorded.artifact_sha256` anchor を追加確認する。
- Evidence Set v1 自体の schema / semantics は変更しない。

### E.2 Completion Policy

- v1 の read-only evaluation、restricted predicates、policy/evidence-set hash receipt、zero-mutation terminal preflight を再利用する。
- actor separationや cross-report binding は意味追加になるため、v1 を変更せず proposed `completion-policy/v2` とする。
- v2 は v1 の operator 実装を共通化してよいが、v1 の `_load_bound_report` 相当を呼ばない。すべての v2 predicate input は verified copied-byte resolver から渡す。
- predicate と validity gate の片方でも失敗すれば terminal mutation を行わない。

### E.3 Approval provenance

- actor / actor_kind、recorder / recorder_kind、source_kind / source_ref、bound Evidence hash を再利用する。
- Work Brief approval と Observation Verdict を同じ event type に混ぜず、Verdict 専用 event payload に nested receipt として使う。
- agent self-review が human gate を満たさない既存挙動を、そのまま Verdict actor floor に適用する。

### E.4 Adaptive Policy

- 既存 adaptive policy の R2/R3 `independent` 語を assurance class へ明示 mapping し、R4 human floor を `human_origin` へ接続する。
- risk は最低床を弱めず、profile が domain-specific cohort を上積みする。
- 最初の slice では明示 strict policy のみを実装し、自動 route 接続は後続 phase にする。

### E.5 外部 adapter / profile

- WEB: viewport / state / input modality、DOM/a11y、breakpoint 周辺 capture。
- 映像: 全尺低コスト signal、異常区間 high-density capture、通し見 rubric。
- ゲーム: build/device/seed/input、全 tick telemetry、replay、要所動画、soak / seed cohort。

これらは例であり、capture 実装・browser・video decoder・game engine・model/provider は PCL コアに入れない。外部 adapter は project-contained work root に report / artifact を出力し、PCL は contract / hash / gate のみを担当する。

---

## F. 後方互換性と段階導入

1. `evidence-set/v1` と `completion-policy/v1` を変更しない。
2. legacy `--evidence` と ordinary adhoc `--evidence-id` の現行挙動をこの slice で削除しない。
3. proposed v2 strict gate は明示 opt-in の Test のみに適用する。
4. 既存 passing Test は自動的に不合格へ戻さない。`pcl test reverify` で voluntary adoption する。
5. config を追加する場合の提案名は `validation.observation_validity: off|advisory|enforced` とし、既存 project の default は `off`、新規導入初期は `advisory` を推奨する。
6. `advisory` は finding と具体的な upgrade command を返すが status を変えない。
7. `enforced` は policy/profile が明示する target にだけ適用し、対象外 legacy terminal を暗黙に strict 化しない。
8. historical event は当時の契約で解釈し、後発 v2 policy で過去を再解釈しない。
9. dashboard は legacy proof を「Legacy / Integrity only」、strict proof を「Validity reviewed」と区別し、`independence_assurance` を別 field で表示する。`declared_separation` を認証済み independent と表現しない。

### F.1 固定する後方互換 matrix

Phase 1D では次を fixture 化し、CLI exit code、JSON shape、warning、Test status、reverify event を golden 比較する。

| 経路 | v2 未指定 | v2 明示指定 | 期待する互換性 |
| --- | --- | --- | --- |
| legacy inline `--evidence` | 現行挙動と warning を維持 | typed `strict_copied_evidence_required` | legacy を暗黙 strict 化しない |
| ordinary adhoc `--evidence-id` | 現行 healthy Evidence gate | non-copy member は typed reject | v2 だけが copy-only |
| Evidence Set v1 + policy v1 | 現行 predicate / mutable work-root semantics を維持 | 適用外 | historical / v1 fixture を変更しない |
| Evidence Set v1 + policy v2 | 適用外 | event-anchored copy-only validity | 新しい opt-in 経路 |

既存 v1 fixture が non-copy Evidence を使う場合、その fixture 自体は v1 で成功を維持し、同じ入力を v2 に与えた負例だけが typed error になることを確認する。

---

## G. CLI / API・state / event・dashboard 候補

### G.1 CLI / API（すべて提案名）

最小候補:

```bash
# policy / rubric / scope / assessment / verdict は既存 generic Evidence で copied 保存
pcl evidence add --file observation-scope.json --copy --summary "..."
pcl evidence add --file rubric.json --copy --summary "..."
pcl evidence add --file completion-policy-v2.json --copy --summary "..."
pcl evidence add --file self-assessment.json --copy --summary "..."
pcl evidence add --file reviewer-verdict.json --copy --summary "..."

# 既存 Evidence Set v1 を記録
pcl evidence-set record ...

# Reviewer Verdict provenance event を記録
pcl verdict record \
  --evidence-set E-SET \
  --verdict-evidence E-VERDICT \
  --policy-evidence E-POLICY \
  --actor "agent:reviewer" \
  --actor-kind agent \
  --source-kind cockpit \
  --source-ref "cockpit:<task-id>" \
  --reason "Reviewed declared scope and copied artifacts"

# 明示 event を失効。target event より後の event sequence で current validity を導出
pcl verdict revoke \
  --verdict-event EV-... \
  --actor "human:owner" \
  --source-kind cockpit \
  --source-ref "cockpit:<task-id>" \
  --reason "Reviewed bytes are no longer accepted"

# read-only preview
pcl completion evaluate \
  --policy-evidence E-POLICY \
  --evidence-set E-SET \
  --verdict-event EV-... \
  --test TC-XXXX

# terminal preflight
pcl test pass TC-XXXX \
  --summary "Independent observation verdict passed" \
  --evidence-id E-SET \
  --completion-policy-evidence E-POLICY \
  --verdict-event EV-...
```

設計上の優先順位:

- 新しい capture command は作らない。
- policy file を暗黙コピーせず、既存 `evidence add --copy` を再利用する。
- Verdict event を暗黙に「latest」選択せず、ID を明示する。
- record / revoke は mutation、show / evaluate は read-only とし、同じ current-validity projection を共有する。
- read-only evaluate と terminal preflight は同じ evaluator を呼ぶ。
- JSON output に `integrity`, `relevance`, `sufficiency`, `verdict`, `independence_assurance`, `residual_risk`, `completion_eligible` を分離して返す。

### G.2 state / event

新テーブルは作らず、次を追加する。

- proposed `observation_verdict_recorded`
  - entity: Verdict report Evidence
  - nested `approval_provenance`
  - set / policy / claim / subject / scope / rubric hashes
  - actor separation result と assurance class
- proposed `observation_verdict_revoked`
  - entity: 失効対象 Verdict report Evidence
  - exact target `observation_verdict_recorded` event ID
  - actor / recorder / source / reason
  - target event より大きい event sequence
  - 同一 target の再 revoke は `{ok: true, changed: false, current_validity: "revoked"}` の event-free no-op とする
- `test_case_passed` / `test_case_reverified`
  - 既存 `completion_evaluation` に加え additive `validity_evaluation`
  - Verdict event ID、policy Evidence ID、Residual Risk summary
- strict validation finding codes（提案例）
  - `observation_report_evidence_mismatch`
  - `observation_wrong_subject`
  - `observation_scope_incomplete`
  - `observation_baseline_required`
  - `observation_verdict_missing`
  - `observation_verdict_self_approved`
  - `observation_evaluator_version_mismatch`
  - `observation_policy_hash_mismatch`
  - `observation_adapter_unknown`
  - `observation_residual_risk_blocking`
  - `observation_event_anchor_missing`
  - `observation_event_anchor_ambiguous`
  - `observation_event_anchor_mismatch`
  - `observation_verdict_revoked`

すべての rejection は Evidence ID / event ID / Test status を消費・変更しない preflight とする。

Verdict の current validity は、明示指定された recorded event を起点に、同一 event ID を target とする後続 revocation event を event sequence 順に投影して導出する。暗黙 latest は使わない。新しい Verdict の記録だけでは古い Verdict を自動失効させないが、contributing Evidence が superseded / unhealthy なら古い Verdict は completion-ineligible になる。revocation 後も過去の `test_case_passed` event は「当時の事実」として保持し、Test row を自動で巻き戻さない。現在 trust view は `revoked_or_unhealthy` とし、enforced target の次回 terminal / reverify を拒否する。

### G.3 dashboard / human review

`dashboard-data.json` に event から導出した validity view を追加する候補:

- `proof_class: legacy_integrity|strict_validity|revoked_or_unhealthy`
- `independence_assurance: none|declared_separation|host_verified_session|human_origin`
- Integrity health
- claim / subject / scope digest と対象 path
- observed cohort / unobserved cohort
- self assessment actor と「diagnostic only」表示
- Reviewer Verdict actor / recorder / source / assurance class
- reviewed Evidence IDs / paths / hashes
- rubric / evaluator / policy versions
- Relevance / Sufficiency / Verdict
- Residual Risks / mitigations
- completion eligibility と blocking findings

human review queue には、`unknown`, `inconclusive`, human-required actor、medium 以上の residual risk、cohort 欠落を載せる。HTML は event/DB からの表示に留め、machine evaluator は HTML を読まない。

Phase 1E では上記のうち `proof_class`、`independence_assurance`、blocking finding count だけを deterministic `dashboard-data.json` に追加する。詳細 drill-down と human queue UI は Phase 4 に残す。

---

## H. 実装フェーズ

### Phase 1 — direct Test の opt-in strict validity（5つの独立 slice）

**Phase 1 の成功条件:** DB migration なしで、自己比較だけでは Test を pass できず、event-anchored copied bytes、versioned policy、Reviewer Verdict、明示 scope、blocking risk なしが揃った場合だけ direct Test を pass / reverify できる。legacy / v1 経路は意味と出力互換性を維持する。

**共通 User Stories:**

1. Test owner として、strict policy が要求する scope / rubric / policy / Reviewer Verdict を event-anchored copied Evidence として揃えたときだけ Test を pass したい。
2. Producer として、self assessment は診断に残したいが、自分の自己評価だけで completion を進めたくない。
3. Reviewer として、actor 分離が自己申告か host-verified か human-origin かを誤読せず確認したい。
4. Maintainer として、既存 v1 / legacy Test flow を変更せず opt-in したい。

#### Phase 1A — immutable copied-byte resolver

**目的:** strict evaluator が信頼する最小 storage primitive を先に確立する。新CLI、Verdict event、Test terminal 変更は行わない。

**変更候補:** `src/pcl/evidence.py`, `src/pcl/evidence_sets.py`、必要なら新規 internal helper、`tests/test_evidence_add.py`, `tests/test_evidence_sets.py`。

**受け入れ条件:**

- adhoc Evidence と Evidence Set はそれぞれ exactly one authoritative record event に解決される。
- current manifest member metadata / Evidence Set canonical artifact hash が event anchor と一致する。
- copied `stored_path` は exact Evidence-ID directory 配下で、regular non-symlink file である。
- file identity を open 前後で確認し、同じ opened bytes を hash と parse に使う。path を hash 後に再読込しない。
- missing / duplicate anchor、manifest rewrite、relocated path、symlink、file replacement、hash mismatch を typed finding にする。
- existing v1 health/read paths の public semantics は変えず、strict resolver を明示呼出しした場合だけ強い invariant を適用する。

**必須負例:** event payload と manifest の member 差し替え、別 Evidence-ID directory、intermediate/final symlink、open 前後の file identity 変化、Evidence Set artifact rewrite、anchor 0件/2件。全て read-only または zero file/DB mutation。

**完了証拠:** targeted tests、同一 bytes の hash/parse spy、canonical path fixtures、strict resolver JSON finding。

**Stop:** portable な no-follow / file identity strategy を standard library で安全に実装できなければ、terminal gate へ進まず threat model と platform support を人間レビューへ戻す。

#### Phase 1B — contracts と read-only validity evaluation

**目的:** provider-free fixtures だけで `observation-scope/v1`、`observation-evaluation/v1`、`completion-policy/v2` と deterministic evaluator を確立する。mutation CLI と Test integration はまだ作らない。

**変更候補:** versioned contract sibling、提案 schema `src/pcl/contracts/schemas/completion-policy-v2.schema.json`、新規候補 `src/pcl/observation_validity.py`、`src/pcl/completion_policies.py` の operator 共通部、contract fixtures、`tests/test_observation_validity.py`。

**受け入れ条件:**

- v2 は v1 の operator semantics だけを共有し、predicate input を Phase 1A resolver から受ける。
- `set.required_report_kinds ⊇ policy.required_report_kinds` を満たす。
- `scope.required == resolved_required`、observed/unobserved の排他・和集合・canonical order・stable ID を検証する。
- selection algorithm/version/seed/input digest/output IDs digest が固定される。
- Test claim digest は current DB Test から、subject/build digest は verified copied artifact から再構築する。
- evaluator は policy が許可した copied artifact hash または versioned builtin identity に bind される。
- self assessment は diagnostic にだけ出し、Reviewer Verdict missing の evaluation は completion-ineligible になる。
- 同じ入力のJSONを2回評価して byte-identical canonical output を得る。

**必須負例:** unrelated Evidence ID、wrong build、cherry-picked capture、baseline missing、cohort overlap/gap/duplicate、selection digest mismatch、adapter `failed|unknown|partial|budget_exhausted`、rubric/policy/evaluator mismatch、Relevance unknown、Sufficiency insufficient、blocking risk、mutable work-root を読む spy。

**完了証拠:** complete / negative fixture set、read-only evaluation JSON、v1 loader 非呼出し assertion、determinism comparison。

#### Phase 1C — Verdict event lifecycle

**目的:** `record|show|revoke`、明示 event selection、actor provenance、current-validity projection を event-only で実装する。Test status はまだ変更しない。

**変更候補:** `src/pcl/approval_provenance.py` の既存 helper 再利用、新規 Verdict service、`src/pcl/cli.py`、event / CLI tests。

**実装前 human gate:** 同一 provider/model の別 session を `declared_separation` として completion に許可する範囲、および privileged local tamper を脅威モデルに含めるかを決める。未決でも human-origin only mode は実装可能とする。

**受け入れ条件:**

- record event は Verdict Evidence / Evidence Set / policy / scope / claim / subject / rubric の exact IDs と hashes、actor/recorder/source、assurance class を持つ。
- `host_verified_session` は検証可能 receipt なしに指定できない。
- show/evaluate/pass は明示 recorded event ID だけを受け、暗黙 latest を使わない。
- revoke は exact recorded event ID を target とし、後続 event sequence から current validity を導出する。
- 同じ recorded event の再 revoke は event-free no-op で、既存 revocation ID / current validity を返す。
- revoked event、別 set/policy/bytes に bound した event、same actor、assurance floor 不足を拒否する。
- 新Verdictは旧Verdictを自動 revoke しない。contributing Evidence supersession は旧Verdictをcompletion-ineligibleにする。
- failed record/revoke は event、outbox、Evidence Link、ID、file を一切増やさない。

**完了証拠:** lifecycle event dump、record/show/revoke JSON、sequence projection fixtures、zero-mutation snapshots。

**Stop:** event scan で current validity を一意・決定論的に投影できなければ、暗黙 latest を足さず、専用 entity/index migration の人間承認へ戻す。

#### Phase 1D — Test pass / reverify integration

**目的:** Phase 1A–1C の evaluator を direct Test 1件の明示 opt-in terminal preflight に接続する。

**変更候補:** `src/pcl/stories.py`, `src/pcl/cli.py`, `tests/test_completion_policy.py`, `tests/test_lifecycle_integrity.py`, `tests/test_observation_validity.py`。

**受け入れ条件:**

- Evidence Set target は exact `TC-XXXX` で、current claim / subject / scope / rubric / policy / Verdict event が一致する。
- Reviewer Verdict が approved、Relevance affirmative、Sufficiency sufficient、required cohort accounted、blocking riskなしの場合だけ pass / reverify する。
- successful terminal event は既存 `completion_evaluation` と additive `validity_evaluation` を保存する。
- F.1 の4経路 compatibility matrix を golden fixture 化する。
- v2 を指定しない legacy / ordinary adhoc / policy v1 tests は無変更で通る。
- exact repeated reverify の event/no-op semantics を既存契約と一致させる。

**zero-mutation snapshot:** Test status/`updated_at`、Feature status/`updated_at`、全domain row count、Evidence Links、event max sequence、outbox rows、ID allocation、`.project-loop/evidence` file listを前後比較する。Verdict record失敗と terminal preflight失敗を別々に検証する。

**必須負例:** self assessment only、same actor、revoked Verdict、別 Test/set/policy/bytes、wrong build、baseline/cohort欠落、adapter unknown、superseded Evidence、policy downgrade、TOCTOU差し替え。すべて zero mutation。

**完了証拠:** successful `test_case_passed` / `test_case_reverified` payload、compatibility goldens、zero-mutation count/file assertions、isolated temp project smoke。

#### Phase 1E — minimal trust presentation

**目的:** strict terminal を導入した同じ milestone 内で、legacy integrity と strict validity を誤読しない最小 derived view を出す。詳細UIは作らない。

**変更候補:** dashboard-data builder / renderer data path、validator、`tests/test_dashboard_data_contract.py`、必要最小のlocale wording。

**受け入れ条件:**

- Test proof に `proof_class=legacy_integrity|strict_validity|revoked_or_unhealthy` を出す。
- strict proof に `independence_assurance` と blocking finding count を出す。
- `declared_separation` を `host_verified` / 「偽装不能な独立評価」と表示しない。
- revocation 後も historical pass event / Test row は書き換えず、current trust view を `revoked_or_unhealthy` にする。
- dashboard-data は DB/event projection から決定論的に生成し、HTML は evaluator input にしない。

**完了証拠:** deterministic dashboard-data snapshots、legacy/strict/revoked fixture、wording assertion。Phase 4 まで詳細カード、review queue、visual polish は非対象。

**Phase 1 共通 QA:** slice ごとの targeted pytest と changed Python の `ruff check` を先に実行し、1E 完了時に relevant suite、full `pytest`、`PYTHONPATH=src python -m pcl --json validate --strict`、isolated temp project smoke を行う。

**Phase 1 共通 rollback / migration gate:** v1 artifact semantics の変更、mutable work-root 依存、event-only projection の非決定性、copy binding に新DB columnが必須のいずれかが判明したら停止する。migration は別計画と人間承認なしに実施しない。

### Phase 2 — Reverify / validate / audit の持続的 trust

**目的:** terminal 時だけでなく、後日の `validate --strict` / review でも strict receipt の健康性を確認する。

**変更候補ファイル:** `src/pcl/validators.py`, `src/pcl/stories.py`, `src/pcl/evidence.py`, `tests/test_validation.py`, `tests/test_lifecycle_integrity.py`, `tests/test_completion_policy.py`。

**User Story:** Maintainer として、Verdict 後の copied artifact 破損、policy mismatch、supersede、actor receipt 不整合を strict validation で検出したい。

**受け入れ条件:**

- `test reverify` が同じ evaluator を使う。
- `validate --strict` は terminal event の receipt と現在の durable copied bytes を照合する。
- mutable original source の churn は、healthy copy があれば validity を壊さない。
- historical v1 Test は advisory/off policy で error にしない。
- exact repeated reverify は event-free no-op。

**失敗系 Tests:** Verdict report copy drift、policy copy missing、event binding mismatch、superseded Evidence、別 Test の receipt、latest event のすり替え。

**QA / 証拠:** validator targeted tests、v1 baseline fixture、reverify before/after event dump、strict finding JSON。

**Rollback / stop:** event scan だけでは deterministic current receipt を一意に選べない場合は、暗黙 latest 選択を足さず明示 event ID を維持する。DB index/entity が必要なら migration approval を求める。

### Phase 3 — Adaptive risk と Observation Job profile の接続

**目的:** R2/R3 reviewer assurance、R4 `human_origin` の既存 floor を runtime actor gate へ接続し、domain profile が最低床へ cohort を上積みできるようにする。

**変更候補ファイル:** `src/pcl/adaptive_policy.py`, `src/pcl/profile_prepare.py`, profile contracts / fixtures, workflow/job prompt templates, `tests/test_adaptive_policy.py`, profile tests, docs。

**User Stories:**

- R2/R3 owner として policy が定めた reviewer assurance floor を必須にしたい。
- R4 owner として human-origin Verdict 以外を拒否したい。
- domain adapter author として WEB / 映像 / ゲーム dimensions を PCL core schema に追加せず profile で宣言したい。

**受け入れ条件:** risk floor は弱められず、profile は required cohort / adapter budget を上積みのみできる。adapter は output bundle を返すだけで terminal mutation を行わない。

**失敗系 Tests:** R4 agent Verdict、custom policy downgrade、provider failure を pass に変換、profile が core command を自動実行、budget exhaustion の黙殺。

**QA / 証拠:** policy resolution fixtures、WEB/映像/ゲーム各1件の外部 fixture mapping、provider-free fixture run。

**Rollback / stop:** 全ドメイン共通最低床、主観評価 mandatory 境界、観測コスト上限が決まらなければ profile 自動選択を実装しない。

### Phase 4 — Dashboard / human review surface

**目的:** Integrity、Validity、Verdict、Residual Risk を誤読しない human view を提供する。

**変更候補ファイル:** `src/pcl/renderer.py`, `src/pcl/templates/dashboard/dashboard.html`, `docs/dashboard-data-contract.md`, `tests/test_dashboard.py`, `tests/test_dashboard_data_contract.py`, locales。

**User Story:** Reviewer として、hash healthy と quality reviewed を一目で区別し、見た bytes、未観測 cohort、actor、rubric、Residual Risk を開けるようにしたい。

**受け入れ条件:** dashboard-data は event/DB から導出され、self assessment は `diagnostic only`、hash は `bytes integrity only` と表示する。blocking unknown / risk は human queue に出る。HTML は evaluator input にならない。

**失敗系 Tests:** Integrity OK だが Verdict missing、self actor conflict、unobserved cohort、legacy receipt、broken evidence link、表示順の非決定性。

**QA / 証拠:** deterministic dashboard-data snapshots、英日 locale tests、human decision card screenshot は表示 QA のみで state proof にしない。

**Rollback / stop:** UI が completion status を独自計算し始めたら停止し、derived data contract に戻す。

### Phase 5 — Workflow / Feature / Task / Goal への限定拡張

**目的:** Test slice の field evidence を確認後、他 terminal surface に同じ validity receipt を適用する。

**変更候補ファイル:** `src/pcl/lifecycle.py`, `src/pcl/commands.py`, `src/pcl/tasks.py`, `src/pcl/finish_execution.py`, completion packet contract の versioned successor、関連 lifecycle / finish tests。

**User Stories:** Workflow / Feature / Task / Goal owner として、対象 claim と risk floor が strict validity を要求する場合に、単なる approved label や configured check success だけで terminal にしない。

**受け入れ条件:**

- Workflow Verification は actor provenance と reviewed Evidence Set を持つ。
- Feature は passing Tests の strict receipt を集約し、単一 unrelated Evidence で上書きしない。
- Task finish packet は「configured checks passed」と「quality claim validity reviewed」を別 claim にし、assurance class を併記する。
- Goal close は exact target Verdict または厳格化された completion packet のみ受ける。
- legacy route は policy 適用前の意味を維持する。

**失敗系 Tests:** approved Verification の actor 不明、別 run / goal / defect Verdict、Task packet の L2 check を主観品質 L3/L4 と誤分類、Feature の一部 Test だけ strict、Goal の cross-target receipt。

**QA / 証拠:** surface ごとの lifecycle matrix、completion packet compatibility fixtures、goal close / finish targeted tests。

**Rollback / stop:** claim source を Work Brief / Story / Test / packet のどれにするか未決の surface は実装しない。completion-packet/v1 の意味変更が必要なら v2 として別承認を取る。

---

## I. セキュリティ / 信頼上の失敗と期待挙動

| 失敗 | 検出 / 扱い |
| --- | --- |
| wrong build | `subject_sha256` / repository / build Evidence mismatch で fail closed |
| manifest / Evidence Set artifact の差し替え | exactly one record event anchor の member metadata / `artifact_sha256` と不一致なら reject |
| anchor 欠落・重複 | typed `event_anchor_missing|ambiguous`。暗黙に現在 manifest を信頼しない |
| copied path relocation / symlink / TOCTOU | Evidence-ID canonical directory、regular non-symlink、single-open file identity/hash/parse で reject |
| cherry-picked capture | scope-required cohort と reviewed Evidence set の差分を finding にし incomplete |
| baseline 不在 | comparison-required policy では typed error。`not_applicable` は理由必須 |
| 同一 actor の自己承認 | producer と Verdict actor 一致を拒否。self assessment は diagnostic only |
| actor/source の文字列偽装 | `declared_separation` として限定表示し、host receipt なしに `host_verified_session` を付与しない |
| cohort 外の未観測 | explicit `unobserved` と Residual Risk に残し、観測済み扱いしない |
| cohort laundering | resolved required cohort、集合等式、stable ID、selection input/output digest の不一致で reject |
| evaluator / rubric 版ずれ | Evidence hash / declared version mismatch で reject |
| evaluator version の自己申告 | copied evaluator artifact/hash または versioned builtin identity がなければ completion-ineligible |
| policy 版ずれ / downgrade | copied policy Evidence hash mismatch、adaptive risk floor 再適用で reject |
| hash を真実性と誤認 | API/dashboard を Integrity と Validity の別 field にし、説明文を固定 |
| unrelated Evidence ID の laundering | included report SHA と copied Evidence member SHA の exact match を必須化 |
| 外部 adapter failure を pass へ倒す | `failed|unknown|partial|budget_exhausted` は completion-ineligible / human review |
| Verdict の再利用 | Evidence Set / policy / scope / subject / claim hash を event に bind し mismatch reject |
| revoked Verdict の明示再利用 | recorded event より後の revocation projection を検出し reject |
| Verdict 後の bytes 変更 | copied Evidence health と terminal receipt の再検証で strict finding |
| symlink / path escape | 既存 work-root / project-root guard を再利用し preflight reject |
| human provenance の偽装 | PCL は認証しないことを明記。mediated human receipt は conversation/cockpit source ref 必須 |
| 証拠量を網羅性と誤認 | required cohort と unobserved cohort を別表示し、全状態証明を claim しない |
| 主観スコアを真実扱い | rubric / evaluator / actor / bytes に bound した外部 Verdict として保存し、score 単独で pass しない |

---

## J. 人間が決める事項、推奨デフォルト、解消期限

| 決定事項 | 推奨デフォルト | 期限 / 解消条件 |
| --- | --- | --- |
| 同一 provider/model の別 session | `declared_separation` として記録可能だが、enforced completion を満たすのは operator が明示 opt-in した policy のみ。host receipt なしに `host_verified_session` としない | Phase 1C の Story approval 前 |
| privileged local tamper を脅威モデルに含めるか | 初回は正規 CLI/service 利用者の取り違え・launderingを対象とし、DB/eventを直接改変できる actor への暗号学的耐性は非対象 | Phase 1A の Story に前提を明記。含める場合は署名/外部root-of-trustの別計画 |
| strict gate の初期適用範囲 | 明示 opt-in の direct Test 1件のみ | Phase 1D Story approval 時 |
| policy versioning | `completion-policy/v1` を不変に保ち、strict semantics は v2 | Phase 1B schema fixture 固定時 |
| copied Evidence requirement | scope、rubric、policy、Verdict、terminal に寄与する capture/report は `--copy` 必須 | Phase 1A/1B acceptance fixture で固定 |
| required cohort の権威 | policy が floor、profile は上積み、scope は resolved cohort と exact match | Phase 1B schema fixture で固定 |
| baseline | comparison claim は必須。absolute inspection は `not_applicable` と理由を許可 | Phase 1B fixture 固定時 |
| unobserved cohort | field 自体と集合等式を必須。non-empty の許容は policy/risk で判断 | Phase 1B fixture 固定時 |
| residual risk threshold | Phase 1 は blocking risk なしのみ pass。low-risk許容は field evidence 後 | Phase 3 route接続前 |
| R2/R3/R4 assurance floor | R2/R3 の既存 `independent` を明示 assuranceへmapping。R4は `human_origin` | Phase 3 Story approval 前 |
| adapter error | 常に fail closed。`unknown` / `incomplete` / human review | Phase 1B acceptance fixture で固定 |
| rollout mode | 既存 project `off`、新規導入 `advisory`、target ごとに `enforced` | Phase 1D CLI contract 固定時 |
| Verdict revocation / supersession | exact event revoke。新Verdictは旧Verdictを自動失効しない。Evidence supersessionはcompletion-ineligible。過去pass rowは巻き戻さずcurrent trustを無効化 | Phase 1C lifecycle fixture で固定 |
| evaluator identity | externalはcopied artifact/hash、builtinはversioned builtin identity。自己申告versionだけは禁止 | Phase 1B schema fixture で固定 |
| DB migration | 不要を推奨。event-only projectionが決定不能と実証された時点で停止 | migration proposal とhuman approvalが揃うまで禁止 |
| dashboard wording | 「bytes integrity verified」「validity reviewed」「declared actor separation」を別表示 | Phase 1E snapshot 固定時 |

**最大の未決事項:** 同一 provider / model の別 session による `declared_separation` を、どの risk level の enforced completion に許可するかである。Phase 1A / 1B は進められるが、Phase 1C の Story approval までに operator が決める。未決のままなら初期 enforced mode は `human_origin` のみとする。

---

## K. 非目標

- 主観品質、美しさ、楽しさ、正しさの自動証明。
- 全 viewport、全 frame、全 tick、全 seed、全状態の網羅証明。
- WEB browser capture、動画 decode / frame extraction、ゲーム replay / telemetry engine の PCL コア実装。
- 特定 LLM / vision model / provider への依存。
- Council 合意やモデル自己採点を独立 proof にすること。
- actor の実世界 identity 認証。
- production telemetry / cloud sync / paid service。
- dashboard を source of truth または evaluator input にすること。
- Evidence Set v1 の「caller-declared completeness」を「現実の完全性」へ意味変更すること。
- 既存 legacy Evidence / terminal history の一括 invalidation。

---

## L. 推奨する最初の実装 slice

**最初に実装するのは Phase 1A — immutable copied-byte resolver である。**

まず adhoc Evidence と Evidence Set を記録時 event payload へ再 anchor し、canonical Evidence-ID path、regular non-symlink file、single-open hash/parse を strict read-only helper と負例 tests で確立する。この slice では新CLI、Verdict event、Test pass/reverify、dashboardを変更しない。

Phase 1A の証拠が揃った後に、1B read-only evaluator、1C Verdict lifecycle、1D Test integration、1E minimal trust presentation の順で進める。1C 前には J の actor assurance decision が必要である。

Phase 1 全体で新しい DB entity / migration は不要を前提とする。event-only 設計で deterministic selection / revocation projection を安全に表現できないと実証された場合だけ、専用 table / index migration を別計画として人間承認へ戻す。

---

## M. 実装 readiness gate

| Gate | 状態 | 次へ進む条件 |
| --- | --- | --- |
| 計画 review P0/P1 反映 | 完了 | 本書 C–J と Phase 1A–1E に反映済み |
| Phase 1A 開始 | **Ready** | Story / Test をPCLへ登録し、docs-only境界を解除する明示実装指示 |
| Phase 1B 開始 | Pending | 1A resolver tests とevent-anchor negative fixturesがgreen |
| Phase 1C 開始 | Human decision pending | same-model `declared_separation` policy と脅威モデルを承認 |
| Phase 1D 開始 | Pending | 1A–1C、compatibility matrix、zero-mutation snapshotsがgreen |
| Phase 1E / Phase 1完了 | Pending | minimal trust class、full tests、strict validate、temp-project smokeがgreen |

Phase 1A–1E のいずれも独立commit可能な単位とし、次の slice に入る前に task-owned diff、targeted tests、残余riskを確認する。
