# Blackbox AI Plugin for G-Assist

Transform your G-Assist experience with the power of Blackbox AI! This plugin integrates Blackbox AI's advanced AI capabilities directly into G-Assist, providing intelligent responses, coding assistance, and comprehensive AI interactions.

## What Can It Do?

- Generate intelligent text responses using Blackbox AI
- Provide coding assistance and programming help
- Hold context-aware conversations that remember previous interactions
- Real-time streaming responses
- Seamless integration with G-Assist

## Before You Start

Make sure you have:

- Python 3.8 or higher
- Blackbox AI API key
- G-Assist installed on your system

💡 **Tip**: You'll need a Blackbox AI API key. Get one from [Blackbox AI](https://www.blackbox.ai)!

## Installation Guide

### Step 1: Get the Files

```bash
git clone <repo link>
cd blackboxai-plugin
```

### Step 2: Set Up Python Packages

```bash
python -m pip install -r requirements.txt
```

### Step 3: Configure Your API Key

1. Create a file named `blackboxai.key` in the root directory
2. Add your API key to the file:

```blackboxai.key
your_api_key_here
```

### Step 4: Configure the Model (Optional)

Adjust `config.json` to your needs:

```json
{
  "model": "blackboxai"
}
```

### Step 5: Build the Plugin

```bash
build.bat
```

This will create a `dist\blackboxai` folder containing all the required files for the plugin.

### Step 6: Install the Plugin

1. Create a new folder here (if it doesn't exist):

   ```
   %PROGRAMDATA%\NVIDIA Corporation\nvtopps\rise\plugins\blackboxai
   ```

   💡 **Tip**: Copy and paste this path into File Explorer's address bar!

2. Copy these files to the folder you just created:
   - `g-assist-plugin-blackboxai.exe` (from the `dist` folder)
   - `manifest.json`
   - `config.json`
   - `blackboxai.key`

## How to Use

Once installed, you can use Blackbox AI through G-Assist! Try these examples:

### Basic AI Queries

- Hey Blackbox, explain quantum computing in simple terms.
- /blackboxai Write a Python function to calculate fibonacci numbers.

### Coding Assistance

- Hey Blackbox, help me debug this JavaScript error.
- /blackboxai Generate a React component for a todo list.

### General Questions

- Hey Blackbox, what's the weather like today?
- /blackboxai Tell me about the latest developments in AI.

## Limitations

- Requires active internet connection
- Subject to Blackbox AI's API rate limits
- Must be used within G-Assist environment

### Logging

The plugin logs all activity to:

```
%USERPROFILE%\blackboxai.log
```

Check this file for detailed error messages and debugging information.

## Troubleshooting Tips

- **API Key Not Working?** Verify your API key is correctly copied to `blackboxai.key`
- **Commands Not Working?** Ensure all files are in the correct plugin directory
- **Unexpected Responses?** Check the configuration in `config.json`
- **Logs**: Check `%USERPROFILE%\blackboxai.log` for detailed logs

## Developer Documentation

### Architecture Overview

The Blackbox AI plugin is implemented as a Python-based service that communicates with G-Assist through a pipe-based protocol. The plugin provides AI-powered responses for various types of queries including general knowledge, coding assistance, and conversational AI.

### Core Components

#### Communication Protocol

- Uses Windows named pipes for IPC (Inter-Process Communication)
- Commands are sent as JSON messages with the following structure:

  ```json
  {
    "tool_calls": [{
      "func": "command_name",
      "properties": {},
      "messages": [],
      "system_info": ""
    }]
  }
  ```

- Responses are returned as JSON with success/failure status and optional messages

#### Key Functions

##### Main Entry Point (`main()`)

- Initializes the plugin and enters command processing loop
- Handles command routing and response generation
- Supports commands: `initialize`, `shutdown`, `query_blackboxai`

##### Query Processing (`execute_query_blackboxai_command()`)

- Processes incoming queries through Blackbox AI
- Handles streaming responses back to the client
- Parameters:
  - `params`: Additional query parameters
  - `context`: Conversation history
  - `system_info`: System information including game data

### Configuration

#### API Key

- Stored in `blackboxai.key` file
- Location: `%PROGRAMDATA%\NVIDIA Corporation\nvtopps\rise\plugins\blackboxai\blackboxai.key`

#### Model Configuration

- Configured via `config.json`
- Default model: `blackboxai`
- Location: `%PROGRAMDATA%\NVIDIA Corporation\nvtopps\rise\plugins\blackboxai\config.json`

### Logging

- Log file location: `%USERPROFILE%\blackboxai.log`
- Log level: INFO
- Format: `%(asctime)s - %(levelname)s - %(message)s`

### Error Handling

- Comprehensive error handling for API calls
- Detailed error logging with stack traces
- User-friendly error messages

### Message Format Conversion

The plugin handles conversion between different message formats:

- OpenAI-style chat history to Blackbox AI format
- Handles role mapping and conversation context

## Want to Contribute?

We'd love your help making this plugin even better! Check out [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to contribute.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
