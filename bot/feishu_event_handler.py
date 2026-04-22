"""
飞书事件处理器
"""
import hashlib
import json
import logging
from typing import Dict, Optional

from bot.feishu_message import UnifiedMessage, MessageFormatter

logger = logging.getLogger(__name__)


class FeishuEventHandler:
    """处理飞书各类事件"""

    def __init__(self, config):
        self.config = config
        self.formatter = MessageFormatter()
        self.approval_handler = None  # 外部注入

    async def handle_event(self, event: Dict) -> Optional[Dict]:
        """分发处理飞书事件"""
        event_type = event.get("header", {}).get("event_type", "")

        if event_type == "im.message.receive_v1":
            return await self.handle_message(event)
        elif event_type == "card.action.trigger":
            return await self.handle_card_callback(event)
        elif "url_verification" in str(event):
            return self.handle_url_verification(event.get("challenge", ""))

        logger.debug(f"[FeishuEvent] 未处理的事件类型: {event_type}")
        return None

    async def handle_message(self, event: Dict) -> Dict:
        """处理消息事件"""
        msg = self.formatter.from_feishu_message(event.get("event", {}))
        if not msg:
            return {"status": "error", "reason": "消息解析失败"}

        # 移除 @机器人的文本
        if msg.mention_bot:
            msg.content = self.formatter.remove_mention_text(msg.content, self.config.bot_name)

        return {"status": "ok", "message": msg}

    async def handle_card_callback(self, event: Dict) -> Dict:
        """处理 Card 按钮回调"""
        if self.approval_handler:
            result = self.approval_handler.handle_callback(event.get("event", {}))
            return {"status": "ok", "approval_result": result}
        return {"status": "error", "reason": "审批处理器未配置"}

    def handle_url_verification(self, challenge: str) -> Dict:
        """处理 URL 验证"""
        return {"challenge": challenge}

    def verify_signature(self, timestamp: str, nonce: str, body: str, signature: str,
                        encrypt_key: str = "") -> bool:
        """验证飞书请求签名"""
        if not encrypt_key:
            return True  # 未配置加密密钥，跳过验证
        try:
            raw = f"{timestamp}{nonce}{encrypt_key}{body}"
            expected = hashlib.sha256(raw.encode()).hexdigest()
            return expected == signature
        except Exception:
            return False
