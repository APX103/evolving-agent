#!/usr/bin/env python3
"""
简单的 MCP Echo Server，用于端到端测试
注册一个 `echo` tool，返回传入的消息
"""
import asyncio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool, ListToolsResult

app = Server("echo-server")

@app.list_tools()
async def list_tools():
    return ListToolsResult(
        tools=[
            Tool(
                name="echo",
                description="Echo the input message back",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"}
                    },
                    "required": ["message"]
                }
            )
        ]
    )

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "echo":
        msg = arguments.get("message", "")
        return [TextContent(type="text", text=f"ECHO: {msg}")]
    raise ValueError(f"Unknown tool: {name}")

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
