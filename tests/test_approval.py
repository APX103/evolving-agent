#!/usr/bin/env python3
"""
ApprovalManager 测试
- 三种模式: blocking / nonblocking / auto
- 审批策略: enabled / disabled / auto_approve
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.approval import ApprovalManager, ApprovalState


def test_requires_approval():
    print("[Approval] 测试 requires_approval...")
    mgr = ApprovalManager()
    assert mgr.requires_approval("shell") is True
    assert mgr.requires_approval("safe_action") is False
    print("   ✅ 审批策略判断正确")


def test_disabled():
    print("[Approval] 测试 disabled...")
    mgr = ApprovalManager(config={"enabled": False})
    assert mgr.requires_approval("shell") is False
    result = mgr.request_approval("shell", "test", {})
    assert result.approved is True
    print("   ✅ 禁用模式直接通过")


def test_auto_mode():
    print("[Approval] 测试 auto 模式...")
    mgr = ApprovalManager(config={"enabled": True}, mode="auto")
    assert mgr.requires_approval("shell") is False
    result = mgr.request_approval("shell", "test", {"cmd": "ls"})
    assert result.approved is True
    assert result.pending is False
    print("   ✅ auto 模式直接通过")


def test_nonblocking_mode():
    print("[Approval] 测试 nonblocking 模式...")
    mgr = ApprovalManager(config={"enabled": True}, mode="nonblocking")
    result = mgr.request_approval("shell", "执行 ls", {"cmd": "ls"})
    assert result.approved is False
    assert result.pending is True
    assert result.request_id is not None

    # 检查 pending 队列
    pending = mgr.get_pending()
    assert len(pending) == 1
    assert pending[0].action_type == "shell"

    # 外部批准
    approved = mgr.approve(result.request_id)
    assert approved.approved is True
    assert len(mgr.get_pending()) == 0

    # 再发一个，测试拒绝
    result2 = mgr.request_approval("file_write", "写入文件", {"path": "/tmp/x"})
    rejected = mgr.reject(result2.request_id, "测试拒绝")
    assert rejected.approved is False
    assert rejected.reason == "测试拒绝"
    print("   ✅ nonblocking 模式队列管理正确")


def test_custom_actions():
    print("[Approval] 测试自定义敏感操作...")
    mgr = ApprovalManager(config={"require_approval_for": ["custom_danger"]})
    assert mgr.requires_approval("custom_danger") is True
    assert mgr.requires_approval("shell") is False
    print("   ✅ 自定义敏感操作列表正确")


if __name__ == "__main__":
    test_requires_approval()
    test_disabled()
    test_auto_mode()
    test_nonblocking_mode()
    test_custom_actions()
    print("\n🎉 ApprovalManager 全部测试通过!")
