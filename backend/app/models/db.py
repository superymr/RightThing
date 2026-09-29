"""SQLite 存储层。

M1 用标准库 sqlite3，零部署成本。
所有 SQL 只出现在本模块与 services/，上层不拼 SQL —— v2 换 Postgres 时只需替换这里。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

# 表与索引**分开**执行：老库要先 ALTER TABLE 补列，索引才建得起来。
# 把 CREATE INDEX 混在表定义里，升级过的库会在启动时炸「no such column」。
SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- 一次完整的用户分析请求
CREATE TABLE IF NOT EXISTS analysis_session (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    input_skills    TEXT NOT NULL,          -- JSON: {"raw": [...], "canonical": [...]}
    city            TEXT,
    llm_provider    TEXT,
    llm_model       TEXT,
    status          TEXT NOT NULL DEFAULT 'created'
);

-- LLM#1 推荐的岗位方向
CREATE TABLE IF NOT EXISTS job_direction (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES analysis_session(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    match_score     REAL,
    reason          TEXT,
    keywords        TEXT,                   -- JSON: 检索关键词
    selected        INTEGER NOT NULL DEFAULT 0
);

-- 采集到的原始岗位（只存原文，不做抽取）
CREATE TABLE IF NOT EXISTS raw_job (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER REFERENCES analysis_session(id) ON DELETE CASCADE,
    direction_id    INTEGER REFERENCES job_direction(id) ON DELETE SET NULL,
    source          TEXT NOT NULL,
    source_job_id   TEXT,
    url             TEXT,
    title           TEXT,
    company         TEXT,
    city            TEXT,
    raw_text        TEXT NOT NULL,
    raw_html_path   TEXT,
    fetched_at      TEXT NOT NULL,
    content_hash    TEXT NOT NULL
);

-- LLM#2 的结构化抽取结果
-- 一次抽取 = (会话, 方向, 岗位) 三元组上的一份快照，所以 session/direction 挂在这里。
-- raw_job 按 JD 内容去重、跨会话共用，因此不能把归属记在 raw_job 上 ——
-- 否则同一条 JD 在第二次分析里会「找不到」。
CREATE TABLE IF NOT EXISTS jd_profile (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_job_id          INTEGER NOT NULL REFERENCES raw_job(id) ON DELETE CASCADE,
    session_id          INTEGER REFERENCES analysis_session(id) ON DELETE CASCADE,
    direction_id        INTEGER REFERENCES job_direction(id) ON DELETE CASCADE,
    prompt_version      TEXT NOT NULL,
    model               TEXT NOT NULL,
    profile_json        TEXT NOT NULL,
    extraction_status   TEXT NOT NULL DEFAULT 'ok',   -- ok | failed | invalid
    token_in            INTEGER DEFAULT 0,
    token_out           INTEGER DEFAULT 0,
    cache_hit           INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);

-- 归一化后的技能（宽表，专为聚合而生）
CREATE TABLE IF NOT EXISTS jd_skill (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    jd_profile_id   INTEGER NOT NULL REFERENCES jd_profile(id) ON DELETE CASCADE,
    raw_job_id      INTEGER REFERENCES raw_job(id) ON DELETE CASCADE,
    skill_canonical TEXT NOT NULL,
    skill_raw       TEXT NOT NULL,
    category        TEXT,
    required        INTEGER NOT NULL DEFAULT 1,
    evidence        TEXT,
    confidence      REAL DEFAULT 1.0
);

-- 技能别名表：系统越用越准（manual 人工维护 / llm 模型判定 / learned 运行时学习）
CREATE TABLE IF NOT EXISTS skill_alias (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical   TEXT NOT NULL,
    alias       TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'manual',
    created_at  TEXT NOT NULL,
    UNIQUE(canonical, alias)
);

-- LLM 结果缓存：保证可复现 + 省钱
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key       TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    model           TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    response_json   TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    hit_count       INTEGER NOT NULL DEFAULT 0
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_raw_job_hash ON raw_job(content_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_job_unique
    ON raw_job(source, source_job_id) WHERE source_job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_jd_profile_job ON jd_profile(raw_job_id);
CREATE INDEX IF NOT EXISTS idx_jd_profile_session ON jd_profile(session_id, direction_id);
CREATE INDEX IF NOT EXISTS idx_jd_skill_canon ON jd_skill(skill_canonical);
CREATE INDEX IF NOT EXISTS idx_jd_skill_job ON jd_skill(raw_job_id);
"""

# 后来新增的列：老库用 ALTER TABLE 补上，新库由 SCHEMA_SQL 直接建好
_COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("jd_profile", "session_id", "INTEGER REFERENCES analysis_session(id)"),
    ("jd_profile", "direction_id", "INTEGER REFERENCES job_direction(id)"),
)


class Database:
    """极薄的 SQLite 封装。短连接模式，避免多进程/多次调用间的状态问题。"""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            # 顺序不能变：建表 → 补列 → 建索引。
            # 索引引用了后加的列（jd_profile.session_id），先建索引会炸。
            conn.executescript(SCHEMA_SQL)
            self._migrate(conn)
            conn.executescript(INDEX_SQL)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """极简迁移：给已存在的表补上后来新增的列。

        `CREATE TABLE IF NOT EXISTS` 不会给旧表加列，所以升级过代码的人
        会撞上「no such column」这种莫名其妙的报错。这类小迁移成本极低，
        但能省掉一次「为什么我这儿跑不起来」的排查。
        """
        for table, column, ddl in _COLUMN_MIGRATIONS:
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if existing and column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # ---- 便捷读写 ----
    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """执行写操作，返回 lastrowid。"""
        with self.connect() as conn:
            cur = conn.execute(sql, params)
            return int(cur.lastrowid or 0)

    def execute_many(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(sql, rows)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return list(conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None
