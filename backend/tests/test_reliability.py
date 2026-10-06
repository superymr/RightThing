"""配置切换、任务恢复与跨来源采集的回归测试；不访问外网。"""

import threading
import time

import pytest

from app.api.errors import ApiError
from app.api.routes.settings import _candidate
from app.api.schemas import LLMSettingsUpdate
from app.config import Settings
from app.llm.extractor import Extractor
from app.llm.schemas import Direction
from app.models.db import Database
from app.services.cache import LLMCache
from app.services.orchestrator import AnalyzeOptions, Orchestrator
from app.services.tasks import Task, TaskManager
from app.sources import RawJob


def test_new_endpoint_requires_new_key():
    current = Settings(llm_provider="openai", llm_api_key="old-key")
    body = LLMSettingsUpdate(base_url="https://new.example/v1", model="same-model")
    with pytest.raises(ApiError):
        _candidate(current, body)
    assert _candidate(current, body.model_copy(update={"base_url": current.llm_base_url})).llm_api_key == "old-key"


def test_endpoint_switch_does_not_reuse_model_cache(tmp_path):
    settings = Settings(db_path=tmp_path / "cache.db")
    db = Database(settings.db_path)
    db.init_schema()
    cache = LLMCache(db)

    class Provider:
        name = "openai"
        model_name = "same-model"
        calls = 0

        def complete_json(self, **kwargs):
            from app.llm.base import LLMResponse
            self.calls += 1
            return LLMResponse(data={"directions": [{"title": "Python工程师", "match_score": 0.8,
                                                     "reason": "Python", "keywords": ["Python工程师"]}]},
                               model=self.model_name)

    provider = Provider()
    extractor = Extractor(provider, settings, cache)
    extractor.recommend_directions(["Python"])
    extractor.recommend_directions(["Python"])
    assert provider.calls == 1
    settings.llm_base_url = "https://new.example/v1"
    extractor.recommend_directions(["Python"])
    assert provider.calls == 2


def test_completed_task_and_events_survive_restart(tmp_path):
    db = Database(tmp_path / "tasks.db")
    db.init_schema()
    manager = TaskManager(db=db)

    def worker(emit):
        emit({"stage": "collect", "message": "found jobs"})
        return {"session_id": 42}

    task = manager.run_sync("analyze", worker)
    manager.shutdown()
    restored = TaskManager(db=db)
    saved = restored.get(task.id)
    assert saved.status == "done"
    assert saved.result == {"session_id": 42}
    assert saved.events[0]["message"] == "found jobs"
    restored.shutdown()


def test_running_snapshot_becomes_interrupted(tmp_path):
    db = Database(tmp_path / "tasks.db")
    db.init_schema()
    manager = TaskManager(db=db)
    task = Task(id="interrupted-test", kind="analyze", status="running")
    manager._save(task)
    manager.shutdown()
    restored = TaskManager(db=db)
    saved = restored.get(task.id)
    assert saved.status == "interrupted"
    assert saved.finished
    assert "服务重启" in saved.error
    assert "interrupted" in "".join(restored.stream(saved))
    restored.shutdown()


def test_domestic_discovery_is_parallel_and_deduplicates_content(tmp_path):
    barrier = threading.Barrier(2)

    class Source:
        supports_discovery = True

        def __init__(self, name):
            self.name = name
            self.calls = 0

        def search(self, keyword, **kwargs):
            self.calls += 1
            if self.calls == 1:
                barrier.wait(timeout=2)
            return [RawJob(source=self.name, source_job_id=self.name,
                           title="Python工程师", company="测试公司", city="北京",
                           raw_text="掌握 Python 与 SQL，负责后端开发", url=f"https://{self.name}.example/job/1")]

    settings = Settings(db_path=tmp_path / "collect.db", target_market="cn_mainland")
    orchestrator = Orchestrator(settings)
    orchestrator.sources = [Source("ncss"), Source("shixiseng")]
    direction = Direction(title="Python工程师", match_score=0.8, reason="Python", keywords=["Python工程师"])
    jobs, errors = orchestrator._collect(direction, AnalyzeOptions(skills=["Python"], source_mode="live"),
                                        emit=lambda *args: None, live_deadline=time.monotonic() + 5)
    assert not errors
    assert len(jobs) == 1
