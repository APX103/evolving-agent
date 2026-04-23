"""
精确代码编辑 Skill（Aider SEARCH/REPLACE 协议）
- SEARCH 必须精确匹配，否则拒绝
- 支持多文件多块编辑
- 失败时文件 untouched
- 自动 git add 作为安全网
"""
import os
import re
import shutil
from typing import Dict, List, Tuple

from agent.skill import Skill, SkillResult
from agent.skills_dev.git_ops import GitSkill


class EditSkill(Skill):
    """精确编辑代码文件"""
    name = "edit"
    description = "精确编辑代码文件（SEARCH/REPLACE 协议）"
    triggers = ["/edit"]
    priority = 75

    # SEARCH/REPLACE 块正则
    EDIT_BLOCK_RE = re.compile(
        r"^###\s*(.+?)\s*$\n"
        r"<<<<<<<\s*SEARCH\n"
        r"(.*?)\n"
        r"=======\n"
        r"(.*?)\n"
        r">>>>>>>\s*REPLACE",
        re.MULTILINE | re.DOTALL,
    )

    def can_handle(self, user_input: str, context: Dict) -> bool:
        return self._match_triggers(user_input)

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        # 解析所有 SEARCH/REPLACE 块
        raw = user_input.replace("/edit", "", 1).strip()
        blocks = self._parse_blocks(raw)

        if not blocks:
            return SkillResult(
                content="未找到有效的 SEARCH/REPLACE 块。格式：\n"
                        "```\n### 文件路径\n"
                        "<<<<<<< SEARCH\n"
                        "旧代码（必须精确匹配）\n"
                        "=======\n"
                        "新代码\n"
                        ">>>>>>> REPLACE\n```",
                success=False,
            )

        results: List[str] = []
        errors: List[str] = []

        for filepath, search_text, replace_text in blocks:
            result = self._apply_edit(filepath, search_text, replace_text)
            if result["ok"]:
                results.append(f"✅ {filepath}: {result['msg']}")
            else:
                errors.append(f"❌ {filepath}: {result['msg']}")

        content = "\n".join(results + errors)
        return SkillResult(
            content=content,
            success=len(errors) == 0,
            metadata={"edited": len(results), "errors": len(errors)},
        )

    def _parse_blocks(self, text: str) -> List[Tuple[str, str, str]]:
        """解析所有 SEARCH/REPLACE 块"""
        blocks = []
        # 尝试匹配标准格式
        for m in self.EDIT_BLOCK_RE.finditer(text):
            filepath = m.group(1).strip()
            search = m.group(2)
            replace = m.group(3)
            blocks.append((filepath, search, replace))
        return blocks

    def _apply_edit(self, filepath: str, search: str, replace: str) -> Dict:
        """应用单个编辑，原子写入"""
        # 安全检查
        resolved = os.path.abspath(os.path.expanduser(filepath))
        allowed_roots = [
            os.path.abspath(os.path.expanduser("~/work")),
            os.path.abspath(os.path.expanduser("~")),
            os.path.abspath(os.getcwd()),
        ]
        if not any(resolved.startswith(r + os.sep) or resolved == r for r in allowed_roots):
            return {"ok": False, "msg": f"路径 {filepath} 超出允许范围"}

        if not os.path.exists(resolved):
            return {"ok": False, "msg": f"文件不存在: {filepath}"}

        try:
            with open(resolved, "r", encoding="utf-8") as f:
                original = f.read()
        except Exception as e:
            return {"ok": False, "msg": f"读取失败: {e}"}

        # 精确匹配验证
        if search not in original:
            return {"ok": False, "msg": "SEARCH 部分未精确匹配，拒绝修改"}

        # 统计出现次数
        count = original.count(search)
        if count > 1:
            return {"ok": False, "msg": f"SEARCH 部分在文件中出现 {count} 次，不唯一，拒绝修改"}

        new_content = original.replace(search, replace, 1)

        # 原子写入
        tmp_path = resolved + ".tmp"
        bak_path = resolved + ".bak"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(new_content)
                f.flush()
                os.fsync(f.fileno())

            # 备份旧文件
            shutil.copy2(resolved, bak_path)
            os.replace(tmp_path, resolved)

            # 自动 git add（如果可用）
            try:
                GitSkill._git_add(resolved)
            except Exception:
                pass

            return {"ok": True, "msg": "已应用修改"}
        except Exception as e:
            # 清理临时文件
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return {"ok": False, "msg": f"写入失败: {e}"}
