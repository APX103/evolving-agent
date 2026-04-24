"""
代码地图 Skill
使用 Python ast 解析项目结构
输出：模块列表、类列表、继承关系、函数签名
"""
import ast
import os
import re
from typing import Dict, List

from agent.skills.base import Skill, SkillResult


class MapSkill(Skill):
    """查看代码结构地图"""
    name = "map"
    description = "分析代码结构（类、函数、继承关系）"
    triggers = ["/map"]
    priority = 72

    def can_handle(self, user_input: str, context: Dict) -> bool:
        return self._match_triggers(user_input)

    def execute(self, user_input: str, context: Dict) -> SkillResult:
        raw = user_input.replace("/map", "", 1).strip()

        # 解析参数
        target = "."
        filter_class = None
        filter_file = None

        if raw:
            parts = raw.split()
            for i, p in enumerate(parts):
                if p == "--class" and i + 1 < len(parts):
                    filter_class = parts[i + 1]
                elif p == "--file" and i + 1 < len(parts):
                    filter_file = parts[i + 1]
                elif not p.startswith("--"):
                    target = p

        target = os.path.expanduser(target)
        if not os.path.exists(target):
            return SkillResult(content=f"路径不存在: {target}", success=False)

        results = []

        if os.path.isfile(target):
            if target.endswith(".py"):
                info = self._analyze_file(target)
                results.append(self._format_file(info, filter_class=filter_class))
            else:
                return SkillResult(content=f"暂不支持 {target} 的代码地图（仅限 .py）", success=False)
        else:
            # 目录：扫描所有 .py 文件
            py_files = []
            for root, _, files in os.walk(target):
                for f in files:
                    if f.endswith(".py"):
                        full = os.path.join(root, f)
                        if filter_file and filter_file not in full:
                            continue
                        py_files.append(full)

            for fp in sorted(py_files)[:20]:  # 限制数量
                try:
                    info = self._analyze_file(fp)
                    formatted = self._format_file(info, filter_class=filter_class)
                    if formatted:
                        results.append(formatted)
                except SyntaxError:
                    results.append(f"⚠️ {fp}: 语法错误，跳过")

        if not results:
            return SkillResult(content="未找到匹配的代码文件或类", success=True)

        return SkillResult(content="\n\n".join(results))

    def _analyze_file(self, filepath: str) -> Dict:
        """用 ast 解析单个 Python 文件"""
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)

        classes = []
        functions = []
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                bases = [self._name(b) for b in node.bases]
                methods = [
                    n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                classes.append({
                    "name": node.name,
                    "bases": bases,
                    "methods": methods,
                    "line": node.lineno,
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 只收集顶层函数（非类方法）
                if not any(isinstance(parent, ast.ClassDef) for parent in ast.walk(tree)):
                    # 更准确：检查 node 是否在 class body 中
                    # 上面的 ast.walk 会遍历所有节点，我们需要检查父级
                    pass

        # 重新收集顶层函数
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                sig = self._function_signature(node)
                functions.append({"name": node.name, "signature": sig, "line": node.lineno})
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}" if module else alias.name)

        return {
            "filepath": filepath,
            "classes": classes,
            "functions": functions,
            "imports": imports,
        }

    def _function_signature(self, node) -> str:
        """提取函数签名"""
        args = []
        for arg in node.args.args:
            args.append(arg.arg)
        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")
        return f"{node.name}({', '.join(args)})"

    def _name(self, node) -> str:
        """从 ast 节点提取名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._name(node.value)}.{node.attr}"
        return "..."

    def _format_file(self, info: Dict, filter_class=None) -> str:
        """格式化输出"""
        lines = [f"📄 {info['filepath']}"]

        if info["classes"]:
            lines.append("  类:")
            for c in info["classes"]:
                if filter_class and filter_class != c["name"]:
                    continue
                base_str = f"({', '.join(c['bases'])})" if c["bases"] else ""
                lines.append(f"    class {c['name']}{base_str}  # 第{c['line']}行")
                for m in c["methods"]:
                    lines.append(f"      - {m}()")

        if info["functions"]:
            lines.append("  函数:")
            for f in info["functions"]:
                lines.append(f"    - {f['signature']}  # 第{f['line']}行")

        if not info["classes"] and not info["functions"]:
            return ""

        return "\n".join(lines)
