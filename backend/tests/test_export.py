"""报告导出测试。

核心要证明的是**同源**：导出的数字必须与看板接口给的完全一致。
如果导出自己重新聚合一遍，就会出现「网页写 83%、导出写 92%」这种最伤信任的
不一致，而且往往几个月后才被发现 —— 所以这里直接拿接口的 payload 做交叉验证。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.services import dashboard, export


def make_client(tmp_path) -> TestClient:
    settings = Settings(llm_provider="mock", db_path=tmp_path / "export.db")
    return TestClient(create_app(settings, configure_logging=False, serve_frontend=False))


def analyze(client: TestClient) -> int:
    response = client.post(
        "/api/analyze",
        json={
            "skills": ["数据分析", "Python", "SQL"],
            "max_directions": 2,
            "limit_per_direction": 12,
            "sync": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]["session_id"]


class TestMarkdownContent:
    def test_covers_the_expected_sections(self, tmp_path):
        with make_client(tmp_path) as client:
            session_id = analyze(client)
            payload = client.get(f"/api/sessions/{session_id}").json()
            markdown = export.render_markdown(payload)

        assert f"# RightThing 正事 · 分析报告（会话 #{session_id}）" in markdown
        for heading in ("## 输入技能", "## 方向：", "### 技能缺口", "### 技能排行", "### 招聘方偏好"):
            assert heading in markdown, f"缺少章节：{heading}"
        assert "## 口径与免责声明" in markdown
        # 免责声明必须真的写进去 —— 样本偏差是这个产品最容易误导人的地方
        assert "不代表全市场" in markdown

    def test_numbers_match_the_dashboard_payload(self, tmp_path):
        """同源性：md 里的覆盖率/加权分必须来自看板 payload，而不是另算一遍。"""
        with make_client(tmp_path) as client:
            session_id = analyze(client)
            payload = client.get(f"/api/sessions/{session_id}").json()
        markdown = export.render_markdown(payload)

        direction = payload["directions"][0]
        # 排行表只展示 Top N，所以要按导出用的同一套排序取前几项 ——
        # 直接遍历 languages + hard_skills 会包含排在表外的技能（例如 Java），
        # 那是在考核测试而不是考核代码。
        for stat in export._all_skills(direction)[:8]:
            assert f"| {stat['canonical']} " in markdown
            # 覆盖率以百分比形式出现，且与 payload 一致
            assert f"{stat['coverage'] * 100:.0f}%" in markdown

    def test_pipes_in_job_titles_do_not_break_tables(self, tmp_path):
        payload = {
            "session_id": 1,
            "created_at": "2026-01-01T00:00:00+00:00",
            "provider": "mock",
            "model": "mock-rule-engine",
            "total_jobs": 1,
            "city": "",
            "input_skills": ["Python"],
            "canonical_skills": ["Python"],
            "directions": [
                {
                    "direction_id": 1,
                    "title": "算法工程师",
                    "match_score": 0.9,
                    "reason": "理由",
                    "keywords": [],
                    "total_jobs": 1,
                    "ok_jobs": 1,
                    "failed_jobs": 0,
                    "languages": [],
                    "hard_skills": [],
                    "domain_knowledge": [],
                    "soft_skills": [],
                    "education": [],
                    "majors": [],
                    "experience": [],
                    "seniority": [],
                    "certificates": [],
                    "preferred_qualifications": [],
                    "gap": {
                        "coverage_score": 0.5,
                        "have": [],
                        "must_learn": [],
                        "should_learn": [],
                        "nice_to_have": [],
                        "marginal": [],
                    },
                    "jobs": [
                        {
                            "title": "算法工程师｜感知方向",
                            "company": "某公司",
                            "city": "深圳",
                            "source": "sample",
                            "status": "ok",
                        }
                    ],
                }
            ],
        }
        markdown = export.render_markdown(payload)
        job_line = next(line for line in markdown.splitlines() if "感知方向" in line)
        # 未转义的 | 会把表格列数冲乱，渲染出一张错位的表
        assert "｜" in job_line
        assert "算法工程师\\|感知方向" not in job_line  # 全角竖线不该被当成表格分隔符
        assert job_line.count("|") == 6  # 5 列 → 6 个分隔符（含首尾）

    def test_direction_without_samples_is_explicit(self, tmp_path):
        payload = {
            "session_id": 2,
            "created_at": "",
            "provider": "mock",
            "model": "mock",
            "total_jobs": 0,
            "city": "",
            "input_skills": [],
            "canonical_skills": [],
            "directions": [
                {
                    "direction_id": 1,
                    "title": "冷门方向",
                    "match_score": 0.5,
                    "reason": "理由",
                    "keywords": [],
                    "total_jobs": 0,
                    "ok_jobs": 0,
                    "failed_jobs": 0,
                    "languages": [],
                    "hard_skills": [],
                    "domain_knowledge": [],
                    "soft_skills": [],
                    "education": [],
                    "majors": [],
                    "experience": [],
                    "seniority": [],
                    "certificates": [],
                    "preferred_qualifications": [],
                    "gap": {"coverage_score": 0.0, "have": [], "must_learn": [],
                            "should_learn": [], "nice_to_have": [], "marginal": []},
                    "jobs": [],
                }
            ],
        }
        markdown = export.render_markdown(payload)
        assert "没有可用样本" in markdown


class TestExportEndpoint:
    def test_returns_markdown_attachment(self, tmp_path):
        with make_client(tmp_path) as client:
            session_id = analyze(client)
            response = client.get(f"/api/sessions/{session_id}/report.md")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert "attachment" in response.headers["content-disposition"]
        assert f"rightthing-session-{session_id}.md" in response.headers["content-disposition"]
        assert response.text.startswith("# RightThing 正事")

    def test_endpoint_and_dashboard_agree(self, tmp_path):
        """接口层也要同源 —— 不能一边读数据库、一边重新跑分析。"""
        with make_client(tmp_path) as client:
            session_id = analyze(client)
            payload = client.get(f"/api/sessions/{session_id}").json()
            markdown = client.get(f"/api/sessions/{session_id}/report.md").text

        assert markdown == export.render_markdown(payload)

    def test_missing_session_is_404_with_error_contract(self, tmp_path):
        with make_client(tmp_path) as client:
            response = client.get("/api/sessions/9999/report.md")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
