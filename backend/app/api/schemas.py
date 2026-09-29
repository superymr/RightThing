"""请求 / 响应模型。

策略：**请求体严格建模，分析结果按原样返回字典。**

分析结果的形状已经由 `report.to_dict()` 与 `services/dashboard.py` 定义，
再写一套 Pydantic 模型等于把同一个契约写两遍 —— 两边一旦不同步，
就会出现「文档说 A、实际返回 B」这种最难查的问题。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator


def _split_skills(value: Any) -> Any:
    """容忍前端把技能写成 "Python,SQL" 或 ["Python", "SQL"]。

    这类容错值得做：字符串是最自然的调用方式，为此返回 422 只会让调用方困惑。
    """
    if isinstance(value, str):
        return [part.strip() for part in value.replace("，", ",").split(",") if part.strip()]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_split_skills(item) if isinstance(item, str) and "," in item else [item])
        return [str(item).strip() for item in out if str(item).strip()]
    return value


class AnalyzeRequest(BaseModel):
    skills: list[str] = Field(default_factory=list, description="技能列表，也接受逗号分隔字符串")
    city: str = Field("", description="城市过滤")
    max_directions: int = Field(2, ge=1, le=10, description="最多分析几个岗位方向")
    limit_per_direction: int = Field(35, ge=1, le=200, description="每个方向最多采集多少条 JD")
    direction_filter: str = Field("", description="只分析标题/关键词匹配该值的方向")
    source_mode: Literal["auto", "sample", "live", "hybrid"] = Field(
        "auto", description="采集源：自动回退 / 仅样例 / 仅在线 / 混合"
    )
    jd_texts: list[str] = Field(
        default_factory=list, description="手动粘贴的 JD 全文（走零风险合规路径，不经过方向推荐）"
    )
    job_urls: list[str] = Field(
        default_factory=list,
        max_length=30,
        description="直接导入的公开岗位详情 URL；当前支持牛客 /jobs/detail/*",
    )
    sync: bool = Field(False, description="true 则同步执行并直接返回结果（仅适合小样本/调试）")
    persist: bool = Field(True, description="是否落库，落库后才能用 /api/sessions/{id} 读回")

    _normalize_skills = field_validator("skills", mode="before")(_split_skills)


class NormalizeRequest(BaseModel):
    skills: list[str] = Field(default_factory=list)

    _normalize_skills = field_validator("skills", mode="before")(_split_skills)


class SkillNormalized(BaseModel):
    raw: str
    canonical: str
    category: str
    known: bool


class NormalizeResponse(BaseModel):
    items: list[SkillNormalized]


class ManualJobRequest(BaseModel):
    text: str = Field(..., min_length=1, description="JD 全文")


class HealthResponse(BaseModel):
    status: str
    version: str
    provider: str
    model: str
    cache_enabled: bool
    prompt_version: str
    database: str
    llm_ready: bool
    detail: str = ""


class LLMSettingsResponse(BaseModel):
    provider: str
    base_url: str
    model: str
    strong_model: str
    temperature: float
    timeout: float
    max_retries: int
    api_key_configured: bool
    api_key_hint: str = ""


class LLMSettingsUpdate(BaseModel):
    provider: Literal["mock", "openai"] = "openai"
    base_url: str = Field("", max_length=500)
    model: str = Field("", max_length=200)
    strong_model: str = Field("", max_length=200)
    api_key: SecretStr | None = Field(None, max_length=4096)
    clear_api_key: bool = False
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    timeout: float = Field(120.0, ge=5.0, le=600.0)
    max_retries: int = Field(2, ge=0, le=10)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("API 地址必须以 http:// 或 https:// 开头")
        return value

    @field_validator("model", "strong_model")
    @classmethod
    def trim_model(cls, value: str) -> str:
        return value.strip()


class TaskStartedResponse(BaseModel):
    task_id: str
    kind: str
    status: str
    events_url: str
    poll_url: str


class DirectionSummary(BaseModel):
    title: str
    match_score: float
    reason: str
    keywords: list[str] = Field(default_factory=list)
    total_jobs: int = 0
    ok_jobs: int = 0
    failed_jobs: int = 0
    coverage_score: float = 0.0


class AnalysisSummary(BaseModel):
    """任务结果里的**精简**摘要。

    刻意不返回完整的看板数据：那可能有上兆字节，塞进任务状态里既占内存
    又会让轮询变得昂贵。完整结果按 session_id 去 `GET /api/sessions/{id}` 取 ——
    这同时保证了「看板不依赖任务是否还在内存里」。
    """

    session_id: int
    provider: str
    model: str
    duration_sec: float
    total_jobs: int
    input_skills: list[str]
    canonical_skills: list[str]
    directions: list[DirectionSummary]


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: Any = None


class ErrorResponse(BaseModel):
    error: ErrorBody
