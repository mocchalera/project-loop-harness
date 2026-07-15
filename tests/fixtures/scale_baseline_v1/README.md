# Scale baseline v1 fixture

This directory contains the deterministic planning fixture for the P2 scale
baseline and event-log policy. It is synthetic and safe to regenerate in a
temporary directory; it is not a copy of the repository's `.project-loop`.

`manifest.json` is the source of truth for workload sizes, the event-type mix,
the advisory bands, and the future benchmark command list. It deliberately
contains no random IDs, wall-clock timestamps, absolute paths, source text, or
latency claims.

The fixture is currently descriptive. A future benchmark runner may expand the
event mix into a temporary initialized project, run each command, and write a
separate result artifact. It must not mutate this manifest or turn the
advisory bands into a runtime gate without a separate approved task.
