# Agent Roles

## Required roles

### mapper

Read-only. Finds routes, APIs, forms, jobs, commands, permissions, and integrations.

### planner

Read-only. Converts project state into a bounded workflow plan.

### implementer

Workspace-write. Makes the smallest safe code change. Should work in a git worktree when parallelism is enabled.

### verifier

Read-only and separate-context. Verifies outputs against expected behavior, tests, and evidence.

### dashboard_reporter

Workspace-write only through `pcl`. Updates state and regenerates dashboard.

## Critical rule

The implementer must not be the final judge of success. A separate verifier or human gate must decide completion.
