"""
Kimi API 客户端封装
使用 OpenAI 兼容接口
"""
import yaml
from openai import OpenAI
from typing import List, Dict, Optional


class KimiClient:
    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        
        kimi_cfg = cfg["kimi"]
        self.client = OpenAI(
            api_key=kimi_cfg["api_key"],
            base_url=kimi_cfg["base_url"]
        )
        self.model = kimi_cfg.get("model", "kimi-latest")
        self.max_tokens = kimi_cfg.get("max_tokens", 4096)
        self.temperature = kimi_cfg.get("temperature", 0.7)
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False
    ):
        """
        发送对话请求
        stream=True 时返回 generator，逐字 yield
        """
        try:
            if stream:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature or self.temperature,
                    max_tokens=max_tokens or self.max_tokens,
                    stream=True
                )
                return self._stream_generator(response)
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature or self.temperature,
                    max_tokens=max_tokens or self.max_tokens,
                    stream=False
                )
                return response.choices[0].message.content or ""
        
        except Exception as e:
            if stream:
                # 流式出错时 yield 错误信息
                yield f"[Kimi API 错误] {str(e)}"
            else:
                return f"[Kimi API 错误] {str(e)}"
    
    def _stream_generator(self, response):
        """流式响应生成器"""
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
    
    def quick_chat(self, prompt: str, system: str = "") -> str:
        """快速单次对话，用于内部处理（学习、反思等）"""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, temperature=0.3, max_tokens=2048, stream=False)
