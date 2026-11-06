# G-Assist Plugin Builder Skill

Generate new G-Assist Protocol V2 plugins from an AI spec. The skill guides an
interactive interview, then produces a complete, in-sync plugin package via
the CLI generator or the Cursor wizard.

## What It Does

| Capability                | Description                                                                                |
| ------------------------- | ------------------------------------------------------------------------------------------ |
| **Interactive interview** | Asks about plugin name, functions, parameters, API keys, streaming, passthrough            |
| **Generate code**         | Creates `plugin.py`, `manifest.json`, `requirements.txt`, and `config.json` from templates |
| **Validate structure**    | Ensures manifest functions match code decorators; reports sync problems                    |
| **CLI generator**         | `python3 generator.py --name ... --desc ... --cmd ...` generates a package from a spec     |
| **JSON spec input**       | Use `--spec` for multi-parameter commands                                                  |
| **Validation**            | `python3 generator.py --validate ./plugin` checks manifest/code sync                       |

## Quick Start

```bash
# 1. Interview the user (name, description, functions/params, streaming, passthrough)

# 2. Generate a plugin package
python3 plugin-builder-skill/generator.py \
    --name my-plugin \
    --desc "A plugin that does X" \
    --cmd "get_weather:string:Get weather for <city>" \
    --cmd "get_forecast:string:Get 5-day forecast for <city>" \
    --out ./my-plugin

# 3. Validate
python3 plugin-builder-skill/generator.py --validate ./my-plugin
```

See [SKILL.md](SKILL.md) for the full instructions and the JSON spec format.
