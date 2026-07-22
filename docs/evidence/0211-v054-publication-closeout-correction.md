# 0211 v0.5.4 publication closeout correction

**Recorded:** 2026-07-23 JST

**Corrects:** the repository-harness-state count in Evidence `E-0569` only

## Final audit state

Evidence `E-0569` recorded the 57-anomaly audit baseline measured before the
closeout documentation and PCL completion sequence. The final post-closeout
audit reports 75 human-review anomalies:

- 3 `current_evidence_corruption` findings;
- 70 `current_source_drift_with_healthy_copy` findings;
- 2 `superseded_historical_drift` findings;
- 0 `current_durable_copy_corruption` findings;
- 0 repairable or unsupported anomalies;
- 0 pending or failed outbox records;
- 0 orphan completion packets.

The 18-finding increase is entirely in mutable-source drift with healthy
durable copies. It does not affect the copied bytes of `E-0569`, completion
packet `E-0575`, the annotated release tag, the GitHub Release, the public PyPI
artifacts, or the clean public-install results.

## PCL completion recovery

The first `pcl finish --emit-packet --goal G-0064` run used the default
120-second check timeout. Ruff passed as `E-0570`; pytest was terminated on
timeout and recorded factually as `E-0571`; incomplete packet `E-0572` was not
used to close the Goal.

The PCL-provided recovery command was then run once with `--timeout 600`:

- Ruff passed as `E-0573`;
- the full pytest suite passed as `E-0574`;
- completion packet `E-0575` returned `COMPLETED_WITH_RISK` because unrelated
  dirty session state remains in the checkout;
- Goal `G-0064` closed with `E-0575`.

Strict validation remains `ok: true` with the same 3 active and 26 historical
warnings. Validation ran before the final dashboard render.

## Boundary

This correction changes no public-release fact and does not claim external
adoption or reuse. It preserves the immutable original Evidence and adds the
later final-state measurement instead of overwriting `E-0569`.
