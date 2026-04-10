"""
异步任务队列

- 并发控制（信号量限制同时运行的爬取任务）
- 任务优先级
- 失败重试
- 进度跟踪
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional
from loguru import logger


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class TaskPriority(Enum):
    HIGH = 0
    NORMAL = 1
    LOW = 2


@dataclass
class ScraperTask:
    """爬取任务"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    platform: str = ""
    action: str = ""                    # search / detail / price
    params: dict = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = 0
    completed_at: float = 0
    retries: int = 0
    max_retries: int = 2

    @property
    def elapsed(self) -> float:
        if self.completed_at:
            return self.completed_at - self.started_at
        elif self.started_at:
            return time.time() - self.started_at
        return 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "platform": self.platform,
            "action": self.action,
            "params": self.params,
            "status": self.status.value,
            "error": self.error,
            "elapsed": round(self.elapsed, 2),
            "retries": self.retries,
        }


class ScraperTaskQueue:
    """
    爬虫任务队列

    支持:
    - 并发上限控制（默认10个并发任务）
    - 任务优先级排序
    - 自动重试
    - 批量提交
    - 进度跟踪
    """

    def __init__(self, max_concurrent: int = 10):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, ScraperTask] = {}
        self._pending: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._running_count = 0
        self._total_completed = 0
        self._total_failed = 0

    async def submit(self, task: ScraperTask) -> str:
        """提交单个任务"""
        self._tasks[task.id] = task
        await self._pending.put((task.priority.value, task.created_at, task.id))
        return task.id

    async def submit_batch(self, tasks: list[ScraperTask]) -> list[str]:
        """批量提交任务"""
        ids = []
        for task in tasks:
            task_id = await self.submit(task)
            ids.append(task_id)
        return ids

    async def process_all(
        self,
        executor: Callable[[ScraperTask], Coroutine[Any, Any, Any]],
    ) -> dict:
        """
        处理队列中所有任务

        Args:
            executor: 异步执行函数，接收 ScraperTask，返回结果

        Returns:
            处理统计
        """
        workers = []

        while not self._pending.empty() or self._running_count > 0:
            try:
                _, _, task_id = self._pending.get_nowait()
                task = self._tasks.get(task_id)
                if not task:
                    continue
                worker = asyncio.create_task(self._run_task(task, executor))
                workers.append(worker)
            except asyncio.QueueEmpty:
                if workers:
                    done, workers_set = await asyncio.wait(
                        workers, timeout=1, return_when=asyncio.FIRST_COMPLETED
                    )
                    workers = list(workers_set - done)
                else:
                    await asyncio.sleep(0.1)

        if workers:
            await asyncio.gather(*workers, return_exceptions=True)

        return self.get_summary()

    async def _run_task(
        self,
        task: ScraperTask,
        executor: Callable[[ScraperTask], Coroutine[Any, Any, Any]],
    ):
        """执行单个任务"""
        async with self._semaphore:
            self._running_count += 1
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()

            try:
                task.result = await executor(task)
                task.status = TaskStatus.COMPLETED
                task.completed_at = time.time()
                self._total_completed += 1
            except Exception as e:
                task.error = str(e)
                task.retries += 1

                if task.retries <= task.max_retries:
                    task.status = TaskStatus.RETRYING
                    logger.info(f"[任务队列] 任务 {task.id} 重试 {task.retries}/{task.max_retries}")
                    await self._pending.put((task.priority.value, time.time(), task.id))
                else:
                    task.status = TaskStatus.FAILED
                    task.completed_at = time.time()
                    self._total_failed += 1
                    logger.warning(f"[任务队列] 任务 {task.id} 最终失败: {e}")
            finally:
                self._running_count -= 1

    def get_task(self, task_id: str) -> Optional[dict]:
        """获取任务状态"""
        task = self._tasks.get(task_id)
        return task.to_dict() if task else None

    def get_summary(self) -> dict:
        """获取队列统计"""
        statuses = {}
        for task in self._tasks.values():
            s = task.status.value
            statuses[s] = statuses.get(s, 0) + 1

        return {
            "total": len(self._tasks),
            "pending": self._pending.qsize(),
            "running": self._running_count,
            "completed": self._total_completed,
            "failed": self._total_failed,
            "statuses": statuses,
        }

    def clear_completed(self):
        """清理已完成的任务"""
        to_remove = [
            tid for tid, t in self._tasks.items()
            if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
        ]
        for tid in to_remove:
            del self._tasks[tid]
