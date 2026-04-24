"""
符号搜索 Skill
优先 ripgrep (rg)，回退 Python os.walk + re
"""
import os
import re
import shutil
import subprocess
from typing import Dict, List

from agent.skills.base import Skill, SkillResult


class GrepSkill(Skill):
    """搜索代码库中的符号"""
    name = "grep"
    description = "搜索代码（ripgrep 优先，正则支持）"
    triggers = ["/grep", r"r:搜索代码[\s]*(.+)", r"r:grep[\s]*(.+)"]
    priority = 73

    def can_handle(self, user_input: str, context: Dict) -> bool:
        return self._match_triggers(user_input)

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        # 提取搜索参数
        raw = user_input.replace("/grep", "", 1).strip()
        for pattern in [r"搜索代码\s*(.+)", r"grep\s*(.+)"]:
            m = re.search(pattern, user_input)
            if m:
                raw = m.group(1).strip()
                break

        if not raw:
            return SkillResult(
                content="用法: /grep <pattern> [--type py] [--path ./src]",
                success=False,
            )

        # 解析参数
        parts = raw.split()
        pattern = parts[0]
        file_type = None
        search_path = "."
        i = 1
        while i < len(parts):
            if parts[i] == "--type" and i + 1 < len(parts):
                file_type = parts[i + 1]
                i += 2
            elif parts[i] == "--path" and i + 1 < len(parts):
                search_path = parts[i + 1]
                i += 2
            else:
                i += 1

        search_path = os.path.expanduser(search_path)

        # 尝试 ripgrep
        if shutil.which("rg"):
            return self._rg_search(pattern, search_path, file_type)
        else:
            return self._python_search(pattern, search_path, file_type)

    def _rg_search(self, pattern: str, path: str, file_type: str = None) -> SkillResult:
        """使用 ripgrep 搜索"""
        cmd = ["rg", "--line-number", "--with-filename", "--color=never", "-C", "2", pattern]
        if file_type:
            cmd.extend(["-t", file_type])
        cmd.append(path)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.getcwd(),
            )
            output = result.stdout.strip()
            if not output:
                return SkillResult(content=f"未找到匹配: `{pattern}`", success=True)

            lines = output.split("\n")
            # 截断
            if len(lines) > 50:
                output = "\n".join(lines[:50]) + f"\n...（共 {len(lines)} 行结果，已截断）"

            return SkillResult(content=f"🔍 搜索 `{pattern}`:\n```\n{output}\n```")
        except subprocess.TimeoutExpired:
            return SkillResult(content="搜索超时（30s）", success=False)
        except Exception as e:
            return SkillResult(content=f"搜索出错: {e}", success=False)

    def _python_search(self, pattern: str, path: str, file_type: str = None) -> SkillResult:
        """Python 回退搜索"""
        results = []
        max_results = 30

        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return SkillResult(content=f"正则表达式错误: {e}", success=False)

        for root, _, files in os.walk(path):
            for f in files:
                if file_type and not f.endswith(f".{file_type}"):
                    continue
                if not file_type and not f.endswith(".py"):
                    continue

                filepath = os.path.join(root, f)
                try:
                    with open(filepath, "r", encoding="utf-8") as fp:
                        for i, line in enumerate(fp, 1):
                            if compiled.search(line):
                                results.append(f"{filepath}:{i}: {line.rstrip()}")
                                if len(results) >= max_results:
                                    break
                except (UnicodeDecodeError, PermissionError):
                    continue

                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break

        if not results:
            return SkillResult(content=f"未找到匹配: `{pattern}`", success=True)

        output = "\n".join(results)
        if len(results) >= max_results:
            output += "\n...（结果过多，已截断）"

        return SkillResult(content=f"🔍 搜索 `{pattern}`:\n```\n{output}\n```")
