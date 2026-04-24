"""
MCP (Model Context Protocol) client
Official MCP SDK (mcp>=1.0), supports stdio / sse / streamable_http transport
Pure async interface
"""
import json
import logging
from contextlib import AsyncExitStack
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from agent.observability import get_tracer
from agent.mcp.security import ToolAuditor, PolicyEnforcer, Decision
from agent.mcp.approval import ApprovalManager

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    server: str = ""


@dataclass
class MCPServerConfig:
    name: str
    transport: str = "stdio"
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    url: Optional[str] = None
    env: Optional[Dict[str, str]] = None


@dataclass
class MCPCallResult:
    success: bool
    content: Any
    error: Optional[str] = None


class MCPClient:
    def __init__(
        self,
        servers: Optional[List[MCPServerConfig]] = None,
        approval_manager: Optional[ApprovalManager] = None,
        security_config: Optional[Dict[str, Any]] = None,
    ):
        self.servers = servers or []
        self._exit_stack: Optional[AsyncExitStack] = None
        self._sessions: Dict[str, ClientSession] = {}
        self._tools: List[MCPTool] = []
        self._tool_schemas: Dict[str, Dict[str, Any]] = {}
        self._security = PolicyEnforcer(
            security_config=security_config,
            approval_manager=approval_manager,
        )

    async def connect_all(self) -> Dict[str, bool]:
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
                    read, write = await self._exit_stack.enter_async_context(stdio_client(params))
                    session = await self._exit_stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    self._sessions[cfg.name] = session
                    results[cfg.name] = True
                    logger.info(f"[MCP] Connected (stdio): {cfg.name}")

                elif cfg.transport in ("sse", "http") and cfg.url:
                    if cfg.transport == "sse":
                        from mcp.client.sse import sse_client
                        read, write = await self._exit_stack.enter_async_context(
                            sse_client(cfg.url)
                        )
                    else:
                        from mcp.client.streamable_http import streamable_http_client
                        read, write, _get_sid = await self._exit_stack.enter_async_context(
                            streamable_http_client(cfg.url)
                        )

                    session = await self._exit_stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    self._sessions[cfg.name] = session
                    results[cfg.name] = True
                    logger.info(f"[MCP] Connected ({cfg.transport}): {cfg.name}")

                else:
                    results[cfg.name] = False
                    logger.warning(
                        f"[MCP] Unsupported transport or missing params: transport={cfg.transport}, "
                        f"command={cfg.command}, url={cfg.url}"
                    )
            except Exception as e:
                results[cfg.name] = False
                logger.warning(f"[MCP] Failed to connect server '{cfg.name}': {e}")

        if any(results.values()):
            await self._refresh_tools()

        return results

    async def disconnect_all(self):
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.warning(f"[MCP] Error disconnecting: {e}")
            finally:
                self._exit_stack = None
                self._sessions.clear()
                self._tools.clear()
                self._tool_schemas.clear()

    def list_tools(self) -> List[MCPTool]:
        return list(self._tools)

    def get_tool_schema(self, server_name: str, tool_name: str) -> Optional[Dict[str, Any]]:
        return self._tool_schemas.get(f"{server_name}::{tool_name}")

    async def _refresh_tools(self):
        all_tools = []
        self._tool_schemas.clear()

        for name, session in self._sessions.items():
            try:
                result = await session.list_tools()
                for tool in result.tools:
                    schema = {}
                    if hasattr(tool, "inputSchema"):
                        schema = tool.inputSchema or {}
                    elif isinstance(tool, dict):
                        schema = tool.get("inputSchema", {})

                    tool_name = (
                        getattr(tool, "name", tool.get("name", ""))
                        if isinstance(tool, dict)
                        else tool.name
                    )
                    tool_desc = (
                        getattr(tool, "description", tool.get("description", ""))
                        if isinstance(tool, dict)
                        else getattr(tool, "description", "")
                    ) or ""

                    mcp_tool = MCPTool(
                        name=tool_name,
                        description=tool_desc,
                        input_schema=schema,
                        server=name,
                    )
                    all_tools.append(mcp_tool)
                    self._tool_schemas[f"{name}::{tool_name}"] = schema
            except Exception as e:
                logger.warning(f"[MCP] Failed to list tools for server '{name}': {e}")

        self._tools = all_tools

        for name, session in self._sessions.items():
            server_tools = [t for t in self._tools if t.server == name]
            if not server_tools:
                continue
            report = ToolAuditor.audit_server(server_tools, server_name=name)
            logger.info(
                f"[MCP Security] Audited server '{name}': {report.tool_count} tools, "
                f"risk={ {k.value: v for k, v in report.risk_summary.items()} }"
            )
            if report.alerts:
                for alert in report.alerts:
                    logger.warning(f"[MCP Security] {alert}")

            for tool in server_tools:
                risk = ToolAuditor.audit_tool(tool.input_schema, tool.name, tool.description)
                alert = self._security.register_tool_schema(name, tool.name, tool.input_schema, risk)
                if alert:
                    logger.warning(f"[MCP Security] {alert}")

            tracer = get_tracer()
            span = tracer.start_span("mcp.security.audit_server", attributes={
                "server_name": name,
                "tool_count": report.tool_count,
            })
            for level, count in report.risk_summary.items():
                span.set_attribute(f"risk.{level.value}", count)
            if report.alerts:
                span.set_attribute("alerts", report.alerts)
            span.end()

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict) -> MCPCallResult:
        tracer = get_tracer()
        span = tracer.start_span("mcp.call_tool", attributes={
            "server_name": server_name,
            "tool_name": tool_name,
        })
        span.set_attribute("arguments", json.dumps(arguments, ensure_ascii=False, default=str)[:500])

        session = self._sessions.get(server_name)
        if not session:
            span.set_attribute("error", "server_not_connected")
            span.end()
            return MCPCallResult(success=False, content=None, error=f"server '{server_name}' not connected")

        schema = self.get_tool_schema(server_name, tool_name)
        description = ""
        for t in self._tools:
            if t.server == server_name and t.name == tool_name:
                description = t.description
                break

        decision = self._security.check_tool(server_name, tool_name, arguments, schema=schema, description=description)
        if decision == Decision.BLOCK:
            msg = f"Security policy blocked tool '{tool_name}' on server '{server_name}'"
            logger.warning(f"[MCP] {msg}")
            span.set_attribute("error", "security_blocked")
            span.set_attribute("security_decision", "block")
            span.end()
            return MCPCallResult(success=False, content=None, error=msg)

        if decision == Decision.REQUIRE_APPROVAL:
            msg = f"Security policy requires approval for tool '{tool_name}' on server '{server_name}'"
            logger.info(f"[MCP] {msg}")
            span.set_attribute("security_decision", "require_approval")
            # ApprovalManager is already invoked inside PolicyEnforcer.check_tool
            # If we reach here with REQUIRE_APPROVAL, it means nonblocking mode pending.
            # For simplicity, treat pending as blocked for now to avoid hanging.
            span.set_attribute("error", "approval_pending")
            span.end()
            return MCPCallResult(success=False, content=None, error=msg)

        try:
            result = await session.call_tool(tool_name, arguments=arguments)
        except Exception as e:
            logger.warning(f"[MCP] Failed to call tool '{tool_name}': {e}")
            span.record_exception(e)
            span.end()
            return MCPCallResult(success=False, content=None, error=str(e))

        texts = []
        for content in result.content:
            if isinstance(content, TextContent):
                texts.append(content.text)
            else:
                texts.append(str(content))

        result_text = "\n".join(texts) if texts else ""
        span.set_attribute("result_length", len(result_text))
        span.set_attribute("is_error", bool(result.isError))
        span.end()

        if result.isError:
            return MCPCallResult(
                success=False,
                content=result_text,
                error="Tool returned error",
            )

        return MCPCallResult(
            success=True,
            content=result_text,
        )

    async def call_tool_by_name(self, tool_name: str, arguments: Dict) -> MCPCallResult:
        for tool in self._tools:
            if tool.name == tool_name:
                return await self.call_tool(tool.server, tool_name, arguments)
        return MCPCallResult(success=False, content=None, error=f"tool not found: {tool_name}")
