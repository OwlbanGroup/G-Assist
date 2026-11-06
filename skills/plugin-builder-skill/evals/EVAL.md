<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (c) 2026 NVIDIA Corporation. All rights reserved. -->

# Evaluating `plugin-builder-skill`

This skill wraps the G-Assist Plugin Builder generator and the Cursor wizard
rule to produce new Protocol V2 plugins from a natural-language spec. Unlike
the g-assist-mcp-skill, this is a developer tooling skill — it does not require
NVIDIA hardware, a driver, or a running G-Assist server. All evaluation runs on
any Python 3.10+ environment with a CWD rooted at the repository.

## Why the dataset is self-contained

A CI runner has no NVIDIA GPU, no RISE, and no `gassist_*` tools. The
plugin-builder skill is verified entirely through static generation and
validation:

- Generate a plugin package from a JSON spec via `generator.py --spec`.
- Validate the generated package with `generator.py --validate`.
- Confirm the generated `plugin.py` and `manifest.json` contain the same
  command names and matching parameter types.

`evals.json` drives these checks. `evals-hardware.json` is intentionally
empty/no-op for this skill.

## Evaluation Tasks

### Positive tasks (generation + validation)

1. Generate a plugin from a flat `--cmd` spec (e.g. `get_weather:string`).
2. Generate a plugin from a JSON `--spec` file with multiple parameters per
   command.
3. Generate a plugin with a default value for an optional parameter.
4. Generate a plugin that sets `passthrough: true` (verifies `on_input` is
   emitted).
5. Generate a plugin and then run `--validate` to confirm sync.

### Negative tasks (error detection)

1. Generate a plugin with a Python keyword as a command name and confirm the
   generator exits non-zero.
2. Generate a plugin with a duplicate command name and confirm non-zero exit.
3. Generate a plugin and then run `--validate` on a tampered manifest (missing
   a function) and confirm non-zero exit with a clear problem message.
4. Generate a plugin with an invalid type (e.g. `foo`) and confirm non-zero exit.
