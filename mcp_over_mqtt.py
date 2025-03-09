import json
import random
import time
import threading
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
    global global_server_info
    global_server_info = {"name": server_name, "version": version}
    connect("server", num_workers, ping_interval, host, port, username, password)
    start_ping_timer(ping_interval)

def run_mcp_client(client_name, version, num_workers = 1, ping_interval=30,
                   host="localhost", port=1883, username=None, password=None):
    global global_client_info
    global_client_info = {"name": client_name, "version": version}
    connect("client", num_workers, ping_interval, host, port, username, password)

def connect(mcp_role, num_workers, ping_interval=30,
            host="localhost", port=1883, username=None, password=None):
    if mcp_role != "server" and mcp_role != "client":
        raise ValueError("Invalid MCP role")
    if num_workers < 1:
        raise ValueError("Invalid number of workers")
    if ping_interval < 1:
        raise ValueError("Invalid ping interval")

    for worker_id in range(num_workers):
        if mcp_role == "client":
            clientid = client_clientid(global_client_info["name"], worker_id)
        elif mcp_role == "server":
            clientid = server_clientid(global_server_info["name"], worker_id)
        userdata = {"mcp_role": mcp_role, "worker_id": worker_id,
                    "num_workers": num_workers, "ping_interval": ping_interval},
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id = clientid,
                             userdata = userdata)
        client.username_pw_set(username, password)
        client.on_message = on_message
        client.on_connect = on_connect
        res = client.connect(host = MQTT_BROKER, port = MQTT_PORT,
                             keepalive = ping_interval * 2)
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
        return f"$share/g/$mcp/server/{server_name}"
    return f"$share/g/$mcp/server/{server_name}/{suffix}"

def server_rpc_topic(server_name, suffix=None):
    if suffix is None:
        return f"$mcp/server/{server_name}"
    return f"$mcp/server/{server_name}/{suffix}"

def server_capability_topic_filter(server_name, capability):
    return f"$mcp/server/{server_name}/capability/{capability}"

def server_ping_topic(server_name):
    return f"$mcp/server/{server_name}/ping"

def client_rpc_topic_filter(client_name, suffix=None):
    if suffix is None:
        return f"$share/g/$mcp/client/{client_name}"
    return f"$share/g/$mcp/client/{client_name}/{suffix}"

def client_rpc_topic(client_name):
    return f"$mcp/client/{client_name}"

def client_capability_topic_filter(client_name, capability):
    return f"$mcp/client/{client_name}/capability/{capability}"

def server_clientid(server_name, worker_id):
    return f"$mcp/server/{server_name}/{worker_id}"

def client_clientid(client_name, worker_id):
    return f"$mcp/client/{client_name}/{worker_id}"

################################################################################
## MCP Helper Functions
################################################################################
def get_clientid_from_rpc_topic(topic_words):
    # skip the first 2 parts of the topic
    clientid = topic_words[2:]
    if len(clientid) == 0:
        return None
    return clientid.join('/')

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

def handle_rpc_message_as_server(client, msg, topic_words):
    client_name = #get_clientid_from_rpc_topic(topic_words)
    data = json.loads(msg.payload)
    if "method" in data:
        method = data["method"]
        if method == "initialize":
            handle_initialize_rpc(client, client_name, data["id"], data["params"])
        else:
            print(f"Unknown method: {method}")
    else:
        print("Invalid RPC message")

def handle_initialize_rpc(client, client_name, request_id, params):
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
            send_mqtt_json_rpc_response(client, client_rpc_topic(client_name),
                                      ("error", error_info), request_id)
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
            ## subscribe to the capability topics if the capabilities is "listChanged: true"
            for cap in capabilities:
                if "listChanged" in capabilities[cap] and capabilities[cap]["listChanged"]:
                    client.subscribe(client_capability_topic_filter(client_name, cap))
            send_mqtt_json_rpc_response(client, client_rpc_topic(client_name),
                                      ("ok", initialize_result), request_id)
    else:
        error_info = {
            "code": ErrorCode.INVALID_PARAMS.value,
            "message": "protocolVersion is required",
            "data": {
                "supported": [PROTOCOL_VERSION],
                "requested": None
            }
        }
        send_mqtt_json_rpc_response(client, client_rpc_topic(client_name),
                                  ("error", error_info), request_id)


def handle_capability_message_as_server(client, msg, topic_words):
    print(f"Received capability message: {msg.payload}")

def start_ping_timer(ping_interval):
    timer = threading.Timer(ping_interval, on_ping_timer)
    timer.start()

################################################################################
## MQTT Callbacks
################################################################################
def on_ping_timer():
    client = pick_mqtt_client_randomly()
    client.publish(server_ping_topic(global_server_info["name"]), "ping")

def on_message(client, userdata, msg):
    print(f"Received: {msg.payload}")
    topic_words = msg.topic.split('/')
    if userdata[0]["mcp_role"] == "server":
        handle_message_as_server(client, msg, topic_words, userdata)
    elif userdata[0]["mcp_role"] == "client":
        handle_message_as_client(client, msg, topic_words, userdata)

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"Connected with result code {reason_code}")
    if userdata[0]["mcp_role"] == "server":
        client.subscribe(server_rpc_topic_filter(global_server_info["name"], "#"))
        client.subscribe(client_capability_topic_filter("+", "#"))
    elif userdata[0]["mcp_role"] == "client":
        client.subscribe(client_rpc_topic_filter(global_client_info["name"], "#"))
        client.subscribe(server_capability_topic_filter("+", "#"))

def handle_message_as_server(client, msg, topic_words, userdata):
    ## Check if it is a RPC message or a client capability message
    ##  - Topic of RPC messages: $mcp/server/<server-name>/<clientid>
    ##  - Topic of capability messages: $mcp/client/<client-id>/capability/<capability>
    if topic_words[0] != "$mcp":
        return
    if topic_words[1] == "server":
        handle_rpc_message_as_server(client, msg, topic_words)
    elif topic_words[1] == "client":
        handle_capability_message_as_server(client, msg, topic_words)

def handle_message_as_client(client, msg, topic_words, userdata):
    if topic_words[0] != "$mcp":
        return
    if topic_words[1] == "client":
        handle_rpc_message_as_client(client, msg, topic_words)
    elif topic_words[1] == "server":
        handle_capability_message_as_client(client, msg, topic_words)

def send_initialize_rpc():
    client = pick_mqtt_client_randomly()
    initialize_params = {"protocolVersion": PROTOCOL_VERSION,
                         "capabilities": global_client_capabilities,
                         "clientInfo": global_client_info
                         }
    send_mqtt_json_rpc(client, server_rpc_topic(client_name, worker_id), 
                       "initialize", initialize_params, 1)

def pick_mqtt_client_randomly():
    num_workers = len(global_mqtt_clients)
    worker_id = random.randint(0, num_workers - 1)
    client_name = global_client_info["name"]
    client = global_mqtt_clients[worker_id]

################################################################################
## Main
################################################################################    
if __name__ == "__main__":
    run_mcp_server("ssh_tool", "0.1.0")
    ## sleep 1s
    time.sleep(1)
    run_mcp_client("mcp_over_mqtt", "0.1.0")
