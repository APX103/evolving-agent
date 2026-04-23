"""
MCP 工具安全审计与策略执行
- 工具风险静态分析
- 运行时策略拦截
- 工具投毒检测（schema 哈希校验）
-  rugs pull 检测（安全工具突然变危险）
"""
import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from agent.approval import ApprovalManager, ApprovalResult
from agent.observability import get_tracer

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Decision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"


@dataclass
class AuditReport:
    """单个 server 的审计报告"""
    server_name: str
    tool_count: int
    risk_summary: Dict[RiskLevel, int] = field(default_factory=dict)
    details: List[Dict[str, Any]] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)


class ToolAuditor:
    """MCP 工具静态风险审计器"""

    # 危险关键词模式（按风险等级分类）
    DANGEROUS_PATTERNS = {
        RiskLevel.CRITICAL: [
            r"\brm\b", r"\bformat\b", r"\bdrop\b", r"\bdelete\b",
            r"\beval\b", r"\bexec\b", r"\bsubprocess\b", r"\bos\.system\b",
            r"\bshell\b", r"\bsh\b", r"\bbash\b", r"\bcmd\b",
            r"\bchmod\b", r"\bchown\b", r"\bmkfs\b", r"\bdd\b",
        ],
        RiskLevel.HIGH: [
            r"\bwrite\b", r"\boverwrite\b", r"\bmodify\b", r"\bedit\b",
            r"\bmove\b", r"\brename\b", r"\bcopy\b", r"\bupload\b",
            r"\bdownload\b", r"\bfetch\b", r"\bcurl\b", r"\bwget\b",
            r"\brequest\b", r"\bhttp\b", r"\burl\b", r"\bnetwork\b",
        ],
        RiskLevel.MEDIUM: [
            r"\bread\b", r"\blist\b", r"\bsearch\b", r"\bfind\b",
            r"\bget\b", r"\bopen\b",
        ],
    }

    # 敏感参数名模式
    SENSITIVE_PARAM_PATTERNS = [
        r"command\b", r"cmd\b", r"shell\b", r"script\b", r"code\b",
        r"eval\b", r"exec\b", r"sql\b", r"path\b",
        r"url\b", r"endpoint\b", r"target\b", r"destination\b",
    ]

    @classmethod
    def audit_tool(cls, schema: Dict[str, Any], tool_name: str = "", tool_description: str = "") -> RiskLevel:
        """对单个 tool 的 input_schema 做静态风险分析"""
        text_to_scan = f"{tool_name} {tool_description}".lower().replace("_", " ").replace("-", " ")

        # 从 schema 中提取所有可扫描文本
        schema_text = json.dumps(schema, ensure_ascii=False).lower()
        text_to_scan += " " + schema_text

        max_risk = RiskLevel.LOW

        # 1. 检查危险关键词
        for level, patterns in cls.DANGEROUS_PATTERNS.items():
            for pattern in patterns:
                import re
                if re.search(pattern, text_to_scan, re.IGNORECASE):
                    if cls._level_value(level) > cls._level_value(max_risk):
                        max_risk = level
                    break

        # 2. 检查敏感参数结构
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for prop_name, prop_schema in properties.items():
            prop_desc = (prop_schema.get("description", "") + " " + prop_name).lower()
            for pattern in cls.SENSITIVE_PARAM_PATTERNS:
                import re
                if re.search(pattern, prop_desc, re.IGNORECASE):
                    if prop_name in required:
                        if cls._level_value(RiskLevel.HIGH) > cls._level_value(max_risk):
                            max_risk = RiskLevel.HIGH
                    else:
                        if cls._level_value(RiskLevel.MEDIUM) > cls._level_value(max_risk):
                            max_risk = RiskLevel.MEDIUM

        # 3. 特殊高危险模式：代码执行字段
        import re
        code_exec_indicators = ["code", "script", "expression", "javascript", "python", "bash"]
        for indicator in code_exec_indicators:
            pat = rf"\b{indicator}\b"
            if re.search(pat, text_to_scan, re.IGNORECASE):
                if cls._level_value(RiskLevel.CRITICAL) > cls._level_value(max_risk):
                    max_risk = RiskLevel.CRITICAL
        return max_risk

    @classmethod
    def audit_server(cls, tools: List[Any], server_name: str = "") -> AuditReport:
        """审计整个 server 的所有 tools"""
        report = AuditReport(server_name=server_name, tool_count=len(tools))
        for tool in tools:
            name = getattr(tool, "name", tool.get("name", "")) if isinstance(tool, dict) else ""
            desc = getattr(tool, "description", tool.get("description", "")) if isinstance(tool, dict) else ""
            schema = getattr(tool, "input_schema", tool.get("inputSchema", {})) if isinstance(tool, dict) else {}
            risk = cls.audit_tool(schema, name, desc)
            report.risk_summary[risk] = report.risk_summary.get(risk, 0) + 1
            report.details.append({
                "tool": name,
                "risk": risk.value,
                "description": desc[:100],
            })
        return report

    @staticmethod
    def _level_value(level: RiskLevel) -> int:
        mapping = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}
        return mapping[level]


class PolicyEnforcer:
    """MCP 工具运行时策略执行器"""

    def __init__(
        self,
        security_config: Optional[Dict[str, Any]] = None,
        approval_manager: Optional[ApprovalManager] = None,
    ):
        self.config = security_config or {}
        self.approval_manager = approval_manager
        self.strict_mode = self.config.get("strict_mode", True)
        # 默认策略：风险等级 -> 决策
        self.default_policy = {
            RiskLevel.LOW: Decision.ALLOW,
            RiskLevel.MEDIUM: Decision.ALLOW,
            RiskLevel.HIGH: Decision.REQUIRE_APPROVAL,
            RiskLevel.CRITICAL: Decision.BLOCK,
        }
        # 从配置覆盖
        policy_cfg = self.config.get("policy", {})
        for level in RiskLevel:
            if level.value in policy_cfg:
                self.default_policy[level] = Decision(policy_cfg[level.value])

        # 工具 schema 哈希缓存，用于投毒检测
        self._schema_hashes: Dict[str, str] = {}
        self._first_seen_risk: Dict[str, RiskLevel] = {}
        # 被明确禁止的 tool 列表
        self._blocked_tools: Set[str] = set(self.config.get("blocked_tools", []))

    def _tool_key(self, server_name: str, tool_name: str) -> str:
        return f"{server_name}::{tool_name}"

    def _hash_schema(self, schema: Dict[str, Any]) -> str:
        """对 schema 做稳定哈希"""
        canonical = json.dumps(schema, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def register_tool_schema(self, server_name: str, tool_name: str, schema: Dict[str, Any], risk: RiskLevel):
        """注册 tool schema（在 tool 发现时调用），用于投毒检测"""
        key = self._tool_key(server_name, tool_name)
        new_hash = self._hash_schema(schema)
        existing_hash = self._schema_hashes.get(key)

        if existing_hash is None:
            self._schema_hashes[key] = new_hash
            self._first_seen_risk[key] = risk
            logger.debug(f"[MCP Security] 注册 schema 哈希: {key} -> {new_hash} (risk={risk.value})")
            return None  # 无异常

        if existing_hash != new_hash:
            # 投毒检测：schema 发生变化
            alert = f"[ALERT] Tool 投毒检测: {key} 的 schema 哈希发生变化! {existing_hash} -> {new_hash}"
            logger.warning(alert)
            return alert

        # rug pull 检测：风险等级升级
        first_risk = self._first_seen_risk.get(key, RiskLevel.LOW)
        if ToolAuditor._level_value(risk) > ToolAuditor._level_value(first_risk):
            alert = f"[ALERT] Rug pull 检测: {key} 风险等级从 {first_risk.value} 升级到 {risk.value}"
            logger.warning(alert)
            return alert

        return None

    def check_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        schema: Optional[Dict[str, Any]] = None,
        description: str = "",
    ) -> Decision:
        """
        运行时检查 tool 调用是否被允许
        返回 Decision，若 REQUIRE_APPROVAL 且配置了 ApprovalManager，会自动请求审批
        """
        tracer = get_tracer()
        span = tracer.start_span("mcp.security.check_tool", attributes={
            "server_name": server_name,
            "tool_name": tool_name,
        })

        key = self._tool_key(server_name, tool_name)

        # 1. 显式黑名单
        if tool_name in self._blocked_tools or key in self._blocked_tools:
            logger.warning(f"[MCP Security] BLOCK: {key} 在黑名单中")
            span.set_attribute("decision", Decision.BLOCK.value)
            span.set_attribute("reason", "blocked_tool")
            span.end()
            return Decision.BLOCK

        # 2. 风险等级评估
        if schema:
            risk = ToolAuditor.audit_tool(schema, tool_name, description)
        else:
            risk = RiskLevel.HIGH
        span.set_attribute("risk_level", risk.value)

        # 3. 投毒 / rug pull 实时检测（若 schema 已注册）
        if schema:
            alert = self.register_tool_schema(server_name, tool_name, schema, risk)
            if alert:
                span.set_attribute("security_alert", alert)
                # rug pull / 投毒 -> 强制阻塞
                if "Rug pull" in alert or "投毒" in alert:
                    logger.warning(f"[MCP Security] BLOCK: {key} 因安全警报被拦截")
                    span.set_attribute("decision", Decision.BLOCK.value)
                    span.set_attribute("reason", "security_alert")
                    span.end()
                    return Decision.BLOCK

        # 4. 应用策略
        has_known_policy = risk in self.default_policy
        decision = self.default_policy.get(risk, Decision.REQUIRE_APPROVAL)

        # strict_mode: 没有 schema 或未知风险等级时强制需要审批
        if self.strict_mode and (schema is None or not has_known_policy):
            decision = Decision.REQUIRE_APPROVAL

        span.set_attribute("decision", decision.value)

        # 5. 审批流程
        if decision == Decision.REQUIRE_APPROVAL and self.approval_manager:
            action_type = f"mcp:{server_name}:{tool_name}"
            result: ApprovalResult = self.approval_manager.request_approval(
                action_type=action_type,
                description=f"MCP 工具调用: {server_name}/{tool_name}",
                details={
                    "server": server_name,
                    "tool": tool_name,
                    "arguments": arguments,
                    "risk_level": risk.value,
                },
            )
            span.set_attribute("approval_approved", result.approved)
            span.set_attribute("approval_pending", result.pending)
            if not result.approved and not result.pending:
                decision = Decision.BLOCK
                span.set_attribute("decision", Decision.BLOCK.value)
                span.set_attribute("reason", "approval_rejected")
            elif result.pending:
                # nonblocking 模式下保持 pending，这里视为需要审批，不阻塞但标记
                pass
            else:
                decision = Decision.ALLOW
                span.set_attribute("decision", Decision.ALLOW.value)

        span.end()
        logger.info(f"[MCP Security] {decision.value.upper()}: {key} (risk={risk.value})")
        return decision
