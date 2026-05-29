# GitHub Copilot repository instructions

Read `AGENTS.md` before proposing code.

## What this repository is

A research system for multi-agent refactoring of actionable Java code smells.

## How to behave

- Preserve pluggability. New code must not entangle experiment variants.
- Prefer adding interfaces, adapters, and config flags instead of hardcoded branches.
- Emit structured outputs for agent communication.
- Keep the implementation reproducible and experiment-friendly.
- When changing pipeline behavior, update:
  - `configs/agent_contracts.yaml`
  - `configs/pipeline_config.template.yaml`
  - related docs in `docs/`

## Validation priorities

Always prefer tool-backed verification over natural-language confidence:
1. parse / AST checks
2. compile
3. targeted tests or generated assertions
4. smell re-detection
5. patch review summary

## Repository conventions

- All task-level outputs must be keyed by `unique_id`.
- Any module that may be ablated must be behind a config switch.
- Treat missing graph/context signals as optional features, not fatal errors.
