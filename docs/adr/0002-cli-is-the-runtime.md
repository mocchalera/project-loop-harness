# ADR 0002: CLI Is the Runtime, Skill Is the Instruction Layer

## Status

Accepted for starter.

## Context

Agent Skills are excellent for repeatable instructions, but they cannot enforce migrations, validation, deterministic rendering, or durable state transitions alone.

## Decision

Build a local CLI named `pcl` as the runtime. Package Skills and plugins around it.

## Consequences

The CLI must be stable, testable, predictable, and model-agnostic.
