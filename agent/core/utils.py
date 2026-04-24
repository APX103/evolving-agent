"""工具函数"""
import json
from datetime import datetime


def now_str() -> str:
    return datetime.now().strftime("%H:%M:%S")


def pretty_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
