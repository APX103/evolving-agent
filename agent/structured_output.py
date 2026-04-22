"""
Pydantic 结构化输出工具
强制 LLM 输出符合指定 Schema，替代手动 json.loads() 解析
"""
import json
import logging
from typing import Type, TypeVar, List, Optional

from pydantic import BaseModel, Field, ValidationError

from agent.llm.base import LLMClient

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class StructuredOutputExtractor:
    """
    Pydantic 强制 LLM 输出指定 Schema
    使用 OpenAI-compatible JSON mode 或 tool_choice
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    def extract(self, model_cls: Type[T], prompt: str, system: str = "") -> Optional[T]:
        """
        调用 LLM 并强制解析为单个 Pydantic 模型
        解析失败时返回 None（不抛异常，保持鲁棒性）
        """
        try:
            raw = self.llm.quick_chat(prompt, system=system)
            cleaned = self._clean_json(raw)
            return model_cls.model_validate_json(cleaned)
        except (ValidationError, json.JSONDecodeError) as e:
            logger.warning(f"[StructuredOutput] 解析失败: {e}, raw={raw[:200]}")
            return None
        except Exception as e:
            logger.warning(f"[StructuredOutput] 提取异常: {e}")
            return None

    def extract_list(self, model_cls: Type[T], prompt: str, system: str = "") -> List[T]:
        """
        调用 LLM 并强制解析为 Pydantic 模型列表
        解析失败时返回空列表
        """
        try:
            raw = self.llm.quick_chat(prompt, system=system)
            cleaned = self._clean_json(raw)
            data = json.loads(cleaned)
            if not isinstance(data, list):
                if isinstance(data, dict):
                    data = [data]
                else:
                    return []
            results = []
            for item in data:
                if isinstance(item, dict):
                    try:
                        results.append(model_cls.model_validate(item))
                    except ValidationError as e:
                        logger.debug(f"[StructuredOutput] 单条验证失败: {e}")
            return results
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"[StructuredOutput] 列表解析失败: {e}, raw={raw[:200] if 'raw' in dir() else 'N/A'}")
            return []

    @staticmethod
    def _clean_json(text: str) -> str:
        """清理 markdown 代码块等包裹"""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()


# ── 通用知识提取模型 ──

class ExtractedKnowledgeItem(BaseModel):
    """结构化知识条目"""
    subject: str = Field(default="用户", description="知识主体")
    predicate: str = Field(default="知道", description="关系/谓词")
    object: str = Field(default="", description="客体/值")
    temporal_state: str = Field(default="current", pattern=r"^(current|past|planned|negated)$")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    category: str = Field(default="fact", description="类别: fact/preference/concept/lesson/profile")
    content: str = Field(default="", description="自然语言描述")


class JudgmentResultItem(BaseModel):
    """质检结果条目"""
    index: int = Field(ge=0)
    is_valid: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="")
    issue_type: Optional[str] = Field(default=None, description="hallucination|subject_confusion|temporal_error|unsupported")
