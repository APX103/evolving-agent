"""
任务规划数据模型
Plan + Step 定义
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class Step:
    """计划中的一个步骤"""
    id: int
    description: str           # 步骤描述（给人看）
    tool: str                  # 使用什么工具: "llm" | "mcp:<name>" | "skill:<name>" | "sandbox"
    arguments: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[int] = field(default_factory=list)  # 依赖的步骤 id
    status: StepStatus = StepStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    retry_count: int = 0


@dataclass
class Plan:
    """任务计划"""
    task: str                  # 原始任务描述
    steps: List[Step]
    status: StepStatus = StepStatus.PENDING
    current_step_id: int = 0
    summary: Optional[str] = None  # 最终结果摘要

    def get_step(self, step_id: int) -> Optional[Step]:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    def get_next_pending(self) -> Optional[Step]:
        """获取下一个可执行的 pending 步骤（所有依赖已完成）"""
        ready = self.get_ready_steps()
        return ready[0] if ready else None

    def get_ready_steps(self) -> List[Step]:
        """获取所有当前可执行的 pending 步骤（依赖全部成功完成）"""
        ready = []
        for s in self.steps:
            if s.status != StepStatus.PENDING:
                continue
            deps_satisfied = all(
                self.get_step(dep_id) and self.get_step(dep_id).status == StepStatus.SUCCESS
                for dep_id in s.depends_on
            )
            if deps_satisfied:
                ready.append(s)
        return ready

    def is_complete(self) -> bool:
        return all(s.status in (StepStatus.SUCCESS, StepStatus.FAILED) for s in self.steps)

    def is_success(self) -> bool:
        return all(s.status == StepStatus.SUCCESS for s in self.steps)

    def to_dict(self) -> Dict:
        return {
            "task": self.task,
            "status": self.status.value,
            "current_step_id": self.current_step_id,
            "summary": self.summary,
            "steps": [
                {
                    "id": s.id,
                    "description": s.description,
                    "tool": s.tool,
                    "arguments": s.arguments,
                    "depends_on": s.depends_on,
                    "status": s.status.value,
                    "result": s.result,
                    "error": s.error,
                    "retry_count": s.retry_count,
                }
                for s in self.steps
            ]
        }
