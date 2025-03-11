import paramiko
import os, time
import mcp_over_mqtt as mcp

SERVER_NAME = "ssh_tool"
VERSION = "0.1.0"

def ssh_execute_command(host, port, username, password, command):
    print(f"------ssh_execute_command host: {host}, port: {port}, username: {username}, password: {password}, command: {command}")
    """
    通过 SSH 连接到远程服务器并执行指定命令。
    
    参数：
    - host: 服务器 IP 或域名
    - port: SSH 端口（默认 22）
    - username: SSH 登录用户名
    - password: SSH 登录密码
    - command: 需要执行的命令
    
    返回：
    - 成功时返回 (stdout, stderr)
    - 失败时返回错误信息
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # 自动接受未知主机密钥
    
    try:
        # 连接 SSH
        client.connect(host, port=port, username=username, password=password, timeout=10)
        
        # 执行命令
        stdin, stdout, stderr = client.exec_command(command)
        output = stdout.read().decode('utf-8').strip()
        error = stderr.read().decode('utf-8').strip()
        
        client.close()
        return output, error if error else None

    except paramiko.AuthenticationException:
        return "SSH authentication failed"
    except paramiko.SSHException as e:
        return f"SSH error: {str(e)}"
    except Exception as e:
        return f"unknown error: {str(e)}"

# 示例使用
if __name__ == "__main__":
    # host = "localhost"
    # port = 22
    # username = os.getenv("SSH_USERNAME", "user")
    # password = os.getenv("SSH_PASSWORD", "password")
    # command = "ls -l"
    # result = ssh_execute_command(host, port, username, password, command)
    # print(result)
    supported_tools = [
        {
            "name": "ssh_execute_command",
            "description": "Execute command on remote server via SSH",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {
                        "type": "string",
                        "description": "Remote server IP or domain name"
                    },
                    "port": {
                        "type": "integer",
                        "description": "SSH port number"
                    },
                    "username": {
                        "type": "string",
                        "description": "SSH login username"
                    },
                    "password": {
                        "type": "string",
                        "description": "SSH login password"
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to execute"
                    }
                },
                "required": ["host", "username", "password", "command"]
            }
        }
    ]
    server_capabilities = {
        "tools": supported_tools
    }
    mcp.run_mcp_server(SERVER_NAME, VERSION, capabilities=server_capabilities,
                       tool_callbacks={"ssh_execute_command": ssh_execute_command})
    while True:
        time.sleep(100)
        pass
