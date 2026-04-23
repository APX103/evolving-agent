"""
任务规划器
将用户的长程任务分解为可执行的步骤计划
支持同步 + 异步双模式
"""
import logging
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field

from agent.llm.base import LLMClient
from agent.structured_output import StructuredOutputExtractor
from agent.plan import Plan, Step, StepStatus

logger = logging.getLogger(__name__)


PLANNER_SYSTEM_PROMPT = """你是一个任务规划专家。请将用户的请求分解为清晰的执行步骤。

可用工具:
- llm: 调用大语言模型进行推理、分析、写作
- mcp:fetch: 获取网页内容（URL → 文本）
- mcp:filesystem: 读写本地文件
- sandbox: 执行 Python 代码
- skill:calc: 简单数学计算
- skill:edit: 精确编辑代码文件
- skill:map: 查看代码结构
- skill:test: 运行测试
- skill:git: 版本控制操作

规划原则:
1. 每个步骤只做一件事
2. 步骤间有明确依赖关系时标注 depends_on
3. 如果某步骤可以用代码/工具完成，不要交给 llm
4. 最后一步总是 "总结"，汇总前面所有结果

只输出 JSON，不要解释。"""


class StepSchema(BaseModel):
    """规划步骤 Schema"""
    id: int
    description: str
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[int] = Field(default_factory=list)


class PlanSchema(BaseModel):
    """规划结果 Schema"""
    needs_planning: bool
    steps: List[StepSchema]
    reason: str = ""


class Planner:
    """
    任务规划器
    使用 LLM 将用户请求分解为 Plan
    """

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.extractor = StructuredOutputExtractor(llm_client)

    async def adecompose(self, task: str, available_tools: list = None) -> Optional[Plan]:
        """
        异步核心：将任务分解为执行计划
        返回 Plan 或 None（如果不需要规划，直接走单轮 chat）
        """
        tools_text = ""
        if available_tools:
            tools_text = "\n".join([f"- {t}" for t in available_tools])
        else:
            tools_text = """- llm: 大语言模型推理
- mcp:fetch: 获取网页
- mcp:filesystem: 文件操作
- sandbox: Python 代码执行
- skill:calc: 数学计算
- skill:edit: 代码精确编辑
- skill:map: 代码结构分析
- skill:test: 运行测试
- skill:git: 版本控制"""

        prompt = f"""请将以下任务分解为执行步骤：

任务: {task}

可用工具:
{tools_text}

输出格式（JSON）：
{{
  "needs_planning": true/false,
  "steps": [
    {{
      "id": 1,
      "description": "步骤描述",
      "tool": "工具名",
      "arguments": {{"参数": "值"}},
      "depends_on": []
    }}
  ],
  "reason": "规划理由"
}}

注意:
- id 从 1 开始递增
- depends_on 填依赖的 id 列表（如 [1] 表示依赖步骤 1）
- tool 必须是可用工具之一"""

        try:
            schema = await self.llm_client.achat_structured(
                prompt,
                response_model=PlanSchema,
                system=PLANNER_SYSTEM_PROMPT,
            )

            if not schema.needs_planning:
                return None  # 不需要规划，走正常 chat

            steps = []
            for s in schema.steps:
                steps.append(Step(
                    id=s.id,
                    description=s.description,
                    tool=s.tool,
                    arguments=s.arguments,
                    depends_on=s.depends_on,
                    status=StepStatus.PENDING,
                ))

            return Plan(task=task, steps=steps)

        except Exception as e:
            raw_str = getattr(e, "raw_text", "")[:200] if hasattr(e, "raw_text") else "N/A"
            logger.warning(f"[Planner] 规划失败: {e}, raw={raw_str}")
            return None

    def should_plan(self, user_input: str) -> bool:
        """
        快速判断用户输入是否需要任务规划
        启发式：包含多个动作词、或显式 /plan 命令
        """
        text = user_input.strip()
        if text.startswith("/plan"):
            return True

        # 启发式：包含"然后"、"接着"、"第一步"、"先...再..."等
        planning_signals = ["然后", "接着", "第一步", "先", "再", "最后", "帮我", "给我", "整理", "总结"]
        signal_count = sum(1 for s in planning_signals if s in text)
        return signal_count >= 2 and len(text) > 20
