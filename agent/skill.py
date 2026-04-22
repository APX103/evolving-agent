"""
Skill 插件系统
可扩展的能力模块，Agent 可动态识别并调用
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import re


@dataclass
class SkillResult:
    """Skill 执行结果"""
    content: str                          # 返回给用户的内容
    success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)  # 🔧 避免共享可变默认 None
    should_learn: bool = True             # 结果是否值得写入记忆


class Skill(ABC):
    """
    Skill 基类
    所有能力模块继承此类
    """
    
    name: str = "base"
    description: str = "基础能力"
    triggers: List[str] = []        # 触发关键词/正则
    priority: int = 0               # 优先级，高优先先匹配
    
    @abstractmethod
    def can_handle(self, user_input: str, context: Dict) -> bool:
        """
        判断当前输入是否由本 Skill 处理
        context: 包含短期记忆、用户画像等上下文
        """
        pass
    
    @abstractmethod
    def execute(self, user_input: str, context: Dict) -> SkillResult:
        """
        执行 Skill，返回结果
        """
        pass
    
    def _match_triggers(self, text: str) -> bool:
        """基于关键词/正则匹配"""
        for trigger in self.triggers:
            if trigger.startswith("/"):
                # 命令式触发（如 /search）
                if text.strip().startswith(trigger):
                    return True
            elif trigger.startswith("r:"):
                # 正则触发
                pattern = trigger[2:]
                if re.search(pattern, text, re.IGNORECASE):
                    return True
            else:
                # 普通关键词
                if trigger.lower() in text.lower():
                    return True
        return False


class SkillRegistry:
    """
    Skill 注册中心
    管理所有可用 Skill，负责路由匹配
    """
    
    def __init__(self):
        self._skills: List[Skill] = []
    
    def register(self, skill: Skill):
        """注册 Skill"""
        self._skills.append(skill)
        # 按优先级排序
        self._skills.sort(key=lambda s: s.priority, reverse=True)
    
    def unregister(self, skill_name: str):
        """卸载 Skill"""
        self._skills = [s for s in self._skills if s.name != skill_name]
    
    def find_handler(self, user_input: str, context: Dict) -> Optional[Skill]:
        """
        找到能处理当前输入的 Skill
        按优先级顺序匹配，第一个匹配的胜出
        """
        for skill in self._skills:
            try:
                if skill.can_handle(user_input, context):
                    return skill
            except Exception:
                continue
        return None
    
    def list_skills(self) -> List[Dict]:
        """列出所有已注册 Skill"""
        return [
            {"name": s.name, "description": s.description, "priority": s.priority}
            for s in self._skills
        ]
