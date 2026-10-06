"""全局配置。

刻意不依赖 pydantic-settings，用标准库实现，保证 M1 零依赖可跑。
解析优先级：真实环境变量 > .env 文件 > 代码默认值。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# backend/app/config.py -> backend/
BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "data"
DEFAULT_SAMPLE_DIR = DATA_DIR / "samples"
DEFAULT_ALIAS_PATH = DATA_DIR / "skill_alias.json"
DEFAULT_DB_PATH = DATA_DIR / "radar.db"
DEFAULT_LIVE_CACHE_DIR = DATA_DIR / "live_cache"


def _parse_dotenv(path: Path) -> dict[str, str]:
    """极简 .env 解析：支持 KEY=VALUE、# 注释、成对引号。不依赖 python-dotenv。"""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key] = value
    return values


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on")


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    """运行时配置。用 Settings.load() 构造，别直接 new。"""

    # ---- LLM ----
    llm_provider: str = "mock"
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_model_strong: str = ""
    llm_temperature: float = 0.0
    llm_max_concurrency: int = 5
    llm_timeout: float = 120.0
    llm_max_retries: int = 2
    llm_compact_extraction: bool = True
    llm_deepseek_thinking: bool = False
    config_path: Path = field(default_factory=lambda: PROJECT_DIR / ".env")

    # ---- 存储 ----
    db_path: Path = field(default_factory=lambda: DEFAULT_DB_PATH)
    cache_enabled: bool = True
    prompt_version: str = "v1"

    # ---- 采集 ----
    enable_live_sources: bool = False
    enable_sample_source: bool = True
    live_cache_dir: Path = field(default_factory=lambda: DEFAULT_LIVE_CACHE_DIR)
    live_source_timeout: float = 20.0
    live_source_interval: float = 0.35
    live_source_budget: float = 90.0
    nowcoder_scan_limit: int = 120
    brave_search_api_key: str = ""
    target_market: str = "cn_mainland"
    enable_ncss_source: bool = True
    enable_shixiseng_source: bool = True
    enable_jobicy_source: bool = True
    enable_arbeitnow_source: bool = True
    arbeitnow_pages: int = 3
    greenhouse_boards: tuple[str, ...] = (
        "figma",
        "discord",
        "airbnb",
        "roblox",
        "pinterest",
    )

    # ---- 路径 ----
    sample_dir: Path = field(default_factory=lambda: DEFAULT_SAMPLE_DIR)
    alias_path: Path = field(default_factory=lambda: DEFAULT_ALIAS_PATH)

    # ---- 派生 ----
    @property
    def extraction_model(self) -> str:
        """抽取用的模型：优先强模型，未配置则复用默认模型。"""
        return self.llm_model_strong or self.llm_model

    @property
    def is_mock(self) -> bool:
        return self.llm_provider.strip().lower() == "mock"

    @property
    def cache_namespace(self) -> str:
        """缓存命名空间 = Prompt 版本 + 词表指纹。

        为什么必须带上词表指纹：mock provider 的抽取结果**取决于 data/skill_alias.json**。
        如果缓存键只含 prompt_version，那么「改了词表但结果没变」就会出现 ——
        一个几乎无法排查的幽灵 bug。把数据依赖显式编进缓存键，是最省心的解法。
        """
        import hashlib

        try:
            fingerprint = hashlib.sha256(self.alias_path.read_bytes()).hexdigest()[:12]
        except OSError:
            fingerprint = "nolex"
        return f"{self.prompt_version}+lex{fingerprint}"

    # ---- 构造 ----
    @classmethod
    def load(cls, env_file: Path | None = None) -> "Settings":
        config_path = env_file or (PROJECT_DIR / ".env")
        dotenv = _parse_dotenv(config_path)

        def get(key: str, default: str | None = None) -> str | None:
            # 真实环境变量优先，其次 .env，最后默认值
            if key in os.environ and os.environ[key] != "":
                return os.environ[key]
            if key in dotenv and dotenv[key] != "":
                return dotenv[key]
            return default

        db_raw = get("JOBRADAR_DB_PATH")
        live_cache_raw = get("JOBRADAR_LIVE_CACHE_DIR")
        return cls(
            llm_provider=(get("LLM_PROVIDER", "mock") or "mock").strip().lower(),
            llm_base_url=(get("LLM_BASE_URL", "https://api.deepseek.com/v1") or "").rstrip("/"),
            llm_api_key=get("LLM_API_KEY", "") or "",
            llm_model=get("LLM_MODEL", "deepseek-chat") or "deepseek-chat",
            llm_model_strong=get("LLM_MODEL_STRONG", "") or "",
            llm_temperature=_as_float(get("LLM_TEMPERATURE"), 0.0),
            llm_max_concurrency=_as_int(get("LLM_MAX_CONCURRENCY"), 5),
            llm_timeout=_as_float(get("LLM_TIMEOUT"), 120.0),
            llm_max_retries=_as_int(get("LLM_MAX_RETRIES"), 2),
            llm_compact_extraction=_as_bool(get("LLM_COMPACT_EXTRACTION"), True),
            llm_deepseek_thinking=_as_bool(get("LLM_DEEPSEEK_THINKING"), False),
            config_path=config_path,
            db_path=Path(db_raw) if db_raw else DEFAULT_DB_PATH,
            cache_enabled=_as_bool(get("JOBRADAR_CACHE"), True),
            prompt_version=get("JOBRADAR_PROMPT_VERSION", "v1") or "v1",
            enable_live_sources=_as_bool(get("JOBRADAR_ENABLE_LIVE_SOURCES"), False),
            enable_sample_source=_as_bool(get("JOBRADAR_ENABLE_SAMPLE_SOURCE"), True),
            live_cache_dir=Path(live_cache_raw) if live_cache_raw else DEFAULT_LIVE_CACHE_DIR,
            live_source_timeout=_as_float(get("JOBRADAR_LIVE_SOURCE_TIMEOUT"), 20.0),
            live_source_interval=_as_float(get("JOBRADAR_LIVE_SOURCE_INTERVAL"), 0.35),
            live_source_budget=_as_float(get("JOBRADAR_LIVE_SOURCE_BUDGET"), 90.0),
            nowcoder_scan_limit=_as_int(get("JOBRADAR_NOWCODER_SCAN_LIMIT"), 120),
            brave_search_api_key=get("BRAVE_SEARCH_API_KEY", "") or "",
            target_market=(get("JOBRADAR_TARGET_MARKET", "cn_mainland") or "cn_mainland").strip().lower(),
            enable_ncss_source=_as_bool(get("JOBRADAR_ENABLE_NCSS_SOURCE"), True),
            enable_shixiseng_source=_as_bool(get("JOBRADAR_ENABLE_SHIXISENG_SOURCE"), True),
            enable_jobicy_source=_as_bool(get("JOBRADAR_ENABLE_JOBICY_SOURCE"), True),
            enable_arbeitnow_source=_as_bool(get("JOBRADAR_ENABLE_ARBEITNOW_SOURCE"), True),
            arbeitnow_pages=_as_int(get("JOBRADAR_ARBEITNOW_PAGES"), 3),
            greenhouse_boards=tuple(
                item.strip()
                for item in (
                    get(
                        "JOBRADAR_GREENHOUSE_BOARDS",
                        "figma,discord,airbnb,roblox,pinterest",
                    )
                    or ""
                ).split(",")
                if item.strip()
            ),
        )

    def describe(self) -> str:
        """给 CLI 打印用的一行摘要（不含密钥）。"""
        if self.is_mock:
            target = "本地规则引擎（零成本 / 完全确定性）"
        else:
            target = f"{self.llm_base_url} · {self.extraction_model}"
        return f"provider={self.llm_provider}  model={target}  cache={'on' if self.cache_enabled else 'off'}"
