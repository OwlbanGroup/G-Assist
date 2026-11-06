#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION &
#   AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
G-Assist Plugin Builder - Code Generator
=========================================

A small generator that turns a declarative plugin spec into a full
SDK-based plugin package (plugin.py, manifest.json, requirements.txt,
config.json).

Usage:
    python generator.py --name my-plugin --desc "My plugin" \
        --cmd greet:string:Greet a user:World \
        --cmd count:integer:Count to a number:5

    # Or from a JSON spec file:
    python generator.py --spec spec.json --out ./my-plugin

The generator produces files matching G-Assist's Protocol V2 SDK
conventions, so the generated manifest and code are always in sync.
"""

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

# Manifest property types -> (Python annotation, JSON schema type)
TYPE_MAP = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "array": "list",
    "object": "dict",
}

# Python annotation -> manifest type (used when reading a JSON spec)
ANNOTATION_TO_TYPE = {v: k for k, v in TYPE_MAP.items()}

# Commands that are reserved by the SDK / passthrough protocol.
RESERVED_COMMANDS = {"on_input"}

# Python keywords that cannot be used as parameter names.
PYTHON_KEYWORDS = {
    "False", "None", "True", "and", "as", "assert", "async", "await", "break",
    "class", "continue", "def", "del", "elif", "else", "except", "finally",
    "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
    "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
}

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PLACEHOLDER_RE = re.compile(r"<(\w+)>")

# Markers left behind by the hand-written template (not by the generator).
TEMPLATE_MARKERS = (
    "RENAME_ME",
    "<plugin-name>",
    "<function_name>",
    "<description>",
)


class SpecError(ValueError):
    """Raised when the plugin spec is invalid."""


# ============================================================================
# NORMALIZATION HELPERS
# ============================================================================
def slugify(value: str) -> str:
    """Lowercase and replace spaces/underscores with hyphens."""
    slug = re.sub(r"[\s_]+", "-", value.strip().lower())
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    if not slug:
        raise SpecError(
            f"Plugin name {value!r} does not contain any usable characters"
        )
    return slug


def type_to_annotation(typ: str) -> str:
    """Convert a manifest type to a Python annotation."""
    if typ not in TYPE_MAP:
        raise SpecError(
            f"Unsupported property type: {typ!r} "
            f"(expected one of {sorted(TYPE_MAP)})"
        )
    return TYPE_MAP[typ]


# Textual spellings of Python literals accepted as defaults.
_LITERAL_ALIASES = {
    "null": "None",
    "None": "None",
    "true": "True",
    "True": "True",
    "false": "False",
    "False": "False",
}


def _is_quoted(text: str) -> bool:
    """Return True when text is wrapped in matching single/double quotes."""
    return (text.startswith("'") and text.endswith("'")) or (
        text.startswith('"') and text.endswith('"')
    )


def format_default(default: Any, typ: str) -> str:
    """Turn a JSON-like default into a Python literal."""
    if default is None:
        return "None"
    if isinstance(default, bool):
        return "True" if default else "False"
    if isinstance(default, (int, float, list, dict)):
        return repr(default)

    text = str(default).strip()
    if text in _LITERAL_ALIASES:
        return _LITERAL_ALIASES[text]
    if text.startswith("[") or text.startswith("{"):
        # Validate that it is a real JSON literal before emitting it.
        try:
            json.loads(text)
        except ValueError as exc:
            raise SpecError(f"Invalid JSON default {text!r}: {exc}") from exc
        return text
    if _is_quoted(text):
        return text
    if typ in ("integer", "number"):
        try:
            return repr(int(text) if typ == "integer" else float(text))
        except ValueError as exc:
            raise SpecError(f"Default {text!r} is not a valid {typ}") from exc
    if typ == "boolean":
        raise SpecError(f"Default {text!r} is not a valid boolean")
    return repr(text)


def _validate_identifier(value: str, kind: str) -> str:
    if not IDENTIFIER_RE.match(value):
        raise SpecError(
            f"{kind} {value!r} must be a valid Python identifier (snake_case)"
        )
    if value in PYTHON_KEYWORDS:
        raise SpecError(f"{kind} {value!r} is a Python keyword")
    return value


def _parse_cmd_arg(raw: str) -> Dict[str, Any]:
    """Parse a ``name:type:description[:default]`` command argument.

    The description may contain colons; the default is only split off when
    the trailing segment looks like a literal (quoted, number, bool, null,
    or JSON array/object) and the type is not ``string`` (for strings the
    trailing segment is treated as part of the description).
    """
    parts = raw.split(":", 2)
    if len(parts) < 2:
        raise SpecError(
            f"Invalid --cmd {raw!r}; "
            "expected name:type[:description[:default]]"
        )
    name, typ = parts[0].strip(), parts[1].strip()
    description = parts[2].strip() if len(parts) > 2 else ""
    default = None

    if ":" in description:
        head, tail = description.rsplit(":", 1)
        tail = tail.strip()
        if typ != "string" and _looks_like_literal(tail):
            description, default = head.strip(), tail

    return {
        "name": name,
        "type": typ,
        "description": description,
        "default": default,
        "required": default is None,
    }


def _looks_like_literal(value: str) -> bool:
    """Return True when value can be interpreted as a default literal."""
    if not value:
        return False
    if value in _LITERAL_ALIASES or _is_quoted(value):
        return True
    if value.startswith("[") or value.startswith("{"):
        try:
            json.loads(value)
            return True
        except ValueError:
            return False
    try:
        float(value)
    except ValueError:
        return False
    return True


def cmd_from_arg(raw: str) -> Dict[str, Any]:
    """Turn one ``--cmd`` argument into a command spec entry.

    The parameter is named after the first placeholder in the description
    when it is written as ``<name>``; otherwise it reuses the command name.
    Use ``--spec`` when a command needs more than one parameter.
    """
    parsed = _parse_cmd_arg(raw)
    match = PLACEHOLDER_RE.search(parsed["description"])
    param_name = match.group(1) if match else parsed["name"]
    return {
        "name": parsed["name"],
        "description": parsed["description"],
        "parameters": [
            {
                "name": param_name,
                "type": parsed["type"],
                "description": parsed["description"],
                "default": parsed["default"],
                "required": parsed["required"],
            }
        ],
    }


def _normalize_params(
    params: List[Dict[str, Any]], cmd_name: str
) -> List[Dict[str, Any]]:
    """Validate and normalize one command's parameter list."""
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for param in params:
        param_name = _validate_identifier(
            (param.get("name") or "").strip(), "Parameter name"
        )
        if param_name in seen:
            raise SpecError(
                f"Duplicate parameter {param_name!r} in command {cmd_name!r}"
            )
        seen.add(param_name)
        typ = (param.get("type") or "string").strip()
        type_to_annotation(typ)  # validates
        default = param.get("default")
        required = param.get("required")
        if required is None:
            required = default is None
        normalized.append(
            {
                "name": param_name,
                "type": typ,
                "description": (param.get("description") or "").strip(),
                "default": default,
                "required": bool(required),
            }
        )
    return normalized


def normalize_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and normalize a plugin spec into a canonical structure."""
    name = slugify(spec.get("name") or "")
    description = (spec.get("description") or "").strip()
    if not description:
        raise SpecError("Plugin description is required")

    commands = spec.get("commands") or []
    if not commands:
        raise SpecError("At least one command is required")

    normalized_commands: List[Dict[str, Any]] = []
    seen_commands = set()
    for cmd in commands:
        cmd_name = _validate_identifier(
            (cmd.get("name") or "").strip(), "Command name"
        )
        if cmd_name in RESERVED_COMMANDS:
            raise SpecError(
                f"Command name {cmd_name!r} is reserved by the SDK "
                "(passthrough handler)"
            )
        if cmd_name in seen_commands:
            raise SpecError(f"Duplicate command name: {cmd_name!r}")
        seen_commands.add(cmd_name)

        normalized_params = _normalize_params(
            cmd.get("parameters") or [], cmd_name
        )

        normalized_commands.append(
            {
                "name": cmd_name,
                "description": (cmd.get("description") or "").strip()
                or f"Handle the {cmd_name.replace('_', ' ')} request.",
                "tags": [str(tag) for tag in (cmd.get("tags") or [])],
                "parameters": normalized_params,
                "streaming": bool(cmd.get("streaming", False)),
                "passthrough": bool(cmd.get("passthrough", False)),
            }
        )

    return {
        "name": name,
        "version": str(spec.get("version") or "1.0.0"),
        "description": description,
        "persistent": bool(spec.get("persistent", True)),
        "commands": normalized_commands,
    }


# Section banner emitted into generated files (kept under 79 columns).
BANNER = "# " + "=" * 74


# ============================================================================
# CODE GENERATION
# ============================================================================
def _signature(command: Dict[str, Any]) -> str:
    """Build the Python parameter list for a command handler."""
    parts = []
    for param in command["parameters"]:
        annotation = type_to_annotation(param["type"])
        if param["required"]:
            parts.append(f"{param['name']}: {annotation}")
        else:
            default = format_default(param["default"], param["type"])
            parts.append(f"{param['name']}: {annotation} = {default}")
    return ", ".join(parts)


def _docstring(command: Dict[str, Any], indent: str = "    ") -> List[str]:
    lines = [f'{indent}"""{command["description"]}']
    if command["parameters"]:
        lines.append("")
        lines.append(f"{indent}Args:")
        for param in command["parameters"]:
            suffix = "" if param["required"] else " (optional)"
            text = param["description"] or param["type"]
            lines.append(f"{indent}    {param['name']}: {text}{suffix}")
    lines.append("")
    lines.append(f"{indent}Returns:")
    lines.append(f"{indent}    The result to send back to the user.")
    lines.append(f'{indent}"""')
    return lines


def _render_command(command: Dict[str, Any]) -> List[str]:
    name = command["name"]
    lines = [
        "@plugin.command(",
        f'    "{name}",',
        f'    description="{command["description"]}",',
        ")",
        f"def {name}({_signature(command)}):",
    ]
    lines.extend(_docstring(command))
    lines.append(f'    logger.info("[CMD] {name} called")')

    label = name.replace("_", " ")
    if command["streaming"]:
        lines.append(f'    plugin.stream("Running {label}...")')

    if command["passthrough"]:
        lines.append("    plugin.set_keep_session(True)")
        lines.append(
            f'    return "Started {label}. Type \'exit\' to finish."'
        )
    else:
        lines.append(f'    return "{label.capitalize()} completed."')
    lines.append("")
    lines.append("")
    return lines


def build_plugin_py(
    name: str, description: str, commands: List[Dict[str, Any]]
) -> str:
    """Return the full plugin.py source code as a string."""
    copyright_line = (
        "# SPDX-FileCopyrightText: Copyright (c) 2025 "
        "NVIDIA CORPORATION & AFFILIATES. All rights reserved."
    )
    lines = [
        copyright_line,
        "# SPDX-License-Identifier: Apache-2.0",
        "#",
        "# Generated by the G-Assist Plugin Builder. The manifest and",
        "# this file are generated together, so keep them in sync when",
        "# editing by hand.",
        "",
        '"""',
        f"{name}",
        "=" * len(name),
        "",
        description,
        "",
        "Protocol V2 (JSON-RPC) plugin built on the G-Assist Python SDK.",
        "The SDK handles heartbeat, ping/pong, framing and shutdown - do not",
        "re-implement them. Use plugin.stream() for output (never print()).",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import json",
        "import logging",
        "import os",
        "import sys",
        "",
        "# The engine adds the plugin's libs/ folder to sys.path;",
        "# add it manually too so the plugin runs during development.",
        "_plugin_dir = os.path.dirname(os.path.abspath(__file__))",
        '_libs_path = os.path.join(_plugin_dir, "libs")',
        "if os.path.exists(_libs_path) and _libs_path not in sys.path:",
        "    sys.path.insert(0, _libs_path)",
        "",
        "try:",
        "    from gassist_sdk import Plugin, Context",
        "except ImportError as exc:  # FATAL: write to stderr, never stdout",
        '    sys.stderr.write(f"FATAL: Cannot import gassist_sdk: {exc}\\n")',
        '    sys.stderr.write("Install the SDK into libs/ first.\\n")',
        "    sys.stderr.flush()",
        "    sys.exit(1)",
        "",
        "",
        BANNER,
        "# CONFIGURATION",
        BANNER,
        f'PLUGIN_NAME = "{name}"',
        "",
        "",
        "def _plugin_data_dir() -> str:",
        '    """Return the per-plugin data directory.',
        "",
        '    Uses %PROGRAMDATA% on Windows and the XDG data directory',
        '    elsewhere so the plugin also runs on Linux/macOS.',
        '    """',
        '    program_data = os.environ.get("PROGRAMDATA")',
        "    if program_data:",
        '        base = os.path.join(',
        '            program_data,',
        '            "NVIDIA Corporation",',
        '            "nvtopps",',
        '            "rise",',
        '            "plugins",',
        "        )",
        "    else:",
        '        base = os.path.join(',
        '            os.environ.get(',
        '                "XDG_DATA_HOME",',
        '                os.path.expanduser("~/.local/share"),',
        "            ),",
        '            "nvidia",',
        '            "nvtopps",',
        '            "rise",',
        '            "plugins",',
        "        )",
        "    return os.path.join(base, PLUGIN_NAME)",
        "",
        "",
        "PLUGIN_DIR = _plugin_data_dir()",
        'CONFIG_FILE = os.path.join(PLUGIN_DIR, "config.json")',
        'LOG_FILE = os.path.join(PLUGIN_DIR, f"{PLUGIN_NAME}.log")',
        "",
        "os.makedirs(PLUGIN_DIR, exist_ok=True)",
        "",
        "logging.basicConfig(",
        "    filename=LOG_FILE,",
        "    level=logging.INFO,",
        '    format="%(asctime)s - %(levelname)s - %(message)s",',
        ")",
        "logger = logging.getLogger(__name__)",
        "",
        "",
        BANNER,
        "# PLUGIN DEFINITION",
        BANNER,
        "plugin = Plugin(",
        "    name=PLUGIN_NAME,",
        '    version="1.0.0",',
        f'    description="{description}",',
        ")",
        "",
        "",
        BANNER,
        "# HELPERS",
        BANNER,
        "def load_config() -> dict:",
        '    """Load config.json; empty dict when missing or invalid."""',
        "    if not os.path.exists(CONFIG_FILE):",
        '        logger.debug("[CONFIG] no config file at %s", CONFIG_FILE)',
        "        return {}",
        "    try:",
        '        with open(CONFIG_FILE, "r", encoding="utf-8") as handle:',
        "            data = json.load(handle)",
        "            return data if isinstance(data, dict) else {}",
        "    except (OSError, ValueError) as exc:",
        '        logger.error("[CONFIG] failed to load config: %s", exc)',
        "        return {}",
        "",
        "",
        "",
        BANNER,
        "# COMMANDS",
        BANNER,
    ]

    for command in commands:
        lines.extend(_render_command(command))

    if any(command["passthrough"] for command in commands):
        lines.extend(
            [
                '@plugin.command("on_input")',
                "def on_input(content: str):",
                '    """Handle follow-up input while in passthrough mode."""',
                "    content = (content or \"\").strip()",
                '    logger.info("[INPUT] received: %r", content[:50])',
                "",
                '    if content.lower() in {"exit", "quit", "bye", "done"}:',
                "        plugin.set_keep_session(False)",
                '        return "Conversation ended."',
                "",
                "    plugin.set_keep_session(True)",
                '    return f"You said: {content}"',
                "",
                "",
            ]
        )

    lines.extend(
        [
            BANNER,
            "# MAIN ENTRY POINT",
            BANNER,
            'if __name__ == "__main__":',
            '    logger.info("Starting %s plugin", PLUGIN_NAME)',
            "    plugin.run()",
        ]
    )
    return "\n".join(lines) + "\n"


def build_manifest(
    name: str,
    description: str,
    commands: List[Dict[str, Any]],
    version: str = "1.0.0",
    persistent: bool = True,
) -> Dict[str, Any]:
    """Return the manifest.json structure for the given commands."""
    functions = []
    for command in commands:
        properties = {}
        required = []
        for param in command["parameters"]:
            properties[param["name"]] = {
                "type": param["type"],
                "description": param["description"]
                or f"The {param['name']} value.",
            }
            if param["required"]:
                required.append(param["name"])
        functions.append(
            {
                "name": command["name"],
                "description": command["description"],
                "tags": command["tags"],
                "properties": properties,
                "required": required,
            }
        )

    return {
        "manifestVersion": 1,
        "name": name,
        "version": version,
        "description": description,
        "executable": "plugin.py",
        "persistent": persistent,
        "protocol_version": "2.0",
        "functions": functions,
    }


def build_requirements() -> str:
    """Return the requirements.txt contents (SDK is copied separately)."""
    return (
        "# Dependencies for the generated plugin.\n"
        "# Installed into libs/ by setup.bat. The G-Assist SDK (gassist_sdk)\n"
        "# is copied separately from plugins/sdk/python.\n"
    )


def build_config() -> Dict[str, Any]:
    """Return a starter config.json."""
    return {}


# ============================================================================
# VALIDATION
# ============================================================================
def validate_manifest(
    manifest: Dict[str, Any], plugin_source: str
) -> List[str]:
    """Check every manifest function has a matching @plugin.command."""
    problems = []
    for function in manifest.get("functions", []):
        name = function.get("name", "")
        if f'"{name}"' not in plugin_source:
            problems.append(
                f"manifest function {name!r} has no matching command handler"
            )
    for name in RESERVED_COMMANDS:
        if any(f.get("name") == name for f in manifest.get("functions", [])):
            problems.append(
                f"reserved command {name!r} must not appear in the manifest"
            )
    return problems


# ============================================================================
# CLI
# ============================================================================
def load_spec_file(path: str) -> Dict[str, Any]:
    """Load a JSON spec file into the internal spec structure."""
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    commands = []
    for cmd in raw.get("commands") or raw.get("functions") or []:
        params = []
        for param in cmd.get("parameters") or []:
            typ = param.get("type", "string")
            if typ in ANNOTATION_TO_TYPE:
                typ = ANNOTATION_TO_TYPE[typ]
            params.append({**param, "type": typ})
        commands.append({**cmd, "parameters": params})

    return {
        "name": raw.get("name"),
        "version": raw.get("version", "1.0.0"),
        "description": raw.get("description"),
        "persistent": raw.get("persistent", True),
        "commands": commands,
    }


def write_package(spec: Dict[str, Any], out_dir: str) -> List[str]:
    """Write the generated package to out_dir and return the file paths."""
    normalized = normalize_spec(spec)
    name = normalized["name"]
    commands = normalized["commands"]

    plugin_source = build_plugin_py(name, normalized["description"], commands)
    manifest = build_manifest(
        name,
        normalized["description"],
        commands,
        version=normalized["version"],
        persistent=normalized["persistent"],
    )

    problems = validate_manifest(manifest, plugin_source)
    if problems:
        raise SpecError(
            "Generated package failed validation: " + "; ".join(problems)
        )

    os.makedirs(out_dir, exist_ok=True)
    written = []

    plugin_path = os.path.join(out_dir, "plugin.py")
    with open(plugin_path, "w", encoding="utf-8") as handle:
        handle.write(plugin_source)
    written.append(plugin_path)

    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")
    written.append(manifest_path)

    requirements_path = os.path.join(out_dir, "requirements.txt")
    with open(requirements_path, "w", encoding="utf-8") as handle:
        handle.write(build_requirements())
    written.append(requirements_path)

    config_path = os.path.join(out_dir, "config.json")
    with open(config_path, "w", encoding="utf-8") as handle:
        json.dump(build_config(), handle, indent=2)
        handle.write("\n")
    written.append(config_path)

    return written


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate a G-Assist Protocol V2 plugin package from a spec."
        )
    )
    parser.add_argument("--name", help="Plugin name (e.g. my-plugin)")
    parser.add_argument("--desc", "--description", dest="description",
                        help="One-line plugin description")
    parser.add_argument("--version", default="1.0.0", help="Plugin version")
    parser.add_argument(
        "--cmd",
        action="append",
        default=[],
        metavar="NAME:TYPE[:DESC[:DEFAULT]]",
        help="Command to generate (repeatable). TYPE is one of "
             + ", ".join(sorted(TYPE_MAP)),
    )
    parser.add_argument(
        "--spec", help="JSON spec file (alternative to --name/--cmd)"
    )
    parser.add_argument(
        "--out", help="Output directory (default: ./<plugin-name>)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files in the output directory",
    )
    parser.add_argument(
        "--validate",
        metavar="DIR",
        help="Only check that DIR's manifest.json and plugin.py are in sync",
    )
    return parser


def validate_directory(directory: str) -> List[str]:
    """Check that a generated package's manifest and code agree."""
    manifest_path = os.path.join(directory, "manifest.json")
    plugin_path = os.path.join(directory, "plugin.py")
    if not os.path.exists(manifest_path):
        raise SpecError(f"Missing manifest.json in {directory}")
    if not os.path.exists(plugin_path):
        raise SpecError(f"Missing plugin.py in {directory}")

    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    with open(plugin_path, "r", encoding="utf-8") as handle:
        source = handle.read()

    problems = validate_manifest(manifest, source)

    # Conversely: every command decorator should be declared in the manifest.
    declared = {f.get("name") for f in manifest.get("functions", [])}
    for name in re.findall(r'@plugin\.command\(\s*"(\w+)"', source):
        if name not in RESERVED_COMMANDS and name not in declared:
            problems.append(
                f"command {name!r} is defined in plugin.py "
                "but missing from manifest.json"
            )

    leftovers = [marker for marker in TEMPLATE_MARKERS if marker in source]
    if leftovers:
        problems.append(
            "plugin.py still contains template placeholders: "
            + ", ".join(leftovers)
        )
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    """Run the generator CLI; returns a process exit code."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.validate:
        try:
            problems = validate_directory(args.validate)
        except (SpecError, OSError, ValueError) as exc:
            sys.stderr.write(f"error: {exc}\n")
            return 1
        if problems:
            sys.stdout.write(f"{args.validate}: {len(problems)} problem(s)\n")
            for problem in problems:
                sys.stdout.write(f"  - {problem}\n")
            return 1
        sys.stdout.write(
            f"{args.validate}: manifest and plugin.py are in sync\n"
        )
        return 0

    try:
        if args.spec:
            spec = load_spec_file(args.spec)
        else:
            if not args.name or not args.description:
                parser.error("--name and --desc are required (or use --spec)")
            commands = [cmd_from_arg(raw) for raw in args.cmd]
            spec = {
                "name": args.name,
                "version": args.version,
                "description": args.description,
                "commands": commands,
            }

        normalized = normalize_spec(spec)
        out_dir = args.out or os.path.join(os.getcwd(), normalized["name"])

        if os.path.isdir(out_dir) and not args.force:
            package_files = (
                "plugin.py",
                "manifest.json",
                "requirements.txt",
                "config.json",
            )
            existing = [
                f
                for f in package_files
                if os.path.exists(os.path.join(out_dir, f))
            ]
            if existing:
                sys.stderr.write(
                    f"Refusing to overwrite {', '.join(existing)} "
                    f"in {out_dir} (use --force)\n"
                )
                return 1

        written = write_package(spec, out_dir)
    except (SpecError, OSError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    sys.stdout.write(f"Generated plugin '{normalized['name']}' in {out_dir}\n")
    for path in written:
        sys.stdout.write(f"  - {os.path.basename(path)}\n")
    sys.stdout.write(
        "\nNext steps:\n"
        f"  cd {out_dir}\n"
        "  python -m json.tool manifest.json\n"
        "  setup.bat <plugin-name> -deploy   (from plugins/examples)\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
