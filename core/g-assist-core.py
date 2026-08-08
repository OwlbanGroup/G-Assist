#!/usr/bin/env python3
# pylint: disable=invalid-name

"""
G-Assist Core System

The main executable for G-Assist, a plugin-based AI assistant for RTX and Blackwell GPUs.
This system manages plugin loading, communication, and provides the core functionality
for interacting with NVIDIA GPUs and running AI workloads.

Author: NVIDIA Corporation
License: Apache 2.0
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Configure logging
LOG_LEVEL = os.environ.get("GASSIST_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(os.environ.get("GASSIST_LOG_FILE", "g-assist.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("g-assist-core")


class PluginManager:
    """Manages loading and communication with G-Assist plugins."""

    def __init__(self, plugins_dir: Optional[str] = None):
        self.plugins_dir = (
            Path(plugins_dir) if plugins_dir else self._get_default_plugins_dir()
        )
        self.plugins: Dict[str, dict] = {}
        self.running_plugins: Dict[str, subprocess.Popen] = {}
        self.plugin_manifests: Dict[str, dict] = {}
        # Guards access to running_plugins and plugin_manifests so concurrent
        # invocations do not corrupt the subprocess pipes.
        self._lock = threading.RLock()
        logger.info("Plugin manager initialized with directory: %s", self.plugins_dir)

    def _get_default_plugins_dir(self) -> Path:
        """Get the default plugins directory based on the system."""
        if sys.platform == "win32":
            program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
            return (
                Path(program_data)
                / "NVIDIA Corporation"
                / "nvtopps"
                / "rise"
                / "plugins"
            )
        # For Linux/macOS, use a user directory
        return Path.home() / ".nvidia" / "g-assist" / "plugins"

    def discover_plugins(self) -> List[str]:
        """Discover available plugins in the plugins directory."""
        if not self.plugins_dir.exists():
            logger.warning("Plugins directory does not exist: %s", self.plugins_dir)
            return []

        plugin_names: List[str] = []
        for item in sorted(self.plugins_dir.iterdir()):
            if item.is_dir() and (item / "manifest.json").exists():
                plugin_names.append(item.name)
                logger.info("Found plugin: %s", item.name)
        return plugin_names

    def load_plugin_manifest(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Load the manifest for a specific plugin."""
        manifest_path = self.plugins_dir / plugin_name / "manifest.json"
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            with self._lock:
                self.plugin_manifests[plugin_name] = manifest
            logger.info("Loaded manifest for plugin: %s", plugin_name)
            return manifest
        except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
            logger.error("Failed to load manifest for plugin %s: %s", plugin_name, e)
            return None

    def start_plugin(self, plugin_name: str) -> bool:
        """Start a plugin process."""
        with self._lock:
            if plugin_name in self.running_plugins:
                logger.warning("Plugin %s is already running", plugin_name)
                return True

            manifest = self.plugin_manifests.get(plugin_name)
            if not manifest:
                manifest = self.load_plugin_manifest(plugin_name)
                if not manifest:
                    return False

            executable = manifest.get("executable")
            if not executable:
                logger.error(
                    "No executable specified in manifest for plugin %s", plugin_name
                )
                return False

            plugin_dir = self.plugins_dir / plugin_name
            exe_path = plugin_dir / executable

            if not exe_path.exists():
                logger.error("Plugin executable not found: %s", exe_path)
                return False

            try:
                process = subprocess.Popen(
                    [str(exe_path)],
                    cwd=str(plugin_dir),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                self.running_plugins[plugin_name] = process
                logger.info("Started plugin: %s (PID: %s)", plugin_name, process.pid)
            except (OSError, subprocess.SubprocessError) as e:
                logger.error("Failed to start plugin %s: %s", plugin_name, e)
                return False

        # Start the monitor thread outside the lock so it can read the pipes.
        threading.Thread(
            target=self._monitor_plugin,
            args=(plugin_name,),
            daemon=True,
            name=f"plugin-monitor-{plugin_name}",
        ).start()
        return True

    def _monitor_plugin(self, plugin_name: str) -> None:
        """Monitor a plugin process, draining its stdout/stderr and logging output."""
        with self._lock:
            process = self.running_plugins.get(plugin_name)
        if process is None:
            return

        # Poll-based drain avoids busy-waiting and prevents the child process
        # from blocking on a full pipe buffer.
        try:
            for line in process.stdout or ():
                logger.debug("Plugin %s output: %s", plugin_name, line.strip())
        except (OSError, ValueError) as e:
            logger.error("Error reading plugin %s stdout: %s", plugin_name, e)

        # Drain stderr after stdout closes.
        for line in process.stderr or ():
            logger.debug("Plugin %s stderr: %s", plugin_name, line.strip())

        return_code = process.wait()
        logger.info("Plugin %s terminated with code: %s", plugin_name, return_code)

        with self._lock:
            # Only remove if it's the same process we monitored.
            if self.running_plugins.get(plugin_name) is process:
                del self.running_plugins[plugin_name]

    def stop_plugin(self, plugin_name: str) -> bool:
        """Stop a running plugin."""
        with self._lock:
            process = self.running_plugins.get(plugin_name)
        if process is None:
            logger.warning("Plugin %s is not running", plugin_name)
            return True

        try:
            process.terminate()
            process.wait(timeout=5)
            logger.info("Stopped plugin: %s", plugin_name)
            return True
        except subprocess.TimeoutExpired:
            logger.warning(
                "Plugin %s did not terminate gracefully, killing...", plugin_name
            )
            process.kill()
            process.wait(timeout=5)
            return True
        except OSError as e:
            logger.error("Error stopping plugin %s: %s", plugin_name, e)
            return False

    def invoke_plugin(
        self,
        plugin_name: str,
        function_name: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Invoke a function on a plugin."""
        if not self._ensure_plugin_running(plugin_name):
            return None

        if not self._check_function_exists(plugin_name, function_name):
            return None

        command = self._prepare_command(function_name, params)
        return self._send_and_receive(plugin_name, command)

    def _ensure_plugin_running(self, plugin_name: str) -> bool:
        """Ensure the plugin is running, start if necessary."""
        with self._lock:
            if plugin_name not in self.running_plugins:
                logger.warning(
                    "Plugin %s is not running, attempting to start...", plugin_name
                )
                return self.start_plugin(plugin_name)
        return True

    def _check_function_exists(self, plugin_name: str, function_name: str) -> bool:
        """Check if the function exists in the plugin manifest."""
        with self._lock:
            manifest = self.plugin_manifests.get(plugin_name)
        if not manifest:
            manifest = self.load_plugin_manifest(plugin_name)
            if not manifest:
                return False

        for func in manifest.get("functions", []):
            if func.get("name") == function_name:
                return True
        logger.error("Function %s not found in plugin %s", function_name, plugin_name)
        return False

    @staticmethod
    def _prepare_command(function_name: str, params: Optional[Dict[str, Any]]) -> dict:
        """Prepare the command dictionary."""
        return {"tool_calls": [{"func": function_name, "properties": params or {}}]}

    def _send_and_receive(
        self, plugin_name: str, command: dict
    ) -> Optional[Dict[str, Any]]:
        """Send command to plugin and receive response."""
        with self._lock:
            process = self.running_plugins.get(plugin_name)
        if process is None or process.stdin is None or process.stdout is None:
            logger.error("No stdin/stdout available for plugin %s", plugin_name)
            return None

        try:
            command_json = json.dumps(command) + "\n"
            with self._lock:
                process.stdin.write(command_json)
                process.stdin.flush()
            logger.debug("Sent command to %s: %s", plugin_name, command_json.strip())

            response_line = process.stdout.readline().strip()
            if not response_line:
                logger.warning("No response received from plugin %s", plugin_name)
                return None
            response = json.loads(response_line)
            logger.debug("Received response from %s: %s", plugin_name, response)
            return response
        except (json.JSONDecodeError, OSError, ValueError) as e:
            logger.error("Error communicating with plugin %s: %s", plugin_name, e)
            return None

    def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a plugin."""
        with self._lock:
            manifest = self.plugin_manifests.get(plugin_name)
            running = plugin_name in self.running_plugins
        if not manifest:
            manifest = self.load_plugin_manifest(plugin_name)
        if not manifest:
            return None

        return {
            "name": plugin_name,
            "description": manifest.get("description", ""),
            "functions": manifest.get("functions", []),
            "tags": manifest.get("tags", []),
            "persistent": manifest.get("persistent", False),
            "running": running,
        }

    def list_plugins(self) -> List[dict]:
        """List all available plugins with their status."""
        return [
            info
            for info in (self.get_plugin_info(name) for name in self.discover_plugins())
            if info is not None
        ]

    def shutdown(self) -> None:
        """Shutdown all running plugins."""
        logger.info("Shutting down all plugins...")
        with self._lock:
            names = list(self.running_plugins.keys())
        for plugin_name in names:
            self.stop_plugin(plugin_name)
        logger.info("All plugins shut down")


class GPUManager:
    """Manages GPU information and monitoring."""

    def __init__(self):
        self.gpu_info: Dict[str, Any] = {}
        self._load_gpu_info()

    def _load_gpu_info(self) -> None:
        """Load basic GPU information."""
        # Attempt to read real info from nvidia-smi when available; fall back
        # to a placeholder so the system still works without a GPU present.
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            line = result.stdout.strip().splitlines()
            if line:
                name, driver, mem_mb = [part.strip() for part in line[0].split(",")]
                self.gpu_info = {
                    "vendor": "NVIDIA",
                    "model": name,
                    "driver_version": driver,
                    "memory_total": f"{int(float(mem_mb)) / 1024:.1f}GB",
                    "cuda_cores": "Available (see nvidia-smi)",
                }
                logger.info("Detected GPU: %s", name)
                return
        except (
            FileNotFoundError,
            subprocess.SubprocessError,
            ValueError,
            IndexError,
        ) as e:
            logger.warning("nvidia-smi unavailable or failed: %s", e)

        self.gpu_info = {
            "vendor": "NVIDIA",
            "model": "GeForce RTX 5090",
            "driver_version": "572.83",
            "memory_total": "32GB",
            "cuda_cores": 17408,
        }
        logger.info("Using placeholder GPU info (nvidia-smi not available)")

    def get_gpu_info(self) -> dict:
        """Get current GPU information."""
        return self.gpu_info

    def get_system_info(self) -> dict:
        """Get system information including GPU details."""
        return {"gpu": self.gpu_info, "os": sys.platform, "python_version": sys.version}


class GAssistCore:
    """Main G-Assist core system."""

    def __init__(self, plugins_dir: Optional[str] = None):
        self.plugin_manager = PluginManager(plugins_dir)
        self.gpu_manager = GPUManager()
        self.running = False
        self.command_handlers: Dict[str, Callable[[dict], dict]] = {
            "list_plugins": self._handle_list_plugins,
            "start_plugin": self._handle_start_plugin,
            "stop_plugin": self._handle_stop_plugin,
            "invoke_plugin": self._handle_invoke_plugin,
            "get_gpu_info": self._handle_get_gpu_info,
            "shutdown": self._handle_shutdown,
        }
        logger.info("G-Assist Core initialized")

    def start(self) -> None:
        """Start the G-Assist core system."""
        logger.info("Starting G-Assist Core...")
        self.running = True
        self._load_persistent_plugins()
        logger.info("G-Assist Core started successfully")

    def stop(self) -> None:
        """Stop the G-Assist core system."""
        logger.info("Stopping G-Assist Core...")
        self.running = False
        self.plugin_manager.shutdown()
        logger.info("G-Assist Core stopped")

    def _load_persistent_plugins(self) -> None:
        """Load all plugins marked as persistent."""
        for plugin in self.plugin_manager.list_plugins():
            if plugin.get("persistent", False):
                logger.info("Starting persistent plugin: %s", plugin["name"])
                self.plugin_manager.start_plugin(plugin["name"])

    def process_command(
        self, command: str, params: Optional[Dict[str, Any]] = None
    ) -> dict:
        """Process a command and return the result."""
        params = params or {}
        handler = self.command_handlers.get(command)
        if handler is None:
            return self._handle_unknown_command(command, params)
        return handler(params)

    def _handle_list_plugins(self, _params: dict) -> dict:
        """Handle list_plugins command."""
        return {"success": True, "plugins": self.plugin_manager.list_plugins()}

    def _handle_start_plugin(self, params: dict) -> dict:
        """Handle start_plugin command."""
        plugin_name = params.get("plugin_name")
        if not plugin_name:
            return {"success": False, "error": "plugin_name parameter required"}
        success = self.plugin_manager.start_plugin(plugin_name)
        return {"success": success, "plugin_name": plugin_name}

    def _handle_stop_plugin(self, params: dict) -> dict:
        """Handle stop_plugin command."""
        plugin_name = params.get("plugin_name")
        if not plugin_name:
            return {"success": False, "error": "plugin_name parameter required"}
        success = self.plugin_manager.stop_plugin(plugin_name)
        return {"success": success, "plugin_name": plugin_name}

    def _handle_invoke_plugin(self, params: dict) -> dict:
        """Handle invoke_plugin command."""
        plugin_name = params.get("plugin_name")
        function_name = params.get("function_name")
        function_params = params.get("params", {})

        if not plugin_name or not function_name:
            return {
                "success": False,
                "error": "plugin_name and function_name parameters required",
            }

        result = self.plugin_manager.invoke_plugin(
            plugin_name, function_name, function_params
        )
        if result is not None:
            return {"success": True, "result": result}
        return {
            "success": False,
            "error": f"Failed to invoke {function_name} on plugin {plugin_name}",
        }

    def _handle_get_gpu_info(self, _params: dict) -> dict:
        """Handle get_gpu_info command."""
        return {"success": True, "gpu_info": self.gpu_manager.get_gpu_info()}

    def _handle_shutdown(self, _params: dict) -> dict:
        """Handle shutdown command."""
        self.stop()
        return {"success": True, "message": "G-Assist Core shutting down"}

    def _handle_unknown_command(self, command: str, _params: dict) -> dict:
        """Handle unknown commands."""
        return {"success": False, "error": f"Unknown command: {command}"}


def _parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="G-Assist Core System")
    parser.add_argument("--plugins-dir", help="Directory containing plugins")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level",
    )
    parser.add_argument(
        "--daemon", action="store_true", help="Run as daemon/background process"
    )
    return parser.parse_args()


def _setup_signal_handlers(core: GAssistCore) -> None:
    """Set up signal handlers for graceful shutdown."""

    def signal_handler(signum, _frame):
        logger.info("Received signal %s, shutting down...", signum)
        core.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def _run_daemon(core: GAssistCore) -> None:
    """Run the core in daemon mode."""
    logger.info("Running as daemon...")
    while core.running:
        time.sleep(1)


def _run_interactive(core: GAssistCore) -> None:
    """Run the core in interactive mode."""
    print("G-Assist Core started. Type 'help' for commands, 'quit' to exit.")

    while core.running:
        try:
            command_line = input("G-Assist> ").strip()
            if not command_line:
                continue

            if command_line.lower() in ["quit", "exit", "q"]:
                break

            if command_line.lower() == "help":
                _print_help()
                continue

            result = _parse_and_process_command(core, command_line)
            _display_result(result)

        except KeyboardInterrupt:
            break
        except (EOFError, ValueError, OSError) as e:
            logger.error("Error processing command: %s", e)
            print(f"Error: {e}")


def _print_help() -> None:
    """Print available commands."""
    print("Available commands:")
    print("  list_plugins - List all available plugins")
    print("  start_plugin <name> - Start a plugin")
    print("  stop_plugin <name> - Stop a plugin")
    print("  invoke_plugin <plugin> <function> - Invoke a plugin function")
    print("  get_gpu_info - Get GPU information")
    print("  help - Show this help")
    print("  quit - Exit")


def _parse_and_process_command(core: GAssistCore, command_line: str) -> dict:
    """Parse command line and process it."""
    parts = command_line.split()
    command = parts[0]
    params: Dict[str, Any] = {}

    if command == "start_plugin" and len(parts) > 1:
        params = {"plugin_name": parts[1]}
    elif command == "stop_plugin" and len(parts) > 1:
        params = {"plugin_name": parts[1]}
    elif command == "invoke_plugin" and len(parts) > 2:
        params = {"plugin_name": parts[1], "function_name": parts[2]}

    return core.process_command(command, params)


def _display_result(result: dict) -> None:
    """Display command result to user."""
    if result.get("success"):
        if "plugins" in result:
            print("Available plugins:")
            for plugin in result["plugins"]:
                status = "RUNNING" if plugin["running"] else "STOPPED"
                print(f"  {plugin['name']} - {plugin['description']} [{status}]")
        elif "gpu_info" in result:
            print("GPU Information:")
            for key, value in result["gpu_info"].items():
                print(f"  {key}: {value}")
        elif "result" in result:
            print(f"Result: {result['result']}")
        else:
            print("Command executed successfully")
    else:
        print(f"Error: {result.get('error', 'Unknown error')}")


def main() -> None:
    """Main entry point for G-Assist Core."""
    args = _parse_args()

    logging.getLogger().setLevel(getattr(logging, args.log_level))

    core = GAssistCore(args.plugins_dir)
    _setup_signal_handlers(core)

    try:
        core.start()
        if args.daemon:
            _run_daemon(core)
        else:
            _run_interactive(core)
    except (ValueError, OSError) as e:
        logger.error("Error in main: %s", e)
        print(f"Error: {e}")
    finally:
        core.stop()


if __name__ == "__main__":
    main()
