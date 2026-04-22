"""
Human-in-the-Loop 敏感操作审批
危险操作执行前暂停，等待用户确认
"""
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ApprovalRequest:
    """审批请求"""
    action_type: str
    description: str
    details: Dict
    request_id: str


@dataclass
class ApprovalResult:
    """审批结果"""
    approved: bool
    reason: Optional[str] = None


class ApprovalManager:
    """
    敏感操作审批管理器
    """

    # 默认需要审批的操作类型
    DEFAULT_SENSITIVE_ACTIONS = {
        "shell",           # Shell 命令
        "file_write",      # 文件写入/覆盖
        "file_delete",     # 文件删除
        "mcp:filesystem:write",
        "mcp:filesystem:delete",
    }

    def __init__(self, config: Optional[Dict] = None):
        self.enabled = True
        self.sensitive_actions = set(self.DEFAULT_SENSITIVE_ACTIONS)
        self._pending: Dict[str, ApprovalRequest] = {}

        if config:
            self.enabled = config.get("enabled", True)
            custom_actions = config.get("require_approval_for", [])
            if custom_actions:
                self.sensitive_actions = set(custom_actions)

    def requires_approval(self, action_type: str) -> bool:
        """判断此操作是否需要审批"""
        if not self.enabled:
            return False
        return action_type in self.sensitive_actions

    def request_approval(self, action_type: str, description: str, details: Dict) -> ApprovalResult:
        """
        请求用户审批
        CLI 模式：打印到终端，等待用户输入 y/n
        Web 模式：返回待审批状态，前端显示确认弹窗
        """
        if not self.requires_approval(action_type):
            return ApprovalResult(approved=True)

        req = ApprovalRequest(
            action_type=action_type,
            description=description,
            details=details,
            request_id=f"{action_type}_{id(details)}",
        )
        self._pending[req.request_id] = req

        # CLI 模式下直接询问
        print(f"\n🔒 敏感操作需要确认:")
        print(f"   操作: {description}")
        print(f"   类型: {action_type}")
        if details:
            for k, v in details.items():
                print(f"   {k}: {v}")
        print()

        try:
            answer = input("确认执行? [y/N]: ").strip().lower()
            approved = answer in ("y", "yes", "是", "确认")
            del self._pending[req.request_id]
            return ApprovalResult(approved=approved, reason="用户拒绝" if not approved else None)
        except (EOFError, KeyboardInterrupt):
            return ApprovalResult(approved=False, reason="输入中断")

    def approve(self, request_id: str) -> bool:
        """Web 模式：外部批准请求"""
        if request_id in self._pending:
            del self._pending[request_id]
            return True
        return False

    def reject(self, request_id: str) -> bool:
        """Web 模式：外部拒绝请求"""
        return self.approve(request_id)  # 从 pending 中移除即可
