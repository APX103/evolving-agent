#!/usr/bin/env python3
"""
MCP Security auditing tests
pytest style
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from agent.mcp_security import (
    ToolAuditor,
    PolicyEnforcer,
    RiskLevel,
    Decision,
    AuditReport,
)
from agent.approval import ApprovalManager


class TestToolAuditor:
    def test_audit_low_risk_tool(self):
        schema = {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Lookup term"}
            }
        }
        risk = ToolAuditor.audit_tool(schema, "lookup", "Lookup for documents")
        assert risk == RiskLevel.LOW

    def test_audit_high_risk_write_tool(self):
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"}
            },
            "required": ["path", "content"]
        }
        risk = ToolAuditor.audit_tool(schema, "write_file", "Write content to a file")
        assert risk == RiskLevel.HIGH

    def test_audit_critical_risk_shell_tool(self):
        schema = {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"}
            },
            "required": ["command"]
        }
        risk = ToolAuditor.audit_tool(schema, "run_shell", "Run a shell command")
        assert risk == RiskLevel.CRITICAL

    def test_audit_critical_risk_eval_in_description(self):
        schema = {
            "type": "object",
            "properties": {
                "code": {"type": "string"}
            }
        }
        risk = ToolAuditor.audit_tool(schema, "execute", "Evaluates python code")
        assert risk == RiskLevel.CRITICAL

    def test_audit_medium_risk_read_tool(self):
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"}
            }
        }
        risk = ToolAuditor.audit_tool(schema, "read_file", "Read a file")
        assert risk == RiskLevel.MEDIUM

    def test_audit_server(self):
        tools = [
            {"name": "safe_lookup", "description": "Lookup", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "delete_file", "description": "Delete a file", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}},
        ]
        report = ToolAuditor.audit_server(tools, server_name="test_server")
        assert report.server_name == "test_server"
        assert report.tool_count == 2
        assert report.risk_summary.get(RiskLevel.LOW, 0) >= 1
        assert report.risk_summary.get(RiskLevel.CRITICAL, 0) >= 1


class TestPolicyEnforcer:
    def test_default_policy_allows_low_risk(self):
        enforcer = PolicyEnforcer()
        schema = {"type": "object", "properties": {"query": {"type": "string"}}}
        decision = enforcer.check_tool("srv", "search", {"query": "hello"}, schema=schema)
        assert decision == Decision.ALLOW

    def test_default_policy_blocks_critical(self):
        enforcer = PolicyEnforcer()
        schema = {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]
        }
        decision = enforcer.check_tool("srv", "run_shell", {"command": "ls"}, schema=schema)
        assert decision == Decision.BLOCK

    def test_blocked_tools_list(self):
        enforcer = PolicyEnforcer(security_config={"blocked_tools": ["dangerous_tool"]})
        decision = enforcer.check_tool("srv", "dangerous_tool", {})
        assert decision == Decision.BLOCK

    def test_custom_policy_override(self):
        enforcer = PolicyEnforcer(security_config={
            "policy": {"high": "block", "critical": "block"}
        })
        schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        decision = enforcer.check_tool("srv", "write_file", {"path": "/tmp/x"}, schema=schema)
        assert decision == Decision.BLOCK

    def test_tool_poisoning_detection(self):
        enforcer = PolicyEnforcer()
        schema_v1 = {"type": "object", "properties": {"query": {"type": "string"}}}
        alert1 = enforcer.register_tool_schema("srv", "search", schema_v1, RiskLevel.LOW)
        assert alert1 is None

        schema_v2 = {"type": "object", "properties": {"query": {"type": "string"}, "cmd": {"type": "string"}}}
        alert2 = enforcer.register_tool_schema("srv", "search", schema_v2, RiskLevel.LOW)
        assert alert2 is not None
        assert "hash" in alert2.lower() or "schema" in alert2.lower() or "schema" in alert2.lower()

    def test_rug_pull_detection(self):
        enforcer = PolicyEnforcer()
        schema = {"type": "object", "properties": {"query": {"type": "string"}}}
        alert1 = enforcer.register_tool_schema("srv", "search", schema, RiskLevel.LOW)
        assert alert1 is None

        alert2 = enforcer.register_tool_schema("srv", "search", schema, RiskLevel.CRITICAL)
        assert alert2 is not None
        assert "Rug pull" in alert2

    def test_approval_integration_blocking(self):
        approval_mgr = ApprovalManager(config={"enabled": True, "mode": "blocking", "auto_approve": True})
        enforcer = PolicyEnforcer(approval_manager=approval_mgr)
        schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        decision = enforcer.check_tool("srv", "write_file", {"path": "/tmp/x"}, schema=schema)
        # auto_approve=True means approval is granted automatically
        assert decision == Decision.ALLOW

    def test_approval_integration_nonblocking(self):
        approval_mgr = ApprovalManager(
            config={
                "enabled": True,
                "mode": "nonblocking",
                "require_approval_for": ["mcp:srv:write_file"]
            }
        )
        enforcer = PolicyEnforcer(approval_manager=approval_mgr)
        schema = {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}
        decision = enforcer.check_tool("srv", "write_file", {"path": "/tmp/x"}, schema=schema)
        assert decision == Decision.REQUIRE_APPROVAL


class TestAuditReport:
    def test_audit_report_structure(self):
        tools = [
            {"name": "t1", "description": "Low risk", "inputSchema": {}},
            {"name": "t2", "description": "Delete files", "inputSchema": {"properties": {"path": {"type": "string"}}}},
        ]
        report = ToolAuditor.audit_server(tools, server_name="srv")
        assert isinstance(report, AuditReport)
        assert report.tool_count == 2
        assert len(report.details) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
