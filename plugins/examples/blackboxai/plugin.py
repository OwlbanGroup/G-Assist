# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

''' Blackbox AI G-Assist plugin. '''
import copy
import ctypes
import json
import logging
import os

from ctypes import byref, windll, wintypes, GetLastError, create_string_buffer
import re
import traceback
from typing import Optional

# Data Types
Response = dict[str, bool | Optional[str]]

# Get the directory where the script is running from
API_KEY_FILE = os.path.join(f'{os.environ.get("PROGRAMDATA", ".")}{r'\NVIDIA Corporation\nvtopps\rise\plugins\blackboxai'}', 'blackboxai.key')
CONFIG_FILE = os.path.join(f'{os.environ.get("PROGRAMDATA", ".")}{r'\NVIDIA Corporation\nvtopps\rise\plugins\blackboxai'}', 'config.json')

LOG_FILE = os.path.join(os.environ.get("USERPROFILE", "."), 'blackboxai.log')
logging.basicConfig(filename=LOG_FILE, level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

API_KEY = None
client = None
model: str = 'blackboxai'  # Default model

def main():
    ''' Main entry point.

    Sits in a loop listening to a pipe, waiting for commands to be issued. After
    receiving the command, it is processed and the result returned. The loop
    continues until the "shutdown" command is issued.

    Returns:
        0 if no errors occurred during execution; non-zero if an error occurred
    '''
    TOOL_CALLS_PROPERTY = 'tool_calls'
    CONTEXT_PROPERTY = 'messages'
    SYSTEM_INFO_PROPERTY = 'system_info'
    FUNCTION_PROPERTY = 'func'
    PARAMS_PROPERTY = 'properties'
    INITIALIZE_COMMAND = 'initialize'
    SHUTDOWN_COMMAND = 'shutdown'

    ERROR_MESSAGE = 'Could not process request.'

    # Generate command handler mapping
    commands = {
        "initialize": execute_initialize_command,
        "shutdown": execute_shutdown_command,
        "query_blackboxai": execute_query_blackboxai_command,
    }
    cmd = ''

    logging.info('Blackbox AI plugin started.')
    while True:
        response = None
        input = read_command()
        if input is None:
            logging.error('Error reading command')
            continue

        if TOOL_CALLS_PROPERTY in input:
            tool_calls = input[TOOL_CALLS_PROPERTY]
            for tool_call in tool_calls:
                if FUNCTION_PROPERTY in tool_call:
                    cmd = tool_call[FUNCTION_PROPERTY]
                    if cmd in commands:
                        if(cmd == INITIALIZE_COMMAND or cmd == SHUTDOWN_COMMAND):
                            response = commands[cmd]()
                        else:
                            response = commands[cmd](
                                input[PARAMS_PROPERTY] if PARAMS_PROPERTY in input else None,
                                input[CONTEXT_PROPERTY] if CONTEXT_PROPERTY in input else None,
                                input[SYSTEM_INFO_PROPERTY] if SYSTEM_INFO_PROPERTY in input else None
                            )
                    else:
                        logging.warning(f'Unknown command: {cmd}')
                        response = generate_failure_response(f'{ERROR_MESSAGE} Unknown command: {cmd}')
                else:
                    logging.warning('Malformed input.')
                    response = generate_failure_response(f'{ERROR_MESSAGE} Malformed input.')
        else:
            logging.warning('Malformed input.')
            response = generate_failure_response(f'{ERROR_MESSAGE} Malformed input.')

        logging.info(f'Response: {response}')
        write_response(response)

        if cmd == SHUTDOWN_COMMAND:
            break

    logging.info('Blackbox AI plugin stopped.')
    return 0

def remove_unicode(s: str) -> str:
    '''Remove non-ASCII characters from a string.

    First decodes escape sequences into Unicode characters, then filters out non-ASCII characters.

    Args:
        s: Input string to process

    Returns:
        String with only ASCII characters
    '''
    try:
        s_decoded = s.encode('utf-8').decode('unicode_escape')
    except Exception:
        s_decoded = s

    ascii_only = ''.join(c for c in s_decoded if ord(c) < 128)
    return ascii_only

def read_command() -> dict | None:
    ''' Reads a command from the communication pipe.

    Reads data in chunks until the full message is received, then processes it as JSON.
    Handles Unicode escapes and ensures the text is printable.

    Returns:
        Command details if the input was proper JSON; `None` otherwise
    '''
    try:
        STD_INPUT_HANDLE = -10
        pipe = windll.kernel32.GetStdHandle(STD_INPUT_HANDLE)

        chunks = []
        while True:
            BUFFER_SIZE = 4096
            message_bytes = wintypes.DWORD()
            buffer = bytes(BUFFER_SIZE)
            success = windll.kernel32.ReadFile(
                pipe,
                buffer,
                BUFFER_SIZE,
                byref(message_bytes),
                None
            )

            if not success:
                logging.error('Error reading from command pipe')
                return None

            chunk = buffer.decode('utf-8')[:message_bytes.value]
            chunks.append(chunk)

            if message_bytes.value < BUFFER_SIZE:
                break

        retval = ''.join(chunks)
        logging.info(f'Raw Input: {retval}')
        clean_text = retval.encode('utf-8').decode('raw_unicode_escape')
        clean_text = ''.join(ch for ch in clean_text if ch.isprintable() or ch in ['\n', '\t', '\r'])
        return json.loads(clean_text)

    except json.JSONDecodeError:
        logging.error(f'Received invalid JSON: {clean_text}')
        logging.exception("JSON decoding failed:")
        return None
    except Exception as e:
        logging.error(f'Exception in read_command(): {str(e)}')
        return None


def write_response(response: Response) -> None:
    ''' Writes a response to the communication pipe.

    Converts the response to JSON and sends it through the pipe with an end marker.

    Args:
        response: Dictionary containing return value(s)
    '''
    try:
        STD_OUTPUT_HANDLE = -11
        pipe = windll.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)

        json_message = json.dumps(response) + '<<END>>'
        message_bytes = json_message.encode('utf-8')
        message_len = len(message_bytes)

        bytes_written = wintypes.DWORD()
        windll.kernel32.WriteFile(
            pipe,
            message_bytes,
            message_len,
            bytes_written,
            None
        )

    except Exception:
        logging.error('Unknown exception caught.')
        pass


def generate_failure_response(message: str = None) -> Response:
    ''' Generates a response indicating failure.

    Args:
        message: String to be returned in the response (optional)

    Returns:
        A failure response with the attached message
    '''
    response = { 'success': False }
    if message:
        response['message'] = message
    return response


def generate_success_response(message: str = None) -> Response:
    ''' Generates a response indicating success.

    Args:
        message: String to be returned in the response (optional)

    Returns:
        A success response with the attached message
    '''
    response = { 'success': True }
    if message:
        response['message'] = message
    return response


def generate_message_response(message:str):
    ''' Generates a message response.

    Args:
        message: String to be returned to the driver

    Returns:
        A message response dictionary
    '''
    return { 'message': message }


def execute_initialize_command() -> dict:
    ''' Initialize the Blackbox AI API connection.

    Reads the API key from file and configures the Blackbox AI client.

    Returns:
        Success or failure response
    '''
    global API_KEY, API_KEY_FILE, client

    key = None
    if os.path.isfile(API_KEY_FILE):
        with open(API_KEY_FILE) as file:
            key = file.read().strip()

    if not key:
        logging.error('No API key found')
        return generate_success_response() # this allows us to print the error ##bug to be fixed in driver

    try:
        # Initialize Blackbox AI client (placeholder - replace with actual Blackbox AI SDK)
        # client = BlackboxAI(api_key=key)
        logging.info('Successfully configured Blackbox AI API')
        API_KEY = key
        return generate_success_response()
    except Exception as e:
        logging.error(f'Configuration failed: {str(e)}')
        API_KEY = None
        return generate_failure_response(str(e))

def execute_shutdown_command() -> dict:
    ''' Cleanup resources.

    Returns:
        Success response
    '''
    logging.info('Blackbox AI plugin shutdown')
    return generate_success_response()

def convert_oai_to_blackboxai_history(oai_history):
    """Convert OpenAI-style chat history to Blackbox AI-compatible format.

    Args:
        oai_history: OpenAI format history

    Returns:
        List of messages in Blackbox AI format
    """
    blackboxai_history = []
    for msg in oai_history:
        role = "assistant" if msg["role"] == "assistant" else "user"
        blackboxai_history.append({
            "role": role,
            "content": msg["content"]
        })
    return blackboxai_history

def execute_query_blackboxai_command(params: dict = None, context: dict = None, system_info: str = None) -> dict:
    ''' Handle Blackbox AI query with conversation history.

    Processes the query by routing to Blackbox AI for response generation.
    Handles streaming responses back to the client.

    Args:
        params: Additional parameters for the query
        context: Conversation history
        system_info: System information including game data

    Returns:
        Success or failure response
    '''
    global API_KEY, CONFIG_FILE, model, client

    if API_KEY is None:
        ERROR_MESSAGE = (
            "It looks like your API key is missing or invalid. Please update " +
            f"{API_KEY_FILE} with a valid key and restart G-Assist.\n\n" +
            "To obtain an API key, visit https://www.blackbox.ai."
        )
        write_response(generate_message_response(ERROR_MESSAGE))
        return generate_success_response() #print nothing, the initialize will have done so ## bug to be fixed in driver

    # Load model config
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as file:
            config = json.load(file)
            model = config.get('model', model)

    try:
        logging.info("BLACKBOXAI_HANDLER: Starting request processing")

        # Validate that context exists
        if not context or len(context) == 0:
            logging.error("BLACKBOXAI_HANDLER: No context provided")
            return generate_failure_response("No context provided")

        # Store the incoming prompt
        prompt = context[-1]["content"] if context else ""
        logging.info(f"BLACKBOXAI_HANDLER: Received prompt: {prompt[:50]}...")

        # Preserve the original context
        incoming_context = copy.deepcopy(context)
        logging.info(f"BLACKBOXAI_HANDLER: Context length: {len(context)}")

        # Augment the prompt with system information
        aug_prompt = f"You are a helpful AI assistant powered by Blackbox AI within the Nvidia G-Assist ecosystem. Keep your responses concise and within 100 words if possible. If a user is inquiring about games and Nvidia GPUs, keep in mind the list of games installed on the user PC including the current playing game as: {system_info}. {incoming_context[-1]['content']}"
        logging.info("BLACKBOXAI_HANDLER: Augmented prompt with system information")

        # Convert OpenAI-style context to Blackbox AI format
        blackboxai_history = convert_oai_to_blackboxai_history(context[:-1])
        logging.info(f"BLACKBOXAI_HANDLER: Converted to Blackbox AI format: {len(blackboxai_history)} messages")

        # Initialize Blackbox AI chat session
        try:
            # Placeholder for Blackbox AI API call
            # response = client.chat.completions.create(
            #     model=model,
            #     messages=blackboxai_history + [{"role": "user", "content": aug_prompt}],
            #     stream=True
            # )

            # Simulate streaming response (replace with actual Blackbox AI API)
            simulated_response = f"Blackbox AI response to: {prompt[:50]}..."
            logging.info("BLACKBOXAI_HANDLER: Streaming simulated response")

            # Stream the response in chunks
            for i in range(0, len(simulated_response), 50):
                chunk = simulated_response[i:i+50]
                write_response(generate_message_response(chunk))
                logging.info(f'BLACKBOXAI_HANDLER: Response chunk: {chunk[:30]}...')

            logging.info("BLACKBOXAI_HANDLER: Response completed successfully")
            return generate_success_response()

        except Exception as api_error:
            logging.error(f'BLACKBOXAI_HANDLER: API error: {str(api_error)}')
            return generate_failure_response(f'API error: {str(api_error)}')

    except Exception as e:
        # Catch and log any other exceptions that occur
        logging.error(f'BLACKBOXAI_HANDLER: General error: {str(e)}')
        logging.error(f'BLACKBOXAI_HANDLER: Stack trace: {traceback.format_exc()}')
        return generate_failure_response(f'General error: {str(e)}')

if __name__ == '__main__':
    main()
