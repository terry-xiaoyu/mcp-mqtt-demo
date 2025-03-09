import json
import random
import time
import threading
import sys
import paho.mqtt.client as mqtt
from paho.mqtt.enums import MQTTErrorCode
from enum import Enum

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
PROTOCOL_VERSION = "0.1.0"

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

################################################################################
## APIs
################################################################################
def run_mcp_server(server_name, version, num_workers = 4, ping_interval=30,
                   host="localhost", port=1883, username=None, password=None):
    connect("server", server_name, num_workers, ping_interval, host, port, username, password)
    send_ping_message(pick_mqtt_client_randomly())
    start_ping_timer(ping_interval)

def run_mcp_client(client_name, version, num_workers = 1, ping_interval=30,
                   host="localhost", port=1883, username=None, password=None):
    connect("client", client_name, num_workers, ping_interval, host, port, username, password)

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
            clientid = client_clientid(name, worker_id)
        elif mcp_role == "server":
            clientid = server_clientid(name, worker_id)
        userdata = {"mcp_role": mcp_role, "name": name, "worker_id": worker_id,
                    "num_workers": num_workers, "ping_interval": ping_interval}
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id = clientid,
                             userdata = userdata)
        client.username_pw_set(username, password)
        client.on_message = on_message
        client.on_connect = on_connect
        res = client.connect(host = MQTT_BROKER, port = MQTT_PORT,
                             keepalive = ping_interval)
        if res != MQTTErrorCode.MQTT_ERR_SUCCESS:
            raise ConnectionError(f"Failed to connect to MQTT Broker: {res}")
        print(f"Connected to MQTT Broker, clientid: {clientid}")
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

def server_clientid(server_name, worker_id):
    return f"$mcp/server/{server_name}/{worker_id}"

def client_clientid(client_name, worker_id):
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
        print(f"get client name failed, invalid topic: {topic_words}")
        raise

def get_server_name_from_rpc_topic(topic_words):
    ## The topic should be $mcp/client_rpc/<client_name>/$mcp/server/<server_name>/<worker_id>
    try:
        return topic_words[5]
    except IndexError:
        print(f"get server name failed, invalid topic: {topic_words}")
        raise

def get_server_clientid(userdata):
    server_name = userdata["name"]
    server_worker_id = userdata["worker_id"]
    return server_clientid(server_name, server_worker_id)

def get_client_clientid(userdata):
    client_name = userdata["name"]
    client_worker_id = userdata["worker_id"]
    return client_clientid(client_name, client_worker_id)

def send_mqtt_json_rpc(client, topic, method, params, request_id):
    json_rpc_message = json_rpc_msg(method, params, request_id)
    payload = json.dumps(json_rpc_message)
    client.publish(topic, payload)
    print(f"Sent: {payload}")

def send_mqtt_json_rpc_response(client, topic, result_or_error, request_id):
    if result_or_error[0] == "ok":
        json_rpc_message = json_rpc_result_msg(result_or_error[1], request_id)
    else:
        json_rpc_message = json_rpc_error_msg(result_or_error[1], request_id)
    payload = json.dumps(json_rpc_message)
    client.publish(topic, payload)
    print(f"Sent: {payload}")

def handle_rpc_message_as_server(client, msg, topic_words, userdata):
    client_name = get_client_name_from_rpc_topic(topic_words)
    data = json.loads(msg.payload)
    if "method" in data:
        method = data["method"]
        if method == "initialize":
            s_clientid = get_server_clientid(userdata)
            handle_initialize_rpc(client, client_name, data["id"], data["params"], s_clientid)
        else:
            print(f"Unknown method: {method}")
    else:
        print("Invalid RPC message, method is missing")

def handle_initialize_rpc(client, client_name, request_id, params, server_clientid):
    topic = client_rpc_topic(client_name, server_clientid)
    print(f"Received initialize RPC message: {params}")
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
                "capabilities": global_server_capabilities,
                "serverInfo": global_server_info
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


def handle_capability_message_as_server(client, msg, topic_words, userdata):
    print(f"Received capability message: {msg.payload}")

def start_ping_timer(ping_interval):
    timer = threading.Timer(ping_interval, on_ping_timer)
    timer.start()

def send_initialize_rpc(server_name):
    client = pick_mqtt_client_randomly()
    userdata = client.user_data_get()
    c_clientid = get_client_clientid(userdata)
    topic = server_rpc_topic(server_name, c_clientid)
    print(f"Sending initialize RPC as {c_clientid}, to {topic}")
    initialize_params = {"protocolVersion": PROTOCOL_VERSION,
                         "capabilities": global_client_capabilities,
                         "clientInfo": global_client_info
                         }
    send_mqtt_json_rpc(client, topic, 
                       "initialize", initialize_params, 1)

def send_ping_message(client):
    ping_message = json_notification_msg("ping", {"timestamp": now_ms()})
    server_name = client.user_data_get()["name"]
    client.publish(topic = server_ping_topic(server_name), 
                   payload = json.dumps(ping_message), retain = True)

def pick_mqtt_client_randomly():
    num_workers = len(global_mqtt_clients)
    worker_id = random.randint(0, num_workers - 1)
    return global_mqtt_clients[worker_id]

def now_ms():
    return int(time.time() * 1000)

################################################################################
## MQTT Callbacks
################################################################################
def on_ping_timer():
    client = pick_mqtt_client_randomly()
    userdata = client.user_data_get()
    send_ping_message(client)
    start_ping_timer(userdata["ping_interval"])

def on_message(client, userdata, msg):
    print(f"Received: {msg.payload}")
    topic_words = msg.topic.split('/')
    if userdata["mcp_role"] == "server":
        handle_message_as_server(client, msg, topic_words, userdata)
    elif userdata["mcp_role"] == "client":
        handle_message_as_client(client, msg, topic_words, userdata)

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected with result code {reason_code}")
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
        print(f"Unknown topic {msg.topic}")
        return None
    if topic_words[1] == "server_rpc":
        handle_rpc_message_as_server(client, msg, topic_words, userdata)
    elif topic_words[1] == "client":
        handle_capability_message_as_server(client, msg, topic_words, userdata)
    else:
        print(f"Unknown topic {msg.topic}")
        return None

def handle_message_as_client(client, msg, topic_words, userdata):
    ## Check the message type by the topic
    ##  - Topic of RPC messages: $mcp/client_rpc/<client_name>/<clientid_of_mcp_server>
    ##  - Topic of server capability messages: $mcp/server/<server_name>/capability/<capability>
    ##  - Topic of server ping messages: $mcp/server/<server_name>/ping
    if topic_words[0] != "$mcp":
        print(f"Unknown topic {msg.topic}")
        return
    if topic_words[1] == "client_rpc":
        handle_rpc_message_as_client(client, msg, topic_words)
    elif topic_words[1] == "server":
        if topic_words[-1] == "ping":
            handle_ping_message_as_client(client, msg, topic_words)
        else:
            handle_capability_message_as_client(client, msg, topic_words)
    else:
        print(f"Unknown topic {msg.topic}")
        return None

def handle_rpc_message_as_client(client, msg, topic_words):
    payload = json.loads(msg.payload)
    print(f"Handling RPC message: {payload}")
    server_name = get_server_name_from_rpc_topic(topic_words)
    global_server_capabilities[server_name] = payload["result"]["capabilities"]
    global_server_info[server_name] = payload["result"]["serverInfo"]

def handle_ping_message_as_client(client, msg, topic_words):
    print(f"Received ping message: {msg.payload}")
    server_name = topic_words[2]
    if global_server_capabilities.get(server_name) is None:
        payload = json.loads(msg.payload)
        timestamp = payload["params"]["timestamp"]
        ## check if the timestamp is within the last 30 seconds
        if now_ms() - timestamp <= 30000:
            send_initialize_rpc(server_name)

def handle_capability_message_as_client(client, msg, topic_words):
    print(f"Received capability message: {msg.payload}")

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
