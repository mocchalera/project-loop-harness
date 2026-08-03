# 0224: P1-C C6 local proof-anchor drift eligibility

## Scope

- **Milestone:** P1-C C6 read-only local proof-anchor drift eligibility
- **Design authority:** Cockpit task `42201ae1` seq4 only
- **Independent design review:** task `7107cd6c` seq1, GO H0/M0/L7
- **Implementation base:** `58678d436fa7a2f21e04b1a5dfcb1ca2944a0d93`
- **Implementation tree:** `35241523479b7fc7449450422cfffb129a346d7c`

## Authorized contract

Implement the internal `proof-anchor-drift-eligibility/v1` predicate described
in `docs/proof-anchor-drift-v1.md`. It resolves C5 authority event-first,
applies invalid/multiple tombstone precedence, observes an existing no-create
shared project lock, pins one schema-8 read-only SQLite snapshot, reconstructs
live C1-C4 authority, and returns a closed drift-only receipt with all rights
false.

The Python 3.10 SQLite mapping is numeric and total: 776 ROLLBACK and 264
RECOVERY are recovery-required; 520 CANTLOCK and BUSY/LOCKED are snapshot-
unavailable; CORRUPT/NOTADB are recovery-required. No raw-message parsing,
read-write retry, journal repair, or WAL acceptance is allowed.

## Effect boundary

Schema 8, migration 0, dependency 0, public CLI/MCP 0, authoritative writes 0,
Evidence/link/event/outbox 0, check execute/skip/substitution 0, terminal and
lifecycle 0, mandatory Evidence and promotion 0, and network/telemetry/
publication 0. C6 does not implement C7, proof reuse, terminal readiness, or a
consumer. The current terminal rule remains Feature done plus healthy current
Evidence.

## Verification

Use authentic missing-module RED before production code. GREEN must include
the closed schema/digests/caps, event-first chain and tombstone classification,
no-create/no-follow lock attacks, pinned snapshot and SQLite error mapping, a
genuine spilled hot rollback-journal observation of numeric 776, C1-C6 and C5
recovery regressions, terminal/public-surface firewalls, full pytest, Ruff,
schema loading, and diff checks. Use worktree source without changing a shared
Python installation, and retain all unique `/private/tmp` roots.

The seven independent-review Lows remain documented limitations or local C6
clarifications. They do not authorize deferred C4/C5 cleanup or any C7 work.
