"""API 层测试。

覆盖三类容易被忽略的东西：
1. **错误契约** —— 前端要靠 error.code 决定展示方式，码值不能漂移；
2. **长任务的两种消费方式** —— SSE 与轮询必须给出同一个结果；
3. **结果不依赖内存** —— 看板从数据库读回，重启后依然可查。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings

ANALYZE_BODY = {
    "skills": ["数据分析", "Python", "SQL"],
    "max_directions": 2,
    "limit_per_direction": 12,
    "sync": True,
}


def make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(**{"llm_provider": "mock", "db_path": tmp_path / "api.db", **overrides})
    # serve_frontend=False：把「根路径是 JSON 还是前端页面」钉死，
    # 否则本机构建过 dist 的开发者会看到测试挂掉、CI 上却是绿的。
    return TestClient(create_app(settings, configure_logging=False, serve_frontend=False))


@pytest.fixture()
def client(tmp_path):
    with make_client(tmp_path) as test_client:
        yield test_client


@pytest.fixture()
def analyzed(client) -> dict:
    """跑完一次同步分析，返回任务结果摘要。"""
    response = client.post("/api/analyze", json=ANALYZE_BODY)
    assert response.status_code == 200, response.text
    return response.json()


class TestMeta:
    def test_root(self, client):
        body = client.get("/").json()
        assert body["version"]
        assert body["docs"] == "/docs"

    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["provider"] == "mock"
        assert body["llm_ready"] is True

    def test_health_deep_in_mock_mode(self, client):
        """mock 模式没有外部依赖，deep 检查也应通过而不是报错。"""
        body = client.get("/api/health", params={"deep": True}).json()
        assert body["llm_ready"] is True
        assert "规则引擎" in body["detail"]

    def test_health_stays_available_when_llm_misconfigured(self, tmp_path):
        """没填 Key 不该让服务起不来 —— 健康检查存在的意义就是把问题报告出来。"""
        with make_client(tmp_path, llm_provider="openai", llm_api_key="") as client:
            response = client.get("/api/health")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "degraded"
            assert body["llm_ready"] is False

    def test_directions(self, client):
        body = client.get("/api/directions").json()
        assert "数据分析师" in body["directions"]
        assert body["total_jobs"] == 24
        assert body["live_sources_enabled"] is False

    def test_source_health(self, client):
        body = client.get("/api/sources/health").json()
        assert body["live_sources_enabled"] is False
        assert body["sources"][0]["name"] == "sample"
        assert body["sources"][0]["status"] == "ok"


class TestLLMSettings:
    def test_get_never_returns_api_key(self, tmp_path):
        with make_client(tmp_path, llm_api_key="sk-secret-123456", config_path=tmp_path / ".env") as client:
            response = client.get("/api/settings/llm")
            body = response.json()
            assert response.status_code == 200
            assert body["api_key_configured"] is True
            assert body["api_key_hint"] == "sk-…3456"
            assert "sk-secret-123456" not in response.text

    def test_update_persists_and_applies_without_restart(self, tmp_path):
        env_path = tmp_path / ".env"
        env_path.write_text("KEEP_ME=yes\nLLM_PROVIDER=mock\n", encoding="utf-8")
        with make_client(tmp_path, config_path=env_path) as client:
            response = client.put(
                "/api/settings/llm",
                json={
                    "provider": "openai",
                    "base_url": "https://llm.example/v1/",
                    "model": "custom-model",
                    "strong_model": "",
                    "api_key": "sk-new-secret",
                    "temperature": 0,
                    "timeout": 90,
                    "max_retries": 3,
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["base_url"] == "https://llm.example/v1"
            health = client.get("/api/health").json()
            assert health["provider"] == "openai"
            assert health["model"] == "custom-model"

        saved = env_path.read_text(encoding="utf-8")
        assert "KEEP_ME=yes" in saved
        assert "LLM_API_KEY=sk-new-secret" in saved
        assert "LLM_MODEL=custom-model" in saved

    def test_update_rejects_incomplete_external_config(self, client):
        response = client.put(
            "/api/settings/llm",
            json={
                "provider": "openai",
                "base_url": "",
                "model": "x",
                "api_key": "secret",
                "temperature": 0,
                "timeout": 120,
                "max_retries": 2,
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_llm_settings"


class TestNormalize:
    def test_normalizes_aliases(self, client):
        response = client.post("/api/skills/normalize", json={"skills": ["python3", "熟练使用ROS"]})
        assert response.status_code == 200
        canonical = {item["canonical"] for item in response.json()["items"]}
        assert canonical == {"Python", "ROS"}

    def test_accepts_comma_separated_string(self, client):
        """容忍字符串输入：为此返回 422 只会让调用方困惑。"""
        body = client.post("/api/skills/normalize", json={"skills": "Python, SQL"}).json()
        assert {item["canonical"] for item in body["items"]} == {"Python", "SQL"}

    def test_unknown_skill_is_reported_not_dropped(self, client):
        body = client.post("/api/skills/normalize", json={"skills": ["星际导航"]}).json()
        item = body["items"][0]
        assert item["canonical"] == "星际导航"
        assert item["known"] is False

    def test_empty_list(self, client):
        assert client.post("/api/skills/normalize", json={"skills": []}).json()["items"] == []


class TestAnalyzeSync:
    def test_rejects_unknown_source_mode(self, client):
        response = client.post(
            "/api/analyze", json={**ANALYZE_BODY, "source_mode": "untrusted-crawler"}
        )
        assert response.status_code == 422

    def test_returns_summary(self, analyzed):
        assert analyzed["status"] == "done"
        assert analyzed["result"]["session_id"] > 0
        assert analyzed["result"]["total_jobs"] == 24
        assert len(analyzed["result"]["directions"]) == 2

    def test_direction_summary_has_coverage(self, analyzed):
        for direction in analyzed["result"]["directions"]:
            assert 0.0 <= direction["coverage_score"] <= 1.0
            assert direction["reason"]

    def test_dashboard_matches_run(self, client, analyzed):
        session_id = analyzed["result"]["session_id"]
        board = client.get(f"/api/sessions/{session_id}").json()

        assert board["session_id"] == session_id
        assert board["total_jobs"] == 24
        assert board["canonical_skills"] == ["数据分析", "Python", "SQL"]

        data_direction = next(d for d in board["directions"] if d["title"] == "数据分析师")
        top_languages = {s["canonical"] for s in data_direction["languages"][:2]}
        assert top_languages == {"SQL", "Python"}
        assert data_direction["gap"]["coverage_score"] > 0
        assert {s["canonical"] for s in data_direction["gap"]["have"]} >= {"SQL", "Python"}

    def test_job_detail_exposes_raw_text_and_evidence(self, client, analyzed):
        session_id = analyzed["result"]["session_id"]
        board = client.get(f"/api/sessions/{session_id}").json()
        job_id = board["directions"][0]["jobs"][0]["job_id"]

        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["raw_text"]
        assert job["profile"] is not None
        assert job["extraction_status"] == "ok"

        skills = (
            job["profile"]["programming_languages"]
            + job["profile"]["hard_skills"]
            + job["profile"]["domain_knowledge"]
        )
        assert skills
        for skill in skills:
            # evidence 必须是原文子串 —— 产品「可回溯」承诺的技术基础
            assert skill["evidence"] in job["raw_text"]

    def test_session_appears_in_history(self, client, analyzed):
        sessions = client.get("/api/sessions").json()["sessions"]
        assert analyzed["result"]["session_id"] in {s["session_id"] for s in sessions}


class TestAnalyzeAsync:
    def test_returns_202_with_urls(self, client):
        response = client.post("/api/analyze", json={**ANALYZE_BODY, "sync": False})
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "running"
        assert body["events_url"] == f"/api/tasks/{body['task_id']}/events"
        assert body["poll_url"] == f"/api/tasks/{body['task_id']}"

    def test_sse_stream_carries_progress_and_terminates(self, client):
        task_id = client.post("/api/analyze", json={**ANALYZE_BODY, "sync": False}).json()["task_id"]

        response = client.get(f"/api/tasks/{task_id}/events")
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        text = response.text

        for stage in ("normalize", "directions", "extract", "aggregate", "done"):
            assert f"event: {stage}" in text, f"缺少 {stage} 阶段的事件"

        payloads = [
            json.loads(line[len("data: ") :])
            for line in text.splitlines()
            if line.startswith("data: ")
        ]
        assert any(p.get("total") == 12 and p.get("current", 0) > 0 for p in payloads), (
            "抽取阶段应当报告 已解析 n/12 的进度"
        )

    def test_polling_and_sse_agree(self, client):
        task_id = client.post("/api/analyze", json={**ANALYZE_BODY, "sync": False}).json()["task_id"]
        client.get(f"/api/tasks/{task_id}/events")  # 消费掉进度流，确保任务结束

        body = client.get(f"/api/tasks/{task_id}").json()
        assert body["status"] == "done"
        assert body["result"]["session_id"] > 0

    def test_task_list(self, client):
        client.post("/api/analyze", json=ANALYZE_BODY)
        body = client.get("/api/tasks").json()
        assert body["tasks"]
        assert body["tasks"][0]["kind"] == "analyze"


class TestManualImport:
    JD = (
        "岗位名称：高级数据工程师\n"
        "岗位职责：\n"
        "1. 负责数据平台建设\n"
        "任职要求：\n"
        "1. 熟练掌握Python与SQL\n"
        "2. 熟悉Flink与Kafka\n"
    )

    def test_imports_and_extracts(self, client):
        response = client.post("/api/jobs/manual", json={"text": self.JD})
        assert response.status_code == 201, response.text
        body = response.json()

        assert body["session_id"] > 0
        job = body["job"]
        assert job["source"] == "manual"
        assert job["title"] == "高级数据工程师"
        names = {
            s["name"]
            for s in (
                job["profile"]["programming_languages"]
                + job["profile"]["hard_skills"]
                + job["profile"]["domain_knowledge"]
            )
        }
        assert {"Python", "SQL", "Flink", "Kafka"} <= names

    def test_imported_job_is_readable_via_session(self, client):
        session_id = client.post("/api/jobs/manual", json={"text": self.JD}).json()["session_id"]
        board = client.get(f"/api/sessions/{session_id}").json()
        assert board["total_jobs"] == 1
        assert board["directions"][0]["title"] == "手动录入岗位"

    def test_analyze_endpoint_accepts_jd_texts(self, client):
        response = client.post(
            "/api/analyze", json={"skills": ["Python"], "jd_texts": [self.JD], "sync": True}
        )
        assert response.status_code == 200
        assert response.json()["result"]["total_jobs"] == 1


class TestErrorContract:
    def test_empty_input(self, client):
        response = client.post("/api/analyze", json={})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "empty_input"

    def test_out_of_range_is_validation_error(self, client):
        response = client.post("/api/analyze", json={"skills": ["Python"], "max_directions": 99})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"
        assert response.json()["error"]["detail"]

    def test_unknown_session(self, client):
        response = client.get("/api/sessions/99999")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_unknown_job(self, client):
        assert client.get("/api/jobs/99999").status_code == 404

    def test_unknown_task(self, client):
        response = client.get("/api/tasks/deadbeef")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_llm_not_configured_returns_503(self, tmp_path):
        with make_client(tmp_path, llm_provider="openai", llm_api_key="") as client:
            response = client.post("/api/analyze", json=ANALYZE_BODY)
            assert response.status_code == 503
            body = response.json()["error"]
            assert body["code"] == "llm_not_configured"
            # 必须告诉用户怎么修，而不只是说「配置错了」
            assert ".env" in body["detail"]["hint"]


class TestCors:
    def test_preflight_allows_vite_dev_server(self, client):
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


class TestOpenApi:
    def test_schema_is_generated(self, client):
        schema = client.get("/openapi.json").json()
        paths = schema["paths"]
        for path in (
            "/api/health",
            "/api/skills/normalize",
            "/api/analyze",
            "/api/tasks/{task_id}/events",
            "/api/sessions/{session_id}",
            "/api/jobs/{job_id}",
            "/api/jobs/manual",
        ):
            assert path in paths
