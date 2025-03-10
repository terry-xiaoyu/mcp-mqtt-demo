import os
import time
import mcp_over_mqtt as mcp

CLIENT_NAME = "exmaple_mcp_client"
VERSION = "0.1.0"

if __name__ == "__main__":
    host = "localhost"
    port = 22
    username = os.getenv("SSH_USERNAME", "user")
    password = os.getenv("SSH_PASSWORD", "password")
    mcp.run_mcp_client(CLIENT_NAME, VERSION, host=host, port=port, username=username, password=password)
    arguments = {
        "host": "localhost",
        "port": 9900,
        "username": username,
        "password": password,
        "command": "ls -l"
    }
    mcp.send_tools_call_rpc("ssh_tool", "ssh_execute_command", arguments)
    while True:
        time.sleep(100)
        pass
