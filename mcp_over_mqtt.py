import base64
import copy
import json
import random
import time
import threading
import sys
import asyncio
import paho.mqtt.client as mqtt
from paho.mqtt.enums import MQTTErrorCode, MQTTProtocolVersion
from enum import Enum

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
PROTOCOL_VERSION = "0.1.0"

METHOD_INIT = "initialize"
METHOD_FUNC_CALL = "tools/call"

class ErrorCode(Enum):
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

global_client_capabilities = {}
global_server_capabilities = {}
global_client_info = {}
global_server_info = {}

global_mqtt_clients = []

server_tool_callbacks = {}

################ TODO
# 1. Client also sends ping message to server, and server sends initialize message to client
# 2. Notify the client when server disconnects

################################################################################
## APIs
################################################################################
def run_mcp_server(server_name, version, num_workers = 4, ping_interval=30,
                   host="localhost", port=1883, username=None, password=None,
                   capabilities=[], tool_callbacks=[]):
    global global_server_capabilities
    global global_server_info
    global server_tool_callbacks
    connect("server", server_name, num_workers, ping_interval, host, port, username, password)
    global_server_capabilities[server_name] = capabilities
    global_server_info[server_name] = {"name": server_name, "version": version}
    server_tool_callbacks = tool_callbacks
    send_ping_message(pick_mqtt_client_randomly())
    start_ping_timer(ping_interval)

def run_mcp_client(client_name, version, num_workers = 1, ping_interval=30,
                   host="localhost", port=1883, username=None, password=None,
                   capabilities=[]):
    global global_client_capabilities
    global global_client_info
    connect("client", client_name, num_workers, ping_interval, host, port, username, password)
    global_client_capabilities[client_name] = capabilities
    global_client_info[client_name] = {"name": client_name, "version": version}
    send_ping_message(pick_mqtt_client_randomly())

def send_tools_call_rpc(server_name, tool_name, arguments):
    client = pick_mqtt_client_randomly()
    userdata = client.user_data_get()
    c_clientid = get_client_clientid(userdata)
    topic = server_rpc_topic(server_name, c_clientid)
    log_debug(f"Sending function call RPC as {c_clientid}, to {topic}")
    tools_call_params = {"name": tool_name, "arguments": arguments}
    return asyncio.run(send_mqtt_json_rpc_and_wait_reply(client, topic, METHOD_FUNC_CALL, tools_call_params))

def get_avaliable_tools_open_ai():
    ## Return tools from all the available server_names in the form of OpenAI
    ## the global_server_capabilities is of the form {server_name: capabilities}
    ## where the capabilities contains a list of tools in the form of {"tools": [tool1, tool2, ...]}
    ## where tool1, tool2, ... are of the form {"name": "tool_name", "description": "tool_description", "parameters": {...}}
    ## We need to convert it to [{"type": "function", "function": {"name": "server_name:tool_name", "description": "tool_description", "parameters": {...}}}]
    ## Note that we also change the the "name" to "server_name:tool_name"
    tools = []
    for server_name, capabilities in global_server_capabilities.items():
        for tool in capabilities.get("tools", []):
            toolc = copy.deepcopy(tool)
            toolc["name"] = f"{server_name}:{toolc['name']}"
            tools.append({"type": "function", "function": toolc})
    return tools

def connect(mcp_role, name, num_workers, ping_interval=30,
            host="localhost", port=1883, username=None, password=None):
    if mcp_role != "server" and mcp_role != "client":
        raise ValueError("Invalid MCP role")
    if num_workers < 1:
        raise ValueError("Invalid number of workers")
    if ping_interval < 1:
        raise ValueError("Invalid ping interval")

    for worker_id in range(num_workers):
        if mcp_role == "client":
            clientid = mk_client_clientid(name, worker_id)
        elif mcp_role == "server":
            clientid = mk_server_clientid(name, worker_id)
        userdata = {"mcp_role": mcp_role, "name": name, "worker_id": worker_id,
                    "num_workers": num_workers, "ping_interval": ping_interval}
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id = clientid,
                             userdata = userdata, protocol = MQTTProtocolVersion.MQTTv5)
        client.username_pw_set(username, password)
        client.on_message = on_message
        client.on_connect = on_connect
        res = client.connect(host = MQTT_BROKER, port = MQTT_PORT,
                             keepalive = ping_interval)
        if res != MQTTErrorCode.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"Failed to connect to MQTT Broker: {res}")
        log_debug(f"Connected to MQTT Broker, clientid: {clientid}")
        global_mqtt_clients.append(client)
        client.loop_start()

################################################################################
## Message and Topic definitions
################################################################################
def json_rpc_msg(method, params, request_id):
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": request_id
    }

def json_rpc_result_msg(result, request_id):
    return {
        "jsonrpc": "2.0",
        "result": result,
        "id": request_id
    }

def json_rpc_error_msg(error, request_id):
    return {
        "jsonrpc": "2.0",
        "error": error,
        "id": request_id
    }

def json_notification_msg(method, params):
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params
    }

def server_rpc_topic_filter(server_name, suffix=None):
    if suffix is None:
        return f"$share/g/$mcp/server_rpc/{server_name}"
    return f"$share/g/$mcp/server_rpc/{server_name}/{suffix}"

def server_rpc_topic(server_name, suffix=None):
    if suffix is None:
        return f"$mcp/server_rpc/{server_name}"
    return f"$mcp/server_rpc/{server_name}/{suffix}"

def server_capability_topic_filter(server_name, capability):
    return f"$mcp/server/{server_name}/capability/{capability}"

def server_ping_topic(server_name):
    return f"$mcp/server/{server_name}/ping"

def client_rpc_topic_filter(client_name, suffix=None):
    if suffix is None:
        return f"$share/g/$mcp/client_rpc/{client_name}"
    return f"$share/g/$mcp/client_rpc/{client_name}/{suffix}"

def client_rpc_topic(client_name, suffix=None):
    if suffix is None:
        return f"$mcp/client_rpc/{client_name}"
    return f"$mcp/client_rpc/{client_name}/{suffix}"

def client_capability_topic_filter(client_name, capability):
    return f"$mcp/client/{client_name}/capability/{capability}"

def client_ping_topic(client_name):
    return f"$mcp/client/{client_name}/ping"

def mk_server_clientid(server_name, worker_id):
    return f"$mcp/server/{server_name}/{worker_id}"

def mk_client_clientid(client_name, worker_id):
    return f"$mcp/client/{client_name}/{worker_id}"

################################################################################
## MCP Helper Functions
################################################################################
def get_client_name_from_rpc_topic(topic_words):
    # The topic is: $mcp/server_rpc/<server_name>/<clientid_of_mcp_client>
    #  where <clientid_of_mcp_client> is $mcp/client/<client_name>/<worker_id>
    try:
        return topic_words[5]
    except IndexError:
        log_debug(f"get client name failed, invalid topic: {topic_words}")
        raise

def get_server_name_from_rpc_topic(topic_words):
    ## The topic should be $mcp/client_rpc/<client_name>/$mcp/server/<server_name>/<worker_id>
    try:
        return topic_words[5]
    except IndexError:
        log_debug(f"get server name failed, invalid topic: {topic_words}")
        raise

def get_server_clientid(userdata):
    server_name = userdata["name"]
    server_worker_id = userdata["worker_id"]
    return mk_server_clientid(server_name, server_worker_id)

def get_client_clientid(userdata):
    client_name = userdata["name"]
    client_worker_id = userdata["worker_id"]
    return mk_client_clientid(client_name, client_worker_id)

def set_pending_request(client, request_id, pending_data):
    userdata = client.user_data_get()
    userdata.setdefault("pending_requests", {})[request_id] = pending_data
    userdata["next_request_id"] = request_id + 1
    client.user_data_set(userdata)

def remove_pending_request(client, request_id):
    userdata = client.user_data_get()
    pending_requests = userdata.get("pending_requests", {})
    if request_id in pending_requests:
        del pending_requests[request_id]
        client.user_data_set(userdata)

def get_next_request_id(client):
    userdata = client.user_data_get()
    return userdata.get("next_request_id", 1)

async def send_mqtt_json_rpc_and_wait_reply(client, topic, method, params, timeout=30):
    loop = maybe_create_event_loop()
    future = loop.create_future()
    request_id = get_next_request_id(client)
    json_rpc_message = json_rpc_msg(method, params, request_id)
    payload = json.dumps(json_rpc_message)
    client.publish(topic, payload)
    pending_data = {"message": json_rpc_message, "future": future}
    set_pending_request(client, request_id, pending_data)
    log_debug(f"Sent: {payload}")
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except asyncio.TimeoutError:
        log_debug(f"RPC timeout waiting for response")
        return ("error", "Tool not responding within {timeout} seconds...")

def send_mqtt_json_rpc(client, topic, method, params):
    request_id = get_next_request_id(client)
    json_rpc_message = json_rpc_msg(method, params, request_id)
    payload = json.dumps(json_rpc_message)
    client.publish(topic, payload)
    pending_data = {"message": json_rpc_message, "future": None}
    set_pending_request(client, request_id, pending_data)
    log_debug(f"Sent: {payload}")

def send_mqtt_json_rpc_response(client, topic, result_or_error, request_id):
    if result_or_error[0] == "ok":
        json_rpc_message = json_rpc_result_msg(result_or_error[1], request_id)
    else:
        json_rpc_message = json_rpc_error_msg(result_or_error[1], request_id)
    payload = json.dumps(json_rpc_message)
    client.publish(topic, payload)
    log_debug(f"Sent: {payload}")

def handle_rpc_message_as_server(client, msg, topic_words, userdata):
    client_name = get_client_name_from_rpc_topic(topic_words)    
    data = json.loads(msg.payload)
    if "method" in data:
        method = data["method"]
        if method == METHOD_INIT:
            handle_initialize_rpc(client, client_name, userdata, data["id"],
                                  data["params"])
        elif method == METHOD_FUNC_CALL:
            handle_tools_call_rpc(client, client_name, userdata, data["id"],
                                  data["params"])
        else:
            log_debug(f"Unsupported method: {method}")
    else:
        log_debug("Invalid RPC message, method is missing")

def handle_initialize_rpc(client, client_name, userdata, request_id, params):
    server_name = userdata["name"]
    server_clientid = get_server_clientid(userdata)
    topic = client_rpc_topic(client_name, server_clientid)
    log_debug(f"Received initialize RPC message: {params}")
    if "protocolVersion" in params:
        protocol_version = params["protocolVersion"]
        if protocol_version != PROTOCOL_VERSION:
            error_info = {
                "code": ErrorCode.INVALID_PARAMS.value,
                "message": "protocolVersion is not supported",
                "data": {
                    "supported": [PROTOCOL_VERSION],
                    "requested": protocol_version
                }
            }
            send_mqtt_json_rpc_response(client, topic, ("error", error_info),
                                        request_id)
            return
        if "capabilities" in params:
            capabilities = params["capabilities"]
            ## store the capabilities of the client
            global_client_capabilities[client_name] = capabilities
            initialize_result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": global_server_capabilities[server_name],
                "serverInfo": global_server_info[server_name]
            }
            send_mqtt_json_rpc_response(client, topic, ("ok", initialize_result),
                                        request_id)
    else:
        error_info = {
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": "protocolVersion is required",
            "data": {
                "supported": [PROTOCOL_VERSION],
                "requested": None
            }
        }
        send_mqtt_json_rpc_response(client, topic, ("error", error_info), request_id)

def handle_tools_call_rpc(client, client_name, userdata, request_id, params):
    server_clientid = get_server_clientid(userdata)
    topic = client_rpc_topic(client_name, server_clientid)
    log_debug(f"Received tools/call RPC message: {params}")
    if "name" in params:
        func_name = (params["name"]).split(":")[-1]
        if func_name in server_tool_callbacks:
            func = server_tool_callbacks[func_name]
            if "arguments" in params:
                tool_args = maybe_decode_json(params["arguments"])
                log_debug(f"---Calling tool: {func_name} with args: {tool_args}")
                result = call_tools(func, **tool_args)
                send_mqtt_json_rpc_response(client, topic, result, request_id)
            else:
                error_info = {
                    "code": ErrorCode.INVALID_PARAMS.value,
                    "message": "arguments is required",
                    "data": {
                        "tool": func_name
                    }
                }
                send_mqtt_json_rpc_response(client, topic, ("error", error_info), request_id)
        else:
            error_info = {
                "code": ErrorCode.METHOD_NOT_FOUND.value,
                "message": "Tool not found",
                "data": {
                    "tool": func_name
                }
            }
            send_mqtt_json_rpc_response(client, topic, ("error", error_info), request_id)
    else:
        error_info = {
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": "Tool name is required",
            "data": {
                "tool": None
            }
        }
        send_mqtt_json_rpc_response(client, topic, ("error", error_info), request_id)

def handle_capability_message_as_server(client, msg, topic_words, userdata):
    log_debug(f"TODO: handle capability message: {msg.payload}")

def start_ping_timer(ping_interval):
    timer = threading.Timer(ping_interval, on_ping_timer)
    timer.start()

def send_initialize_rpc(server_name):
    client = pick_mqtt_client_randomly()
    userdata = client.user_data_get()
    c_clientid = get_client_clientid(userdata)
    topic = server_rpc_topic(server_name, c_clientid)
    log_debug(f"Sending initialize RPC as {c_clientid}, to {topic}")
    initialize_params = {"protocolVersion": PROTOCOL_VERSION,
                         "capabilities": global_client_capabilities,
                         "clientInfo": global_client_info
                         }
    send_mqtt_json_rpc(client, topic, METHOD_INIT, initialize_params)

def send_ping_message(client):
    ping_message = json_notification_msg("ping", {"timestamp": now_ms()})
    name = client.user_data_get()["name"]
    if client.user_data_get()["mcp_role"] == "server":
        topic = server_ping_topic(name)
    else:
        topic = client_ping_topic(name)
    client.publish(topic = topic, payload = json.dumps(ping_message), retain = True)

def pick_mqtt_client_randomly():
    num_workers = len(global_mqtt_clients)
    worker_id = random.randint(0, num_workers - 1)
    return global_mqtt_clients[worker_id]

def now_ms():
    return int(time.time() * 1000)

def call_tools(func, **kwargs):
    ## call the function and return error if it crashes
    try:
        result = func(**kwargs)
        return ("ok", {"content": format_result(result)})
    except Exception as e:
        log_debug(f"Tools call failed: {str(e)}")
        return ("ok", {"content": [error_result(str(e))], "isError": True})

def format_result(result):
    if isinstance(result, list):
        return [do_format_result(r) for r in result]
    else:
        return [do_format_result(result)]

def do_format_result(result):
    if isinstance(result, str):
        return text_result(result)
    elif isinstance(result, dict):
        return json_result(result)
    elif isinstance(result, tuple):
        res_type, result = result
        if res_type == "text":
            return text_result(result)
        elif res_type == "json":
            return json_result(result)
        elif res_type == "image":
            return image_result(result)
    else:
        return error_result(f"Invalid result type: {type(result)}")

def text_result(result):
    return {"type": "text", "text": result}

def json_result(result):
    return {"type": "text", "text": json.dumps(result)}

def image_result(result):
    ## base64 encode the image
    return {"type": "image", "data": base64.b64encode(result["data"]).decode(),
            "mimeType": result["mimeType"]}

def error_result(error_msg):
    return {"type": "text", "text": error_msg}

def maybe_create_event_loop():
    try:
        return asyncio.get_event_loop()
    except RuntimeError as e:
        if str(e).startswith('There is no current event loop in thread'):
            return asyncio.new_event_loop()
        else:
            raise

def maybe_decode_json(arguments):
    if isinstance(arguments, str):
        try:
            return json.loads(arguments)
        except:
            return arguments
    return arguments

################################################################################
## MQTT Callbacks
################################################################################
def on_ping_timer():
    client = pick_mqtt_client_randomly()
    userdata = client.user_data_get()
    send_ping_message(client)
    start_ping_timer(userdata["ping_interval"])

def on_message(client, userdata, msg):
    topic_words = msg.topic.split('/')
    if userdata["mcp_role"] == "server":
        handle_message_as_server(client, msg, topic_words, userdata)
    elif userdata["mcp_role"] == "client":
        handle_message_as_client(client, msg, topic_words, userdata)
    else:
        log_debug(f"Unknown MCP role: {userdata['mcp_role']}")

def on_connect(client, userdata, flags, reason_code, properties):
    log_debug(f"Connected with result code {reason_code}")
    if userdata["mcp_role"] == "server":
        server_name = userdata["name"]
        client.subscribe(server_rpc_topic_filter(server_name, "#"))
        client.subscribe(client_capability_topic_filter("+", "#"))
    elif userdata["mcp_role"] == "client":
        client_name = userdata["name"]
        client.subscribe(client_rpc_topic_filter(client_name, "#"))
        client.subscribe(server_capability_topic_filter("+", "#"))
        client.subscribe(server_ping_topic("+"))

def handle_message_as_server(client, msg, topic_words, userdata):
    ## Check if it is a RPC message or a client capability message
    ##  - Topic of RPC messages: $mcp/server_rpc/<server_name>/<clientid_of_mcp_client>
    ##  - Topic of client capability messages: $mcp/client/<client_name>/capability/<capability>
    if topic_words[0] != "$mcp":
        log_debug(f"Unknown topic {msg.topic}")
        return None
    if topic_words[1] == "server_rpc":
        handle_rpc_message_as_server(client, msg, topic_words, userdata)
    elif topic_words[1] == "client":
        handle_capability_message_as_server(client, msg, topic_words, userdata)
    else:
        log_debug(f"Unknown topic {msg.topic}")
        return None

def handle_message_as_client(client, msg, topic_words, userdata):
    ## Check the message type by the topic
    ##  - Topic of RPC messages: $mcp/client_rpc/<client_name>/<clientid_of_mcp_server>
    ##  - Topic of server capability messages: $mcp/server/<server_name>/capability/<capability>
    ##  - Topic of server ping messages: $mcp/server/<server_name>/ping
    if topic_words[0] != "$mcp":
        log_debug(f"Unknown topic {msg.topic}")
        return
    if topic_words[1] == "client_rpc":
        handle_rpc_message_as_client(client, msg, topic_words)
    elif topic_words[1] == "server":
        if topic_words[-1] == "ping":
            handle_ping_message_as_client(client, msg, topic_words)
        else:
            handle_capability_message_as_client(client, msg, topic_words)
    else:
        log_debug(f"Unknown topic {msg.topic}")
        return None

def handle_rpc_message_as_client(client, msg, topic_words):
    pending_requests = client.user_data_get().get("pending_requests", {})
    payload = json.loads(msg.payload)
    log_debug(f"Handling RPC message: {payload}")
    request_id = payload["id"]
    if request_id in pending_requests:
        pending_data = pending_requests[request_id]
        request = pending_data["message"]
        future = pending_data.get("future", None)
        method = request["method"]
        if method == METHOD_INIT:
            response = handle_initialize_rpc_response(client, payload, topic_words)
        elif method == METHOD_FUNC_CALL:
            response = ("ok", payload["result"])
        else:
            log_debug(f"Unknown method: {method}")
            response = ("error", f"Unknown method: {method}")

        ## set the result and remove the pending request
        if future is not None:
            future.set_result(response)
        remove_pending_request(client, request_id)
    else:
        log_debug(f"Unknown request id: {request_id}")

def handle_initialize_rpc_response(client, payload, topic_words):
    log_debug(f"Handling initialize response: {payload}")
    global global_server_capabilities
    global global_server_info
    server_name = get_server_name_from_rpc_topic(topic_words)
    global_server_capabilities[server_name] = payload["result"]["capabilities"]
    global_server_info[server_name] = payload["result"]["serverInfo"]
    return ("ok", "initialize response received")

def handle_ping_message_as_client(client, msg, topic_words):
    log_debug(f"Received ping message: {msg.payload}")
    server_name = topic_words[2]
    if global_server_capabilities.get(server_name) is None:
        payload = json.loads(msg.payload)
        timestamp = payload["params"]["timestamp"]
        ## check if the timestamp is within the last 30 seconds
        if now_ms() - timestamp <= 30000:
            send_initialize_rpc(server_name)

def handle_capability_message_as_client(client, msg, topic_words):
    log_debug(f"Received capability message: {msg.payload}")

################################################################################
## Helper Functions
################################################################################
def log_debug(msg):
    log("DEBUG", msg)

def log_info(msg):
    log("INFO", msg)

def log_error(msg):
    log("ERROR", msg)

def log(level, msg):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    level = "DEBUG"
    print(f"[{timestamp}] [MCP/MQTT] [{level}] - {msg}")

################################################################################
## Main
################################################################################    
if __name__ == "__main__":
    arg = sys.argv[1]
    if arg == "client":
        run_mcp_client("ssh_tool", "0.1.0")
    elif arg == "server":
        run_mcp_server("mcp_over_mqtt", "0.1.0")
    else:
        print(f"Invalid argument: {arg}")
        print("Usage: python mcp_over_mqtt.py client|server")
        sys.exit(1)

    while True:
        time.sleep(100)
        pass
