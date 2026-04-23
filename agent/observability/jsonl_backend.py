"""
本地 JSONL 追踪后端（默认）
按天分目录，每个 trace 一个 .jsonl 文件
"""
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class JsonlBackend:
    """
    将 Span 写入本地 JSONL 文件
    路径: storage/traces/{YYYY-MM-DD}/{trace_id}.jsonl
    """

    def __init__(self, base_dir: str = "./storage/traces"):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def export_span(self, span_data: Dict[str, Any]) -> None:
        trace_id = span_data.get("trace_id", "unknown")
        date_str = datetime.fromtimestamp(span_data.get("start_time", time.time())).strftime("%Y-%m-%d")
        dir_path = os.path.join(self.base_dir, date_str)
        os.makedirs(dir_path, exist_ok=True)

        filepath = os.path.join(dir_path, f"{trace_id}.jsonl")
        try:
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(span_data, ensure_ascii=False, default=str) + "\n")
        except Exception as e:
            logger.warning(f"[JsonlBackend] 写入失败: {e}")

    def list_traces(self, date_str: Optional[str] = None, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        """列出最近 trace 文件"""
        target_date = date_str or datetime.now().strftime("%Y-%m-%d")
        dir_path = os.path.join(self.base_dir, target_date)
        if not os.path.exists(dir_path):
            return {"traces": [], "total": 0}

        files = sorted(
            [f for f in os.listdir(dir_path) if f.endswith(".jsonl")],
            key=lambda x: os.path.getmtime(os.path.join(dir_path, x)),
            reverse=True,
        )
        total = len(files)
        files = files[offset: offset + limit]

        traces = []
        for fname in files:
            trace_id = fname.replace(".jsonl", "")
            filepath = os.path.join(dir_path, fname)
            first_line = None
            span_count = 0
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        span_count += 1
                        if first_line is None:
                            first_line = json.loads(line)
            except Exception:
                continue
            traces.append({
                "trace_id": trace_id,
                "span_count": span_count,
                "start_time": first_line.get("start_time") if first_line else None,
                "root_name": first_line.get("name") if first_line else None,
            })

        return {"traces": traces, "total": total}

    def get_trace(self, trace_id: str, date_str: Optional[str] = None) -> Dict[str, Any]:
        """获取完整 trace 树"""
        target_date = date_str or self._guess_date(trace_id)
        filepath = os.path.join(self.base_dir, target_date, f"{trace_id}.jsonl")
        if not os.path.exists(filepath):
            # 尝试在所有日期目录中查找
            for d in os.listdir(self.base_dir):
                candidate = os.path.join(self.base_dir, d, f"{trace_id}.jsonl")
                if os.path.exists(candidate):
                    filepath = candidate
                    break
            else:
                return {"trace_id": trace_id, "spans": []}

        spans = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    spans.append(json.loads(line))
        except Exception as e:
            logger.warning(f"[JsonlBackend] 读取 trace 失败: {e}")

        # 构建树结构
        span_map = {s["span_id"]: s for s in spans}
        roots = []
        for s in spans:
            pid = s.get("parent_id")
            if pid and pid in span_map:
                span_map[pid].setdefault("children", []).append(s)
            else:
                roots.append(s)

        return {"trace_id": trace_id, "spans": spans, "tree": roots}

    def _guess_date(self, trace_id: str) -> str:
        """尝试猜测 trace 所在日期（默认今天）"""
        return datetime.now().strftime("%Y-%m-%d")
