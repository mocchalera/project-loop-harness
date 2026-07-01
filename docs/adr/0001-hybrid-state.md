# ADR 0001: Use SQLite + JSONL + Generated HTML

## Status

Accepted for starter.

## Context

CSV is easy to inspect but weak for joins and validation. SQLite is strong for state but weak for Git diff. JSONL is strong for audit but weak for current queries.

## Decision

Use:

- SQLite for current normalized state;
- JSONL for append-only audit events;
- generated HTML for human dashboard;
- CSV/Markdown export for human review.

## Consequences

All state mutation must go through the CLI so SQLite and JSONL stay consistent.
