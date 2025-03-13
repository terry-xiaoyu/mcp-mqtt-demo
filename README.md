## MCP over MQTT Demo

It includes a simple MCP over MQTT Python SDK, some demo MCP servers and a MCP client.

### Try it
```
uv sync

## run the client, click connect before sending any messages
uv run simple_mcp_client_gui.py

## run the servers
uv run simple_mcp_server_ssh.py
uv run simple_mcp_server_weather.py
```
