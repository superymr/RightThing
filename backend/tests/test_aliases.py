"""别名自学习闭环的测试。

这个模块补的是一个**断层**：`normalizer` 把没见过的技能登记进数据库（learned），
但词表 `skill_alias.json` 才是 `SkillLexicon` 真正读的东西 —— 不写回 json，
「学到了」就只停在一张没人看的表里。

所以测试的重点不是「函数有没有返回」，而是三件事：

1. **写回 json 之后，归一化真的变了**（词汇表是活的，不是写了个寂寞）；
2. **缓存自动失效**（否则会出现「我明明改了词表，结果怎么没变」的幽灵问题）；
3. **文件排版不打乱**（词表是人工维护的，格式 diff 会淹没真实改动）。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.analytics.lexicon import SkillLexicon
from app.analytics.normalizer import Normalizer
from app.config import DEFAULT_ALIAS_PATH, Settings
from app.models.db import Database
from app.services import aliases as alias_service
from app.utils.timeutil import now_iso


@pytest.fixture()
def alias_path(tmp_path) -> Path:
    """词表副本。**绝不**让测试碰仓库里的 data/skill_alias.json。"""
    target = tmp_path / "skill_alias.json"
    shutil.copy(DEFAULT_ALIAS_PATH, target)
    return target


@pytest.fixture()
def db(tmp_path) -> Database:
    database = Database(tmp_path / "alias.db")
    database.init_schema()
    return database


def learn(db: Database, name: str) -> None:
    """模拟 normalizer 遇到生词时的登记行为。"""
    db.execute(
        "INSERT OR IGNORE INTO skill_alias (canonical, alias, source, created_at) "
        "VALUES (?, ?, 'learned', ?)",
        (name, name, now_iso()),
    )


class TestFileFormat:
    """词表是人工维护的文件，格式必须稳住。"""

    def test_roundtrip_is_byte_identical(self, alias_path):
        """序列化器必须能原样往返现有词表。

        这条测试是防回归的关键：一旦有人把 `dump_skill_file` 改成通用的
        `json.dumps(indent=2)`，整份文件会被重排，之后每次真实改动都会淹没在
        几千行格式 diff 里 —— 那样词表就没人愿意维护了。
        """
        original = alias_path.read_text(encoding="utf-8")
        payload = alias_service.load_skill_file(alias_path)
        assert alias_service.dump_skill_file(payload) == original

    def test_keeps_one_skill_per_line_and_category_gaps(self, alias_path):
        payload = alias_service.load_skill_file(alias_path)
        text = alias_service.dump_skill_file(payload)
        skill_lines = [line for line in text.splitlines() if line.strip().startswith("{ ")]
        assert len(skill_lines) == len(payload["skills"])
        # 类别切换处保留空行
        assert "\n\n" in text

    def test_unknown_top_level_keys_survive(self, alias_path):
        payload = alias_service.load_skill_file(alias_path)
        payload["future_field"] = {"nested": ["值"]}
        text = alias_service.dump_skill_file(payload)
        assert json.loads(text)["future_field"] == {"nested": ["值"]}


class TestPromote:
    def test_alias_lands_in_lexicon_and_changes_normalization(self, alias_path, db):
        """最关键的一条：写回 json 之后，归一化必须真的生效。

        刻意选「回环检测」——它在词表里完全不存在，所以走的是**精确别名查找**这条
        路径。用「PID控制算法」这类词是测不出问题的：包含匹配（find_in_text）本来
        就能把 `PID控制算法` 收敛成 `PID控制`，词表改没改都一样。
        """
        learn(db, "回环检测")

        before = SkillLexicon.load(alias_path)
        assert before.lookup("回环检测") is None
        assert Normalizer(before).normalize_one("回环检测", persist=False).canonical == "回环检测"

        result = alias_service.promote(db, "回环检测", "SLAM", alias_path=alias_path)
        assert result.changed and result.added_alias

        after = SkillLexicon.load(alias_path)
        rule = after.lookup("回环检测")
        assert rule is not None and rule.canonical == "SLAM"
        assert Normalizer(after).normalize_one("回环检测", persist=False).canonical == "SLAM"

    def test_creates_entry_when_canonical_is_new(self, alias_path, db):
        payload = alias_service.load_skill_file(alias_path)
        assert alias_service.find_entry(payload, "点云配准") is None, "前提变了：词表里已经有这个规范名"

        result = alias_service.promote(
            db, "点云配准库", "点云配准", alias_path=alias_path, category="机器人/感知"
        )
        assert result.created_entry
        entry = alias_service.find_entry(alias_service.load_skill_file(alias_path), "点云配准")
        assert entry is not None
        assert entry["category"] == "机器人/感知"
        assert "点云配准库" in entry["aliases"]

    def test_is_idempotent(self, alias_path, db):
        alias_service.promote(db, "回环检测", "SLAM", alias_path=alias_path)
        again = alias_service.promote(db, "回环检测", "SLAM", alias_path=alias_path)
        assert not again.changed
        entry = alias_service.find_entry(alias_service.load_skill_file(alias_path), "SLAM")
        assert entry["aliases"].count("回环检测") == 1

    def test_moves_alias_away_from_a_conflicting_entry(self, alias_path, db):
        """同一个别名不能同时指向两个规范名 —— 命中哪个取决于加载顺序，那就是随机结果。"""
        before = SkillLexicon.load(alias_path)
        assert before.lookup("ros2") is not None  # 词表里 ros2 属于 ROS
        assert before.lookup("ros2").canonical == "ROS"

        result = alias_service.promote(
            db, "ros2", "ROS2", alias_path=alias_path, category="机器人/感知"
        )
        assert "ROS" in result.removed_from

        after = SkillLexicon.load(alias_path)
        assert after.lookup("ros2").canonical == "ROS2"

    def test_case_only_rename_is_allowed(self, alias_path, db):
        """`ros2` → `ROS2` 只差大小写，但它是有意义的拆分，不能被当成空操作挡掉。"""
        result = alias_service.promote(
            db, "ros2", "ROS2", alias_path=alias_path, category="机器人/感知"
        )
        assert result.changed
        payload = alias_service.load_skill_file(alias_path)
        assert alias_service.find_entry(payload, "ROS2") is not None
        assert alias_service.find_entry(payload, "ROS")["aliases"].count("ros2") == 0

    def test_same_name_is_rejected(self, alias_path, db):
        with pytest.raises(alias_service.AliasError):
            alias_service.promote(db, "ROS", "ROS", alias_path=alias_path)

    def test_empty_input_rejected(self, alias_path, db):
        with pytest.raises(alias_service.AliasError):
            alias_service.promote(db, "  ", "ROS", alias_path=alias_path)

    def test_dry_run_writes_nothing(self, alias_path, db):
        original = alias_path.read_text(encoding="utf-8")
        result = alias_service.promote(
            db, "回环检测", "SLAM", alias_path=alias_path, dry_run=True
        )
        assert result.changed and result.dry_run
        assert alias_path.read_text(encoding="utf-8") == original
        assert db.query_one("SELECT 1 FROM skill_alias WHERE source='manual'") is None

    def test_db_sync_replaces_learned_row(self, alias_path, db):
        learn(db, "回环检测")
        alias_service.promote(db, "回环检测", "SLAM", alias_path=alias_path)

        rows = db.query("SELECT canonical, source FROM skill_alias WHERE alias = '回环检测'")
        assert len(rows) == 1, f"应只剩一条记录，实际 {[dict(r) for r in rows]}"
        assert rows[0]["source"] == "manual"
        assert rows[0]["canonical"] == "SLAM"

    def test_missing_file_reports_readable_error(self, tmp_path, db):
        with pytest.raises(alias_service.AliasError) as exc:
            alias_service.promote(db, "a", "b", alias_path=tmp_path / "nope.json")
        assert "不存在" in str(exc.value)


class TestMerge:
    def test_moves_all_aliases_and_drops_entry(self, alias_path, db):
        # 先造一个独立的规范名条目，再把它整个并回 ROS
        alias_service.promote(
            db, "机器人操作系统", "ROS操作系统", alias_path=alias_path, category="机器人/感知"
        )
        assert alias_service.find_entry(
            alias_service.load_skill_file(alias_path), "ROS操作系统"
        ) is not None

        result = alias_service.merge(db, "ROS操作系统", "ROS", alias_path=alias_path)
        assert "机器人操作系统" in result.moved_aliases

        payload = alias_service.load_skill_file(alias_path)
        assert alias_service.find_entry(payload, "ROS操作系统") is None
        entry = alias_service.find_entry(payload, "ROS")
        assert "机器人操作系统" in entry["aliases"]

    def test_unknown_source_rejected(self, alias_path, db):
        with pytest.raises(alias_service.AliasError):
            alias_service.merge(db, "不存在的技能", "ROS", alias_path=alias_path)

    def test_unknown_target_rejected(self, alias_path, db):
        with pytest.raises(alias_service.AliasError):
            alias_service.merge(db, "ROS", "不存在的技能", alias_path=alias_path)

    def test_dry_run_writes_nothing(self, alias_path, db):
        original = alias_path.read_text(encoding="utf-8")
        alias_service.merge(db, "ROS", "Python", alias_path=alias_path, dry_run=True)
        assert alias_path.read_text(encoding="utf-8") == original


class TestCacheInvalidation:
    """改词表必须让旧缓存失效，否则会出现「改了词表结果没变」这种无法排查的现象。"""

    def test_cache_namespace_changes_after_promote(self, alias_path, db):
        before = Settings(llm_provider="mock", alias_path=alias_path).cache_namespace

        alias_service.promote(db, "回环检测", "SLAM", alias_path=alias_path)

        after = Settings(llm_provider="mock", alias_path=alias_path).cache_namespace
        assert after != before

    def test_old_cache_entry_is_not_reused(self, alias_path, db):
        """用真实缓存做一遍：同一个 JD，词表变了之后必须未命中。"""
        from app.services.cache import LLMCache, make_cache_key

        jd = "任职要求：熟悉 回环检测 与 ROS"

        def key_for(namespace: str) -> str:
            return make_cache_key(
                kind="jd_extract", prompt_version=namespace, model="mock", payload=jd
            )

        before_key = key_for(Settings(llm_provider="mock", alias_path=alias_path).cache_namespace)
        cache = LLMCache(db)
        cache.put(
            before_key,
            kind="jd_extract",
            model="mock",
            prompt_version="old",
            payload={"job_title": "旧结果"},
        )
        assert cache.get(before_key) is not None

        alias_service.promote(db, "回环检测", "SLAM", alias_path=alias_path)

        after_key = key_for(Settings(llm_provider="mock", alias_path=alias_path).cache_namespace)
        assert after_key != before_key
        assert cache.get(after_key) is None


class TestListing:
    def test_filters_and_sorts_by_usage(self, alias_path, db):
        learn(db, "位姿图优化")
        learn(db, "回环检测")
        learn(db, "动力学建模")

        # 造两份抽取结果：位姿图优化 出现在 2 条 JD，另两个各 1 条。
        # 必须先插 raw_job —— jd_profile.raw_job_id 有外键约束，跳过它只会拿到一个
        # FOREIGN KEY constraint failed，看不出真正的原因。
        for job_id, names in (
            (1, ["位姿图优化", "回环检测"]),
            (2, ["位姿图优化"]),
            (3, ["动力学建模"]),
        ):
            db.execute(
                "INSERT INTO raw_job (id, source, source_job_id, raw_text, fetched_at, content_hash) "
                "VALUES (?, 'test', ?, 'JD 正文', ?, ?)",
                (job_id, f"job-{job_id}", now_iso(), f"hash-{job_id}"),
            )
            profile_id = db.execute(
                "INSERT INTO jd_profile (raw_job_id, prompt_version, model, profile_json, "
                " extraction_status, created_at) VALUES (?, 'v1', 'mock', '{}', 'ok', ?)",
                (job_id, now_iso()),
            )
            for name in names:
                db.execute(
                    "INSERT INTO jd_skill (jd_profile_id, raw_job_id, skill_canonical, "
                    " skill_raw, category, required) VALUES (?, ?, ?, ?, '其他', 1)",
                    (profile_id, job_id, name, name),
                )

        rows = alias_service.list_aliases(db, source="learned")
        # 主序：被多少条 JD 抽到过（多的在前）；同分时按规范名排序，保证结果稳定
        assert [r.alias for r in rows][:3] == ["位姿图优化", "动力学建模", "回环检测"]
        assert rows[0].jobs == 2
        assert {r.jobs for r in rows} == {2, 1}

        only_busy = alias_service.list_aliases(db, source="learned", min_jobs=2)
        assert [r.alias for r in only_busy] == ["位姿图优化"]

        assert alias_service.list_aliases(db, source="manual") == []
