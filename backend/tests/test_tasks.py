from __future__ import annotations

import threading
import time

from app.services.tasks import CANCELED, TaskManager


def test_running_task_can_be_canceled():
    manager = TaskManager(max_workers=1)
    entered = threading.Event()
    release = threading.Event()

    def worker(emit):
        entered.set()
        release.wait(timeout=2)
        emit({"stage": "collect", "message": "next checkpoint"})

    task = manager.submit("analyze", worker)
    assert entered.wait(timeout=1)
    assert manager.cancel(task.id) is task
    release.set()
    deadline = time.monotonic() + 2
    while not task.finished and time.monotonic() < deadline:
        time.sleep(0.01)
    assert task.status == CANCELED
    assert task.error == "任务已由用户取消"
    manager.shutdown()
