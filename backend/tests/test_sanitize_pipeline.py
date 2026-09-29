"""脱敏在完整链路里的行为。

`test_sanitize.py` 验证的是纯函数；这里验证的是**接入位置是否正确** ——
脱敏一旦放错环节（比如放在展示层而不是入库前），测试全绿但明文照样落库、
照样发给模型。所以这几条断言必须走真实链路、直接查库。
"""

from __future__ import annotations

from app.config import Settings
from app.services import dashboard
from app.services.orchestrator import AnalyzeOptions, Orchestrator

JD_WITH_PII = """岗位名称：数据分析师
公司：某互联网公司
工作地点：深圳

岗位职责：
1. 负责业务数据的指标体系搭建与日常分析
2. 输出分析报告，支撑运营决策

任职要求：
1. 本科及以上学历，3年以上数据分析经验
2. 熟练掌握 Python、SQL 与数据可视化工具
3. 简历请发送至 zhang.san@example.com，或加微信：hr_recruit2024
4. 紧急联系：13812345678
"""


def _analyze(tmp_path) -> Orchestrator:
    settings = Settings(llm_provider="mock", db_path=tmp_path / "pii.db")
    orchestrator = Orchestrator(settings)
    orchestrator.analyze(
        AnalyzeOptions(skills=[], jd_texts=[JD_WITH_PII], limit_per_direction=1),
    )
    return orchestrator


class TestPipelineRedaction:
    def test_pii_never_reaches_the_database(self, tmp_path):
        """最重要的一条：明文绝不能落库。"""
        orchestrator = _analyze(tmp_path)
        row = orchestrator.db.query_one("SELECT raw_text FROM raw_job ORDER BY id DESC LIMIT 1")
        assert row is not None
        stored = row["raw_text"]

        assert "zhang.san@example.com" not in stored
        assert "hr_recruit2024" not in stored
        assert "13812345678" not in stored
        # 打码后仍然能看出「这里原本是联系方式」
        assert "z***@example.com" in stored
        assert "138****5678" in stored

    def test_evidence_still_traces_back_to_stored_text(self, tmp_path):
        """脱敏放在抽取之前，所以 evidence 仍是入库原文的子串 —— 高亮与幻觉度量不破。"""
        orchestrator = _analyze(tmp_path)
        payload = dashboard.load_job(
            orchestrator.db,
            int(
                orchestrator.db.query_one("SELECT id FROM raw_job ORDER BY id DESC LIMIT 1")["id"]
            ),
        )
        assert payload is not None
        profile = payload["profile"]
        assert profile is not None

        checked = 0
        for item in profile["programming_languages"] + profile["hard_skills"]:
            evidence = (item.get("evidence") or "").strip()
            if not evidence:
                continue
            checked += 1
            assert evidence in payload["raw_text"], f"evidence 不在入库原文中：{evidence}"
        assert checked > 0, "样例 JD 没有抽到任何带证据的技能，测试失去意义"

    def test_skill_extraction_unaffected_by_masking(self, tmp_path):
        """脱敏不能把技能也打掉：联系方式所在的那行仍有 Python/SQL。"""
        orchestrator = _analyze(tmp_path)
        payload = dashboard.load_job(
            orchestrator.db,
            int(
                orchestrator.db.query_one("SELECT id FROM raw_job ORDER BY id DESC LIMIT 1")["id"]
            ),
        )
        names = {item["name"] for item in payload["profile"]["hard_skills"]}
        names |= {item["name"] for item in payload["profile"]["programming_languages"]}
        assert {"Python", "SQL"} & names, f"抽取结果异常：{names}"

    def test_clean_jd_is_stored_verbatim(self, tmp_path):
        """没有个人信息时，存库文本必须与输入逐字节相同 —— 脱敏不能顺手改写 JD。

        基准取 `ManualPasteSource` 归一化后的文本，而不是原始输入字符串：
        手动粘贴源自己会 strip()（既有行为），把它算到脱敏头上会让这条测试
        变成在考核别的东西。
        """
        from app.sources import ManualPasteSource

        settings = Settings(llm_provider="mock", db_path=tmp_path / "clean.db")
        orchestrator = Orchestrator(settings)
        clean = (
            "岗位名称：数据分析师\n\n任职要求：\n"
            "1. 熟练使用 Python 3.10 与 SQL\n"
            "2. 3年以上数据分析经验\n"
            "3. 薪资 15000-25000 元/月\n"
        )
        baseline = ManualPasteSource().add_text(clean).raw_text

        orchestrator.analyze(AnalyzeOptions(skills=[], jd_texts=[clean], limit_per_direction=1))
        row = orchestrator.db.query_one("SELECT raw_text FROM raw_job ORDER BY id DESC LIMIT 1")
        assert row["raw_text"] == baseline

    def test_redaction_emits_progress_event(self, tmp_path):
        """脱敏必须在进度流里可见 —— 静默改动用户给进来的文本是不可接受的。"""
        settings = Settings(llm_provider="mock", db_path=tmp_path / "event.db")
        orchestrator = Orchestrator(settings)
        events: list[dict] = []
        orchestrator.analyze(
            AnalyzeOptions(skills=[], jd_texts=[JD_WITH_PII], limit_per_direction=1),
            on_event=lambda event: events.append(event.to_dict()),
        )
        sanitize_events = [e for e in events if e["stage"] == "sanitize"]
        assert sanitize_events, f"没有发出 sanitize 事件：{[e['stage'] for e in events]}"
        message = sanitize_events[0]["message"]
        assert "脱敏" in message
        # 事件消息里不能回显被打码的内容
        assert "13812345678" not in message
        assert "zhang.san@example.com" not in message


class TestSampleJobsNotMutated:
    """`SampleSource` 每次 search 返回的是同一批 RawJob 实例。

    如果脱敏就地修改它们，第一个方向跑完后第二个方向拿到的就是被改过的对象 ——
    这类跨调用的状态泄漏在真实数据上表现为「结果时好时坏」，极难排查。
    """

    def test_repeated_analysis_is_stable(self, tmp_path):
        settings = Settings(llm_provider="mock", db_path=tmp_path / "stable.db")
        orchestrator = Orchestrator(settings)
        options = AnalyzeOptions(
            skills=["数据分析", "Python", "SQL"], max_directions=2, limit_per_direction=12
        )

        first = orchestrator.analyze(options)
        second = orchestrator.analyze(options)

        def signature(report):
            return [
                (item.direction.title, item.total, item.gap.coverage_score)
                for item in report.reports
            ]

        assert signature(first) == signature(second)
