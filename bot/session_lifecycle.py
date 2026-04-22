"""
会话生命周期管理器 - 30min TTL + 自动启停
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional

from bot.feishu_message import UnifiedMessage

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    user_id: str
    started_at: datetime
    last_active: datetime
    is_active: bool = True
    metadata: Dict = field(default_factory=dict)

    def is_expired(self, ttl_seconds: int) -> bool:
        return datetime.now() - self.last_active > timedelta(seconds=ttl_seconds)


class SessionLifecycleManager:
    """会话生命周期管理：30min TTL，自动 end_session/start_session"""

    def __init__(self, ttl_seconds: int = 1800):
        self.ttl = ttl_seconds
        self._sessions: Dict[str, SessionState] = {}
        self._timers: Dict[str, Optional[asyncio.TimerHandle]] = {}
        self.logger = logging.getLogger(__name__)

    async def on_message(self, user_id: str, message: UnifiedMessage) -> bool:
        """
        收到消息时调用
        返回: 是否应该处理此消息
        """
        # 群聊中未 @机器人，跳过
        if message.chat_type == "group" and not message.mention_bot:
            self.logger.debug(f"[Session] 群聊消息未 @机器人，跳过: {user_id}")
            return False

        state = self._sessions.get(user_id)

        if state is None or state.is_expired(self.ttl):
            if state:
                self.logger.info(f"[Session] 会话过期，结束: {user_id}")
                await self._end_session(user_id)
            self.logger.info(f"[Session] 新会话开始: {user_id}")
            await self._start_session(user_id)
        else:
            state.last_active = datetime.now()

        self._reset_timer(user_id)
        return True

    async def _start_session(self, user_id: str):
        self._sessions[user_id] = SessionState(
            user_id=user_id,
            started_at=datetime.now(),
            last_active=datetime.now()
        )

    async def _end_session(self, user_id: str):
        if user_id in self._sessions:
            self._sessions[user_id].is_active = False
            del self._sessions[user_id]
        if user_id in self._timers:
            timer = self._timers.pop(user_id)
            if timer:
                timer.cancel()

    def _reset_timer(self, user_id: str):
        if user_id in self._timers and self._timers[user_id]:
            self._timers[user_id].cancel()

        loop = asyncio.get_event_loop()
        self._timers[user_id] = loop.call_later(
            self.ttl,
            lambda: asyncio.create_task(self._on_session_timeout(user_id))
        )

    async def _on_session_timeout(self, user_id: str):
        self.logger.info(f"[Session] TTL 到期，结束会话: {user_id}")
        await self._end_session(user_id)

    def is_session_active(self, user_id: str) -> bool:
        state = self._sessions.get(user_id)
        return state is not None and state.is_active and not state.is_expired(self.ttl)

    def get_session_info(self, user_id: str) -> Optional[Dict]:
        state = self._sessions.get(user_id)
        if not state:
            return None
        return {
            "user_id": state.user_id,
            "started_at": state.started_at.isoformat(),
            "last_active": state.last_active.isoformat(),
            "is_active": state.is_active,
        }
