"""
LLM 客户端抽象接口
后续接入 OpenAI / Claude / 本地模型时，只需实现此接口并注入即可
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, List, Optional, Union
import numpy as np


class LLMClient(ABC):
    """大语言模型客户端接口"""

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
