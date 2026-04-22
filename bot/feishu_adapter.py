"""
飞书机器人适配器 - 核心入口
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Dict, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class FeishuConfig:
    app_id: str
    app_secret: str
    encrypt_key: str = ""
    verification_token: str = ""
    bot_name: str = "Evo"
    session_ttl: int = 1800


class FeishuBotAdapter:
    """飞书机器人适配器"""

    API_BASE = "https://open.feishu.cn/open-apis"

    def __init__(self, config: FeishuConfig):
        self.config = config
        self._token: Optional[str] = None
        self._token_expire: float = 0
        self.logger = logging.getLogger(__name__)

    async def _get_tenant_access_token(self) -> str:
        """获取租户访问令牌（带缓存）"""
        import time
        import aiohttp

        if self._token and time.time() < self._token_expire - 300:
            return self._token

        url = f"{self.API_BASE}/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.config.app_id, "app_secret": self.config.app_secret}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if data.get("code") == 0:
                    self._token = data["tenant_access_token"]
                    self._token_expire = time.time() + data.get("expire", 7200)
                    return self._token
                raise RuntimeError(f"获取 token 失败: {data}")

    async def send_message(self, chat_id: str, content: Union[str, Dict],
                          msg_type: str = "text", message_id: str = None) -> str:
        """发送消息，如果 message_id 提供则编辑"""
        import aiohttp

        token = await self._get_tenant_access_token()

        if isinstance(content, str):
            if msg_type == "markdown":
                payload = {"receive_id": chat_id, **MessageFormatter.to_feishu_markdown(content)}
            else:
                payload = {"receive_id": chat_id, **MessageFormatter.to_feishu_text(content)}
        else:
            payload = {"receive_id": chat_id, **content}

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        if message_id:
            # 编辑消息
            url = f"{self.API_BASE}/im/v1/messages/{message_id}"
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, json=payload, headers=headers) as resp:
                    data = await resp.json()
                    if data.get("code") == 0:
                        return data["data"]["message_id"]
                    self.logger.error(f"[Feishu] 编辑消息失败: {data}")
                    return ""
        else:
            # 发送新消息
            url = f"{self.API_BASE}/im/v1/messages?receive_id_type=chat_id"
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    data = await resp.json()
                    if data.get("code") == 0:
                        return data["data"]["message_id"]
                    self.logger.error(f"[Feishu] 发送消息失败: {data}")
                    return ""

    async def send_typing_indicator(self, chat_id: str):
        """发送正在输入状态"""
        import aiohttp
        token = await self._get_tenant_access_token()
        url = f"{self.API_BASE}/im/v1/chats/{chat_id}/typing"
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"type": "text"}
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(url, json=payload, headers=headers)
        except Exception as e:
            self.logger.debug(f"[Feishu] 发送 typing 失败: {e}")

    async def start(self):
        """启动 HTTP server"""
        from fastapi import FastAPI, Request, Response
        import uvicorn

        app = FastAPI()

        @app.post("/webhook")
        async def webhook(request: Request):
            body = await request.body()
            try:
                data = json.loads(body)
                # URL 验证
                if "challenge" in data:
                    return {"challenge": data["challenge"]}
                # 处理事件
                result = await self._handle_event(data)
                return result or {"status": "ok"}
            except Exception as e:
                self.logger.error(f"[Feishu] Webhook 处理失败: {e}")
                return {"status": "error"}

        @app.get("/health")
        async def health():
            return {"status": "ok"}

        self.logger.info(f"[Feishu] HTTP server 启动在 0.0.0.0:8080")
        config = uvicorn.Config(app, host="0.0.0.0", port=8080, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    async def _handle_event(self, event: Dict):
        """处理飞书事件"""
        from bot.feishu_event_handler import FeishuEventHandler
        handler = FeishuEventHandler(self.config)
        return await handler.handle_event(event)


# 避免循环导入
from bot.feishu_message import MessageFormatter
