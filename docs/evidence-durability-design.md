# Design: Evidence Durability Modes

Status: **DRAFT — awaiting human approval.** Design only; no
implementation task is cut until the decision points at the end are
approved. Origin: v0.2.2 review agenda blind spot A ("hash-pin is not
durability"), task `agent-tasks/0097-evidence-durability-design.md`.

## Problem

v0.2.2 adhoc evidence (`pcl evidence add`) records member `path` +
`size_bytes` + `sha256` and never copies the file. This is the honest
minimum: it proves the caller pointed at content with a specific hash
at record time. It is weak for later review:

- `work/reports/pytest-out.txt` is deleted by cleanup → member
  missing, only a drift warning remains.
- CI artifacts expire; screenshots live in `/tmp` or another machine.
- The file is overwritten → hash drift; the recorded claim survives
  but the reviewable artifact is gone.

A naive copy does not fix this either: `.project-loop/evidence/` is
**gitignored** (`.gitignore:20`), so a copy survives local cleanup
but never travels to another machine or reviewer. Durability is
therefore two separate questions, and conflating them produces a
feature that quietly fails its promise:

1. **Local durability** — does the artifact survive workspace churn
   on this machine? (a copy answers this)
2. **Transfer durability** — can another machine/reviewer see it?
   (a copy inside a gitignored directory does NOT answer this)

## Design principles (unchanged from evidence-entry-paths)

- Evidence rows are claims with pointers. Copying a file never
  upgrades the claim: PLH asserts "a byte-identical copy of what the
  caller pointed at was stored at record time", never "this content
  is correct".
- Copying is **opt-in per invocation**. No default copy: silently
  ingesting large or secret-shaped artifacts into `.project-loop` is
  a side effect the caller must ask for.
- Guards (task 0096) run before storage. Durability must never
  weaken the sensitive-path or scope guards.

## Proposed modes

### `reference` (today; stays the default)

Exactly v0.2.2 behavior. Promise: content with this hash existed at
the recorded path at record time. Non-promise: readable later.

### `copied` (new; explicit `--copy` on `pcl evidence add`)

At record time, after all 0096 guards pass, each member file is
copied to:

```text
.project-loop/evidence/adhoc-files/<evidence-id>/<NN>-<basename>
```

(`NN` = two-digit member index; prevents basename collisions inside a
bundle). The copy is re-hashed after writing and must equal the
source hash — a mismatch (file changed mid-copy) is a typed error
with zero traces, same atomicity rule as 0093/0096: copies are staged
in a temp directory and moved into place only after every member
succeeds and before the DB row/event are written.

Manifest accounting (member-level, uniform per invocation):

```json
{
  "path": "work/reports/pytest-out.txt",
  "size_bytes": 4231,
  "sha256": "…",
  "storage_mode": "copied",
  "stored_path": ".project-loop/evidence/adhoc-files/e-0021/01-pytest-out.txt"
}
```

`storage_mode` is member-level (health assessment from 0095 is
member-driven) but v1 semantics are one mode per invocation — no
mixed bundles. Reference-mode members simply omit both fields
(pre-existing manifests stay valid, same additive rule as 0096).

Drift semantics for copied members:

- The **copy** is the reviewable artifact: missing/drifted copy →
  `warning` with new finding codes `copy_missing` /
  `copy_hash_mismatch` (a drifted copy also implies something
  touched `.project-loop`, which is worth seeing).
- The **original** drifting is expected workspace churn and is
  informational only (finding `source_drifted`, no warning) — the
  point of copying is precisely that the original may go away.

### `snapshot` — rejected as a third record-time mode

A record-time "snapshot" adds nothing over `copied`. The real third
need is **transfer**, which is a read-side operation, not a
record-time mode: a future `pcl evidence export <E-id> --out <zip>`
that produces a self-contained review bundle (manifest + whichever
members are still readable + a health report). Export also gives CI
and cross-machine hand-off an explicit, auditable path. Design
separately; not part of this proposal's implementation scope.

## The gitignore boundary

Options considered:

- **(a) Keep `.project-loop/evidence/` local-only (recommended).**
  `--copy` answers local durability; transfer stays explicit via the
  future export command. No repo bloat, no accidental secrets in git
  history, no change to the versioning contract of `.project-loop`.
- **(b) Carve out `adhoc-files/` from `.gitignore`.** Evidence would
  travel with the repo, but screenshots/logs in git history bloat
  every clone forever, and one `--allow-sensitive-evidence --copy`
  away from a secret in a pushed commit. Rejected as a PLH default.
  The stored path is stable and documented, so a project that truly
  wants versioned evidence can edit its own `.gitignore` — that is
  the operator's deliberate choice, not a PLH feature.
- **(c) Export bundles (future `pcl evidence export`).** The
  recommended transfer story; composes with (a).

Recommendation: **(a) now, (c) later, (b) rejected.**

## Interaction with 0096 guards

- **Sensitive-shaped members.** Guards run first; `--copy` on a
  sensitive-matched member still requires
  `--allow-sensitive-evidence`. If allowed, the copy inherits
  `sensitive_pattern` in the manifest, and the future export command
  must exclude sensitive-flagged members by default. Copying a secret
  amplifies exposure (it now lives in two places and in any backup of
  `.project-loop`) — the warning text for the combined case should
  say exactly that.
- **Outside-root members.** Copying an outside-root file (e.g.
  `/tmp/report.txt`) pulls the artifact inside the project boundary.
  This is a feature, not a loophole, and it is honest **because** the
  manifest keeps the original path with
  `path_scope: outside_project` while `stored_path` provides the
  durable local copy. This is the single strongest use case for
  `--copy`. `evidence.allow_outside_root: false` still blocks the
  recording entirely — configuration wins over copy.

## Size discipline

- New config `evidence.copy_max_member_bytes`, default **10 MB**.
  A member over the cap → typed error `evidence_copy_member_too_large`
  (zero traces). The cap is a config knob, not a CLI flag — raising
  it is a project-level decision, not a per-invocation reflex.
- Members over half the cap are recorded with a
  `large_evidence_member` warning (aligns with review blind spot F
  vocabulary so a later validation-cost budget can reuse it).
- Health checks for copied members hash the **copy only** (the
  original is informational), so 0095's "each evidence id hashed once
  per stats invocation" cost model is unchanged.
- Reference mode is untouched by the cap: pointing at a 2 GB trace
  stays legal; copying it does not.

## Truthfulness boundary

`storage_mode: copied` asserts exactly: "at record time, PLH wrote a
byte-identical copy (same sha256) of the file the caller named, to
`stored_path`". It never asserts the content is correct, complete, or
produced by `--command`. Docs and `--help` must keep the existing
claim/pointer vocabulary; "durable" in user-facing text is always
scoped as "survives workspace cleanup on this machine", never
"permanent" or "guaranteed".

## Decision points (for approval)

1. Add opt-in `--copy` with member-level `storage_mode` /
   `stored_path` as specified? (recommended: yes)
2. Gitignore boundary: option (a) local-only copies now, future
   `pcl evidence export` as the transfer story, (b) rejected?
   (recommended: yes)
3. Sensitive × copy: allow under the same
   `--allow-sensitive-evidence` flag with amplified warning text — or
   refuse to copy sensitive-matched members outright (reference-only
   for them)? (recommended: same flag, amplified warning; an outright
   refusal pushes operators to strip the flag semantics with shell
   copies)
4. Original-drift on copied members is informational, copy-drift is a
   warning? (recommended: yes)
5. `copy_max_member_bytes` default 10 MB, over-cap = typed error,
   half-cap = `large_evidence_member` warning? (recommended: yes)
6. Timing: implementation is a v0.2.4+ task, cut only after 0095/0096
   land and dogfood confirms demand for `--copy`? (recommended: yes)
