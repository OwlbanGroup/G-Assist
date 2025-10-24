#!/usr/bin/env python3
"""
Build script for Blackbox AI plugin.

This script packages the Blackbox AI plugin for distribution.
"""

import sys
import shutil
from pathlib import Path

def build_plugin():
    """Build the Blackbox AI plugin."""
    plugin_dir = Path(__file__).parent
    build_dir = plugin_dir / "dist" / "blackboxai"
    build_dir.mkdir(parents=True, exist_ok=True)

    print("Building Blackbox AI plugin...")

    # Copy necessary files
    files_to_copy = [
        "manifest.json",
        "config.json",
        "plugin.py",
        "requirements.txt",
        "README.md"
    ]

    for file in files_to_copy:
        src = plugin_dir / file
        if src.exists():
            shutil.copy2(src, build_dir / file)
            print(f"Copied {file}")

    # Create executable (for demonstration, just copy the Python file)
    # In a real build, this would compile to an exe
    exe_name = "g-assist-plugin-blackboxai.exe"
    exe_path = build_dir / exe_name

    # For now, create a batch file that runs the Python script
    # In production, this would be a compiled executable
    batch_content = f'''@echo off
python "{plugin_dir / "plugin.py"}" %*
'''
    exe_path.write_text(batch_content)
    print(f"Created {exe_name}")

    print(f"Plugin built successfully in {build_dir}")
    return True

if __name__ == "__main__":
    SUCCESS = build_plugin()
    sys.exit(0 if SUCCESS else 1)
