"""端到端测试：从技能输入到排行榜输出的完整链路。

这里验证的是 M1 的交付标准：
1. 全流程能跑通，产出有意义的排行榜；
2. **重跑命中缓存且结果完全一致** —— 分析类产品的可复现性底线。
"""

from __future__ import annotations

import json

import pytest

from app import report as report_module
from app.config import Settings
from app.services.orchestrator import AnalyzeOptions, Orchestrator

SKILLS = ["数据分析", "Python", "SQL", "Excel", "数据可视化"]


def make_settings(tmp_path, *, cache: bool = True) -> Settings:
    return Settings(
        llm_provider="mock",
        db_path=tmp_path / "e2e.db",
        cache_enabled=cache,
    )


def signature(report) -> list[tuple]:
    """把结果压缩成可比较的指纹（剔除 session_id / 耗时这类非确定性字段）。"""
    out = []
    for item in report.reports:
        out.append(
            (
                item.direction.title,
                item.total,
                [
                    (s.canonical, s.count, s.required_count, s.weighted_score)
                    for s in item.aggregate.all_skills
                ],
                item.gap.coverage_score,
            )
        )
    return out


@pytest.fixture()
def report(tmp_path):
    orchestrator = Orchestrator(make_settings(tmp_path))
    return orchestrator.analyze(
        AnalyzeOptions(skills=SKILLS, max_directions=2, limit_per_direction=12)
    )


class TestPipeline:
    def test_produces_multiple_directions(self, report):
        titles = [item.direction.title for item in report.reports]
        assert "数据分析师" in titles

    def test_all_sample_jobs_analyzed(self, report):
        assert report.total_jobs == 24

    def test_no_extraction_failures(self, report):
        assert all(item.failed == 0 for item in report.reports)

    def test_direction_reports_have_skills(self, report):
        for item in report.reports:
            assert item.aggregate.languages, f"{item.direction.title} 没有抽到任何编程语言"


class TestRankings:
    def test_sql_and_python_are_top_languages_for_data_direction(self, report):
        data = next(r for r in report.reports if r.direction.title == "数据分析师")
        top = {s.canonical for s in data.aggregate.languages[:2]}
        assert top == {"SQL", "Python"}

    def test_coverage_never_exceeds_one(self, report):
        for item in report.reports:
            for stat in item.aggregate.all_skills:
                assert 0 < stat.coverage <= 1.0
                assert stat.count <= item.aggregate.total_jobs

    def test_weighted_score_matches_formula(self, report):
        for item in report.reports:
            for stat in item.aggregate.all_skills:
                expected = round(stat.required_count * 1.0 + stat.preferred_count * 0.4, 2)
                assert stat.weighted_score == expected

    def test_preferred_qualifications_are_ranked(self, report):
        data = next(r for r in report.reports if r.direction.title == "数据分析师")
        assert data.aggregate.preferred_qualifications
        counts = [p.count for p in data.aggregate.preferred_qualifications]
        assert counts == sorted(counts, reverse=True)


class TestGapAnalysis:
    def test_owned_skills_appear_in_have(self, report):
        data = next(r for r in report.reports if r.direction.title == "数据分析师")
        have = {s.canonical for s in data.gap.have}
        assert {"SQL", "Python", "数据分析", "数据可视化"} <= have

    def test_robot_skills_are_marginal_for_data_direction(self, report):
        data = next(r for r in report.reports if r.direction.title == "数据分析师")
        assert "SQL" not in {i.stat.canonical for i in data.gap.missing}

    def test_gap_partitions_the_market(self, report):
        for item in report.reports:
            owned = {s.canonical for s in item.gap.have}
            missing = {i.stat.canonical for i in item.gap.missing}
            assert not (owned & missing)
            assert len(owned) + len(missing) == len(item.aggregate.all_skills)


class TestReproducibility:
    def test_second_run_hits_cache_and_matches(self, tmp_path):
        settings = make_settings(tmp_path)
        options = AnalyzeOptions(skills=SKILLS, max_directions=2, limit_per_direction=12)

        first = Orchestrator(settings).analyze(options)
        assert all(item.cache_hits == 0 for item in first.reports)

        second = Orchestrator(settings).analyze(options)
        for item in second.reports:
            assert item.cache_hits == item.total, "第二次运行应当全部命中缓存"
            assert item.failed == 0

        assert signature(first) == signature(second)

    def test_disabling_cache_still_gives_same_numbers(self, tmp_path):
        """缓存只影响速度，绝不能影响结果。"""
        options = AnalyzeOptions(skills=SKILLS, max_directions=2, limit_per_direction=12)
        cached = Orchestrator(make_settings(tmp_path)).analyze(options)
        uncached = Orchestrator(make_settings(tmp_path, cache=False)).analyze(options)
        assert signature(cached) == signature(uncached)


class TestPersistence:
    def test_session_is_recorded(self, report, tmp_path):
        assert report.session_id > 0
        from app.models.db import Database

        db = Database(tmp_path / "e2e.db")
        assert db.query_one("SELECT COUNT(*) AS c FROM analysis_session")["c"] == 1
        assert db.query_one("SELECT COUNT(*) AS c FROM raw_job")["c"] == 24
        assert db.query_one("SELECT COUNT(*) AS c FROM jd_skill")["c"] > 0

    def test_jobs_are_linked_to_session_and_direction(self, report, tmp_path):
        """raw_job 跨会话去重，所以归属关系必须落在 jd_profile 上。

        这条不变量一旦破坏，「从数据库读回一次历史分析」就会串台或查空。
        """
        from app.models.db import Database

        db = Database(tmp_path / "e2e.db")
        rows = db.query("SELECT DISTINCT session_id, direction_id FROM jd_profile")
        assert all(row["session_id"] == report.session_id for row in rows)
        assert len(rows) == 2, "两个方向应各存一份抽取结果"


class TestSerialization:
    def test_json_export_is_valid_and_complete(self, report):
        payload = json.loads(report_module.to_json(report))
        assert payload["input_skills"] == SKILLS
        assert len(payload["directions"]) == len(report.reports)

        direction = payload["directions"][0]
        for key in (
            "languages",
            "hard_skills",
            "domain_knowledge",
            "soft_skills",
            "preferred_qualifications",
            "gap",
            "jobs",
        ):
            assert key in direction, f"导出结果缺少字段 {key}"

        assert direction["gap"]["must_learn"]

    def test_console_report_renders_without_error(self, report):
        text = report_module.render(report)
        assert "技能缺口分析" in text
        assert "编程语言排行" in text


class TestFreeTextCanonicalization:
    """真实大模型返回的是自由文本，必须在聚合前收敛为规范值。

    这是 mock 路径**永远测不出来**的一类缺陷：mock 的名字来自词表，天生规范。
    没有这道收敛，一次分析能抽出 97 个「不同」技能（mock 路径只有 36 个），
    学历被拆成三行，排行榜与缺口清单同时失效。
    """

    class StubProvider:
        name = "stub"
        model_name = "stub-1"

        def complete_json(self, *, system, user, schema_name, json_schema=None):
            from app.llm.base import LLMResponse

            if schema_name == "direction_recommendation":
                data = {
                    "directions": [
                        {
                            "title": "机器人算法工程师",
                            "match_score": 0.9,
                            "reason": "stub",
                            "keywords": ["机器人算法工程师"],
                        }
                    ]
                }
            else:
                data = {
                    "job_title": "测试岗位",
                    "education": "硕士及以上学历",
                    "experience_years": "3年以上SLAM相关研发经验",
                    "major": ["机械电子工程", "自动化"],
                    "programming_languages": [
                        {"name": "C++", "required": True, "evidence": "精通C++"},
                        {"name": "Python3", "required": True, "evidence": "熟悉Python3"},
                    ],
                    "hard_skills": [
                        {"name": "PID控制算法", "required": True, "evidence": "熟悉PID控制算法"},
                        {"name": "Git版本管理", "required": True, "evidence": "熟悉Git版本管理"},
                        {
                            "name": "嵌入式开发与单片机移植",
                            "required": False,
                            "evidence": "熟悉嵌入式开发与单片机移植者优先",
                        },
                    ],
                    "domain_knowledge": [
                        {"name": "卡尔曼滤波方法", "required": True, "evidence": "熟悉卡尔曼滤波方法"}
                    ],
                    "soft_skills": [
                        {"name": "团队协作意识", "required": True, "evidence": "具备团队协作意识"}
                    ],
                    "certificates": [],
                    "preferred_qualifications": ["有机器人项目经验者优先"],
                    "responsibilities": ["做算法"],
                    "summary": "s",
                }
            return LLMResponse(data=data, model="stub-1")

    @pytest.fixture()
    def stub_report(self, tmp_path, monkeypatch):
        from app.services import orchestrator as orchestrator_module

        monkeypatch.setattr(
            orchestrator_module, "build_provider", lambda settings: self.StubProvider()
        )
        return Orchestrator(make_settings(tmp_path)).analyze(
            AnalyzeOptions(skills=["Python"], max_directions=1, limit_per_direction=3)
        )

    def names(self, report, bucket: str) -> set[str]:
        aggregate = report.reports[0].aggregate
        return {s.canonical for s in getattr(aggregate, bucket)}

    def test_decorated_names_collapse(self, stub_report):
        assert self.names(stub_report, "languages") == {"C++", "Python"}
        assert self.names(stub_report, "hard_skills") == {"Git"}
        assert "PID控制" in self.names(stub_report, "domain_knowledge")
        assert "卡尔曼滤波" in self.names(stub_report, "domain_knowledge")
        assert "团队协作" in self.names(stub_report, "soft_skills")

    def test_compound_name_is_split(self, stub_report):
        """「嵌入式开发与单片机移植」本来就要求两项技能，应拆成两条。"""
        domain = self.names(stub_report, "domain_knowledge")
        assert "嵌入式开发" in domain
        assert "单片机" in domain

    def test_category_is_overridden_by_lexicon(self, stub_report):
        """模型自创的分类五花八门（script / 方法论 / 工具），认识的技能一律用词表分类。

        副作用是技能所属的统计分组会变 —— 这是好事：mock 与真模型现在
        对同一个技能会给出同一个分组，两条路径的结果才可比。
        """
        assert self.names(stub_report, "soft_skills") == {"团队协作"}

    def test_structured_fields_are_canonicalized(self, stub_report):
        aggregate = stub_report.reports[0].aggregate
        assert [s.label for s in aggregate.education] == ["硕士及以上"]
        assert [s.label for s in aggregate.experience] == ["3年以上"]
        assert {m.label for m in aggregate.majors} == {"机械", "自动化"}

    def test_no_long_tail_of_one_off_names(self, stub_report):
        """收敛前会产出大量 count=1 的孤立项 —— 这里必须没有。"""
        aggregate = stub_report.reports[0].aggregate
        one_offs = [s.canonical for s in aggregate.all_skills if s.count == 1]
        assert one_offs == [], f"出现未收敛的孤立技能项：{one_offs}"


class TestManualPaste:
    def test_manual_jd_file_is_analyzed(self, tmp_path):
        jd = tmp_path / "my_jd.txt"
        jd.write_text(
            "岗位名称：高级数据工程师\n"
            "岗位职责：\n"
            "1. 负责数据平台建设\n"
            "任职要求：\n"
            "1. 熟练掌握Python与SQL\n"
            "2. 熟悉Flink与Kafka\n"
            "3. 熟悉Docker\n",
            encoding="utf-8",
        )
        orchestrator = Orchestrator(make_settings(tmp_path))
        result = orchestrator.analyze(AnalyzeOptions(skills=["Python"], jd_files=[jd]))
        assert result.total_jobs == 1
        assert result.reports[0].direction.title == "手动录入岗位"
        names = {s.canonical for s in result.reports[0].aggregate.all_skills}
        assert {"Python", "SQL", "Flink", "Kafka", "Docker"} <= names
