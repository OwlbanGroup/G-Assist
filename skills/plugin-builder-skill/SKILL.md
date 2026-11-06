---
name: plugin-builder
description: >-
  Use this skill to generate new G-Assist Protocol V2 plugins from an AI spec.
  Guides developers through an interactive interview, then generates a complete,
  in-sync plugin package (plugin.py, manifest.json, requirements.txt, config.json)
  using the G-Assist Plugin Builder generator.
license: Apache-2.0
metadata:
  author: NVIDIA
  version: "1.0.0"
  tags: [g-assist, plugin, generator, protocol-v2, cursor, sdk]
---

# G-Assist Plugin Builder

Generate new G-Assist plugins (Protocol V2 / JSON-RPC) from a natural-language
spec using an interactive interview, then produce a complete, in-sync plugin
package. This skill wraps the `plugins/plugin-builder` generator so the manifest
and code are always kept in sync.

## When to use this skill

Use this skill whenever the user wants to:

- Create a new G-Assist plugin from scratch (weather, smart lighting, task
  management, API integrations, etc.)
- Add new commands/functions to an existing plugin
- Convert a legacy V1 plugin to Protocol V2
- Validate that a plugin's manifest and code are in sync
- Set up a development workflow with the Cursor wizard or the CLI generator

## Prerequisites

- [Cursor IDE](https://cursor.com/) (for the interactive wizard workflow)
- The G-Assist SDK Python package (`gassist_sdk`) installed into the plugin's
  `libs/` folder via `setup.bat`
- Python 3.x matching the RISE embedded Python version (for CLI generation)

## How to use

### 1. Interview the user

Follow the plugin-builder interview steps (from `.cursor/rules/RULE.md`):

1. **Gather Requirements**
    - Plugin name (lowercase, hyphenated, e.g. `my-plugin`)
    - One-line description of what it does
    - Target APIs/services or hardware it interacts with
    - Functions to expose: name (snake_case), parameters (name, type,
      description, required?), tags, streaming, passthrough, persistent flag
    - Does it need a setup wizard? (API keys, authentication)
    - Does it need passthrough mode? (multi-turn conversations)
    - Should it be persistent? (long-running background process)

2. **Confirm Summary** — echo a structured summary and confirm accuracy.

3. **Generate the plugin** — use the generator with `--name`, `--desc`, and
   `--cmd` flags, or write a JSON spec and use `--spec`.

### 2. Generate from the CLI

```bash
python3 plugins/plugin-builder/generator.py \
    --name my-plugin \
    --desc "A plugin that does X" \
    --cmd "cmd_name:string:Description:default_value" \
    --cmd "another_cmd:integer:Description:5" \
    --out ./my-plugin
```

For multiple parameters per command, use a JSON spec:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "One-line description",
  "commands": [
    {
      "name": "do_something",
      "description": "Description for the LLM",
      "tags": ["tag1", "tag2"],
      "parameters": [
        {"name": "param", "type": "string", "description": "param description"}
      ]
    }
  ]
}
```

```bash
python3 plugins/plugin-builder/generator.py --spec spec.json --out ./my-plugin
```

### 3. Validate the package

```bash
python3 plugins/plugin-builder/generator.py --validate ./my-plugin
```

Exits non-zero with a list of problems if the manifest and code are out of sync.

## SDK Key Patterns

- **Basic command**: `@plugin.command("function_name")`
- **Streaming**: use `plugin.stream(...)` for output, never `print()`
- **Passthrough**: use `plugin.set_keep_session(True)` and an `on_input`
  handler (auto-generated when any command has `"passthrough": true`)
- **Setup wizard**: check `is_configured()` before exposing commands

## Important Rules

1. Never implement heartbeat, ping/pong, or message framing — the SDK does this.
2. Every function in `manifest.json` must have a matching `@plugin.command()`
   handler. `on_input` is for passthrough and does NOT go in the manifest.
3. Never use `print()` — use `plugin.stream()` for output and `plugin.log()` for
   debugging.
4. Manifest and code are generated together and must stay in sync.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Plugin not loading | Ensure manifest functions match `@plugin.command()` decorators |
| Generator refuses to clobber | Use `--force` or choose a different `--out` directory |
| Invalid command | Pass `--cmd "name:type[:desc[:default]]"`; use `--spec` for multi-param commands |