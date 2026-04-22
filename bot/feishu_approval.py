"""
飞书审批 Card 渲染与回调处理
"""
import json
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class FeishuApprovalRenderer:
    """飞书审批 Card 渲染器"""

    @staticmethod
    def render(request_id: str, description: str, details: Optional[Dict] = None) -> Dict:
        """渲染交互式审批卡片（Card 2.0 格式）"""
        details_text = ""
        if details:
            for k, v in details.items():
                details_text += f"**{k}**: {v}\n"

        card = {
            "schema": "2.0",
            "header": {
                "title": {"tag": "plain_text", "content": "🔒 敏感操作需要确认"},
                "subtitle": {"tag": "plain_text", "content": description[:100]}
            },
            "body": {
                "elements": [
                    {"tag": "markdown", "content": details_text or description},
                    {"tag": "action", "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "✅ 确认执行"},
                            "type": "primary",
                            "value": {"action": "approve", "request_id": request_id}
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "❌ 拒绝"},
                            "type": "danger",
                            "value": {"action": "reject", "request_id": request_id}
                        }
                    ]}
                ]
            }
        }

        return {
            "msg_type": "interactive",
            "card": json.dumps(card, ensure_ascii=False)
        }


class FeishuApprovalHandler:
    """处理飞书审批回调"""

    def __init__(self):
        self._pending_cards: Dict[str, str] = {}  # request_id -> message_id
        self._callbacks: Dict[str, Dict] = {}     # request_id -> callback_data
        self.logger = logging.getLogger(__name__)

    def register_pending(self, request_id: str, message_id: str):
        """注册待审批的卡片"""
        self._pending_cards[request_id] = message_id

    def handle_callback(self, callback_data: Dict) -> Dict:
        """
        处理飞书 Card 回调
        返回: {"approved": bool, "request_id": str}
        """
        try:
            action = callback_data.get("action", {})
            action_type = action.get("value", {}).get("action", "")
            request_id = action.get("value", {}).get("request_id", "")

            self._callbacks[request_id] = callback_data

            if action_type == "approve":
                self.logger.info(f"[Approval] 用户确认: {request_id}")
                return {"approved": True, "request_id": request_id}
            elif action_type == "reject":
                self.logger.info(f"[Approval] 用户拒绝: {request_id}")
                return {"approved": False, "request_id": request_id}
            else:
                return {"approved": False, "request_id": request_id, "error": "未知操作"}

        except Exception as e:
            self.logger.error(f"[Approval] 回调处理失败: {e}")
            return {"approved": False, "error": str(e)}

    def get_pending_message_id(self, request_id: str) -> Optional[str]:
        return self._pending_cards.get(request_id)

    def remove_pending(self, request_id: str):
        self._pending_cards.pop(request_id, None)
