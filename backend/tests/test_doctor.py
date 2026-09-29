"""环境自检（doctor）测试。

doctor 是用户配置 Key 之后第一个会运行的命令，
它必须在「没配 Key」「配错模型」「provider=mock」这些状态下都给出**可执行**的指引，
而不是抛一个堆栈出来。
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.doctor import (
    ExtractionRun,
    _is_reasoning_like,
    _mask,
    _pick_job,
    _run_extraction,
    _same_concept,
    _split_by_overlap,
    run_doctor,
)
from app.llm.base import LLMError
from app.llm.mock_provider import MockProvider
from app.llm.schemas import JDProfile
from app.sources import SampleSource


def make_settings(tmp_path, **overrides) -> Settings:
    base = {"db_path": tmp_path / "doctor.db"}
    base.update(overrides)
    return Settings(**base)


class TestMask:
    def test_empty(self):
        assert _mask("") == "（未配置）"

    def test_short_secret_is_not_fully_exposed(self):
        masked = _mask("short")
        assert "short" not in masked

    def test_long_secret_keeps_only_edges(self):
        secret = "sk-1234567890abcdefghij"
        masked = _mask(secret)
        assert secret not in masked
        assert masked.startswith("sk-123")
        assert "abcdefghij" not in masked


class TestPickJob:
    def test_picks_by_id(self, tmp_path):
        source = SampleSource(make_settings(tmp_path).sample_dir)
        job = _pick_job(source, "robot-001")
        assert job.source_job_id == "robot-001"

    def test_unknown_id_raises(self, tmp_path):
        source = SampleSource(make_settings(tmp_path).sample_dir)
        with pytest.raises(LLMError):
            _pick_job(source, "does-not-exist")

    def test_default_pick_is_a_median_length_sample(self, tmp_path):
        """默认样本不能是最长或最短的那条 —— 极端样本会给用户错误的质量印象。"""
        settings = make_settings(tmp_path)
        jobs = sorted(SampleSource(settings.sample_dir).all_jobs(), key=lambda j: len(j.raw_text))
        picked = _pick_job(source=SampleSource(settings.sample_dir), job_id="")
        assert picked.source_job_id != jobs[0].source_job_id
        assert picked.source_job_id != jobs[-1].source_job_id


class TestSameConcept:
    """对比展示的核心：把「说法不同但指同一件事」认出来。

    这个函数不参与产品统计，但它错了会让用户对模型质量做出错误判断 ——
    把「力控」和「力控算法」报成不一致，用户会以为模型在乱抽。
    """

    @pytest.mark.parametrize(
        "a,b",
        [
            ("力控", "力控算法"),
            ("嵌入式开发", "嵌入式开发与单片机移植"),
            ("单片机", "嵌入式开发与单片机移植"),
            ("EtherCAT", "EtherCAT总线通信"),
            ("实时系统", "实时系统开发"),
            ("机械臂", "机械臂运动学建模"),
        ],
    )
    def test_recognizes_same_concept(self, a, b):
        assert _same_concept(a, b)
        assert _same_concept(b, a), "必须对称"

    @pytest.mark.parametrize(
        "a,b",
        [
            ("SQL", "MySQL"),  # 3 字符 ASCII 不允许包含匹配
            ("C", "C++"),
            ("ROS", "SQL"),
            ("力控", "运动控制"),
            ("CAN总线", "EtherCAT"),
        ],
    )
    def test_rejects_different_concepts(self, a, b):
        assert not _same_concept(a, b)
        assert not _same_concept(b, a)


class TestSplitByOverlap:
    def test_separates_common_and_unique(self):
        common, only_mock, only_real = _split_by_overlap(
            {"力控", "ROS", "单片机"},
            {"力控算法", "ROS", "视觉引导抓取"},
        )
        assert common == {"力控", "ROS"}
        assert only_mock == ["单片机"]
        assert sorted(only_real) == ["视觉引导抓取"]

    def test_compound_phrase_matches_multiple_mock_skills(self):
        """一个复合短语可以同时对上 mock 的多个规范名，不能被重复报成独有项。"""
        common, only_mock, only_real = _split_by_overlap(
            {"嵌入式开发", "单片机"},
            {"嵌入式开发与单片机移植"},
        )
        assert common == {"嵌入式开发", "单片机"}
        assert only_mock == []
        assert only_real == []


class TestReasoningModelDetection:
    def make_run(self, *, token_in=1000, token_out=5000, seconds=60.0) -> ExtractionRun:
        return ExtractionRun(
            label="x", profile=JDProfile(), seconds=seconds, token_in=token_in, token_out=token_out
        )

    def test_flags_slow_verbose_model(self):
        assert _is_reasoning_like(self.make_run(token_out=5000, seconds=62.0))

    def test_does_not_flag_fast_verbose_model(self):
        """输出啰嗦但很快的模型不能被误报 —— 否则会给出「换个更快的」这种反向建议。"""
        assert not _is_reasoning_like(self.make_run(token_out=2182, seconds=7.6))

    def test_does_not_flag_concise_model(self):
        assert not _is_reasoning_like(self.make_run(token_in=1000, token_out=800, seconds=60.0))


class TestExtractionRun:
    def test_mock_baseline_has_valid_evidence_for_every_skill(self, tmp_path):
        settings = make_settings(tmp_path)
        job = _pick_job(SampleSource(settings.sample_dir), "robot-001")
        run = _run_extraction("mock", MockProvider(), settings, job)

        assert run.status == "ok"
        assert run.skill_count > 0
        assert run.evidence_total == run.skill_count
        assert run.evidence_rate == 1.0, "mock 抽取的 evidence 必须 100% 来自原文"


class TestRunDoctor:
    def test_mock_mode_passes_and_points_at_offline_usage(self, tmp_path, capsys):
        code = run_doctor(make_settings(tmp_path, llm_provider="mock"))
        out = capsys.readouterr().out
        assert code == 0
        assert "mock" in out
        assert "LLM_PROVIDER=openai" in out

    def test_missing_key_fails_with_actionable_guidance(self, tmp_path, capsys):
        settings = make_settings(tmp_path, llm_provider="openai", llm_api_key="")
        code = run_doctor(settings)
        out = capsys.readouterr().out
        assert code == 2
        assert "LLM_API_KEY" in out
        assert ".env" in out, "必须告诉用户改哪个文件，而不只是说『未配置』"

    def test_config_summary_never_leaks_the_key(self, tmp_path, capsys):
        secret = "sk-abcdefghijklmnopqrstuvwxyz"
        settings = make_settings(tmp_path, llm_provider="mock", llm_api_key=secret)
        run_doctor(settings)
        out = capsys.readouterr().out
        assert secret not in out
