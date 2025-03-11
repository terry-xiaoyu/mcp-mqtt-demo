import os
import time
import mcp_over_mqtt as mcp
from openai import OpenAI
from datetime import datetime
import json

CLIENT_NAME = "exmaple_mcp_client"
VERSION = "0.1.0"

client = OpenAI(
    api_key = os.getenv("DASHSCOPE_API_KEY"),
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

def simple_call_tools():
    arguments = {
        "host": "localhost",
        "port": 9900,
        "username": os.getenv("SSH_USERNAME", "user"),
        "password": os.getenv("SSH_PASSWORD", "password"),
        "command": "ls -l"
    }
    return mcp.send_tools_call_rpc("ssh_tool", "ssh_execute_command", arguments)

def call_tools(server_name, function_name, arguments):
    return mcp.send_tools_call_rpc(server_name, function_name, arguments)

def query_llm_chat_completion(messages):
    # https://help.aliyun.com/zh/model-studio/getting-started/models
    model_name = "qwen-max-latest"
    tools = mcp.get_avaliable_tools_open_ai()
    if len(tools) == 0:
        print("--------No tools are available. Calling the model without tools")
        completion = client.chat.completions.create(
            model=model_name,
            messages=messages
            )
    else:
        print(f"--------Calling the model with tools. The available tools: {tools}")
        completion = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=tools
            )
    return completion.model_dump()

def call_with_messages():
    print('\n')
    messages = [
        {
            "content": input('please input:'),
            "role": "user"
        }
    ]
    print("-"*60)

    i = 1
    first_response = query_llm_chat_completion(messages)
    assistant_output = first_response['choices'][0]['message']
    print(f"\n The first LLM output: {first_response}\n")
    if assistant_output['content'] is None:
        assistant_output['content'] = ""
    messages.append(assistant_output)

    # reply the user if no need to call tools
    if assistant_output['tool_calls'] == None:
        print(f"No tools call is needed. Anwser: {assistant_output['content']}")
        return

    while assistant_output['tool_calls'] != None:
        tool_name = assistant_output['tool_calls'][0]['function']['name']
        arguments = assistant_output['tool_calls'][0]['function']['arguments']
        tool_call_id = assistant_output['tool_calls'][0]['id']
        server_name, function_name = parse_tool_name(tool_name)
        is_ok, tool_result = call_tools(server_name, function_name, maybe_decode_json(arguments))
        if is_ok == "error":
            print(f"The tool replied an error: {tool_result}")
            break

        print(f"The output of tools: {tool_result}\n")
        tool_info = {
            "name": tool_name,
            "role":"tool",
            "tool_call_id": tool_call_id,
            "content": maybe_encode_json(tool_result)
            }
        print("-"*60)
        messages.append(tool_info)

        ## call the model again
        assistant_output = query_llm_chat_completion(messages)['choices'][0]['message']
        if assistant_output['content'] is None:
            assistant_output['content'] = ""
        messages.append(assistant_output)
        i += 1
        print(f"The {i}st output of the LLM: {assistant_output}\n")

    print(f"The final anwser: {assistant_output['content']}")

def maybe_decode_json(arguments):
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except:
            return arguments
    return arguments

def maybe_encode_json(arguments):
    if isinstance(arguments, dict):
        return json.dumps(arguments)
    return arguments

def parse_tool_name(tool_name):
    words = tool_name.split(":")
    if len(words) == 2:
        return words[0], words[1]
    else:
        raise ValueError(f"Invalid tool name: {tool_name}")

if __name__ == "__main__":
    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "1883"))
    username = os.getenv("MQTT_USERNAME", "user")
    password = os.getenv("MQTT_PASSWORD", "password")
    mcp.run_mcp_client(CLIENT_NAME, VERSION, host=host, port=port, username=username, password=password)
    time.sleep(2)
    while True:
        call_with_messages()
        pass
