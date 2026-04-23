"""Benchmark runner that orchestrates task execution."""
import asyncio
from typing import List, Type

from benchmarks.framework.task import Task, TaskResult


class BenchmarkRunner:
    """Runs a suite of benchmark tasks and collects results."""

    def __init__(self, agent, max_concurrency: int = 4):
        self.agent = agent
        self.max_concurrency = max_concurrency
        self.results: List[TaskResult] = []

    async def run_task(self, task: Task, limit: int | None = None) -> List[TaskResult]:
        """Execute a single task over its dataset."""
        dataset = task.load_dataset()
        if limit is not None:
            dataset = dataset[:limit]

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _run_one(instance):
            async with semaphore:
                return await task.evaluate(self.agent, instance)

        results = await asyncio.gather(*[_run_one(d) for d in dataset])
        self.results.extend(results)
        return results

    async def run_suite(self, tasks: List[Task], limit: int | None = None) -> List[TaskResult]:
        """Execute multiple tasks sequentially."""
        all_results = []
        for task in tasks:
            results = await self.run_task(task, limit=limit)
            all_results.extend(results)
        return all_results

    def summary(self) -> dict:
        """Return a simple score summary."""
        if not self.results:
            return {"total": 0, "average_score": 0.0}
        total = len(self.results)
        avg = sum(r.score for r in self.results) / total
        return {"total": total, "average_score": round(avg, 4)}
