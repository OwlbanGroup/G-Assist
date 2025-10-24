#!/usr/bin/env python3
"""
G-Assist Core System

The main executable for G-Assist, a plugin-based AI assistant for RTX and Blackwell GPUs.
This system manages plugin loading, communication, and provides the core functionality
for interacting with NVIDIA GPUs and running AI workloads.

Author: NVIDIA Corporation
License: Apache 2.0
"""

import os
import sys
import json
import logging
import subprocess
import threading
import time
from typing import Dict, List, Optional, Any
from pathlib import Path
import argparse
import signal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('g-assist.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('g-assist-core')

class PluginManager:
    """Manages loading and communication with G-Assist plugins."""

    def __init__(self, plugins_dir: Optional[str] = None):
        self.plugins_dir = Path(plugins_dir) if plugins_dir else self._get_default_plugins_dir()
        self.plugins: Dict[str, dict] = {}
        self.running_plugins: Dict[str, subprocess.Popen] = {}
        self.plugin_manifests: Dict[str, dict] = {}

        logger.info("Plugin manager initialized with directory: %s", self.plugins_dir)

    def _get_default_plugins_dir(self) -> Path:
        """Get the default plugins directory based on the system."""
        if sys.platform == 'win32':
            program_data = os.environ.get('PROGRAMDATA', 'C:\\ProgramData')
            return Path(program_data) / 'NVIDIA Corporation' / 'nvtopps' / 'rise' / 'plugins'
        else:
            # For Linux/macOS, use a user directory
            home = Path.home()
            return home / '.nvidia' / 'g-assist' / 'plugins'

    def discover_plugins(self) -> List[str]:
        """Discover available plugins in the plugins directory."""
        if not self.plugins_dir.exists():
            logger.warning("Plugins directory does not exist: %s", self.plugins_dir)
            return []

        plugin_names = []
        for item in self.plugins_dir.iterdir():
            if item.is_dir():
                manifest_path = item / 'manifest.json'
                if manifest_path.exists():
                    plugin_names.append(item.name)
                    logger.info("Found plugin: %s", item.name)

        return plugin_names

    def load_plugin_manifest(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Load the manifest for a specific plugin."""
        manifest_path = self.plugins_dir / plugin_name / 'manifest.json'
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
                self.plugin_manifests[plugin_name] = manifest
                logger.info("Loaded manifest for plugin: %s", plugin_name)
                return manifest
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error("Failed to load manifest for plugin %s: %s", plugin_name, e)
            return None

    def start_plugin(self, plugin_name: str) -> bool:
        """Start a plugin process."""
        if plugin_name in self.running_plugins:
            logger.warning("Plugin %s is already running", plugin_name)
            return True

        manifest = self.plugin_manifests.get(plugin_name)
        if not manifest:
            manifest = self.load_plugin_manifest(plugin_name)
            if not manifest:
                return False

        executable = manifest.get('executable')
        if not executable:
            logger.error("No executable specified in manifest for plugin %s", plugin_name)
            return False

        plugin_dir = self.plugins_dir / plugin_name
        exe_path = plugin_dir / executable

        if not exe_path.exists():
            logger.error("Plugin executable not found: %s", exe_path)
            return False

        try:
            # Start the plugin process
            process = subprocess.Popen(
                [str(exe_path)],
                cwd=str(plugin_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            self.running_plugins[plugin_name] = process
            logger.info("Started plugin: %s (PID: %s)", plugin_name, process.pid)

            # Start a thread to monitor the plugin
            threading.Thread(
                target=self._monitor_plugin,
                args=(plugin_name, process),
                daemon=True
            ).start()

            return True

        except Exception as e:
            logger.error("Failed to start plugin %s: %s", plugin_name, e)
            return False

    def _monitor_plugin(self, plugin_name: str, process: subprocess.Popen):
        """Monitor a plugin process and handle its output."""
        try:
            while process.poll() is None:
                # Read stdout
                if process.stdout is not None:
                    line = process.stdout.readline()
                    if line:
                        logger.debug("Plugin %s output: %s", plugin_name, line.strip())

                time.sleep(0.1)

            # Process has terminated
            return_code = process.returncode
            logger.info("Plugin %s terminated with code: %s", plugin_name, return_code)

        except (OSError, ValueError) as e:
            logger.error("Error monitoring plugin %s: %s", plugin_name, e)
        finally:
            # Clean up
            if plugin_name in self.running_plugins:
                del self.running_plugins[plugin_name]

    def stop_plugin(self, plugin_name: str) -> bool:
        """Stop a running plugin."""
        if plugin_name not in self.running_plugins:
            logger.warning("Plugin %s is not running", plugin_name)
            return True

        process = self.running_plugins[plugin_name]
        try:
            process.terminate()
            process.wait(timeout=5)
            logger.info("Stopped plugin: %s", plugin_name)
            return True
        except subprocess.TimeoutExpired:
            logger.warning("Plugin %s did not terminate gracefully, killing...", plugin_name)
            process.kill()
            return True
        except Exception as e:
            logger.error("Error stopping plugin %s: %s", plugin_name, e)
            return False

    def invoke_plugin(self, plugin_name: str, function_name: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Invoke a function on a plugin."""
        if plugin_name not in self.running_plugins:
            logger.warning("Plugin %s is not running, attempting to start...", plugin_name)
            if not self.start_plugin(plugin_name):
                return None

        manifest = self.plugin_manifests.get(plugin_name)
        if not manifest:
            return None

        # Check if the function exists in the manifest
        functions = manifest.get('functions', [])
        function_info = None
        for func in functions:
            if func.get('name') == function_name:
                function_info = func
                break

        if not function_info:
            logger.error("Function %s not found in plugin %s", function_name, plugin_name)
            return None

        # Prepare the command
        command = {
            "tool_calls": [{
                "func": function_name,
                "properties": params or {}
            }]
        }

        # Send command to plugin
        process = self.running_plugins[plugin_name]
        if not process.stdin:
            logger.error("No stdin available for plugin %s", plugin_name)
            return None

        try:
            # Send the command
            command_json = json.dumps(command) + '\n'
            process.stdin.write(command_json)
            process.stdin.flush()
            logger.debug("Sent command to %s: %s", plugin_name, command_json.strip())

            # Read response (this is simplified - in practice you'd need proper async handling)
            if process.stdout is not None:
                response_line = process.stdout.readline().strip()
                if response_line:
                    response = json.loads(response_line)
                    logger.debug("Received response from %s: %s", plugin_name, response)
                    return response
                else:
                    logger.warning("No response received from plugin %s", plugin_name)
                    return None
            else:
                logger.error("No stdout available for plugin %s", plugin_name)
                return None

        except Exception as e:
            logger.error("Error communicating with plugin %s: %s", plugin_name, e)
            return None

    def get_plugin_info(self, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Get information about a plugin."""
        manifest = self.plugin_manifests.get(plugin_name)
        if not manifest:
            manifest = self.load_plugin_manifest(plugin_name)

        if not manifest:
            return None

        return {
            'name': plugin_name,
            'description': manifest.get('description', ''),
            'functions': manifest.get('functions', []),
            'tags': manifest.get('tags', []),
            'persistent': manifest.get('persistent', False),
            'running': plugin_name in self.running_plugins
        }

    def list_plugins(self) -> List[dict]:
        """List all available plugins with their status."""
        plugin_names = self.discover_plugins()
        plugins_info = []

        for name in plugin_names:
            info = self.get_plugin_info(name)
            if info:
                plugins_info.append(info)

        return plugins_info

    def shutdown(self):
        """Shutdown all running plugins."""
        logger.info("Shutting down all plugins...")
        for plugin_name in self.running_plugins.keys():
            self.stop_plugin(plugin_name)
        logger.info("All plugins shut down")


class GPUManager:
    """Manages GPU information and monitoring."""

    def __init__(self):
        self.gpu_info = {}
        self._load_gpu_info()

    def _load_gpu_info(self):
        """Load basic GPU information."""
        # This would typically use NVAPI or similar to get GPU info
        # For now, we'll use placeholder information
        self.gpu_info = {
            'vendor': 'NVIDIA',
            'model': 'GeForce RTX 5090',
            'driver_version': '572.83',
            'memory_total': '32GB',
            'cuda_cores': 17408
        }

    def get_gpu_info(self) -> dict:
        """Get current GPU information."""
        return self.gpu_info

    def get_system_info(self) -> dict:
        """Get system information including GPU details."""
        return {
            'gpu': self.gpu_info,
            'os': sys.platform,
            'python_version': sys.version
        }


class GAssistCore:
    """Main G-Assist core system."""

    def __init__(self, plugins_dir: Optional[str] = None):
        self.plugin_manager = PluginManager(plugins_dir)
        self.gpu_manager = GPUManager()
        self.running = False
        self.command_handlers = {
            'list_plugins': self._handle_list_plugins,
            'start_plugin': self._handle_start_plugin,
            'stop_plugin': self._handle_stop_plugin,
            'invoke_plugin': self._handle_invoke_plugin,
            'get_gpu_info': self._handle_get_gpu_info,
            'shutdown': self._handle_shutdown
        }

        logger.info("G-Assist Core initialized")

    def start(self):
        """Start the G-Assist core system."""
        logger.info("Starting G-Assist Core...")
        self.running = True

        # Load persistent plugins
        self._load_persistent_plugins()

        logger.info("G-Assist Core started successfully")

    def stop(self):
        """Stop the G-Assist core system."""
        logger.info("Stopping G-Assist Core...")
        self.running = False
        self.plugin_manager.shutdown()
        logger.info("G-Assist Core stopped")

    def _load_persistent_plugins(self):
        """Load all plugins marked as persistent."""
        plugins = self.plugin_manager.list_plugins()
        for plugin in plugins:
            if plugin.get('persistent', False):
                logger.info("Starting persistent plugin: %s", plugin['name'])
                self.plugin_manager.start_plugin(plugin['name'])

    def process_command(self, command: str, params: Optional[Dict[str, Any]] = None) -> dict:
        """Process a command and return the result."""
        if command in self.command_handlers:
            return self.command_handlers[command](params or {})
        else:
            return self._handle_unknown_command(command, params or {})

    def _handle_list_plugins(self, params: dict) -> dict:
        """Handle list_plugins command."""
        plugins = self.plugin_manager.list_plugins()
        return {
            'success': True,
            'plugins': plugins
        }

    def _handle_start_plugin(self, params: dict) -> dict:
        """Handle start_plugin command."""
        plugin_name = params.get('plugin_name')
        if not plugin_name:
            return {
                'success': False,
                'error': 'plugin_name parameter required'
            }

        success = self.plugin_manager.start_plugin(plugin_name)
        return {
            'success': success,
            'plugin_name': plugin_name
        }

    def _handle_stop_plugin(self, params: dict) -> dict:
        """Handle stop_plugin command."""
        plugin_name = params.get('plugin_name')
        if not plugin_name:
            return {
                'success': False,
                'error': 'plugin_name parameter required'
            }

        success = self.plugin_manager.stop_plugin(plugin_name)
        return {
            'success': success,
            'plugin_name': plugin_name
        }

    def _handle_invoke_plugin(self, params: dict) -> dict:
        """Handle invoke_plugin command."""
        plugin_name = params.get('plugin_name')
        function_name = params.get('function_name')
        function_params = params.get('params', {})

        if not plugin_name or not function_name:
            return {
                'success': False,
                'error': 'plugin_name and function_name parameters required'
            }

        result = self.plugin_manager.invoke_plugin(plugin_name, function_name, function_params)
        if result is not None:
            return {
                'success': True,
                'result': result
            }
        else:
            return {
                'success': False,
                'error': 'Failed to invoke %s on plugin %s' % (function_name, plugin_name)
            }

    def _handle_get_gpu_info(self, params: dict) -> dict:
        """Handle get_gpu_info command."""
        gpu_info = self.gpu_manager.get_gpu_info()
        return {
            'success': True,
            'gpu_info': gpu_info
        }

    def _handle_shutdown(self, params: dict) -> dict:
        """Handle shutdown command."""
        self.stop()
        return {
            'success': True,
            'message': 'G-Assist Core shutting down'
        }

    def _handle_unknown_command(self, command: str, params: Optional[Dict[str, Any]]) -> dict:
        """Handle unknown commands."""
        return {
            'success': False,
            'error': 'Unknown command: %s' % command
        }


def main():
    """Main entry point for G-Assist Core."""
    parser = argparse.ArgumentParser(description='G-Assist Core System')
    parser.add_argument('--plugins-dir', help='Directory containing plugins')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       default='INFO', help='Logging level')
    parser.add_argument('--daemon', action='store_true',
                       help='Run as daemon/background process')

    args = parser.parse_args()

    # Set log level
    logging.getLogger().setLevel(getattr(logging, args.log_level))

    # Create core instance
    core = GAssistCore(args.plugins_dir)

    # Handle signals for graceful shutdown
    def signal_handler(signum, frame):
        logger.info("Received signal %s, shutting down...", signum)
        core.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Start the core system
        core.start()

        if args.daemon:
            # Run as daemon - keep running until signal received
            logger.info("Running as daemon...")
            while core.running:
                time.sleep(1)
        else:
            # Interactive mode - simple command loop
            print("G-Assist Core started. Type 'help' for commands, 'quit' to exit.")

            while core.running:
                try:
                    command_line = input("G-Assist> ").strip()
                    if not command_line:
                        continue

                    if command_line.lower() in ['quit', 'exit', 'q']:
                        break

                    if command_line.lower() == 'help':
                        print("Available commands:")
                        print("  list_plugins - List all available plugins")
                        print("  start_plugin <name> - Start a plugin")
                        print("  stop_plugin <name> - Stop a plugin")
                        print("  invoke_plugin <plugin> <function> - Invoke a plugin function")
                        print("  get_gpu_info - Get GPU information")
                        print("  help - Show this help")
                        print("  quit - Exit")
                        continue

                    # Parse command
                    parts = command_line.split()
                    command = parts[0]
                    params = {}

                    if command == 'start_plugin' and len(parts) > 1:
                        params = {'plugin_name': parts[1]}
                    elif command == 'stop_plugin' and len(parts) > 1:
                        params = {'plugin_name': parts[1]}
                    elif command == 'invoke_plugin' and len(parts) > 2:
                        params = {
                            'plugin_name': parts[1],
                            'function_name': parts[2]
                        }

                    # Process command
                    result = core.process_command(command, params)

                    if result['success']:
                        if 'plugins' in result:
                            print("Available plugins:")
                            for plugin in result['plugins']:
                                status = "RUNNING" if plugin['running'] else "STOPPED"
                                print(f"  {plugin['name']} - {plugin['description']} [{status}]")
                        elif 'gpu_info' in result:
                            gpu_info = result['gpu_info']
                            print("GPU Information:")
                            for key, value in gpu_info.items():
                                print(f"  {key}: {value}")
                        elif 'result' in result:
                            print(f"Result: {result['result']}")
                        else:
                            print("Command executed successfully")
                    else:
                        print(f"Error: {result.get('error', 'Unknown error')}")

                except KeyboardInterrupt:
                    break
                except Exception as e:
                    logger.error("Error processing command: %s", e)
                    print("Error: %s", e)

    except Exception as e:
        logger.error("Error in main: %s", e)
        print("Error: %s", e)
    finally:
        core.stop()


if __name__ == '__main__':
    main()
