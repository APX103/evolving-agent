"""
Skills 模块：Agent 技能体系
"""
from agent.skills.base import Skill, SkillResult, SkillRegistry
from agent.skills.builtin import build_default_skills
from agent.skills.mcp_tool import MCPToolSkill, MCPRouterSkill

__all__ = [
    "Skill",
    "SkillResult",
    "SkillRegistry",
    "build_default_skills",
    "MCPToolSkill",
    "MCPRouterSkill",
]
