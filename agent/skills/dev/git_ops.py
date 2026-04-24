"""
Git 操作 Skill
支持 diff/status/log/commit/revert
每次 edit 前自动 git add 作为安全网
"""
import os
import re
import subprocess
from typing import Dict

from agent.skills.base import Skill, SkillResult


class GitSkill(Skill):
    """版本控制操作"""
    name = "git"
    description = "git diff/status/log/commit/revert"
    triggers = ["/git"]
    priority = 70

    def can_handle(self, user_input: str, context: Dict) -> bool:
        return self._match_triggers(user_input)

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        raw = user_input.replace("/git", "", 1).strip()

        if not raw:
            # 默认显示 status
            return self._git_status()

        parts = raw.split()
        cmd = parts[0]

        if cmd == "status":
            return self._git_status()
        elif cmd == "diff":
            return self._git_diff(" ".join(parts[1:]) if len(parts) > 1 else "")
        elif cmd == "log":
            n = parts[1] if len(parts) > 1 else "5"
            return self._git_log(n)
        elif cmd == "commit":
            msg = " ".join(parts[1:]) if len(parts) > 1 else "Agent 自动提交"
            return self._git_commit(msg)
        elif cmd == "revert":
            target = parts[1] if len(parts) > 1 else "HEAD"
            return self._git_revert(target)
        elif cmd == "add":
            files = " ".join(parts[1:]) if len(parts) > 1 else "."
            return self._git_add(files)
        else:
            return SkillResult(
                content=f"未知 git 命令: {cmd}\n"
                        "支持: status, diff, log, commit, revert, add",
                success=False,
            )

    def _git_status(self) -> SkillResult:
        out, err, code = self._run_git(["status", "-s"])
        if code != 0:
            return SkillResult(content=f"git status 失败: {err}", success=False)
        if not out.strip():
            return SkillResult(content="✅ 工作区干净，无未提交更改")
        return SkillResult(content=f"📋 Git 状态:\n```\n{out}\n```")

    def _git_diff(self, target: str) -> SkillResult:
        cmd = ["diff"]
        if target:
            cmd.append(target)
        out, err, code = self._run_git(cmd)
        if code != 0:
            return SkillResult(content=f"git diff 失败: {err}", success=False)
        if not out.strip():
            return SkillResult(content="无差异")
        # 截断
        lines = out.split("\n")
        if len(lines) > 80:
            out = "\n".join(lines[:80]) + "\n...（差异过长，已截断）"
        return SkillResult(content=f"📊 Diff:\n```diff\n{out}\n```")

    def _git_log(self, n: str) -> SkillResult:
        out, err, code = self._run_git(["log", f"--oneline", "-n", n])
        if code != 0:
            return SkillResult(content=f"git log 失败: {err}", success=False)
        return SkillResult(content=f"📜 最近提交:\n```\n{out}\n```")

    def _git_commit(self, msg: str) -> SkillResult:
        # 先 add
        _, err, code = self._run_git(["add", "-A"])
        if code != 0:
            return SkillResult(content=f"git add 失败: {err}", success=False)

        out, err, code = self._run_git(["commit", "-m", msg])
        if code != 0:
            if "nothing to commit" in err.lower() or "nothing to commit" in out.lower():
                return SkillResult(content="✅ 没有需要提交的更改")
            return SkillResult(content=f"git commit 失败: {err}", success=False)
        return SkillResult(content=f"✅ 已提交: {msg}\n```\n{out}\n```")

    def _git_revert(self, target: str) -> SkillResult:
        out, err, code = self._run_git(["revert", "--no-commit", target])
        if code != 0:
            return SkillResult(content=f"git revert 失败: {err}", success=False)
        return SkillResult(
            content=f"✅ 已 revert {target}（未提交，可查看 diff 后 commit）",
            metadata={"reverted": target},
        )

    def _run_git(self, args: list) -> tuple:
        """运行 git 命令"""
        cmd = ["git"] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                cwd=os.getcwd(),
            )
            return result.stdout, result.stderr, result.returncode
        except Exception as e:
            return "", str(e), 1

    @staticmethod
    def _git_add(target: str) -> None:
        """静态方法：供 EditSkill 调用，在编辑前自动 add"""
        cmd = ["git", "add", target]
        try:
            subprocess.run(cmd, capture_output=True, timeout=5, cwd=os.getcwd())
        except Exception:
            pass
