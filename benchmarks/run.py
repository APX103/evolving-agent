"""CLI entry point for running benchmarks."""
import argparse
import asyncio
import sys
import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from benchmarks.framework.runner import BenchmarkRunner
from benchmarks.tasks.tool_use import ToolUseBenchmark


def load_suite(name: str):
    if name == "mini":
        return [ToolUseBenchmark()]
    if name == "full":
        # Future expansion point
        return [ToolUseBenchmark()]
    raise ValueError(f"Unknown suite: {name}")


async def main():
    parser = argparse.ArgumentParser(description="Evolving Agent Benchmark Runner")
    parser.add_argument("--suite", default="mini", help="Benchmark suite name (mini, full)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of instances per task")
    parser.add_argument("--report-json", default=None, help="Path to write JSON report")
    parser.add_argument("--report-html", default=None, help="Path to write HTML report")
    args = parser.parse_args()

    tasks = load_suite(args.suite)

    # Lazy-import agent to avoid heavy import unless needed
    from agent.core.agent import EvolvingAgent

    agent = EvolvingAgent("config.yaml")
    runner = BenchmarkRunner(agent)

    results = await runner.run_suite(tasks, limit=args.limit)
    summary = runner.summary()

    print(f"Benchmark complete: {summary}")

    if args.report_json or args.report_html:
        from benchmarks.framework.report import BenchmarkReport

        report = BenchmarkReport(results)
        if args.report_json:
            report.to_json(args.report_json)
            print(f"JSON report written to {args.report_json}")
        if args.report_html:
            report.to_html(args.report_html)
            print(f"HTML report written to {args.report_html}")


if __name__ == "__main__":
    asyncio.run(main())
