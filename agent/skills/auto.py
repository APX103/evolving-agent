"""
Skill 自动生成器
复杂任务完成后，自动提取经验并生成可复用 Skill
"""
import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SkillOptimizationStep(BaseModel):
    """Skill 优化步骤 Schema"""
    order: int
    tool: str
    purpose: str
    notes: str = ""


class SkillOptimizationResult(BaseModel):
    """Skill 优化结果 Schema"""
    description: str = ""
    steps: List[SkillOptimizationStep] = Field(default_factory=list)
    pitfalls: List[str] = Field(default_factory=list)
    verification: List[str] = Field(default_factory=list)


class AutoSkillGenerator:
    """
    自动 Skill 生成器
    - 分析任务执行轨迹（plan steps + tool calls + results）
    - 提取通用步骤、常见陷阱、验证方法
    - 生成标准 SKILL.md 格式文件
    - 支持加载自生成 Skill 并匹配相似任务
    """

    def __init__(self, storage_path: str = "./storage/auto_skills"):
        self.storage_path = storage_path
        os.makedirs(self.storage_path, exist_ok=True)
        self._skill_index: Dict[str, Dict] = {}
        self._load_index()

    def generate_skill(self, task_description: str, execution_trace: List[Dict],
                       llm_client=None) -> Optional[Dict]:
        """
        从执行轨迹生成 Skill
        execution_trace: [{"step": 1, "tool": "llm", "input": "...", "output": "..."}, ...]
        """
        if len(execution_trace) < 2:
            logger.debug("[AutoSkill] 轨迹太短，跳过生成")
            return None

        # 1. 提取关键步骤（去重、简化）
        steps = self._extract_steps(execution_trace)

        # 2. 提取陷阱和注意事项
        pitfalls = self._extract_pitfalls(execution_trace)

        # 3. 生成 Skill 元数据
        skill_name = self._normalize_name(task_description)
        skill = {
            "name": skill_name,
            "description": f"自动生成的 Skill: {task_description[:80]}",
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "source_task": task_description,
            "steps": steps,
            "pitfalls": pitfalls,
            "verification": self._extract_verification(execution_trace),
            "keywords": self._extract_keywords(task_description),
            "use_count": 0,
            "success_count": 0,
        }

        # 4. 如果有 LLM，用 LLM 优化 Skill 描述
        if llm_client and len(execution_trace) >= 3:
            try:
                optimized = self._llm_optimize(skill, llm_client)
                if optimized:
                    skill.update(optimized)
            except Exception as e:
                logger.warning(f"[AutoSkill] LLM 优化失败: {e}")

        # 5. 保存
        self._save_skill(skill)
        self._index_skill(skill)

        logger.info(f"[AutoSkill] 生成 Skill: {skill_name} ({len(steps)} 步骤)")
        return skill

    def find_matching_skill(self, task_description: str) -> Optional[Dict]:
        """根据任务描述匹配已生成的 Skill"""
        desc_lower = task_description.lower()
        best_match = None
        best_score = 0.0

        for skill in self._skill_index.values():
            score = 0.0
            # 关键词匹配
            keywords = skill.get("keywords", [])
            for kw in keywords:
                if kw.lower() in desc_lower:
                    score += 2.0

            # 任务描述相似度
            source = skill.get("source_task", "").lower()
            if source in desc_lower or desc_lower in source:
                score += 3.0

            # 成功率高优先
            use_count = skill.get("use_count", 0)
            success_count = skill.get("success_count", 0)
            if use_count > 0:
                score += (success_count / use_count) * 2.0

            if score > best_score and score >= 2.0:
                best_score = score
                best_match = skill

        if best_match:
            logger.info(f"[AutoSkill] 匹配 Skill: {best_match['name']} (score={best_score:.1f})")
        return best_match

    def record_success(self, skill_name: str):
        """记录 Skill 使用成功"""
        if skill_name in self._skill_index:
            self._skill_index[skill_name]["use_count"] = self._skill_index[skill_name].get("use_count", 0) + 1
            self._skill_index[skill_name]["success_count"] = self._skill_index[skill_name].get("success_count", 0) + 1
            self._skill_index[skill_name]["last_used"] = datetime.now().isoformat()
            self._save_index()

    def record_failure(self, skill_name: str):
        """记录 Skill 使用失败"""
        if skill_name in self._skill_index:
            self._skill_index[skill_name]["use_count"] = self._skill_index[skill_name].get("use_count", 0) + 1
            self._save_index()

    def list_skills(self) -> List[Dict]:
        """列出所有自动生成的 Skill"""
        return list(self._skill_index.values())

    # ── 内部提取逻辑 ──

    def _extract_steps(self, trace: List[Dict]) -> List[Dict]:
        """从执行轨迹提取通用步骤"""
        steps = []
        seen_tools = set()
        for item in trace:
            tool = item.get("tool", "unknown")
            if tool in seen_tools and tool in ("llm", "chat"):
                continue
            seen_tools.add(tool)
            steps.append({
                "order": len(steps) + 1,
                "tool": tool,
                "purpose": item.get("input", "")[:100],
                "notes": item.get("output", "")[:200],
            })
        return steps[:10]  # 最多 10 步

    def _extract_pitfalls(self, trace: List[Dict]) -> List[str]:
        """提取常见陷阱"""
        pitfalls = []
        for item in trace:
            output = item.get("output", "")
            if "error" in output.lower() or "失败" in output or "exception" in output.lower():
                # 提取错误信息
                error_msg = output.split("\n")[0][:150]
                if error_msg not in pitfalls:
                    pitfalls.append(f"注意: {error_msg}")
        # 如果没有任何错误，添加一些通用注意事项
        if not pitfalls:
            pitfalls.append("执行前请确认参数正确")
        return pitfalls[:5]

    def _extract_verification(self, trace: List[Dict]) -> List[str]:
        """提取验证方法"""
        verifications = []
        # 最后一步的输出通常包含结果验证
        if trace:
            last = trace[-1]
            output = last.get("output", "")
            if output:
                verifications.append(f"检查结果: {output[:100]}")
        verifications.append("确认输出符合预期格式")
        return verifications

    def _extract_keywords(self, task: str) -> List[str]:
        """提取任务关键词（滑动窗口分词）"""
        stopwords = {"帮我", "请", "一下", "的", "和", "在", "是", "了", "吗", "怎么", "如何", "什么",
                     "一个", "一下", "需要", "想要", "可以", "给我", "为你", "为你", "这个", "那个"}
        # 滑动窗口提取 2-4 字词
        candidates = set()
        for length in [4, 3, 2]:
            for i in range(len(task) - length + 1):
                word = task[i:i+length]
                # 只保留纯中文或纯英文
                if re.match(r'^[\u4e00-\u9fa5]+$', word) or re.match(r'^[a-zA-Z_]+$', word):
                    if word not in stopwords:
                        candidates.add(word)
        return sorted(candidates)[:8]

    def _normalize_name(self, task: str) -> str:
        """将任务描述规范化为 Skill 名称"""
        # 取前 4 个关键词拼接
        words = re.findall(r'[\u4e00-\u9fa5]{2,}|[a-zA-Z_]+', task)
        name = "_".join(words[:4]).lower()
        name = re.sub(r'[^\w\u4e00-\u9fff]', "_", name)
        timestamp = datetime.now().strftime("%m%d")
        return f"auto_{name}_{timestamp}"

    def _llm_optimize(self, skill: Dict, llm_client) -> Optional[Dict]:
        """用 LLM 优化 Skill 描述"""
        prompt = f"""请优化以下自动生成的 Skill，使其更清晰、更通用：

原始描述: {skill['source_task']}
步骤: {json.dumps(skill['steps'], ensure_ascii=False)}
陷阱: {json.dumps(skill['pitfalls'], ensure_ascii=False)}

请输出 JSON 格式：
{{
  "description": "更精炼的描述",
  "steps": [{{"order": 1, "tool": "...", "purpose": "...", "notes": "..."}}],
  "pitfalls": ["..."],
  "verification": ["..."]
}}
"""
        try:
            result = llm_client.chat_structured(
                prompt,
                response_model=SkillOptimizationResult,
                system="你是一个技术文档优化专家",
            )
            return result.model_dump()
        except Exception:
            return None

    # ── 持久化 ──

    def _skill_file(self, name: str) -> str:
        safe = re.sub(r'[^\w]', '_', name)
        return os.path.join(self.storage_path, f"{safe}.json")

    def _save_skill(self, skill: Dict):
        path = self._skill_file(skill["name"])
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(skill, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[AutoSkill] 保存 Skill 失败: {e}")

    def _load_index(self):
        """加载所有 Skill 到内存索引"""
        if not os.path.exists(self.storage_path):
            return
        for fname in os.listdir(self.storage_path):
            if fname.endswith(".json"):
                try:
                    with open(os.path.join(self.storage_path, fname), "r", encoding="utf-8") as f:
                        skill = json.load(f)
                        self._skill_index[skill["name"]] = skill
                except Exception:
                    continue
        logger.info(f"[AutoSkill] 加载 {len(self._skill_index)} 个自动 Skill")

    def _index_skill(self, skill: Dict):
        self._skill_index[skill["name"]] = skill
        self._save_index()

    def _save_index(self):
        index_path = os.path.join(self.storage_path, "index.json")
        try:
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(self._skill_index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[AutoSkill] 保存索引失败: {e}")
