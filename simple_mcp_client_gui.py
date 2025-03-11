import json
import wx
import os
import mcp_over_mqtt as mcp
import threading
from openai import OpenAI

CLIENT_NAME = "simple_mcp_client_gui"
VERSION = "0.1.0"
MainTitle = "Simple MCP/MQTT Client GUI"

client = OpenAI(
    api_key = os.getenv("DASHSCOPE_API_KEY"),
    base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

class ChatWindow(wx.Frame):
    def __init__(self):
        super().__init__(None, title=MainTitle, size=(800, 600))

        # 创建主面板
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.HORIZONTAL)
        vbox = wx.BoxSizer(wx.VERTICAL)

        # ======== MQTT 登录设置 ======== #
        grid = wx.FlexGridSizer(2, 4, 5, 5)  # 2行4列，行间距5，列间距5
        grid.AddGrowableCol(0, 1)
        grid.AddGrowableCol(1, 4)
        grid.AddGrowableCol(2, 1)
        grid.AddGrowableCol(3, 4)

        grid.Add(wx.StaticText(panel, label="MQTT Host:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.host_input = wx.TextCtrl(panel, value="localhost")
        grid.Add(self.host_input, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="MQTT Port:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.port_input = wx.TextCtrl(panel, value="1883")
        grid.Add(self.port_input, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Username:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.username_input = wx.TextCtrl(panel)
        grid.Add(self.username_input, 1, wx.EXPAND)

        grid.Add(wx.StaticText(panel, label="Password:"), 0, wx.ALIGN_CENTER_VERTICAL)
        self.password_input = wx.TextCtrl(panel, style=wx.TE_PASSWORD)  # 密码框
        grid.Add(self.password_input, 1, wx.EXPAND)

        vbox.Add(grid, 0, wx.ALL | wx.EXPAND, 10)

        # ========== 右侧：好友在线状态栏 ========== #
        self.tool_panel = wx.Panel(panel, size=(120, -1))
        self.tool_panel.SetBackgroundColour(wx.Colour(240, 240, 240))
        self.tool_sizer = wx.BoxSizer(wx.VERTICAL)

        self.tool_panel.SetSizer(self.tool_sizer)
        main_sizer.Add(self.tool_panel, 1, wx.EXPAND | wx.ALL, 5)

        # 连接按钮
        self.connect_button = wx.Button(panel, label="Connect")
        vbox.Add(self.connect_button, 0, wx.ALL | wx.EXPAND, 5)
        self.connect_button.Bind(wx.EVT_BUTTON, self.run_mcp_client)

        # ======== 聊天窗口 ======== #
        self.chat_display = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SUNKEN)
        vbox.Add(self.chat_display, 1, wx.EXPAND | wx.ALL, 5)

        # 输入框 + 发送按钮
        hbox = wx.BoxSizer(wx.HORIZONTAL)
        self.input_box = wx.TextCtrl(panel, style=wx.TE_PROCESS_ENTER)
        self.send_button = wx.Button(panel, label="Send")

        hbox.Add(self.input_box, 1, wx.EXPAND | wx.ALL, 5)
        hbox.Add(self.send_button, 0, wx.ALL, 5)

        vbox.Add(hbox, 0, wx.EXPAND)

        self.send_button.Bind(wx.EVT_BUTTON, self.send_message)
        self.input_box.Bind(wx.EVT_TEXT_ENTER, self.send_message)

        main_sizer.Add(vbox, 2, wx.EXPAND | wx.ALL)
        panel.SetSizer(main_sizer)
        self.Centre()

        self.tools = {}
        self.history_msgs = []
        self.mqtt_client = None
        self.is_connected = False

    def run_mcp_client(self, event):
        host = self.host_input.GetValue()
        port = int(self.port_input.GetValue())
        username = self.username_input.GetValue()
        password = self.password_input.GetValue()
        capability_change_callback = (self.on_server_capability_change, {})
        mcp.run_mcp_client(
            CLIENT_NAME, VERSION, host=host, port=port,
            username=username, password=password,
            on_server_capability_change=capability_change_callback)

    def on_server_capability_change(self, server_name):
        tools = mcp.get_avaliable_tools_open_ai()
        ## tools is in form of: [{"type": "function", "function": {"name": "server_name:tool_name", "description": "tool_description", "parameters": {...}}}]
        ## we need to extract the "name"s and create the tool status panel for each tool
        for tool in tools:
            tool_name = tool['function']['name']
            if tool_name not in self.tools:
                self.add_tool(tool_name)
    
    def create_tool_status(self, label):
        """创建一个带绿点的工具状态组件"""
        panel = wx.Panel(self.tool_panel)
        sizer = wx.BoxSizer(wx.HORIZONTAL)

        green_dot = wx.Panel(panel, size=(10, 10))
        green_dot.SetBackgroundColour(wx.Colour(0, 200, 0))

        label = wx.StaticText(panel, label=label)

        sizer.Add(green_dot, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
        sizer.Add(label, 1, wx.ALIGN_CENTER_VERTICAL)

        panel.SetSizer(sizer)
        return panel

    def add_tool(self, label):
        if label not in self.tools:
            tool_panel = self.create_tool_status(label)
            self.tool_sizer.Add(tool_panel, 0, wx.ALL, 5)
            self.tools[label] = tool_panel
            self.tool_panel.Layout()
            self.tool_panel.Refresh()

    def remove_tool(self, label):
        if self.tools:
            tool_panel = self.tools.pop(label)
            tool_panel.Destroy()
            self.tool_panel.Layout()
            self.tool_panel.Refresh()

    def send_message(self, event):
        """发送消息"""
        message = self.input_box.GetValue().strip()
        if message:
            self.chat_display.AppendText(f"[User]: {message}\n")
            self.input_box.SetValue("")  # Clear the input box
            threading.Thread(target=self.async_call_with_messages,
                             args=(message, self.history_msgs), daemon=True).start()

    def async_call_with_messages(self, message, history_msgs):
        ## disable the send button
        wx.CallAfter(self.send_button.Disable)
        try:
            ## call the assistant asynchronously to avoid blocking the GUI
            call_with_messages(self, message, history_msgs)
        except Exception as e:
            err_msg = f"[Assistant]: Error: {e}\n"
            self.append_text_to_chat_win(err_msg)
        finally:
            ## enable the send button
            wx.CallAfter(self.send_button.Enable)

    def append_text_to_chat_win(self, text):
        wx.CallAfter(self.chat_display.AppendText, text)

def query_llm_chat_completion(history_msgs):
    # https://help.aliyun.com/zh/model-studio/getting-started/models
    model_name = "qwen-max-latest"
    tools = mcp.get_avaliable_tools_open_ai()
    if len(tools) == 0:
        print("--------No tools are available. Calling the model without tools")
        completion = client.chat.completions.create(
            model=model_name,
            messages=history_msgs
            )
    else:
        print(f"--------Calling the model with tools. The available tools: {tools}")
        completion = client.chat.completions.create(
            model=model_name,
            messages=history_msgs,
            tools=tools
            )
    return completion.model_dump()

def call_with_messages(self, text_msg, history_msgs):
    print('\n')
    print("-"*60)
    print('\n')

    new_msg = [
        {
            "content": text_msg,
            "role": "user"
        }
    ]
    history_msgs.extend(new_msg)

    i = 1
    first_response = query_llm_chat_completion(history_msgs)
    assistant_output = first_response['choices'][0]['message']
    print(f"\n The first LLM output: {first_response}\n")
    if assistant_output['content'] is None:
        assistant_output['content'] = ""
    history_msgs.append(assistant_output)

    # reply the user if no need to call tools
    if assistant_output['tool_calls'] == None:
        answer = f"No tools call is needed. Anwser: {assistant_output['content']}"
        self.append_text_to_chat_win(f"[Assistant]: {answer}\n")

    if assistant_output['tool_calls'] != None:
        tool_name = assistant_output['tool_calls'][0]['function']['name']
        arguments = assistant_output['tool_calls'][0]['function']['arguments']
        tool_call_id = assistant_output['tool_calls'][0]['id']
        server_name, function_name = parse_tool_name(tool_name)
        self.append_text_to_chat_win(f"[Assistant]: Calling the tool: {tool_name} ...\n")
        is_ok, tool_result = mcp.send_tools_call_rpc(server_name, function_name, maybe_decode_json(arguments))
        print(f"The output of tools: {tool_result}\n")
        if is_ok == "error":
            tool_response = f"The tool replied an error: {tool_result}"
            self.append_text_to_chat_win(f"[Assistant][{tool_name}]: {tool_response}\n")

        tool_info = {
            "name": tool_name,
            "role":"tool",
            "tool_call_id": tool_call_id,
            "content": maybe_encode_json(tool_result)
            }
        print("-"*60)
        history_msgs.append(tool_info)

        ## call the model again
        assistant_output = query_llm_chat_completion(history_msgs)['choices'][0]['message']
        if assistant_output['content'] is None:
            assistant_output['content'] = ""
        history_msgs.append(assistant_output)
        i += 1
        print(f"The {i}st output of the LLM: {assistant_output}\n")
        self.append_text_to_chat_win(f"[Assistant]: {assistant_output['content']}\n")

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
    app = wx.App(False)
    frame = ChatWindow()
    frame.Show()
    app.MainLoop()
