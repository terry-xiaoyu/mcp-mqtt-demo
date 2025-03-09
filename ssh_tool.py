import paramiko
import os
import mcp_over_mqtt as mcp

def ssh_execute_command(host, port, username, password, command):
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
        return "SSH 认证失败，请检查用户名或密码。"
    except paramiko.SSHException as e:
        return f"SSH 连接错误: {str(e)}"
    except Exception as e:
        return f"未知错误: {str(e)}"

# 示例使用
if __name__ == "__main__":
    # host = "localhost"
    # port = 22
    # username = os.getenv("SSH_USERNAME", "user")
    # password = os.getenv("SSH_PASSWORD", "password")
    # command = "ls -l"
    # result = ssh_execute_command(host, port, username, password, command)
    # print(result)
    mcp.global_server_capabilities["tools"] = {
        "listChanged": True,
        "list": [
            {
                "name": "ssh",
                "description": "Execute command on remote server via SSH",
                "inputSchema": {
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
    }
    mcp.run_mcp_server("ssh_tool")
