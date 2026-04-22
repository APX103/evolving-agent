"""
Human-in-the-Loop 敏感操作审批
支持 CLI 阻塞模式、非阻塞模式和自动审批模式
"""
import logging
import uuid
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class ApprovalRequest:
    """审批请求"""
    action_type: str
    description: str
    details: Dict
    request_id: str
    state: ApprovalState = ApprovalState.PENDING


@dataclass
class ApprovalResult:
    """审批结果"""
    approved: bool
    pending: bool = False
    request_id: Optional[str] = None
    reason: Optional[str] = None


class ApprovalManager:
    """
    敏感操作审批管理器
    支持三种模式：
    - blocking (CLI): 直接 input() 等待用户确认
    - nonblocking (Web): 将请求加入 pending 队列，返回 pending 状态
    - auto: 根据 auto_approve 配置自动通过（仅用于测试/沙箱环境）
    """

    # 默认需要审批的操作类型
    DEFAULT_SENSITIVE_ACTIONS = {
        "shell",           # Shell 命令
        "file_write",      # 文件写入/覆盖
        "file_delete",     # 文件删除
        "mcp:filesystem:write",
        "mcp:filesystem:delete",
    }

    def __init__(self, config: Optional[Dict] = None, mode: str = "blocking"):
        self.enabled = True
        self.mode = mode  # "blocking" | "nonblocking" | "auto"
        self.sensitive_actions = set(self.DEFAULT_SENSITIVE_ACTIONS)
        self._pending: Dict[str, ApprovalRequest] = {}
        self._auto_approve = False

        if config:
            self.enabled = config.get("enabled", True)
            self._auto_approve = config.get("auto_approve", False)
            custom_actions = config.get("require_approval_for", [])
            if custom_actions:
                self.sensitive_actions = set(custom_actions)
            # 配置可覆盖模式
            if "mode" in config:
                self.mode = config["mode"]

    def requires_approval(self, action_type: str) -> bool:
        """判断此操作是否需要审批"""
        if not self.enabled:
            return False
        if self.mode == "auto" or self._auto_approve:
            return False
        return action_type in self.sensitive_actions

    def request_approval(self, action_type: str, description: str, details: Dict) -> ApprovalResult:
        """
        请求用户审批
        - blocking 模式：打印到终端，等待用户输入 y/n
        - nonblocking 模式：返回 pending 状态，请求加入队列等待外部处理
        - auto 模式：直接通过
        """
        if not self.requires_approval(action_type):
            return ApprovalResult(approved=True)

        req = ApprovalRequest(
            action_type=action_type,
            description=description,
            details=details,
            request_id=str(uuid.uuid4())[:8],
        )
        self._pending[req.request_id] = req

        if self.mode == "auto" or self._auto_approve:
            del self._pending[req.request_id]
            return ApprovalResult(approved=True)

        if self.mode == "nonblocking":
            logger.info(f"[Approval] 请求 {req.request_id} 等待审批: {description}")
            return ApprovalResult(
                approved=False,
                pending=True,
                request_id=req.request_id,
                reason="等待用户审批",
            )

        # blocking 模式（CLI）
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
            req.state = ApprovalState.APPROVED if approved else ApprovalState.REJECTED
            del self._pending[req.request_id]
            return ApprovalResult(
                approved=approved,
                request_id=req.request_id,
                reason=None if approved else "用户拒绝",
            )
        except (EOFError, KeyboardInterrupt):
            req.state = ApprovalState.REJECTED
            del self._pending[req.request_id]
            return ApprovalResult(approved=False, request_id=req.request_id, reason="输入中断")

    def get_pending(self) -> List[ApprovalRequest]:
        """获取所有待审批的请求（nonblocking 模式下使用）"""
        return list(self._pending.values())

    def get_pending_by_id(self, request_id: str) -> Optional[ApprovalRequest]:
        """获取指定待审批请求"""
        return self._pending.get(request_id)

    def approve(self, request_id: str) -> ApprovalResult:
        """外部批准请求（Web 模式）"""
        req = self._pending.pop(request_id, None)
        if req:
            req.state = ApprovalState.APPROVED
            return ApprovalResult(approved=True, request_id=request_id)
        return ApprovalResult(approved=False, request_id=request_id, reason="请求不存在或已处理")

    def reject(self, request_id: str, reason: str = "用户拒绝") -> ApprovalResult:
        """外部拒绝请求（Web 模式）"""
        req = self._pending.pop(request_id, None)
        if req:
            req.state = ApprovalState.REJECTED
            return ApprovalResult(approved=False, request_id=request_id, reason=reason)
        return ApprovalResult(approved=False, request_id=request_id, reason="请求不存在或已处理")
