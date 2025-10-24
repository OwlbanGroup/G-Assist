#!/usr/bin/env python3
"""
G-Assist Build Script

Builds the G-Assist system components including plugins and core modules.
Handles compilation of C++ components and packaging of Python modules.

Usage:
    python build.py [component]

Components:
    core        - Build the core system
    plugins     - Build all plugins
    python      - Build Python bindings
    all         - Build everything (default)
"""

import sys
import subprocess
import shutil
import argparse
from pathlib import Path
import logging
from typing import Optional, Union

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

SETUP_PY = "setup.py"


class Builder:
    """Main build system for G-Assist."""

    def __init__(self, build_dir: str = "build"):
        self.root_dir = Path(__file__).parent
        self.build_dir = self.root_dir / build_dir
        self.build_dir.mkdir(exist_ok=True)

    def run_command(self, cmd: list, cwd: Optional[Union[str, Path]] = None,
                    check: bool = True) -> bool:
        """Run a shell command and return success status."""
        try:
            logger.info("Running: %s", ' '.join(cmd))
            if cwd:
                logger.info("In directory: %s", cwd)
            result = subprocess.run(cmd, cwd=cwd or self.root_dir, check=check)
            return result.returncode == 0
        except subprocess.CalledProcessError as e:
            logger.error("Command failed: %s", e)
            return False
        except FileNotFoundError:
            logger.error("Command not found: %s", cmd[0])
            return False

    def build_python_bindings(self) -> bool:
        """Build Python bindings."""
        logger.info("Building Python bindings...")

        python_dir = self.root_dir / "api" / "bindings" / "python"

        # Check if Visual Studio is available (Windows)
        if sys.platform == "win32":
            # Try to build with MSBuild
            sln_file = python_dir / "python_binding.sln"
            if sln_file.exists() and not self.run_command(
                ["MSBuild", str(sln_file), "/p:Configuration=Release"], cwd=python_dir
            ):
                logger.warning("MSBuild failed, trying alternative build methods")

            # Try with setuptools
            setup_py = python_dir / SETUP_PY
            if setup_py.exists() and not self.run_command(
                [sys.executable, SETUP_PY, "build_ext", "--inplace"],
                cwd=python_dir
            ):
                logger.error("Failed to build Python bindings")
                return False

        # Install Python package
        if not self.run_command(
            [sys.executable, "-m", "pip", "install", "-e", "."],
            cwd=python_dir
        ):
            logger.error("Failed to install Python package")
            return False

        logger.info("Python bindings built successfully")
        return True

    def build_plugin(self, plugin_dir: Path) -> bool:
        """Build a single plugin."""
        plugin_name = plugin_dir.name
        logger.info("Building plugin: %s", plugin_name)

        # Check for build script
        build_script = (plugin_dir / "build.bat" if sys.platform == "win32"
                        else plugin_dir / "build.sh")
        if build_script.exists() and (
            (sys.platform == "win32" and self.run_command([str(build_script)], cwd=plugin_dir)) or
            (sys.platform != "win32" and self.run_command(["bash", str(build_script)],
                                                          cwd=plugin_dir))
        ):
            return True

        # Check for Python setup
        setup_py = plugin_dir / SETUP_PY
        if setup_py.exists():
            return self.run_command([sys.executable, SETUP_PY, "build"],
                                    cwd=plugin_dir)

        # Check for requirements.txt
        requirements = plugin_dir / "requirements.txt"
        if requirements.exists():
            return self.run_command([sys.executable, "-m", "pip", "install", "-r",
                                     str(requirements)], cwd=plugin_dir)

        # No build system found - assume it's ready
        logger.info("No build system found %s, assuming pre-built", plugin_name)
        return True

    def build_plugins(self) -> bool:
        """Build all plugins."""
        logger.info("Building plugins...")

        plugins_dir = self.root_dir / "plugins"
        if not plugins_dir.exists():
            logger.warning("No plugins directory found")
            return True

        success = True
        for plugin_dir in plugins_dir.rglob("*"):
            if plugin_dir.is_dir() and (plugin_dir / "manifest.json").exists():
                if not self.build_plugin(plugin_dir):
                    logger.error("Failed to build plugin: %s", plugin_dir.name)
                    success = False

        if success:
            logger.info("All plugins built successfully")
        return success

    def build_core(self) -> bool:
        """Build the core system."""
        logger.info("Building core system...")

        core_dir = self.root_dir / "core"

        # Install requirements
        requirements = core_dir / "requirements.txt"
        if requirements.exists():
            pip_cmd = [sys.executable, "-m", "pip", "install", "-r", str(requirements)]
            if not self.run_command(pip_cmd, cwd=core_dir):
                logger.error("Failed to install core requirements")
                return False

        # Check for setup.py
        setup_py = core_dir / SETUP_PY
        if setup_py.exists():
            build_cmd = [sys.executable, SETUP_PY, "build"]
            if not self.run_command(build_cmd, cwd=core_dir):
                logger.error("Failed to build core")
                return False

        logger.info("Core system built successfully")
        return True

    def build_all(self) -> bool:
        """Build everything."""
        logger.info("Building all components...")

        success = True

        if not self.build_core():
            success = False

        if not self.build_python_bindings():
            success = False

        if not self.build_plugins():
            success = False

        if success:
            logger.info("All components built successfully")
        else:
            logger.error("Some components failed to build")

        return success

    def clean(self) -> bool:
        """Clean build artifacts."""
        logger.info("Cleaning build artifacts...")

        # Remove build directory
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
            logger.info("Removed build directory")

        # Clean Python bytecode
        for pyc in self.root_dir.rglob("*.pyc"):
            pyc.unlink()
        for pycache in self.root_dir.rglob("__pycache__"):
            shutil.rmtree(pycache)

        # Clean dist directories
        for dist in self.root_dir.rglob("dist"):
            shutil.rmtree(dist)
        for build in self.root_dir.rglob("build"):
            if build != self.build_dir:
                shutil.rmtree(build)

        logger.info("Clean completed")
        return True


def main():
    """Main entry point for the build script."""
    parser = argparse.ArgumentParser(description="G-Assist Build System")
    parser.add_argument("component", nargs="?", default="all",
                       choices=["core", "plugins", "python", "all", "clean"],
                       help="Component to build")
    parser.add_argument("--clean", action="store_true",
                        help="Clean build artifacts before building")

    args = parser.parse_args()

    builder = Builder()

    if args.clean or args.component == "clean":
        if not builder.clean():
            sys.exit(1)
        if args.component == "clean":
            sys.exit(0)

    success = False

    if args.component == "core":
        success = builder.build_core()
    elif args.component == "plugins":
        success = builder.build_plugins()
    elif args.component == "python":
        success = builder.build_python_bindings()
    elif args.component == "all":
        success = builder.build_all()

    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
