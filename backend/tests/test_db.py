"""存储层测试。

重点是**迁移路径**：`CREATE TABLE IF NOT EXISTS` 不会给已存在的表加列，
所以升级过代码的人手里会留着一个旧结构的库。这条路径不测，
用户就会撞上启动即崩的「no such column」。
"""

from __future__ import annotations

import sqlite3

from app.models.db import Database

# M1 时期的 jd_profile：没有 session_id / direction_id
LEGACY_JD_PROFILE = """
CREATE TABLE jd_profile (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_job_id          INTEGER NOT NULL,
    prompt_version      TEXT NOT NULL,
    model               TEXT NOT NULL,
    profile_json        TEXT NOT NULL,
    extraction_status   TEXT NOT NULL DEFAULT 'ok',
    token_in            INTEGER DEFAULT 0,
    token_out           INTEGER DEFAULT 0,
    cache_hit           INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);
"""


def make_legacy_db(path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(LEGACY_JD_PROFILE)
    conn.commit()
    conn.close()


class TestSchema:
    def test_creates_all_tables(self, tmp_path):
        db = Database(tmp_path / "fresh.db")
        db.init_schema()
        tables = {
            row["name"] for row in db.query("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "analysis_session",
            "job_direction",
            "raw_job",
            "jd_profile",
            "jd_skill",
            "skill_alias",
            "llm_cache",
        } <= tables

    def test_is_idempotent(self, tmp_path):
        db = Database(tmp_path / "twice.db")
        db.init_schema()
        db.init_schema()  # 重复初始化不应报错
        assert db.query("SELECT COUNT(*) AS c FROM jd_profile")[0]["c"] == 0


class TestMigration:
    def test_adds_new_columns_to_legacy_table(self, tmp_path):
        path = tmp_path / "legacy.db"
        make_legacy_db(path)

        db = Database(path)
        db.init_schema()  # 修复前：这里会抛 "no such column: session_id"

        columns = {row["name"] for row in db.query("PRAGMA table_info(jd_profile)")}
        assert {"session_id", "direction_id"} <= columns

    def test_preserves_existing_rows(self, tmp_path):
        path = tmp_path / "legacy_data.db"
        make_legacy_db(path)
        conn = sqlite3.connect(path)
        conn.execute(
            "INSERT INTO jd_profile (raw_job_id, prompt_version, model, profile_json, created_at) "
            "VALUES (1, 'v1', 'm', '{}', '2024-01-01T00:00:00+00:00')"
        )
        conn.commit()
        conn.close()

        db = Database(path)
        db.init_schema()

        row = db.query_one("SELECT * FROM jd_profile")
        assert row["prompt_version"] == "v1"
        assert row["session_id"] is None

    def test_indexes_exist_after_migration(self, tmp_path):
        """索引引用了后加的列，所以必须在补列之后创建。"""
        path = tmp_path / "legacy_index.db"
        make_legacy_db(path)

        db = Database(path)
        db.init_schema()

        indexes = {
            row["name"] for row in db.query("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "idx_jd_profile_session" in indexes
