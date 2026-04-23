"""
LLM 客户端抽象接口
支持同步 + 异步双模式，后续接入 OpenAI / Claude / 本地模型时只需实现此接口
"""
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, Generator, List, Optional, Type, TypeVar, Union
import numpy as np


T = TypeVar("T")


class StructuredOutputError(Exception):
    """结构化输出解析失败时抛出，附带原始 LLM 文本"""

    def __init__(self, message: str, raw_text: str = ""):
        super().__init__(message)
        self.raw_text = raw_text


class LLMClient(ABC):
    """大语言模型客户端接口（同步 + 异步）"""

    # ── 同步接口 ──

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> Union[str, Generator[str, None, None]]:
        """
        发送对话请求
        stream=True 返回生成器，stream=False 返回字符串
        """
        pass

    @abstractmethod
    def quick_chat(self, prompt: str, system: str = "") -> str:
        """快速单次对话，用于内部处理"""
        pass

    @abstractmethod
    def embed(self, texts: Union[str, List[str]]) -> np.ndarray:
        """
        文本向量化
        返回: numpy array，shape 必须为 (n_texts, dim)
        """
        pass

    @abstractmethod
    def cosine_similarity(self, query_vec: np.ndarray, doc_vecs: np.ndarray) -> np.ndarray:
        """计算余弦相似度"""
        pass

    # ── 异步接口 ──

    @abstractmethod
    async def achat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
    ) -> Union[str, AsyncGenerator[str, None]]:
        """
        异步发送对话请求
        stream=True 返回异步生成器，stream=False 返回字符串
        """
        pass

    @abstractmethod
    async def aquick_chat(self, prompt: str, system: str = "") -> str:
        """异步快速单次对话"""
        pass

    @abstractmethod
    async def aembed(self, texts: Union[str, List[str]]) -> np.ndarray:
        """异步文本向量化"""
        pass

    # ── 结构化输出接口 ──

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

    def chat_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system: str = "",
        **kwargs,
    ) -> T:
        """
        调用 LLM 并强制解析为指定 Pydantic 模型
        解析失败时抛出 StructuredOutputError
        """
        from pydantic import ValidationError

        raw = self.quick_chat(prompt, system=system)
        cleaned = self._clean_json(raw)
        try:
            return response_model.model_validate_json(cleaned)
        except ValidationError as e:
            raise StructuredOutputError(
                f"Failed to validate structured output: {e}",
                raw_text=raw,
            ) from e
        except Exception as e:
            raise StructuredOutputError(
                f"Failed to parse structured output: {e}",
                raw_text=raw,
            ) from e

    async def achat_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system: str = "",
        **kwargs,
    ) -> T:
        """
        异步调用 LLM 并强制解析为指定 Pydantic 模型
        解析失败时抛出 StructuredOutputError
        """
        from pydantic import ValidationError

        raw = await self.aquick_chat(prompt, system=system)
        cleaned = self._clean_json(raw)
        try:
            return response_model.model_validate_json(cleaned)
        except ValidationError as e:
            raise StructuredOutputError(
                f"Failed to validate structured output: {e}",
                raw_text=raw,
            ) from e
        except Exception as e:
            raise StructuredOutputError(
                f"Failed to parse structured output: {e}",
                raw_text=raw,
            ) from e
