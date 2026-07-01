# ADR 0003: Static Workflows Before Dynamic Workflows

## Status

Accepted for starter.

## Context

Dynamic workflows are powerful but can be hard to debug, expensive, and unsafe without approval gates.

## Decision

Start with static YAML workflow templates. Add dynamic workflow proposal later, not immediate execution.

## Consequences

The first workflow runner only needs to interpret known declarative workflow files.
