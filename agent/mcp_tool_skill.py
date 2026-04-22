"""
MCP Tool → Skill 适配器
让 Agent 的 SkillRegistry 能够调用 MCP Server 提供的工具
"""
import logging
from typing import Dict, List, Optional

from agent.skill import Skill, SkillResult
from agent.mcp_client import MCPClient, MCPCallResult

logger = logging.getLogger(__name__)


class MCPToolSkill(Skill):
    """
    MCP Tool 的 Skill 包装器
    每个 MCP Tool 动态生成一个 MCPToolSkill 实例
    """

    def __init__(self, mcp_client: MCPClient, tool_name: str, description: str, server: str):
        self.mcp_client = mcp_client
        self.tool_name = tool_name
        self.server = server
        # Skill 基类属性
        self.name = f"mcp_{tool_name}"
        self.description = description
        self.triggers = [f"/mcp {tool_name}"]
        self.priority = 60  # 低于内置 Skill，但高于默认

    def can_handle(self, user_input: str, context: Dict) -> bool:
        """
        匹配方式：
        1. 显式命令: /mcp <tool_name> <args>
        2. LLM 路由: 如果上层已通过 LLM 判断应调用此 tool，context 中会有 "mcp_tool" 标记
        """
        # 显式命令
        if user_input.strip().startswith(f"/mcp {self.tool_name}"):
            return True
        # LLM 路由标记
        if context.get("mcp_tool") == self.tool_name:
            return True
        return False

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        """执行 MCP Tool"""
        # 解析参数
        arguments = self._parse_arguments(user_input)
        
        logger.info(f"[MCP Skill] 调用 {self.tool_name}({arguments})")
        result = self.mcp_client.call_tool(self.server, self.tool_name, arguments)
        
        if result.success:
            return SkillResult(
                content=f"[{self.tool_name}]\n{result.content}",
                metadata={"tool": self.tool_name, "server": self.server, "args": arguments}
            )
        else:
            return SkillResult(
                content=f"[{self.tool_name}] 调用失败: {result.error}",
                success=False,
                metadata={"tool": self.tool_name, "error": result.error}
            )

    def _parse_arguments(self, user_input: str) -> Dict:
        """
        从用户输入解析 tool 参数
        简单策略：/mcp tool_name 之后的所有内容作为单个 "input" 参数
        复杂 schema 需要 LLM 辅助解析
        """
        prefix = f"/mcp {self.tool_name}"
        remaining = user_input.strip()
        if remaining.startswith(prefix):
            remaining = remaining[len(prefix):].strip()
        
        # 简单参数提取：如果没有复杂 schema，直接作为 input 传入
        return {"input": remaining} if remaining else {}


class MCPRouterSkill(Skill):
    """
    MCP 路由 Skill
    用 LLM 判断用户意图，自动选择并调用最合适的 MCP Tool
    用户无需记住 /mcp 命令
    """

    name = "mcp_router"
    description = "智能路由到 MCP 工具（搜索、浏览、文件操作等）"
    triggers = ["/search", "/browse", "/fetch", r"r:搜索", r"r:查一下", r"r:浏览"]
    priority = 65

    def __init__(self, mcp_client: MCPClient, llm_client=None):
        self.mcp_client = mcp_client
        self.llm_client = llm_client

    def can_handle(self, user_input: str, context: Dict) -> bool:
        return self._match_triggers(user_input)

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        """
        1. 获取所有可用 MCP tools
        2. 用 LLM 判断用户意图，选择最佳 tool + 参数
        3. 执行 tool
        4. 返回结果
        """
        tools = self.mcp_client.list_tools()
        if not tools:
            return SkillResult(content="暂无可用的 MCP 工具。", success=False)

        # 构建 tool 描述
        tool_descriptions = []
        for t in tools:
            tool_descriptions.append(f"- {t.name}: {t.description}")
        tools_text = "\n".join(tool_descriptions)

        # 用 LLM 做路由决策
        if self.llm_client:
            prompt = f"""你是一个工具路由助手。根据用户请求，选择最合适的工具。

可用工具:
{tools_text}

用户请求: {user_input}

请输出 JSON 格式:
{{
  "tool": "工具名称",
  "arguments": {{"参数名": "参数值"}},
  "reason": "选择理由"
}}

如果没有合适工具，输出 {{"tool": null}}"""
            
            try:
                raw = self.llm_client.quick_chat(prompt, system="你只输出 JSON，不要解释。")
                import json
                decision = json.loads(raw.strip().strip("`").replace("```json", "").replace("```", ""))
                tool_name = decision.get("tool")
                arguments = decision.get("arguments", {})
                
                if not tool_name:
                    return SkillResult(content="没有找到合适的工具来处理这个请求。", success=False)
                
                result = self.mcp_client.call_tool_by_name(tool_name, arguments)
                if result.success:
                    return SkillResult(
                        content=f"【{tool_name}】\n{result.content}",
                        metadata={"tool": tool_name, "args": arguments, "reason": decision.get("reason", "")}
                    )
                else:
                    return SkillResult(content=f"【{tool_name}】调用失败: {result.error}", success=False)
            except Exception as e:
                logger.warning(f"[MCP Router] LLM 路由失败: {e}")
                return SkillResult(content=f"工具路由失败: {e}", success=False)
        
        # 无 LLM 时 fallback：列出可用工具
        return SkillResult(
            content=f"可用 MCP 工具:\n{tools_text}\n\n请使用 `/mcp <工具名> <参数>` 调用。",
            metadata={"tools": [t.name for t in tools]}
        )
