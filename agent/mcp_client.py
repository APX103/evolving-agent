"""
轻量级 MCP (Model Context Protocol) 客户端
兼容 Python 3.9，不依赖官方 mcp SDK
支持 stdio 和 sse 两种传输方式
"""
import json
import logging
import subprocess
import threading
import time
import urllib.request
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """MCP Tool 描述"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    server: str = ""  # 来源 server


@dataclass
class MCPServerConfig:
    """MCP Server 配置"""
    name: str
    transport: str = "stdio"  # stdio | sse
    command: Optional[str] = None      # stdio: 启动命令
    args: List[str] = field(default_factory=list)  # stdio: 启动参数
    url: Optional[str] = None          # sse: 服务端点
    env: Dict[str, str] = field(default_factory=dict)


@dataclass
class MCPCallResult:
    """MCP Tool 调用结果"""
    success: bool
    content: Any
    error: Optional[str] = None


class MCPClient:
    """
    轻量级 MCP 协议客户端
    支持 stdio（本地子进程）和 sse（HTTP 流）传输
    """

    def __init__(self, servers: Optional[List[MCPServerConfig]] = None):
        self.servers = {s.name: s for s in (servers or [])}
        self._sessions: Dict[str, Any] = {}  # server_name -> session
        self._tools: List[MCPTool] = []
        self._message_id = 0
        self._lock = threading.Lock()

    # ── 连接管理 ──

    def connect_all(self) -> Dict[str, bool]:
        """连接所有配置的 MCP Server，返回连接结果"""
        results = {}
        for name, config in self.servers.items():
            try:
                if config.transport == "stdio":
                    self._connect_stdio(name, config)
                elif config.transport == "sse":
                    self._connect_sse(name, config)
                results[name] = True
                logger.info(f"[MCP] 已连接 server: {name}")
            except Exception as e:
                results[name] = False
                logger.warning(f"[MCP] 连接 server '{name}' 失败: {e}")
        
        # 刷新工具列表
        self._refresh_tools()
        return results

    def disconnect_all(self):
        """断开所有连接"""
        for name, session in list(self._sessions.items()):
            try:
                if isinstance(session, subprocess.Popen):
                    session.terminate()
                    session.wait(timeout=2)
                # SSE 连接无需显式关闭（HTTP 短连接）
            except Exception:
                pass
        self._sessions.clear()
        self._tools.clear()

    def _connect_stdio(self, name: str, config: MCPServerConfig):
        """通过 stdio 连接 MCP Server"""
        env = {**os.environ, **config.env}
        proc = subprocess.Popen(
            [config.command] + config.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,
        )
        self._sessions[name] = proc
        # 发送 initialize 请求
        self._send_stdio(name, {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "evolving-agent", "version": "3.2"}
            }
        })
        # 读取 initialize 响应
        resp = self._read_stdio(name, timeout=10)
        if resp is None:
            raise RuntimeError("initialize 无响应")

    def _connect_sse(self, name: str, config: MCPServerConfig):
        """通过 SSE 连接 MCP Server（简化版：仅存储 URL）"""
        self._sessions[name] = {"type": "sse", "url": config.url}

    # ── 工具发现 ──

    def list_tools(self) -> List[MCPTool]:
        """列出所有可用 MCP tools"""
        return list(self._tools)

    def _refresh_tools(self):
        """从所有已连接 server 刷新工具列表"""
        all_tools = []
        for name in self._sessions:
            try:
                tools = self._list_tools_from_server(name)
                for t in tools:
                    all_tools.append(MCPTool(
                        name=t["name"],
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {}),
                        server=name,
                    ))
            except Exception as e:
                logger.warning(f"[MCP] 获取 server '{name}' tools 失败: {e}")
        self._tools = all_tools

    def _list_tools_from_server(self, server_name: str) -> List[Dict]:
        """从单个 server 获取工具列表"""
        resp = self._call_method(server_name, "tools/list", {})
        return resp.get("tools", []) if resp else []

    # ── 工具调用 ──

    def call_tool(self, server_name: str, tool_name: str, arguments: Dict) -> MCPCallResult:
        """调用指定 MCP tool"""
        try:
            resp = self._call_method(server_name, "tools/call", {
                "name": tool_name,
                "arguments": arguments
            })
            if resp is None:
                return MCPCallResult(success=False, content=None, error="无响应")
            
            if "error" in resp:
                return MCPCallResult(success=False, content=None, error=resp["error"].get("message", "未知错误"))
            
            result = resp.get("result", {})
            content = result.get("content", [])
            # 提取文本内容
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return MCPCallResult(success=True, content="\n".join(texts) if texts else content)
        except Exception as e:
            logger.warning(f"[MCP] 调用 tool '{tool_name}' 失败: {e}")
            return MCPCallResult(success=False, content=None, error=str(e))

    def call_tool_by_name(self, tool_name: str, arguments: Dict) -> MCPCallResult:
        """根据 tool name 自动查找 server 并调用"""
        for tool in self._tools:
            if tool.name == tool_name:
                return self.call_tool(tool.server, tool_name, arguments)
        return MCPCallResult(success=False, content=None, error=f"未找到 tool: {tool_name}")

    # ── 底层通信 ──

    def _call_method(self, server_name: str, method: str, params: Dict) -> Optional[Dict]:
        """调用 JSON-RPC 方法"""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params
        }
        
        session = self._sessions.get(server_name)
        if session is None:
            raise RuntimeError(f"server '{server_name}' 未连接")
        
        if isinstance(session, subprocess.Popen):
            self._send_stdio(server_name, req)
            return self._read_stdio(server_name, timeout=30)
        elif isinstance(session, dict) and session.get("type") == "sse":
            return self._send_http(session["url"], req)
        else:
            raise RuntimeError(f"不支持的 session 类型: {type(session)}")

    def _send_stdio(self, server_name: str, message: Dict):
        """通过 stdin 发送消息"""
        proc = self._sessions[server_name]
        line = json.dumps(message, ensure_ascii=False) + "\n"
        proc.stdin.write(line)
        proc.stdin.flush()

    def _read_stdio(self, server_name: str, timeout: int = 30) -> Optional[Dict]:
        """通过 stdout 读取响应"""
        proc = self._sessions[server_name]
        import select
        import os as os_mod
        
        start = time.time()
        while time.time() - start < timeout:
            # 检查是否有可读数据
            readable, _, _ = select.select([proc.stdout], [], [], 0.5)
            if readable:
                line = proc.stdout.readline()
                if line:
                    try:
                        return json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue
            # 检查进程是否已退出
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        return None

    def _send_http(self, url: str, message: Dict) -> Optional[Dict]:
        """通过 HTTP POST 发送 JSON-RPC 请求"""
        req = urllib.request.Request(
            url,
            data=json.dumps(message).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning(f"[MCP] HTTP 请求失败: {e}")
            return None

    def _next_id(self) -> int:
        with self._lock:
            self._message_id += 1
            return self._message_id


import os  # 放在末尾避免循环导入问题
