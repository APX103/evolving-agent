"""
MCP (Model Context Protocol) 客户端
使用官方 MCP SDK (mcp>=1.0)，支持 stdio 传输
"""
import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """MCP Tool 描述"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    server: str = ""


@dataclass
class MCPServerConfig:
    """MCP Server 配置"""
    name: str
    transport: str = "stdio"
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    url: Optional[str] = None
    env: Optional[Dict[str, str]] = None


@dataclass
class MCPCallResult:
    """MCP Tool 调用结果"""
    success: bool
    content: Any
    error: Optional[str] = None


class MCPClient:
    """
    MCP 协议客户端（官方 SDK 封装）
    对外提供同步接口，内部使用 asyncio 驱动官方 async SDK
    """

    def __init__(self, servers: Optional[List[MCPServerConfig]] = None):
        self.servers = servers or []
        self._exit_stack: Optional[AsyncExitStack] = None
        self._sessions: Dict[str, ClientSession] = {}
        self._tools: List[MCPTool] = []

    # ── 连接管理 ──

    def connect_all(self) -> Dict[str, bool]:
        """连接所有配置的 MCP Server，返回连接结果"""
        try:
            return asyncio.run(self._connect_all_async())
        except Exception as e:
            logger.warning(f"[MCP] 连接失败: {e}")
            return {s.name: False for s in self.servers}

    async def _connect_all_async(self) -> Dict[str, bool]:
        self._exit_stack = AsyncExitStack()
        results = {}

        for cfg in self.servers:
            try:
                if cfg.transport == "stdio" and cfg.command:
                    params = StdioServerParameters(
                        command=cfg.command,
                        args=cfg.args,
                        env=cfg.env,
                    )
                    # 进入 stdio_client 和 ClientSession 上下文
                    read, write = await self._exit_stack.enter_async_context(stdio_client(params))
                    session = await self._exit_stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    self._sessions[cfg.name] = session
                    results[cfg.name] = True
                    logger.info(f"[MCP] ✅ 已连接 server: {cfg.name}")
                else:
                    results[cfg.name] = False
                    logger.warning(f"[MCP] 不支持的传输方式: {cfg.transport}")
            except Exception as e:
                results[cfg.name] = False
                logger.warning(f"[MCP] 连接 server '{cfg.name}' 失败: {e}")

        # 刷新工具列表
        if any(results.values()):
            await self._refresh_tools_async()

        return results

    def disconnect_all(self):
        """断开所有连接"""
        if self._exit_stack:
            try:
                asyncio.run(self._exit_stack.aclose())
            except Exception as e:
                logger.warning(f"[MCP] 断开连接时出错: {e}")
            finally:
                self._exit_stack = None
                self._sessions.clear()
                self._tools.clear()

    # ── 工具发现 ──

    def list_tools(self) -> List[MCPTool]:
        """列出所有可用 MCP tools"""
        return list(self._tools)

    async def _refresh_tools_async(self):
        """异步刷新工具列表"""
        all_tools = []
        for name, session in self._sessions.items():
            try:
                result = await session.list_tools()
                for tool in result.tools:
                    all_tools.append(MCPTool(
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=tool.inputSchema or {},
                        server=name,
                    ))
            except Exception as e:
                logger.warning(f"[MCP] 获取 server '{name}' tools 失败: {e}")
        self._tools = all_tools

    # ── 工具调用 ──

    def call_tool(self, server_name: str, tool_name: str, arguments: Dict) -> MCPCallResult:
        """调用指定 MCP tool（同步包装）"""
        try:
            return asyncio.run(self._call_tool_async(server_name, tool_name, arguments))
        except Exception as e:
            logger.warning(f"[MCP] 调用 tool '{tool_name}' 失败: {e}")
            return MCPCallResult(success=False, content=None, error=str(e))

    async def _call_tool_async(self, server_name: str, tool_name: str, arguments: Dict) -> MCPCallResult:
        session = self._sessions.get(server_name)
        if not session:
            return MCPCallResult(success=False, content=None, error=f"server '{server_name}' 未连接")

        result = await session.call_tool(tool_name, arguments=arguments)

        # 提取文本内容
        texts = []
        for content in result.content:
            if isinstance(content, TextContent):
                texts.append(content.text)
            else:
                texts.append(str(content))

        # 检查是否有错误
        if result.isError:
            return MCPCallResult(
                success=False,
                content="\n".join(texts),
                error="Tool 返回错误"
            )

        return MCPCallResult(
            success=True,
            content="\n".join(texts) if texts else "",
        )

    def call_tool_by_name(self, tool_name: str, arguments: Dict) -> MCPCallResult:
        """根据 tool name 自动查找 server 并调用"""
        for tool in self._tools:
            if tool.name == tool_name:
                return self.call_tool(tool.server, tool_name, arguments)
        return MCPCallResult(success=False, content=None, error=f"未找到 tool: {tool_name}")
