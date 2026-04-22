"""
飞书消息模型与格式转换
"""
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class UnifiedMessage:
    """统一消息格式（所有端通用）"""
    message_id: str
    user_id: str
    chat_id: str
    chat_type: str  # "p2p" | "group"
    content: str
    content_type: str = "text"  # text | markdown | card | image
    mention_bot: bool = False
    create_time: int = 0
    raw: Dict = field(default_factory=dict)


class MessageFormatter:
    """消息格式转换器：统一格式 <-> 飞书格式"""

    @staticmethod
    def to_feishu_text(content: str) -> Dict:
        return {"msg_type": "text", "content": json.dumps({"text": content}, ensure_ascii=False)}

    @staticmethod
    def to_feishu_markdown(content: str) -> Dict:
        return {
            "msg_type": "interactive",
            "card": json.dumps({
                "schema": "2.0",
                "body": {"elements": [{"tag": "markdown", "content": content}]}
            }, ensure_ascii=False)
        }

    @staticmethod
    def from_feishu_message(event: Dict) -> Optional[UnifiedMessage]:
        """从飞书事件转换为统一消息"""
        try:
            message = event.get("message", {})
            sender = event.get("sender", {})
            chat = event.get("message", {}).get("chat_id", "")
            chat_type = event.get("message", {}).get("chat_type", "p2p")

            msg_type = message.get("msg_type", "text")
            content_raw = message.get("content", "{}")
            try:
                content_json = json.loads(content_raw)
            except json.JSONDecodeError:
                content_json = {"text": content_raw}

            # 解析文本内容
            text_content = ""
            if msg_type == "text":
                text_content = content_json.get("text", "")
            elif msg_type == "post":
                text_content = MessageFormatter._extract_post_text(content_json)
            elif msg_type == "interactive":
                text_content = content_json.get("text", "[卡片消息]")

            # 检查是否 @了机器人
            mentions = message.get("mentions", [])
            mention_bot = any(
                m.get("key") == "@_user_1" or m.get("tenant_key") == ""
                for m in mentions
            )

            return UnifiedMessage(
                message_id=message.get("message_id", ""),
                user_id=sender.get("sender_id", {}).get("user_id", ""),
                chat_id=chat,
                chat_type=chat_type,
                content=text_content,
                content_type=msg_type if msg_type in ("text", "markdown", "card", "image") else "text",
                mention_bot=mention_bot,
                create_time=int(message.get("create_time", "0")),
                raw=event
            )
        except Exception as e:
            logger.error(f"[MessageFormatter] 解析飞书消息失败: {e}")
            return None

    @staticmethod
    def _extract_post_text(content: Dict) -> str:
        """从 post 类型消息中提取文本"""
        parts = []
        content_list = content.get("content", [])
        for item in content_list:
            if isinstance(item, list):
                for sub in item:
                    if isinstance(sub, dict):
                        tag = sub.get("tag", "")
                        if tag == "text":
                            parts.append(sub.get("text", ""))
                        elif tag == "at":
                            parts.append(f"@{sub.get('user_name', '')}")
        return "".join(parts)

    @staticmethod
    def remove_mention_text(text: str, bot_name: str = "") -> str:
        """移除消息中的 @机器人 文本"""
        import re
        # 移除 @_user_1 格式
        text = re.sub(r'@_user_\d+\s*', '', text)
        # 移除 @bot_name 格式
        if bot_name:
            text = re.sub(rf'@{re.escape(bot_name)}\s*', '', text, flags=re.IGNORECASE)
        return text.strip()
