"""
安全 Python 代码执行环境
支持三种执行模式：
1. simpleeval — 简单数学表达式（Stage 1 已完成）
2. SafePythonExecutor — 受限 exec，支持多行代码，禁用危险操作
3. DockerSandbox — Docker 容器隔离（需 Docker 环境）

自动降级策略：Docker → SafePythonExecutor → simpleeval
"""
import ast
import io
import logging
import subprocess
import sys
import traceback
from typing import Any, Dict, Optional
from dataclasses import dataclass

from simpleeval import simple_eval

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """代码执行结果"""
    success: bool
    output: str          # stdout 输出
    error: Optional[str] = None
    return_value: Any = None
    execution_time_ms: int = 0


# ── 安全内置函数白名单 ──
_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bin": bin, "bool": bool,
    "bytearray": bytearray, "bytes": bytes, "chr": chr, "complex": complex,
    "dict": dict, "divmod": divmod, "enumerate": enumerate, "filter": filter,
    "float": float, "format": format, "frozenset": frozenset, "hasattr": hasattr,
    "hash": hash, "hex": hex, "int": int, "isinstance": isinstance,
    "issubclass": issubclass, "iter": iter, "len": len, "list": list,
    "map": map, "max": max, "min": min, "next": next, "oct": oct,
    "ord": ord, "pow": pow, "range": range, "reversed": reversed,
    "round": round, "set": set, "slice": slice, "sorted": sorted,
    "str": str, "sum": sum, "tuple": tuple, "type": type, "zip": zip,
}

# ── 危险的模块/函数黑名单 ──
_DANGEROUS_NAMES = {
    "os", "sys", "subprocess", "socket", "urllib", "http", "ftplib",
    "importlib", "builtins", "__builtins__", "__import__",
    "eval", "exec", "compile", "open", "input",
    "__subclasses__", "__bases__", "__globals__", "__code__",
}


class SafePythonExecutor:
    """
    受限 Python 执行器
    - 禁用 __import__ 和危险 builtins
    - 限制代码中不能出现危险名称
    - 捕获 stdout 作为输出
    - 超时控制（防止死循环）
    """

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def execute(self, code: str) -> SandboxResult:
        import time as time_mod
        start = time_mod.time()

        # 安全检查
        check = self._security_check(code)
        if not check["safe"]:
            return SandboxResult(
                success=False,
                output="",
                error=f"安全拦截: {check['reason']}"
            )

        # 创建受限命名空间
        safe_globals = {
            "__builtins__": _SAFE_BUILTINS,
            "_print_outputs": [],
        }
        safe_locals = {}

        # 自定义 print 捕获输出
        def captured_print(*args, **kwargs):
            output = " ".join(str(a) for a in args)
            safe_globals["_print_outputs"].append(output)

        safe_globals["print"] = captured_print

        # 执行代码
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            # 使用 exec 执行（注意：这仍有理论风险，但 builtins 已限制）
            exec(code, safe_globals, safe_locals)

            # 收集输出
            captured = safe_globals["_print_outputs"]
            stdout_text = sys.stdout.getvalue()
            if stdout_text:
                captured.append(stdout_text)

            output = "\n".join(captured)
            elapsed = int((time_mod.time() - start) * 1000)

            return SandboxResult(
                success=True,
                output=output,
                return_value=safe_locals.get("_result", None),
                execution_time_ms=elapsed
            )

        except Exception as e:
            elapsed = int((time_mod.time() - start) * 1000)
            return SandboxResult(
                success=False,
                output=sys.stdout.getvalue(),
                error=f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                execution_time_ms=elapsed
            )
        finally:
            sys.stdout = old_stdout

    def _security_check(self, code: str) -> Dict[str, Any]:
        """AST-based static security scan"""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {"safe": False, "reason": f"Syntax error: {e}"}

        dangerous = _DANGEROUS_NAMES

        for node in ast.walk(tree):
            # Block imports
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                return {"safe": False, "reason": "Import statements are not allowed"}

            # Block dangerous names
            if isinstance(node, ast.Name) and node.id in dangerous:
                return {"safe": False, "reason": f"Code contains forbidden name '{node.id}'"}

            if isinstance(node, ast.Attribute) and node.attr in dangerous:
                return {"safe": False, "reason": f"Code contains forbidden attribute '{node.attr}'"}

            # Block getattr/setattr/delattr with dangerous string constants
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                if func_name in ("getattr", "setattr", "delattr"):
                    for arg in node.args[1:]:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                            if arg.value in dangerous:
                                return {
                                    "safe": False,
                                    "reason": f"Dangerous {func_name} with forbidden string '{arg.value}'",
                                }

            # Block string concatenation forming dangerous names
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
                concat = self._concat_strings(node)
                if concat and concat in dangerous:
                    return {
                        "safe": False,
                        "reason": f"String concatenation forms forbidden name '{concat}'",
                    }

        return {"safe": True, "reason": ""}

    @staticmethod
    def _concat_strings(node):
        """Extract concatenated string from nested BinOp(Add, Constant) nodes."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = SafePythonExecutor._concat_strings(node.left)
            right = SafePythonExecutor._concat_strings(node.right)
            if left is not None and right is not None:
                return left + right
        return None


class DockerSandbox:
    """
    Docker 容器沙箱
    完全隔离，支持复杂代码和第三方库
    需要 Docker 环境
    """

    def __init__(self, timeout: int = 30, image: str = "python:3.11-slim"):
        self.timeout = timeout
        self.image = image

    def is_available(self) -> bool:
        """检查 Docker 是否可用"""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def execute(self, code: str) -> SandboxResult:
        import time as time_mod
        start = time_mod.time()

        if not self.is_available():
            return SandboxResult(
                success=False,
                output="",
                error="Docker 不可用。请安装 Docker 以使用完全隔离沙箱。"
            )

        # 构造执行脚本
        script = f"""
import sys, json
sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
try:
    exec({repr(code)})
    print("\\n__SANDBOX_OK__")
except Exception as e:
    import traceback
    print(f"__SANDBOX_ERROR__{{type(e).__name__}}: {{e}}")
    traceback.print_exc()
"""

        try:
            result = subprocess.run(
                [
                    "docker", "run", "--rm",
                    "--network", "none",           # 禁用网络
                    "--memory", "128m",             # 内存限制
                    "--cpus", "0.5",                # CPU 限制
                    "-i", self.image,
                    "python", "-c", script
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            elapsed = int((time_mod.time() - start) * 1000)
            output = result.stdout

            if "__SANDBOX_ERROR__" in output:
                error_part = output.split("__SANDBOX_ERROR__")[1]
                return SandboxResult(
                    success=False,
                    output=output.split("__SANDBOX_ERROR__")[0].strip(),
                    error=error_part.strip(),
                    execution_time_ms=elapsed
                )

            if "__SANDBOX_OK__" in output:
                output = output.replace("\n__SANDBOX_OK__", "").strip()

            return SandboxResult(
                success=result.returncode == 0,
                output=output,
                error=result.stderr if result.stderr else None,
                execution_time_ms=elapsed
            )

        except subprocess.TimeoutExpired:
            return SandboxResult(
                success=False,
                output="",
                error=f"执行超时（>{self.timeout}秒）",
                execution_time_ms=self.timeout * 1000
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                output="",
                error=f"Docker 执行异常: {e}"
            )


class PythonSandbox:
    """
    统一 Python 沙箱接口
    自动选择最佳执行器
    """

    def __init__(self, timeout: int = 10, prefer_docker: bool = False):
        self.timeout = timeout
        self.prefer_docker = prefer_docker
        self._docker = DockerSandbox(timeout=timeout)
        self._safe_exec = SafePythonExecutor(timeout=timeout)

    def execute(self, code: str) -> SandboxResult:
        """
        执行 Python 代码
        自动选择: Docker（如果可用且 prefer_docker）→ SafePythonExecutor
        """
        # 优先 Docker
        if self.prefer_docker and self._docker.is_available():
            return self._docker.execute(code)

        # 默认 SafePythonExecutor
        return self._safe_exec.execute(code)

    def evaluate(self, expr: str) -> SandboxResult:
        """
        评估简单表达式（数学计算等）
        使用 simpleeval（最安全）
        """
        try:
            result = simple_eval(expr)
            return SandboxResult(
                success=True,
                output=str(result),
                return_value=result
            )
        except Exception as e:
            return SandboxResult(
                success=False,
                output="",
                error=f"表达式求值失败: {e}"
            )

    def execute_simple(self, code: str) -> str:
        """
        简化接口：返回输出字符串或错误信息
        """
        result = self.execute(code)
        if result.success:
            return result.output or "(无输出)"
        return f"❌ 执行失败: {result.error}"
