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

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Union

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SETUP_PY = "setup.py"


class Builder:
    """Main build system for G-Assist."""

    def __init__(self, build_dir: str = "build"):
        self.root_dir = Path(__file__).parent
        self.build_dir = self.root_dir / build_dir
        self.build_dir.mkdir(exist_ok=True)

    def run_command(
        self,
        cmd: List[str],
        cwd: Optional[Union[str, Path]] = None,
        check: bool = True,
    ) -> bool:
        """Run a shell command and return success status.

        Returns False only when the command fails to run OR exits non-zero.
        A missing executable is reported clearly rather than swallowed.
        """
        try:
            logger.info("Running: %s", " ".join(cmd))
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

        if not python_dir.exists():
            logger.error("Python bindings directory not found: %s", python_dir)
            return False

        # Check if Visual Studio is available (Windows)
        if sys.platform == "win32":
            sln_file = python_dir / "python_binding.sln"
            if sln_file.exists():
                if self.run_command(
                    ["MSBuild", str(sln_file), "/p:Configuration=Release"],
                    cwd=python_dir,
                ):
                    logger.info("Python bindings built with MSBuild")
                    return True
                logger.warning("MSBuild failed, trying alternative build methods")
            else:
                logger.info("No .sln found, using setuptools build")

            setup_py = python_dir / SETUP_PY
            if setup_py.exists():
                if self.run_command(
                    [sys.executable, SETUP_PY, "build_ext", "--inplace"],
                    cwd=python_dir,
                ):
                    logger.info("Python bindings built with setuptools")
                    return True
                logger.error("Failed to build Python bindings")
                return False

        # Install Python package
        if not self.run_command(
            [sys.executable, "-m", "pip", "install", "-e", "."],
            cwd=python_dir,
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
        build_script = (
            plugin_dir / "build.bat"
            if sys.platform == "win32"
            else plugin_dir / "build.sh"
        )
        if build_script.exists():
            if sys.platform == "win32":
                if self.run_command([str(build_script)], cwd=plugin_dir):
                    return True
            else:
                if self.run_command(["bash", str(build_script)], cwd=plugin_dir):
                    return True
            logger.warning("Build script failed for %s, trying setup.py", plugin_name)
            return self.build_plugin_from_setup(plugin_dir)

        return self.build_plugin_from_setup(plugin_dir)

    def build_plugin_from_setup(self, plugin_dir: Path) -> bool:
        """Build a plugin using its setup.py or requirements.txt."""
        setup_py = plugin_dir / SETUP_PY
        if setup_py.exists():
            return self.run_command([sys.executable, SETUP_PY, "build"], cwd=plugin_dir)

        requirements = plugin_dir / "requirements.txt"
        if requirements.exists():
            return self.run_command(
                [sys.executable, "-m", "pip", "install", "-r", str(requirements)],
                cwd=plugin_dir,
            )

        # No build system found - assume it's ready
        logger.info("No build system found for %s, assuming pre-built", plugin_dir.name)
        return True

    def build_plugins(self) -> bool:
        """Build all plugins."""
        logger.info("Building plugins...")

        plugins_dir = self.root_dir / "plugins"
        if not plugins_dir.exists():
            logger.warning("No plugins directory found")
            return True

        success = True
        # Only scan immediate subdirectories that have a manifest, not deep trees.
        for plugin_dir in plugins_dir.iterdir():
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
            try:
                pyc.unlink()
            except OSError as e:
                logger.warning("Could not remove %s: %s", pyc, e)
        for pycache in self.root_dir.rglob("__pycache__"):
            try:
                shutil.rmtree(pycache)
            except OSError as e:
                logger.warning("Could not remove %s: %s", pycache, e)

        # Clean dist directories
        for dist in self.root_dir.rglob("dist"):
            try:
                shutil.rmtree(dist)
            except OSError as e:
                logger.warning("Could not remove %s: %s", dist, e)
        for build in self.root_dir.rglob("build"):
            if build != self.build_dir:
                try:
                    shutil.rmtree(build)
                except OSError as e:
                    logger.warning("Could not remove %s: %s", build, e)

        logger.info("Clean completed")
        return True


def main() -> None:
    """Main entry point for the build script."""
    parser = argparse.ArgumentParser(description="G-Assist Build System")
    parser.add_argument(
        "component",
        nargs="?",
        default="all",
        choices=["core", "plugins", "python", "all", "clean"],
        help="Component to build",
    )
    parser.add_argument(
        "--clean", action="store_true", help="Clean build artifacts before building"
    )

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
