"""
飞书 WebSocket 客户端 - 事件订阅长连接
支持自动重连、心跳保活、消息分发
"""
import asyncio
import json
import logging
import time
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class WebSocketClient:
    """飞书 WebSocket 事件订阅客户端"""

    # 飞书 WebSocket 网关（国际版）
    WS_BOOT_URL = "wss://wsboot.byteoversea.com/websocket"
    # 心跳间隔（秒）
    HEARTBEAT_INTERVAL = 30
    # 重连退避配置
    RECONNECT_MIN = 2
    RECONNECT_MAX = 60

    def __init__(self, config, event_handler: Optional[Callable] = None):
        self.config = config
        self.event_handler = event_handler
        self._ws = None
        self._session = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._reconnect_delay = self.RECONNECT_MIN
        self._running = False
        self._device_id = f"evo_{int(time.time())}"
        self.logger = logging.getLogger(__name__)

    async def connect(self):
        """建立 WebSocket 连接并启动事件循环"""
        self._running = True
        while self._running:
            try:
                await self._connect_once()
                # 连接成功后重置退避
                self._reconnect_delay = self.RECONNECT_MIN
            except Exception as e:
                self.logger.error(f"[WebSocket] 连接异常: {e}")
                await self._backoff_reconnect()

    async def _connect_once(self):
        """单次连接尝试"""
        import aiohttp

        token = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Device-Id": self._device_id,
        }

        self.logger.info(f"[WebSocket] 连接到 {self.WS_BOOT_URL}")

        self._session = aiohttp.ClientSession()
        async with self._session.ws_connect(
            self.WS_BOOT_URL,
            headers=headers,
            heartbeat=self.HEARTBEAT_INTERVAL,
            autoping=True,
        ) as ws:
            self._ws = ws
            self.logger.info("[WebSocket] 连接成功")

            # 发送连接请求（ping）
            await self._send_ping()

            # 启动心跳
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # 消息接收循环
            async for msg in ws:
                if not self._running:
                    break
                await self._handle_message(msg)

    async def _handle_message(self, msg):
        """处理 WebSocket 消息"""
        import aiohttp

        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
                msg_type = data.get("type", "")

                if msg_type == "pong":
                    self.logger.debug("[WebSocket] 收到 pong")
                elif msg_type == "error":
                    self.logger.error(f"[WebSocket] 服务器错误: {data}")
                elif msg_type == "event":
                    # 分发事件
                    if self.event_handler:
                        await self.event_handler(data.get("event", {}))
                else:
                    # 未识别的消息类型也尝试作为事件处理
                    if self.event_handler and "header" in data:
                        await self.event_handler(data)
            except json.JSONDecodeError:
                self.logger.warning(f"[WebSocket] 无法解析消息: {msg.data[:200]}")
        elif msg.type == aiohttp.WSMsgType.CLOSED:
            self.logger.info("[WebSocket] 连接已关闭")
        elif msg.type == aiohttp.WSMsgType.ERROR:
            self.logger.error("[WebSocket] 连接错误")

    async def _heartbeat_loop(self):
        """心跳保活循环"""
        while self._running and self._ws:
            try:
                await asyncio.sleep(self.HEARTBEAT_INTERVAL)
                if self._ws and not self._ws.closed:
                    await self._send_ping()
            except Exception as e:
                self.logger.debug(f"[WebSocket] 心跳异常: {e}")
                break

    async def _send_ping(self):
        """发送 ping 消息"""
        if self._ws and not self._ws.closed:
            await self._ws.send_json({
                "type": "ping",
                "device_id": self._device_id,
                "timestamp": int(time.time())
            })

    async def _backoff_reconnect(self):
        """指数退避重连"""
        self.logger.info(f"[WebSocket] {self._reconnect_delay}秒后重连...")
        await asyncio.sleep(self._reconnect_delay)
        self._reconnect_delay = min(self._reconnect_delay * 2, self.RECONNECT_MAX)

    async def disconnect(self):
        """断开连接"""
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()
        self.logger.info("[WebSocket] 已断开")

    async def _get_access_token(self) -> str:
        """获取访问令牌"""
        import aiohttp
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {"app_id": self.config.app_id, "app_secret": self.config.app_secret}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if data.get("code") == 0:
                    return data["tenant_access_token"]
                raise RuntimeError(f"获取 token 失败: {data}")
