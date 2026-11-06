# G-Assist Plugin Builder — Skill Card

## Description

Use the G-Assist Plugin Builder to generate new G-Assist Protocol V2 plugins
from an AI spec. The skill guides an interactive interview and then generates
a complete, in-sync plugin package (plugin.py, manifest.json, requirements.txt,
config.json) via the generator CLI or Cursor wizard.

This skill is ready for commercial/non-commercial use.

## Owner

NVIDIA

### License/Terms of Use

Apache-2.0

## Use Case

Developers, AI assistants, and plugin creators who want to build G-Assist
plugins without writing boilerplate — they describe what the plugin should do,
and the tool generates the SDK-based Protocol V2 code, manifest, config, and
dependencies.

## Requirements / Dependencies

**Requires API Key or External Credential:** [No] (the generator itself needs no
API key; generated plugins may need API keys for their specific services)
**Credential Type(s):** [None]

Do not include secrets in prompts/logs/output; use least-privilege credentials;
rotate keys as appropriate.

## Known Risks and Mitigations

Risk: Generated code may not match a user's exact requirements or may miss
needed safety checks.
Mitigation: Always review generated code, confirm the spec interview summary
before generating, and validate with `generator.py --validate`.

## Reference(s)

- SKILL.md
- README (source: plugins/plugin-builder)

## Skill Output

**Output Type(s):** [Configuration instructions, Code generation]
**Output Format:** [Markdown]
**Output Parameters:** [1D]
**Other Properties Related to Output:** [None]

## Evaluation Agents Used

- Claude Code (aws/anthropic/bedrock-claude-opus-4-8)

## Evaluation Tasks

1. Create a new plugin from a natural-language description.
2. Validate that a generated plugin's manifest and code are in sync.
3. Generate a plugin with streaming and passthrough mode from a spec.

## Evaluation Metrics Used

Reported benchmark dimensions:

- Correctness: Checks the generated plugin behaves as specified.
- Discoverability: Checks whether the plugin-builder skill was selected for
  plugin-generation requests.
- Effectiveness: Checks whether the generated package is complete and in sync.
- Efficiency: Checks whether the workflow used the minimal correct steps.

## Skill Version(s)

1.0.0 (source: SKILL.md frontmatter)

## Ethical Considerations

NVIDIA believes Trustworthy AI is a shared responsibility. When generating code
that will run on user systems, always review the output for correctness and
safety before deploying.
