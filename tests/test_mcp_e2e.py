#!/usr/bin/env python3
"""
MCP 端到端测试
启动一个本地 echo server，测试 MCPClient 的连接、list_tools、call_tool
运行: python tests/test_mcp_e2e.py
"""
import os
import sys
import asyncio
import subprocess
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.mcp_client import MCPClient, MCPServerConfig


def log(msg):
    print(f"[E2E] {msg}")


async def test_mcp_connection():
    log("=" * 50)
    log("测试 MCP 端到端连接")
    log("=" * 50)

    server_script = os.path.join(os.path.dirname(__file__), "mcp_e2e_server.py")
    assert os.path.exists(server_script), f"Server 脚本不存在: {server_script}"

    client = MCPClient(servers=[
        MCPServerConfig(
            name="echo",
            transport="stdio",
            command=sys.executable,
            args=[server_script],
        )
    ])

    # 1. 连接
    log("1. 连接 MCP Server...")
    results = await client.connect_all()
    log(f"   连接结果: {results}")
    assert results.get("echo") is True, "连接失败"
    log("   ✅ 连接成功")

    # 2. 列出工具
    log("2. 列出 tools...")
    tools = client.list_tools()
    log(f"   发现 {len(tools)} 个 tool:")
    for t in tools:
        log(f"   - {t.name}: {t.description}")
    assert len(tools) >= 1, "未发现 tools"
    assert any(t.name == "echo" for t in tools), "未发现 echo tool"
    log("   ✅ list_tools 成功")

    # 3. 调用 tool
    log("3. 调用 echo tool...")
    result = await client.call_tool("echo", "echo", {"message": "Hello MCP!"})
    log(f"   success={result.success}")
    log(f"   content={result.content[:100] if result.content else 'None'}")
    assert result.success is True, f"调用失败: {result.error}"
    assert "Hello MCP!" in result.content, f"返回内容不对: {result.content}"
    log("   ✅ call_tool 成功")

    # 4. call_tool_by_name
    log("4. 通过名称调用...")
    result2 = await client.call_tool_by_name("echo", {"message": "By name!"})
    assert result2.success is True, f"by_name 调用失败: {result2.error}"
    assert "By name!" in result2.content, f"by_name 返回不对: {result2.content}"
    log("   ✅ call_tool_by_name 成功")

    # 5. 断开连接
    log("5. 断开连接...")
    await client.disconnect_all()
    log("   ✅ 断开成功")

    log("")
    log("🎉 全部 MCP 端到端测试通过!")
    return True


if __name__ == "__main__":
    asyncio.run(test_mcp_connection())
