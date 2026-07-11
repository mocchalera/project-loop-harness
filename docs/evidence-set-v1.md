# Evidence Set v1

`evidence-set/v1` is an immutable, target-bound completeness receipt. It
answers a narrower question than ordinary Evidence: not only “what did the
agent select?”, but “which reports were known, which were included, which were
excluded, and did every declared required report pass?”

## Boundary

- PCL discovers reports only from an explicit `evidence-report-manifest/v1`
  inside an explicit project-contained work root.
- It does not scan parent directories or guess relationships from filesystem
  proximity.
- Every declared manifest/report path is resolved before mutation. Missing
  files, path escape, symlink escape, malformed JSON, duplicate report kinds,
  duplicate selections, unknown Evidence IDs, and unknown targets fail before
  Evidence ID allocation or artifact/event writes.
- Excluded optional reports are visible warnings but do not make the set
  incomplete.
- A required kind is incomplete when it is absent, excluded, or included with
  a status other than `pass`.
- An incomplete receipt may be recorded honestly. Task 0151 owns any later
  terminal-transition policy that requires a complete receipt.
- Report files are hashed and summarized; their bodies are not embedded.
- Schema remains 8.

## Report manifest

Paths are normalized POSIX paths relative to the work root:

```json
{
  "contract_version": "evidence-report-manifest/v1",
  "reports": [
    {"kind": "visual_check", "path": "reports/visual.json", "status": "pass"},
    {"kind": "box_report", "path": "reports/box.json", "status": "fail"}
  ]
}
```

Supported statuses are `pass`, `fail`, `warning`, and `unknown`. Report kinds
must be unique and use lowercase identifier characters.

## Read-only plan

```bash
pcl evidence-set plan \
  --target task:T-0001 \
  --work-root work/lp \
  --manifest work/lp/reports/report-manifest.json \
  --required-kind visual_check \
  --required-kind box_report \
  --include visual_check=E-0001:acceptance \
  --json
```

The plan has zero state/file mutations. Its `excluded_reports` list includes
the known `box_report`; completeness is `incomplete` because that required
report was not selected.

## Record and inspect

```bash
pcl evidence-set record \
  --target task:T-0001 \
  --work-root work/lp \
  --manifest work/lp/reports/report-manifest.json \
  --required-kind visual_check \
  --include visual_check=E-0001:acceptance \
  --summary "LP verification evidence set" \
  --json

pcl evidence-set show --evidence E-0002 --json
pcl contract validate --type evidence-set/v1 \
  .project-loop/evidence/evidence-sets/e-0002-evidence-set-v1.json --json
```

Recording creates one `evidence_set` Evidence row, one target link with role
`evidence_set`, and one `evidence_set_recorded` event. The stored receipt is
deterministic and contains hashes for the report manifest and every known
report, including excluded reports.

## Epistemic meaning

Completeness is evaluated only against the caller-declared required kinds and
the explicit report manifest. It proves that this declaration was evaluated
consistently; it does not prove that the manifest contains every report that
could exist or that an external tool's report is truthful.
