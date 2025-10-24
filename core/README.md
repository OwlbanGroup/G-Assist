# G-Assist Core

The core system for G-Assist, providing plugin management, GPU monitoring, and system integration.

## Features

- **Plugin Management**: Load, start, stop, and communicate with plugins
- **GPU Monitoring**: Access to NVIDIA GPU information and performance metrics
- **System Integration**: Windows pipe communication and process management
- **Command Processing**: Handle user commands and route them to appropriate plugins

## Installation

```bash
cd core
pip install -r requirements.txt
```

## Usage

### As a Library

```python
from core.g_assist_core import GAssistCore

# Initialize core
core = GAssistCore()

# Start the system
core.start()

# Process commands
result = core.process_command('list_plugins')
print(result)

# Shutdown
core.stop()
```

### As a Standalone Application

```bash
python core/g-assist-core.py --help
python core/g-assist-core.py  # Interactive mode
python core/g-assist-core.py --daemon  # Background mode
```

## Architecture

The G-Assist Core consists of several key components:

- **PluginManager**: Handles plugin discovery, loading, and communication
- **GPUManager**: Provides access to GPU information and monitoring
- **GAssistCore**: Main orchestration class that coordinates all components

## Plugin Development

Plugins communicate with the core via JSON messages over stdin/stdout pipes. Each plugin must have:

- `manifest.json`: Plugin configuration and function definitions
- Executable: The plugin binary or script
- Optional config files

See the [Blackbox AI plugin](../plugins/examples/blackboxai/) for a complete example.

## API Reference

### GAssistCore

#### Methods

- `start()`: Initialize and start the core system
- `stop()`: Shutdown the core system and all plugins
- `process_command(command, params)`: Process a command with optional parameters

#### Commands

- `list_plugins`: List all available plugins
- `start_plugin`: Start a specific plugin
- `stop_plugin`: Stop a specific plugin
- `invoke_plugin`: Call a function on a plugin
- `get_gpu_info`: Get GPU information
- `shutdown`: Shutdown the core system

## Configuration

The core system can be configured via command-line arguments:

- `--plugins-dir`: Directory containing plugins (default: system-dependent)
- `--log-level`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `--daemon`: Run as background process

## Logging

All activity is logged to `g-assist.log` with configurable log levels. Logs include:

- Plugin lifecycle events
- Command processing
- Error conditions
- GPU information updates

## Requirements

- Python 3.8+
- Windows (primary platform), Linux/macOS (experimental)
- NVIDIA GPU with appropriate drivers
- Access to plugin directory

## Troubleshooting

### Common Issues

1. **Plugin not found**: Check that plugins are in the correct directory and have valid manifests
2. **GPU info unavailable**: Ensure NVIDIA drivers are installed and accessible
3. **Communication errors**: Verify plugin executables are present and executable

### Debug Mode

Run with `--log-level DEBUG` for detailed logging information.

## Contributing

See the main [CONTRIBUTING.md](../CONTRIBUTING.md) for development guidelines.
