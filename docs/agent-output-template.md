# Agent Output Template

Use this as the minimum `agent-output/v1` shape for external or manual agent work.

````md
# Short result summary

## Findings

- Finding, change, or observation.

## Evidence

- `path/to/file.ext`
- command output or report path

## Recommended pcl Commands

```bash
pcl jobs complete J-0001 --summary "..."
pcl verification record --run WR-0001 --result approved --reason "..."
```
````

`pcl ingest-agent-run` rejects empty files, files whose first non-empty line is not an H1 summary, and files missing `## Findings` or `## Evidence`. It uses the H1 as the evidence summary, so keep the heading concise.
