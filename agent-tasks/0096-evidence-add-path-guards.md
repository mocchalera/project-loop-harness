# Task 0096: Evidence Add Path Guards — Scope + Sensitive Shape (v0.2.3, P0)

Origin: GPT-5.5-pro v0.2.2 review agenda, blind spots C (project
boundary) and D (secret-shaped files), merged into one task because
both are record-time guards on the same code path
(`src/pcl/evidence.py::_adhoc_members`). No migration, no new runtime
dependency; schema stays v5. Runs AFTER 0095 is merged (both touch
`evidence.py` / `validators.py`).

## Goal

`pcl evidence add` accepts any existing local file. Two gaps:

1. A file outside the project root is silently recorded with a
   `../...` relative member path — invisible in the manifest, likely
   unreproducible on another machine.
2. An agent can pass `.env`, a private key, or a credentials file and
   PLH records it without any friction.

Add explicit accounting for the project boundary and a name-shaped
sensitive-path guard. PLH is NOT a content scanner and must not
become one: both guards look at paths only, never file contents, and
docs must say so.

## Part A: path scope accounting

### Member field

Every manifest member (and the members echoed in the
`adhoc_evidence_recorded` event payload and the CLI JSON result)
gains:

```json
"path_scope": "in_project" | "outside_project"
```

Determination: after the existing `resolve()`, the member is
`in_project` iff `resolved.relative_to(paths.root.resolve())`
succeeds — the same boundary `_relative_path` already uses.

### Behavior

- Default: `outside_project` members are recorded, with a warning.
  - Text mode: warning line on stderr.
  - JSON mode: additive top-level `"warnings": [...]` array in the
    result (present only when non-empty), one entry per
    outside-project member, e.g.
    `"evidence member outside project root: ../tmp/report.txt"`.
- `pcl.yaml` opt-in hard boundary:

  ```yaml
  evidence:
    allow_outside_root: false
  ```

  When set to `false`, any outside-project member → typed error
  `evidence_add_outside_root` (exit 2). Absent key or `true` =
  default warning behavior. Read the key with the same tolerant
  pcl.yaml reading approach used elsewhere (see
  `_configured_yaml_list` in `src/pcl/code_context/scan.py` for the
  house style; a scalar sibling helper is fine).

## Part B: sensitive-shaped path guard

### Patterns

- Reuse `DEFAULT_SENSITIVE_EXCLUDES` and `_path_pattern_matches` from
  `pcl.code_context` (import them; do NOT copy the pattern list —
  one source of truth).
- Optional additional patterns from `pcl.yaml`:

  ```yaml
  evidence:
    sensitive_exclude:
      - "*.sqlite3"
  ```

- `code_index.sensitive_include_override` does NOT apply here — it is
  index-scoped. There is no override list for evidence; the override
  is the explicit CLI flag below.

### Matching

For each member, match patterns against:

1. the recorded member path (the project-relative / `../`-relative
   form that goes into the manifest), and
2. the file's basename (so `/Users/x/.env` recorded as
   `../../.env` still matches `.env`; directory patterns like
   `.aws/` cannot anchor across `../` prefixes otherwise).

### Behavior

- If any member matches and `--allow-sensitive-evidence` was NOT
  passed → typed error `evidence_add_sensitive_path` (exit 2) listing
  the matched paths and patterns in `details`, and telling the caller
  about `--allow-sensitive-evidence`. This is the default in ALL
  modes — the CLI is non-interactive; there is no prompt.
- With `--allow-sensitive-evidence`:
  - members are recorded; each matched member gains
    `"sensitive_pattern": "<pattern>"` in the manifest/event/result;
  - the manifest gains top-level
    `"sensitive_path_warning_count": <int>` (count of matched
    members); the event payload carries the same count;
  - a warning is still emitted (stderr in text mode, `warnings` array
    entry in JSON mode).
- Help text and docs must state: this is a filename-shape check only;
  PLH does not scan file contents and recording with the flag is the
  caller's explicit decision.

## Guard ordering and atomicity

Both guards run inside the pre-DB stage (`_adhoc_members`), after the
existing exists/readable/duplicate checks, before any ID allocation,
manifest write, DB insert, or event append. Protective invariant,
scoped, same as 0093: **on any typed error from `pcl evidence add`,
zero traces — no evidence row, no JSONL event, no manifest file, no
consumed evidence ID, and the `evidence/adhoc/` directory file count
is unchanged** (assert in tests).

Evaluation order when multiple guards fire: report the sensitive
error first (it is the safety guard), then outside-root. A single
typed error is enough; do not build a multi-error report.

## Validators (`src/pcl/validators.py`)

- New optional member fields `path_scope`, `sensitive_pattern` and
  manifest field `sensitive_path_warning_count` are accepted:
  - absent → fine (pre-0096 manifests stay valid, no new errors);
  - present with an invalid value (unknown scope string,
    non-string pattern, negative/non-int count) → error.
- New warning, applies to old and new manifests alike since it is
  derivable from the path itself: a member path starting with `../`
  → warning `Adhoc evidence <id> member <path> is outside the project
  root.` This complements, not replaces, the existing drift warnings.
- The 0095 shared assessment function gains a corresponding finding
  code `member_outside_project_root` at `warning` severity, so stats
  health reflects the same fact. Existing fixtures without outside
  members must produce byte-identical validate output.

## Non-goals

- No content scanning, no entropy heuristics, no secret detection.
- No change to code index sensitive behavior or context receipts.
- No dashboard/report highlighting (v0.2.4 UX round).
- No copy/snapshot mode (task 0097 designs it).
- No interactive confirmation prompts.

## Tests

1. In-project file → `path_scope: "in_project"`, no warnings key,
   output otherwise identical to v0.2.2 shape plus the new field.
2. File under a temp dir outside root → recorded, member has
   `outside_project`, JSON result has `warnings`, manifest path is
   `../...`.
3. Same with `evidence.allow_outside_root: false` → typed
   `evidence_add_outside_root`, exit 2, zero traces.
4. `.env` inside project without flag → typed
   `evidence_add_sensitive_path`, exit 2, zero traces.
5. `.env` with `--allow-sensitive-evidence` → recorded;
   `sensitive_pattern` on the member;
   `sensitive_path_warning_count: 1`; warning emitted.
6. Outside-project `/tmp/.../credentials-prod.json` without flag →
   blocked via basename matching.
7. `evidence.sensitive_exclude` additional pattern matches → blocked
   without flag.
8. Bundle mixing one sensitive + one clean member without flag →
   blocked, zero traces (no partial manifest).
9. Sensitive + outside-root simultaneously, no flag → the sensitive
   error is the one reported.
10. Validators: pre-0096 manifest (no new fields) still valid;
    manifest with `../` member path → outside-root warning; invalid
    `path_scope` value → error.
11. Strict validate output for existing fixtures unchanged.

## Definition of done

- Implementation + tests green (`python3 -m pytest`).
- Live smoke in a scratch project (`pcl init /tmp/pcl-demo` style):
  demonstrate cases 2, 4, 5 with real files and show the manifest
  JSON. Do NOT add sensitive-named files to the live PLH repo DB.
- `docs/evidence-entry-paths-design.md` gains a short "Path guards
  (0096)" section documenting scope accounting, the guard, the
  config keys, and the not-a-content-scanner boundary.
- Evidence paths for all claims.
