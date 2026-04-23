"""Benchmark report generation."""
import json
from dataclasses import asdict
from typing import List

from benchmarks.framework.task import TaskResult


class BenchmarkReport:
    """Collects results and exports to HTML or JSON."""

    def __init__(self, results: List[TaskResult]):
        self.results = results

    def to_json(self, path: str) -> None:
        """Export results as JSON lines."""
        with open(path, "w", encoding="utf-8") as f:
            for r in self.results:
                f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    def to_html(self, path: str) -> None:
        """Export a simple HTML report."""
        total = len(self.results)
        avg = sum(r.score for r in self.results) / total if total else 0.0
        rows = ""
        for r in self.results:
            color = "#90ee90" if r.score >= 1.0 else "#ffb6c1" if r.score <= 0.0 else "#fffacd"
            rows += (
                f"<tr style='background:{color}'>"
                f"<td>{r.task_name}</td>"
                f"<td>{r.score:.2f}</td>"
                f"<td><pre>{json.dumps(r.input_data, ensure_ascii=False)[:200]}</pre></td>"
                f"<td><pre>{str(r.actual)[:200]}</pre></td>"
                f"</tr>"
            )

        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Benchmark Report</title></head>
<body>
<h1>Benchmark Report</h1>
<p>Total: {total} | Average Score: {avg:.4f}</p>
<table border="1" cellpadding="4">
<tr><th>Task</th><th>Score</th><th>Input</th><th>Actual</th></tr>
{rows}
</table>
</body>
</html>"""
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
