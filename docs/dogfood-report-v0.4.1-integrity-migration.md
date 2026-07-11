# v0.4.1 integrity migration dogfood

## Result

The migration gate passed on 2026-07-11 (Asia/Tokyo). A disposable project
created with released `pcl 0.3.0` source at commit
`f04d9f70394eb288cfdb5dd2cd1bedef3f07c96c` migrated from schema 7 to schema 8
with current worktree revision `32913cd958520fd4484c5d4edb688e24f224a332`.
No dependency, schema, completion-packet, fresh-default, or release metadata
change was required.

The reviewed project was `/tmp/pcl-v041-dogfood.FybprW`. It is disposable
evidence, not repository state. The following transcript is independently
reproducible from a checkout containing the released `v0.3.0` Git object.

## Legacy setup and migration

Set up isolated source and project directories:

```bash
CURRENT_SRC=$(pwd -P)
LEGACY_SRC=$(mktemp -d /tmp/pcl-v030-source.XXXXXX)
PROJECT=$(mktemp -d /tmp/pcl-v041-dogfood.XXXXXX)
git archive v0.3.0 | tar -x -C "$LEGACY_SRC"
git rev-parse v0.3.0^{commit}
git rev-parse HEAD
```

Every legacy mutation used the released public CLI. After initialization, the
proof file is created with exactly 24 bytes (`legacy acceptance proof\n`):

```bash
PYTHONPATH="$LEGACY_SRC/src" python -m pcl --version
PYTHONPATH="$LEGACY_SRC/src" python -m pcl init --target "$PROJECT"
printf 'legacy acceptance proof\n' > "$PROJECT/legacy-proof.txt"
wc -c "$PROJECT/legacy-proof.txt"
shasum -a 256 "$PROJECT/legacy-proof.txt"
PYTHONPATH="$LEGACY_SRC/src" python -m pcl --root "$PROJECT" feature add --name "Legacy integrity migration" --surface "cli:pcl" --json
PYTHONPATH="$LEGACY_SRC/src" python -m pcl --root "$PROJECT" story draft --feature F-0001 --actor operator --goal "review migrated lifecycle meaning" --expected-behavior "the operator explicitly chooses the Story relationship" --json
PYTHONPATH="$LEGACY_SRC/src" python -m pcl --root "$PROJECT" test plan --feature F-0001 --type acceptance --scenario "released legacy command accepts an unlinked terminal Test" --expected "migration preserves proof and requires explicit Story selection" --json
PYTHONPATH="$LEGACY_SRC/src" python -m pcl --root "$PROJECT" test pass TC-0001 --summary "Legacy acceptance passed" --evidence legacy-proof.txt --json
PYTHONPATH="$LEGACY_SRC/src" python -m pcl --root "$PROJECT" validate --strict --json
```

This produced F-0001, draft US-0001, passing unlinked TC-0001, and legacy inline
Evidence E-0001. The old CLI accepted that relationship gap. Current migration
applied only `008_event_outbox.sql`; `migrate status --json` then reported
versions 1 through 8, `current_schema_version: 8`, and `consistent: true`.

```bash
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" migrate --json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" migrate status --json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" validate --strict --json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" audit check --json
```

The migration event was sequence 15. The policy remained advisory because the
legacy `pcl.yaml` had no `validation.lifecycle_integrity` key. Pre-policy
validation used `--strict`; non-strict validation intentionally skips strict
invariants.

## Deterministic read-only plan

```bash
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" repair lifecycle --json > /tmp/dogfood-plan-1.json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" repair lifecycle --dry-run --json > /tmp/dogfood-plan-2.json
cmp /tmp/dogfood-plan-1.json /tmp/dogfood-plan-2.json
shasum -a 256 /tmp/dogfood-plan-1.json /tmp/dogfood-plan-2.json
shasum -a 256 "$PROJECT/.project-loop/project.db" "$PROJECT/.project-loop/events.jsonl" "$PROJECT/pcl.yaml"
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" audit check --json
```

The outputs were byte-identical. Both SHA-256 values were
`92f22672dfaf003913442e8f40639661a68547b6e41083084def23592cb722ea`.
An independent repeat also held DB events and JSONL lines at 15. In a second
reproduction, the before/after tracked hashes remained:

- SQLite: `e3c988e3c050ef7531f4c052fcab97ee59029c8b66abd6bc0dbfe530c1051446`
- events JSONL: `8b2254567d731739795a37f1f3bfbe7d6b36ec606c06dfdfa2fc0cbe41b7c8b7`
- `pcl.yaml`: `849fd81e5e31aa38719c829505045fcfde4900ef84ae2de8897ea6fa727b0a52`

The plan contained exactly two actions: semantic `inspect_story_candidate` for
US-0001 and unsupported `report_invalid_test_evidence` for E-0001. E-0001 is a
legacy `test_case_pass` inline record, not healthy hash-bound artifact Evidence;
the planner correctly did not reinterpret it.

Both read-only inspection commands emitted by this dogfood plan executed through
the real normalized CLI with exit 0 and valid JSON:

```bash
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" story read US-0001 --json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" evidence show E-0001 --json
```

The regression repeats exactly those emitted argv values under the target root
and proves a byte-hashed snapshot of every project file is unchanged. Direct
`build_parser()` parsing is not equivalent to public CLI normalization and was
not used as evidence.

## Structural and semantic repair

No safe structural action existed. Consequently both exact applications were
the required event-free no-op; fabricating a structural event would violate the
planner and human-gate contracts:

```json
{"applied_action_ids": [], "changed": false, "event_id": null, "mode": "apply_structural", "ok": true, "relationships": []}
```

```bash
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" repair lifecycle --apply-structural --json > /tmp/dogfood-structural-1.json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" repair lifecycle --apply-structural --json > /tmp/dogfood-structural-2.json
cmp /tmp/dogfood-structural-1.json /tmp/dogfood-structural-2.json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" audit check --json
```

The operator then resolved every remaining choice explicitly:

```bash
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" story review US-0001 --summary "Operator reviewed the legacy acceptance behavior during v0.4.1 migration." --json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" story approve US-0001 --summary "Operator explicitly approves the legacy acceptance contract before linking it." --json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" evidence add --file legacy-proof.txt --summary "Hash-pinned copy of the legacy acceptance proof reviewed during migration." --command "legacy v0.3.0 acceptance run" --copy --json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" test link TC-0001 --story US-0001 --evidence-id E-0002 --summary "Operator selected the reviewed Story and replacement Evidence." --json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" repair lifecycle --json
```

The copied E-0002 member SHA-256 was
`983e68bed17259d53608c853158245891e844afee59fd9e8371d07e2cc483bd6`.
`test link` changed the pointer from E-0001/no Story to E-0002/US-0001 and
appended `test_links_repaired` event `EV-12BAB79D75CB`. A new plan returned zero
actions.

Only then did the operator append the policy and run every final status,
validation, audit, and render command. The final counts quoted below come from
the `counts` object returned by the last `audit check --json`:

```bash
printf '\nvalidation:\n  lifecycle_integrity: enforced\n' >> "$PROJECT/pcl.yaml"
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" migrate status --json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" repair lifecycle --json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" validate --strict --json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" audit check --json
PYTHONPATH="$CURRENT_SRC/src" python -m pcl --root "$PROJECT" render --json
```

`validate --strict --json` returned exactly
`{"errors":[],"findings":[],"ok":true,"warnings":[]}`, and `render --json`
succeeded. Final audit was clean with 19 DB events, 19 JSONL events, 19 delivered
outbox records, and zero anomalies or evidence mismatches.

## Automated regression and residual risk

`tests/test_integrity_migration_dogfood.py` freezes the schema-7 migration,
byte-identical/read-only planner, structural no-op, explicit Story/Evidence/Test
repair, enforced validation, and render sequence. The immutable input DB was
created by released v0.3.0 `pcl init`; the separate transcript above is the
real-source proof that v0.3.0 public commands create the exercised gap.

Residual risk is limited to legacy states outside this representative path,
especially conflicting links, drifted artifacts, invalid goal proof, and open
Defects. Those remain deliberately unsupported or human-reviewed plan actions.
This run does not claim automatic repair for them and does not weaken any human
semantic gate.
