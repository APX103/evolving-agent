"""
本地 JSON 文件存储实现
原子写入（.tmp → os.replace），自动保留 .bak 备份
"""
import fcntl
import json
import os
import shutil
from typing import Any

from agent.storage.base import StorageBackend


class LocalJsonStorage(StorageBackend):
    """
    本地 JSON 存储后端
    - 原子写入：先写 .tmp，再用 os.replace 替换
    - 自动备份：旧文件保留为 .bak
    - 目录自动创建
    - 文件锁防止并发写入竞争
    """

    def ensure_dir(self, path: str) -> str:
        """确保目录存在，返回规范化路径"""
        if path and not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        return path

    def load_json(self, filename: str, directory: str, default: Any = None) -> Any:
        """加载 JSON 文件，不存在时返回 default"""
        filepath = os.path.join(directory, filename)
        if not os.path.exists(filepath):
            return default
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # 尝试从 .bak 恢复
            bak_path = filepath + ".bak"
            if os.path.exists(bak_path):
                try:
                    with open(bak_path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
            return default

    def save_json(self, data: Any, filename: str, directory: str) -> None:
        """原子保存 JSON：.tmp → replace，旧文件保留为 .bak"""
        self.ensure_dir(directory)
        filepath = os.path.join(directory, filename)
        tmp_path = filepath + ".tmp"
        bak_path = filepath + ".bak"
        lock_path = filepath + ".lock"

        lock_file = None
        try:
            lock_file = open(lock_path, "w")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

            # 写入临时文件
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())

            # 已有文件则备份
            if os.path.exists(filepath):
                shutil.copy2(filepath, bak_path)

            # 原子替换
            os.replace(tmp_path, filepath)
        finally:
            if lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            # 清理临时文件
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
