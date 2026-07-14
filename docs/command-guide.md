# Structured command guide

`pcl guide` is a local, read-only orientation surface for agents and operators
who know their purpose but do not yet know the full PCL command route.

```bash
pcl guide
pcl guide --json
pcl guide direct --json
pcl guide finish
```

The supported topics are:

- `start`: inspect adoption and register one literal intent;
- `direct`: deliver one Feature through Story, Test, Evidence, and Goal close;
- `finish`: preview and perform evidence-backed terminal closure;
- `dashboard`: validate, render, and prepare human review orientation;
- `recover`: diagnose a stopped or resumed loop with read-only context.

The `command-guide/v1` JSON contract returns ordered command templates. Each
step states whether it mutates project state, whether a human decision is
required, which placeholders must be supplied, and what should be true after
the command. `human_required` does not authorize an agent to approve on a
human's behalf.

The guide is available before `pcl init` and does not create `.project-loop`.
It complements `pcl next --json`: use `guide` to learn a purpose-oriented route
and `next` to read the authoritative recommendation for the current project
state.
