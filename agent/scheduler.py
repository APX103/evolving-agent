"""
Cron 主动调度器
支持自然语言定时任务，Agent 可 24/7 后台自主运行
"""
import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Callable, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    """定时任务定义"""
    task_id: str
    name: str
    description: str
    trigger_type: str          # "cron" | "interval" | "date"
    trigger_config: Dict       # {"hour": 8, "minute": 0} 或 {"seconds": 3600}
    prompt: str                # 触发时发送给 Agent 的提示
    agent_name: str = "companion"  # 目标 Agent
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_run: Optional[str] = None
    run_count: int = 0


class AgentScheduler:
    """
    Agent 主动调度器
    - 基于 APScheduler 的异步调度
    - 支持 cron 表达式、间隔触发、自然语言解析
    - 任务持久化到 JSON
    - 触发时调用回调函数（由 AgentRegistry 处理）
    """

    def __init__(self, storage_path: str = "./storage/scheduler"):
        self.storage_path = storage_path
        os.makedirs(self.storage_path, exist_ok=True)
        self._tasks: Dict[str, ScheduledTask] = {}
        self._scheduler = AsyncIOScheduler()
        self._callback: Optional[Callable[[ScheduledTask], asyncio.Future]] = None
        self._load_tasks()

    def set_callback(self, callback: Callable[[ScheduledTask], asyncio.Future]):
        """设置任务触发时的回调（由 AgentRegistry 注册）"""
        self._callback = callback

    def start(self):
        """启动调度器"""
        self._scheduler.start()
        logger.info(f"[Scheduler] 已启动，加载 {len(self._tasks)} 个任务")
        for task in self._tasks.values():
            if task.enabled:
                self._register_job(task)

    def shutdown(self):
        """关闭调度器"""
        self._scheduler.shutdown()
        logger.info("[Scheduler] 已关闭")

    # ── 任务管理 ──

    def add_task(self, task: ScheduledTask) -> str:
        """添加任务并持久化"""
        if not task.task_id:
            task.task_id = str(uuid.uuid4())[:8]
        self._tasks[task.task_id] = task
        self._save_tasks()
        if task.enabled:
            self._register_job(task)
        logger.info(f"[Scheduler] 添加任务: {task.name} ({task.task_id})")
        return task.task_id

    def remove_task(self, task_id: str) -> bool:
        """删除任务"""
        if task_id in self._tasks:
            self._scheduler.remove_job(task_id)
            del self._tasks[task_id]
            self._save_tasks()
            return True
        return False

    def enable_task(self, task_id: str) -> bool:
        """启用任务"""
        if task_id in self._tasks:
            self._tasks[task_id].enabled = True
            self._register_job(self._tasks[task_id])
            self._save_tasks()
            return True
        return False

    def disable_task(self, task_id: str) -> bool:
        """禁用任务"""
        if task_id in self._tasks:
            self._tasks[task_id].enabled = False
            try:
                self._scheduler.remove_job(task_id)
            except Exception:
                pass
            self._save_tasks()
            return True
        return False

    def list_tasks(self) -> List[Dict]:
        """列出所有任务"""
        return [asdict(t) for t in self._tasks.values()]

    # ── 自然语言解析 ──

    def parse_natural_language(self, text: str) -> Optional[ScheduledTask]:
        """
        简单的自然语言定时任务解析
        例: "每天早上8点发日报" -> cron trigger
            "每30分钟检查一次" -> interval trigger
            "周五下午6点提醒下班" -> cron trigger
        """
        import re

        text_lower = text.lower()

        def _parse_chinese_time(t: str) -> tuple:
            """解析中文时间，如 '早上8点', '下午6点', '8:00', '18点'"""
            # 尝试 HH:MM
            m = re.search(r'(\d{1,2}):(\d{2})', t)
            if m:
                return int(m.group(1)), int(m.group(2))
            # 早上/上午 N点
            m = re.search(r'(?:早上|上午)\s*(\d{1,2})\s*点', t)
            if m:
                return int(m.group(1)), 0
            # 下午/晚上 N点
            m = re.search(r'(?:下午|晚上)\s*(\d{1,2})\s*点', t)
            if m:
                h = int(m.group(1))
                return (h + 12) if h < 12 else h, 0
            # N点
            m = re.search(r'(\d{1,2})\s*点', t)
            if m:
                return int(m.group(1)), 0
            return 9, 0

        # 模式 1: 每天
        if "每天" in text or "每日" in text:
            hour, minute = _parse_chinese_time(text)
            return ScheduledTask(
                task_id="",
                name="每日定时任务",
                description=text,
                trigger_type="cron",
                trigger_config={"hour": hour, "minute": minute},
                prompt=text,
            )

        # 模式 2: 每 N 分钟/小时/秒
        m = re.search(r'每\s*(\d+)\s*(分钟|小时|秒)', text)
        if m:
            val = int(m.group(1))
            unit = m.group(2)
            config_map = {"分钟": "minutes", "小时": "hours", "秒": "seconds"}
            config = {config_map[unit]: val}
            return ScheduledTask(
                task_id="",
                name=f"每{val}{unit}任务",
                description=text,
                trigger_type="interval",
                trigger_config=config,
                prompt=text,
            )

        # 模式 3: 每周 X
        weekdays = {"周一": "mon", "周二": "tue", "周三": "wed", "周四": "thu",
                    "周五": "fri", "周六": "sat", "周日": "sun"}
        for cn, en in weekdays.items():
            if cn in text:
                hour, minute = _parse_chinese_time(text)
                return ScheduledTask(
                    task_id="",
                    name=f"每周{cn}任务",
                    description=text,
                    trigger_type="cron",
                    trigger_config={"day_of_week": en, "hour": hour, "minute": minute},
                    prompt=text,
                )

        return None

    # ── 内部 ──

    def _register_job(self, task: ScheduledTask):
        """注册 APScheduler job"""
        try:
            self._scheduler.remove_job(task.task_id)
        except Exception:
            pass

        if task.trigger_type == "cron":
            trigger = CronTrigger(**task.trigger_config)
        elif task.trigger_type == "interval":
            trigger = IntervalTrigger(**task.trigger_config)
        else:
            return

        self._scheduler.add_job(
            self._on_trigger,
            trigger=trigger,
            id=task.task_id,
            args=[task.task_id],
            replace_existing=True,
        )

    async def _on_trigger(self, task_id: str):
        """任务触发回调"""
        task = self._tasks.get(task_id)
        if not task or not task.enabled:
            return

        task.last_run = datetime.now().isoformat()
        task.run_count += 1
        self._save_tasks()

        logger.info(f"[Scheduler] 任务触发: {task.name} -> {task.agent_name}")

        if self._callback:
            try:
                await self._callback(task)
            except Exception as e:
                logger.error(f"[Scheduler] 任务执行失败: {e}")

    # ── 持久化 ──

    def _tasks_file(self) -> str:
        return os.path.join(self.storage_path, "tasks.json")

    def _load_tasks(self):
        path = self._tasks_file()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                task = ScheduledTask(**item)
                self._tasks[task.task_id] = task
        except Exception as e:
            logger.warning(f"[Scheduler] 加载任务失败: {e}")

    def _save_tasks(self):
        path = self._tasks_file()
        try:
            data = [asdict(t) for t in self._tasks.values()]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[Scheduler] 保存任务失败: {e}")
