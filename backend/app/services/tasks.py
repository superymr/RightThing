"""后台任务管理与事件流。

**为什么必须有这一层：**
一次完整分析要几十秒到几分钟（取决于模型与样本量）。同步 HTTP 请求会把
浏览器和网关拖到超时，用户也看不到任何进展。所以：

    POST /api/analyze            → 立刻返回 task_id
    GET  /api/tasks/{id}/events  → SSE 持续推送进度
    GET  /api/tasks/{id}         → 轮询兜底（SSE 被代理掐断时用）

**两个容易做错的地方：**

1. **事件必须留档。** SSE 客户端可能在任务开始之后才连上。若只推增量，
   早期事件就永久丢失，用户永远看不到「正在归一化技能」那一步。
   所以每个任务保留完整事件列表，新订阅者先回放历史。
2. **必须有终止信号。** 任务结束时要把流显式关掉，否则 SSE 连接会一直挂着，
   前端只能靠超时猜「是不是结束了」。
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from ..utils.timeutil import now_iso

# SSE 心跳间隔：代理通常在 30~60 秒无数据时断开连接
KEEPALIVE_SECONDS = 15
_END = None  # 队列里的终止哨兵

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELED = "canceled"
TERMINAL = frozenset({DONE, FAILED, CANCELED})


class TaskCanceled(RuntimeError):
    pass


@dataclass
class Task:
    id: str
    kind: str
    status: str = PENDING
    created_at: str = field(default_factory=now_iso)
    started_at: str = ""
    finished_at: str = ""
    events: list[dict] = field(default_factory=list)
    result: Any = None
    error: str = ""
    cancel_requested: bool = False
    subscribers: list[queue.Queue] = field(default_factory=list)

    @property
    def finished(self) -> bool:
        return self.status in TERMINAL

    def summary(self) -> dict:
        return {
            "task_id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "event_count": len(self.events),
            "last_event": self.events[-1] if self.events else None,
            "error": self.error,
        }


class TaskManager:
    """把长任务放到线程池里跑，并把进度以事件流的形式暴露出去。"""

    def __init__(self, *, max_workers: int = 3, max_history: int = 50) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="jobradar-task"
        )
        self._max_history = max_history

    # ------------------------------------------------------------------
    def submit(self, kind: str, worker: Callable[[Callable[[dict], None]], Any]) -> Task:
        """提交任务。worker 接受一个 emit 回调，返回值即任务结果。"""
        task = Task(id=uuid.uuid4().hex[:12], kind=kind, status=RUNNING, started_at=now_iso())
        with self._lock:
            self._prune_locked()
            self._tasks[task.id] = task
        self._executor.submit(self._run, task, worker)
        return task

    def run_sync(self, kind: str, worker: Callable[[Callable[[dict], None]], Any]) -> Task:
        """同步执行（小样本、调试、测试用）。不占线程池，直接在当前线程跑完。"""
        task = Task(id=uuid.uuid4().hex[:12], kind=kind, status=RUNNING, started_at=now_iso())
        with self._lock:
            self._prune_locked()
            self._tasks[task.id] = task
        self._run(task, worker)
        return task

    def _run(self, task: Task, worker: Callable[[Callable[[dict], None]], Any]) -> None:
        def emit(payload: dict) -> None:
            if task.cancel_requested:
                raise TaskCanceled("任务已由用户取消")
            self._publish(task, payload)

        try:
            task.result = worker(emit)
            task.status = DONE
        except TaskCanceled as exc:
            task.status = CANCELED
            task.error = str(exc)
        except Exception as exc:  # noqa: BLE001 - 任务边界，必须转成状态而不是让线程静默死掉
            task.status = FAILED
            task.error = f"{type(exc).__name__}: {exc}"[:500]
            self._publish(task, {"stage": "error", "message": task.error})
        finally:
            task.finished_at = now_iso()
            self._publish(task, {"stage": task.status, "message": task.error or "任务结束"})
            self._close(task)

    def cancel(self, task_id: str) -> Task | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is not None and not task.finished:
                task.cancel_requested = True
            return task

    # ------------------------------------------------------------------
    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list(self) -> list[Task]:
        with self._lock:
            return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    # ------------------------------------------------------------------
    def subscribe(self, task: Task) -> queue.Queue:
        channel: queue.Queue = queue.Queue()
        with self._lock:
            task.subscribers.append(channel)
        return channel

    def unsubscribe(self, task: Task, channel: queue.Queue) -> None:
        with self._lock:
            if channel in task.subscribers:
                task.subscribers.remove(channel)

    def _publish(self, task: Task, payload: dict) -> None:
        event = dict(payload)
        event.setdefault("at", now_iso())
        with self._lock:
            task.events.append(event)
            channels = list(task.subscribers)
        for channel in channels:
            channel.put(event)

    def _close(self, task: Task) -> None:
        with self._lock:
            channels = list(task.subscribers)
        for channel in channels:
            channel.put(_END)

    # ------------------------------------------------------------------
    def stream(self, task: Task) -> Iterator[str]:
        """SSE 事件流。

        先回放历史事件再转入实时推送 —— 晚连的客户端不会丢失任何进度。
        同步生成器即可：Starlette 会把它放进线程池消费，不阻塞事件循环。
        """
        channel = self.subscribe(task)
        try:
            for event in list(task.events):
                yield _format_sse(event)

            if task.finished:
                return

            while True:
                try:
                    event = channel.get(timeout=KEEPALIVE_SECONDS)
                except queue.Empty:
                    # 心跳注释：防止反向代理因长时间无数据而掐断连接
                    yield ": keepalive\n\n"
                    continue
                if event is _END:
                    break
                yield _format_sse(event)
        finally:
            self.unsubscribe(task, channel)

    # ------------------------------------------------------------------
    def _prune_locked(self) -> None:
        """只保留最近 max_history 个任务，避免长时间运行后内存无限增长。"""
        if len(self._tasks) <= self._max_history:
            return
        ordered = sorted(self._tasks.values(), key=lambda t: t.created_at)
        for task in ordered[: len(self._tasks) - self._max_history]:
            if not task.finished and task.subscribers:
                continue  # 还在跑的、还有人听的，不清理
            self._tasks.pop(task.id, None)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def _format_sse(event: dict) -> str:
    stage = event.get("stage", "message")
    payload = json.dumps(event, ensure_ascii=False)
    return f"event: {stage}\ndata: {payload}\n\n"
