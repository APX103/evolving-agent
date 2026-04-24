"""
测试运行 Skill
执行 pytest / unittest，捕获输出，超时控制
"""
import os
import re
import subprocess
from typing import Dict

from agent.skills.base import Skill, SkillResult


class TestSkill(Skill):
    """运行测试"""
    name = "test"
    description = "运行 pytest / unittest 测试"
    triggers = ["/test"]
    priority = 71

    def can_handle(self, user_input: str, context: Dict) -> bool:
        return self._match_triggers(user_input)

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        raw = user_input.replace("/test", "", 1).strip()

        # 安全检查：只能在项目目录内运行
        project_root = os.path.abspath(os.getcwd())

        # 解析参数
        target = raw if raw else "tests/"
        target_path = os.path.abspath(os.path.join(project_root, target))
        if not target_path.startswith(project_root + os.sep) and target_path != project_root:
            return SkillResult(
                content=f"⛔ 安全限制：只能在项目目录内运行测试。目标: {target}",
                success=False,
            )

        # 检测测试框架
        if os.path.exists("pytest.ini") or os.path.exists("pyproject.toml"):
            return self._run_pytest(target)
        else:
            return self._run_pytest(target)  # 默认 pytest

    def _run_pytest(self, target: str) -> SkillResult:
        """运行 pytest"""
        cmd = ["python", "-m", "pytest", target, "-v", "--tb=short"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=os.getcwd(),
            )

            stdout = result.stdout
            stderr = result.stderr

            # 检测 pytest 未安装
            if "No module named pytest" in stderr:
                return SkillResult(content="❌ 未找到 pytest。请安装: pip install pytest", success=False)

            # 提取关键信息
            passed = stdout.count(" PASSED")
            failed = stdout.count(" FAILED")
            errors = stdout.count(" ERROR")

            summary = f"📊 测试结果: {passed} 通过, {failed} 失败, {errors} 错误"
            if result.returncode == 0:
                summary = f"✅ {summary}"
            else:
                summary = f"❌ {summary}"

            # 截取输出（保留失败详情）
            lines = stdout.split("\n")
            output_lines = []
            for line in lines:
                if "FAILED" in line or "ERROR" in line or "passed" in line.lower():
                    output_lines.append(line)

            # 如果有失败，附加 traceback
            if failed > 0 or errors > 0:
                # 提取失败详情
                fail_details = []
                capture = False
                for line in lines:
                    if line.startswith("FAILED ") or line.startswith("ERROR "):
                        capture = True
                    if capture:
                        fail_details.append(line)
                        if len(fail_details) > 30:
                            break
                if fail_details:
                    output_lines.extend(["", "失败详情:"])
                    output_lines.extend(fail_details[:30])

            detail = "\n".join(output_lines) if output_lines else stdout[:500]
            if stderr and (failed > 0 or errors > 0):
                detail += f"\n\nStderr:\n{stderr[:500]}"

            content = f"{summary}\n```\n{detail}\n```"
            return SkillResult(
                content=content,
                success=result.returncode == 0,
                metadata={"passed": passed, "failed": failed, "errors": errors},
            )

        except subprocess.TimeoutExpired:
            return SkillResult(content="⏱️ 测试运行超时（60s）", success=False)
        except FileNotFoundError:
            return SkillResult(content="❌ 未找到 pytest。请安装: pip install pytest", success=False)
        except Exception as e:
            return SkillResult(content=f"测试运行出错: {e}", success=False)

        # 检测 pytest 未安装（stderr 中有提示）
        if "No module named pytest" in stderr:
            return SkillResult(content="❌ 未找到 pytest。请安装: pip install pytest", success=False)
