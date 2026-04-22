"""
内置 Skills 实现
"""
import os
import re
import subprocess
from typing import Dict
import logging

from simpleeval import simple_eval
from agent.skill import Skill, SkillResult
from agent.sandbox import PythonSandbox
from agent.approval import ApprovalManager

logger = logging.getLogger(__name__)


class EchoSkill(Skill):
    """回声 Skill：测试插件系统"""
    name = "echo"
    description = "复读用户的话"
    triggers = ["/echo"]
    priority = 100

    def can_handle(self, user_input: str, context: Dict) -> bool:
        return self._match_triggers(user_input)

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        content = user_input.replace("/echo", "").strip()
        return SkillResult(
            content=f"🔊 回声: {content}" if content else "你说 /echo 什么呢？",
            metadata={"type": "echo"}
        )


class CalcSkill(Skill):
    """计算器 Skill：安全计算表达式"""
    name = "calc"
    description = "计算数学表达式"
    triggers = ["/calc", r"r:计算?一下?[\s]*([0-9\+\-\*\/\(\)\^\.]+)", r"r:([0-9\+\-\*\/\(\)\^\s\.]+)=\s*\?"]
    priority = 80

    def can_handle(self, user_input: str, context: Dict) -> bool:
        return self._match_triggers(user_input)

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        # 提取表达式
        expr = user_input.replace("/calc", "").strip()
        for pattern in [r"计算?一下?\s*([0-9\+\-\*\/\(\)\^\s\.]+)", r"([0-9\+\-\*\/\(\)\^\s\.]+)=\s*\?"]:
            m = re.search(pattern, user_input)
            if m:
                expr = m.group(1).strip()
                break

        if not expr:
            return SkillResult(content="请提供一个数学表达式，比如 `/calc 123 + 456`")

        # 安全过滤：只允许数字和基本运算符
        if not re.match(r"^[0-9\+\-\*\/\(\)\^\s\.]+$", expr):
            return SkillResult(content="表达式包含不安全字符，我只支持基本数学运算。", success=False)

        try:
            # 使用 simpleeval 替代 eval，消除逃逸风险
            safe_expr = expr.replace("^", "**")
            result = simple_eval(safe_expr)
            return SkillResult(
                content=f"🧮 {expr} = {result}",
                metadata={"expr": expr, "result": result}
            )
        except Exception as e:
            return SkillResult(content=f"计算出错: {e}", success=False)


class FileReadSkill(Skill):
    """文件读取 Skill"""
    name = "fileread"
    description = "读取文件内容"
    triggers = ["/read", r"r:读一下?文件[\s]*(.+)", r"r:看看文件[\s]*(.+)"]
    priority = 70

    def can_handle(self, user_input: str, context: Dict) -> bool:
        return self._match_triggers(user_input)

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        # 提取文件路径
        filepath = user_input.replace("/read", "").strip()
        for pattern in [r"读一下?文件\s*(.+)", r"看看文件\s*(.+)", r"读取\s*(.+)"]:
            m = re.search(pattern, user_input)
            if m:
                filepath = m.group(1).strip().strip("\"'")
                break

        if not filepath:
            return SkillResult(content="请指定文件路径，比如 `/read ~/notes.txt`")

        # 扩展 ~
        filepath = os.path.expanduser(filepath)

        # 安全检查：只允许读取特定目录（工作区、用户目录）
        resolved = os.path.abspath(filepath)
        allowed_roots = [
            os.path.abspath(os.path.expanduser("~/work")) + os.sep,
            os.path.abspath(os.path.expanduser("~")) + os.sep,
            os.path.abspath(os.getcwd()) + os.sep,
        ]
        if not any(resolved.startswith(r) for r in allowed_roots):
            return SkillResult(
                content=f"⛔ 安全限制：不允许读取 {filepath} 路径。只允许读取工作区和用户目录下的文件。",
                success=False
            )

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            # 截断过长内容
            max_len = 3000
            if len(content) > max_len:
                content = content[:max_len] + f"\n...（共 {len(content)} 字符，已截断）"
            return SkillResult(
                content=f"📄 {filepath}:\n```\n{content}\n```",
                metadata={"filepath": filepath, "size": len(content)}
            )
        except FileNotFoundError:
            return SkillResult(content=f"❌ 文件不存在: {filepath}", success=False)
        except Exception as e:
            return SkillResult(content=f"❌ 读取失败: {e}", success=False)


class FileWriteSkill(Skill):
    """文件写入 Skill"""
    name = "filewrite"
    description = "写入/创建文件"
    triggers = ["/write", r"r:写个?文件[\s]*(.+)"]
    priority = 70

    def can_handle(self, user_input: str, context: Dict) -> bool:
        return self._match_triggers(user_input)

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        # 解析：/write ~/file.txt content...
        rest = user_input.replace("/write", "").strip()
        lines = rest.split("\n", 1)

        if len(lines) < 2:
            return SkillResult(
                content="格式: `/write 文件路径\n文件内容...`",
                success=False
            )

        filepath = os.path.expanduser(lines[0].strip().strip("\"'"))
        content = lines[1]

        # 安全检查
        resolved = os.path.abspath(filepath)
        allowed_roots = [
            os.path.abspath(os.path.expanduser("~/work")) + os.sep,
            os.path.abspath(os.path.expanduser("~")) + os.sep,
        ]
        if not any(resolved.startswith(r) for r in allowed_roots):
            return SkillResult(
                content=f"⛔ 安全限制：不允许写入 {filepath}",
                success=False
            )

        try:
            # 修复：确保目录存在
            dir_part = os.path.dirname(filepath)
            if dir_part:
                os.makedirs(dir_part, exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            return SkillResult(
                content=f"✅ 已写入 {filepath} ({len(content)} 字符)",
                metadata={"filepath": filepath, "size": len(content)}
            )
        except Exception as e:
            return SkillResult(content=f"❌ 写入失败: {e}", success=False)


class ShellSkill(Skill):
    """
    Shell 执行 Skill（受限版本）
    ⚠️ 只允许安全命令
    """
    name = "shell"
    description = "执行安全 Shell 命令"
    triggers = ["/sh", r"r:执行[\s]*(.+)", r"r:运行[\s]*(.+)"]
    priority = 60

    # 允许的安全命令白名单（精确匹配第一个 token）
    ALLOWED_CMDS = [
        "ls", "cat", "head", "tail", "grep", "find", "wc",
        "pwd", "echo", "date", "whoami", "uname",
        "git", "python", "python3", "node", "npm", "pip", "brew",
    ]

    # 危险命令黑名单
    BLOCKED_PATTERNS = [
        r"rm\s+-rf", r"rm\s+.*[/\*]", r">[/\*]",
        r"mkfs", r"dd\s+if=", r"chmod\s+777",
        r"sudo", r"su\s+-", r"curl.*\|.*sh",
    ]

    def can_handle(self, user_input: str, context: Dict) -> bool:
        return self._match_triggers(user_input)

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        # 提取命令
        cmd = user_input.replace("/sh", "").strip()
        for pattern in [r"执行\s*(.+)", r"运行\s*(.+)"]:
            m = re.search(pattern, user_input)
            if m:
                cmd = m.group(1).strip()
                break

        if not cmd:
            return SkillResult(content="请提供命令，比如 `/sh ls -la ~/work`")

        # 安全检查 1：黑名单
        for pattern in self.BLOCKED_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                return SkillResult(
                    content=f"⛔ 安全限制：命令包含危险操作 `{pattern}`，已阻止。",
                    success=False
                )

        # 安全检查 2：白名单（精确匹配第一个 token）
        first_token = cmd.split()[0] if cmd.split() else ""
        allowed = first_token in self.ALLOWED_CMDS
        if not allowed:
            return SkillResult(
                content=f"⛔ 安全限制：命令 `{first_token}` 不在白名单中。允许的命令: {', '.join(self.ALLOWED_CMDS)}",
                success=False
            )

        # 人工审批
        approval_result = self.approval.request_approval(
            action_type="shell",
            description=f"执行 Shell 命令: {cmd}",
            details={"command": cmd, "cwd": os.getcwd()}
        )
        if not approval_result.approved:
            return SkillResult(
                content=f"⛔ 操作已取消: {approval_result.reason or '用户拒绝'}",
                success=False
            )

        # 执行
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.getcwd()
            )
            output = result.stdout
            if result.stderr:
                output += f"\n[stderr] {result.stderr}"

            # 截断
            max_len = 2000
            if len(output) > max_len:
                output = output[:max_len] + f"\n...（共 {len(output)} 字符，已截断）"

            return SkillResult(
                content=f"$ {cmd}\n```\n{output or '(无输出)'}\n```",
                metadata={"cmd": cmd, "returncode": result.returncode}
            )
        except subprocess.TimeoutExpired:
            return SkillResult(content="⏱️ 命令执行超时（30秒）", success=False)
        except Exception as e:
            return SkillResult(content=f"❌ 执行失败: {e}", success=False)


class PythonSkill(Skill):
    """Python 代码执行 Skill：安全沙箱执行多行 Python 代码"""
    name = "python"
    description = "执行 Python 代码（安全沙箱）"
    triggers = ["/python", r"r:用?Python[\s]*(.+)"]
    priority = 75

    def __init__(self):
        self.sandbox = PythonSandbox()

    def can_handle(self, user_input: str, context: Dict) -> bool:
        return self._match_triggers(user_input)

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        # 提取代码
        code = user_input.replace("/python", "").strip()
        if not code:
            return SkillResult(content="请提供 Python 代码，例如 `/python print([i**2 for i in range(5)])`")

        result = self.sandbox.execute(code)
        if result.success:
            output = result.output or "(无输出)"
            info = f"⏱️ {result.execution_time_ms}ms"
            return SkillResult(
                content=f"```python\n{code}\n```\n```\n{output}\n```\n{info}",
                metadata={"code": code, "time_ms": result.execution_time_ms}
            )
        else:
            return SkillResult(
                content=f"```python\n{code}\n```\n❌ {result.error}",
                success=False,
                metadata={"code": code, "error": result.error}
            )


def build_default_skills():
    """构建默认 Skill 集合"""
    from agent.skill import SkillRegistry

    registry = SkillRegistry()
    registry.register(EchoSkill())
    registry.register(CalcSkill())
    registry.register(PythonSkill())
    registry.register(FileReadSkill())
    registry.register(FileWriteSkill())
    registry.register(ShellSkill())

    return registry
