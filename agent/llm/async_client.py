"""
异步 LLM 客户端 - 基于 aiohttp + SSE
"""
import asyncio
import logging
import json
from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional, Union
import numpy as np

logger = logging.getLogger(__name__)


class AsyncLLMClient(ABC):
    @abstractmethod
    async def achat(self, messages: List[Dict], **kwargs) -> str: ...

    @abstractmethod
    async def astream_chat(self, messages: List[Dict], **kwargs) -> AsyncGenerator[str, None]: ...

    @abstractmethod
    async def aembed(self, texts: Union[str, List[str]]) -> np.ndarray: ...


class AsyncKimiClient(AsyncLLMClient):
    """基于 aiohttp 的异步 Kimi 客户端"""

    def __init__(self, config):
        from agent.config import Config
        cfg = config if isinstance(config, Config) else Config(config)
        kimi_cfg = cfg.kimi if hasattr(cfg, 'kimi') else cfg.raw.get("kimi", {})

        self.api_key = kimi_cfg.get("api_key", "")
        self.base_url = kimi_cfg.get("base_url", "https://api.moonshot.cn/v1")
        self.model = kimi_cfg.get("model", "kimi-latest")
        self.max_tokens = kimi_cfg.get("max_tokens", 4096)
        self.temperature = kimi_cfg.get("temperature", 0.7)
        self.embedding_model = kimi_cfg.get("embedding_model", "text-embedding")
        self.timeout = kimi_cfg.get("timeout", 30)
        self.max_retries = kimi_cfg.get("max_retries", 3)

        self._session: Optional[Any] = None
        self._semaphore = asyncio.Semaphore(kimi_cfg.get("connection_pool_size", 10))

    async def _get_session(self):
        if self._session is None or self._session.closed:
            import aiohttp
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=100, limit_per_host=20),
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            )
        return self._session

    async def achat(self, messages: List[Dict], temperature: Optional[float] = None,
                    max_tokens: Optional[int] = None) -> str:
        t = temperature if temperature is not None else self.temperature
        mt = max_tokens if max_tokens is not None else self.max_tokens

        async with self._semaphore:
            for attempt in range(self.max_retries):
                try:
                    session = await self._get_session()
                    payload = {
                        "model": self.model,
                        "messages": messages,
                        "temperature": t,
                        "max_tokens": mt,
                    }
                    async with session.post(f"{self.base_url}/chat/completions", json=payload) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            raise RuntimeError(f"API {resp.status}: {text[:200]}")
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"] or ""
                except Exception as e:
                    logger.warning(f"[AsyncKimi] achat 失败 (尝试 {attempt+1}/{self.max_retries}): {e}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        return f"[API 错误] {e}"
            return "[API 错误] 所有重试失败"

    async def astream_chat(self, messages: List[Dict], temperature: Optional[float] = None,
                           max_tokens: Optional[int] = None) -> AsyncGenerator[str, None]:
        t = temperature if temperature is not None else self.temperature
        mt = max_tokens if max_tokens is not None else self.max_tokens

        async with self._semaphore:
            for attempt in range(self.max_retries):
                try:
                    session = await self._get_session()
                    payload = {
                        "model": self.model,
                        "messages": messages,
                        "temperature": t,
                        "max_tokens": mt,
                        "stream": True,
                    }
                    async with session.post(f"{self.base_url}/chat/completions", json=payload) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            raise RuntimeError(f"API {resp.status}: {text[:200]}")
                        async for line in resp.content:
                            line = line.decode("utf-8").strip()
                            if line.startswith("data: "):
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    break
                                try:
                                    data = json.loads(data_str)
                                    delta = data["choices"][0]["delta"]
                                    content = delta.get("content") or ""
                                    if content:
                                        yield content
                                except (json.JSONDecodeError, KeyError):
                                    continue
                        return
                except Exception as e:
                    logger.warning(f"[AsyncKimi] stream 失败 (尝试 {attempt+1}/{self.max_retries}): {e}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        yield f"[API 错误] {e}"
                        return

    async def aembed(self, texts: Union[str, List[str]]) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]

        async with self._semaphore:
            for attempt in range(self.max_retries):
                try:
                    session = await self._get_session()
                    payload = {"model": self.embedding_model, "input": texts}
                    async with session.post(f"{self.base_url}/embeddings", json=payload) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            raise RuntimeError(f"Embed API {resp.status}: {text[:200]}")
                        data = await resp.json()
                        vectors = [item["embedding"] for item in data["data"]]
                        arr = np.array(vectors, dtype=np.float32)
                        if arr.ndim == 1:
                            arr = arr.reshape(1, -1)
                        return arr
                except Exception as e:
                    logger.warning(f"[AsyncKimi] embed 失败 (尝试 {attempt+1}/{self.max_retries}): {e}")
                    if attempt < self.max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                    else:
                        raise
