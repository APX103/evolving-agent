"""
统一配置中心
只读一次 yaml，全局通过 Config 单例访问
"""
import os
from typing import Any, Dict

import yaml

from agent.core.config_models import AppConfig


class Config:
    """配置单例"""
    _instance = None
    _config: Dict[str, Any] = {}

    def __new__(cls, config_path: str = "config.yaml"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load(config_path)
        return cls._instance

    def _load(self, config_path: str):
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        with open(config_path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f) or {}
        self._path = config_path
        self._validated = AppConfig.model_validate(self._config)

    @property
    def raw(self) -> Dict[str, Any]:
        return self._config

    @property
    def kimi(self) -> Dict[str, Any]:
        return self._validated.kimi.model_dump()

    @property
    def agent(self) -> Dict[str, Any]:
        return self._validated.agent.model_dump()

    @property
    def storage(self) -> Dict[str, Any]:
        return self._validated.storage.model_dump()

    def get(self, key: str, default: Any = None) -> Any:
        """支持点号分隔路径，如 'agent.name'"""
        keys = key.split(".")
        val = self._config
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val


def get_config(config_path: str = "config.yaml") -> Config:
    """获取配置单例（兼容旧代码直接调用的方式）"""
    return Config(config_path)
