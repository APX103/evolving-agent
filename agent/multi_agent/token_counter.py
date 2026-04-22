"""
Token 计数器 - 优先 tiktoken，fallback 字符估算
"""
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class TokenCounter:
    def __init__(self):
        self._encoder = None
        self._init_encoder()

    def _init_encoder(self):
        try:
            import tiktoken
            self._encoder = tiktoken.get_encoding("cl100k_base")
            logger.info("[TokenCounter] 使用 tiktoken cl100k_base")
        except ImportError:
            self._encoder = None
            logger.info("[TokenCounter] tiktoken 不可用，使用字符估算")

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._encoder:
            return len(self._encoder.encode(text))
        return int(len(text) * 0.6)

    def count_messages(self, messages: List[Dict]) -> int:
        total = 0
        for m in messages:
            total += self.count(m.get("content", ""))
            total += 4  # 格式开销
        return total
