"""抽取器：Prompt 组装 + 缓存 + 调用 + 校验 + 重试。

上层（orchestrator）只跟这个类打交道，不直接接触 Provider 或 Prompt。
这样「换模型」「改 Prompt」「加缓存策略」都被收敛在一个文件里。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import Settings
from ..services.cache import LLMCache, make_cache_key
from .base import ChatProvider, LLMError
from .prompts import (
    DIRECTION_SYSTEM,
    DIRECTION_USER_TEMPLATE,
    JD_EXTRACT_SYSTEM,
    JD_EXTRACT_USER_TEMPLATE,
)
from .schemas import DIRECTION_SCHEMA, JD_PROFILE_SCHEMA, Direction, JDProfile

DIRECTION_KIND = "direction_recommendation"
PROFILE_KIND = "jd_profile"


@dataclass
class ProfileOutcome:
    """一次 JD 抽取的完整结果，含可观测性信息。"""

    profile: JDProfile
    cache_hit: bool = False
    model: str = ""
    token_in: int = 0
    token_out: int = 0
    status: str = "ok"
    error: str = ""

    @property
    def skill_count(self) -> int:
        return len(self.profile.all_skills())


class Extractor:
    def __init__(
        self,
        provider: ChatProvider,
        settings: Settings,
        cache: LLMCache | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.cache = cache

    # ------------------------------------------------------------------
    def recommend_directions(self, skills: list[str]) -> list[Direction]:
        user = DIRECTION_USER_TEMPLATE.format(skills="、".join(skills))
        payload = self._call(
            kind=DIRECTION_KIND,
            system=DIRECTION_SYSTEM,
            user=user,
            schema_name=DIRECTION_KIND,
            json_schema=DIRECTION_SCHEMA,
            cache_payload="|".join(sorted(skills)),
        )
        return Direction.list_from(payload)

    # ------------------------------------------------------------------
    def extract_profile(self, *, job_title: str, company: str, jd_text: str) -> ProfileOutcome:
        user = JD_EXTRACT_USER_TEMPLATE.format(
            job_title=job_title or "未标注",
            company=company or "未标注",
            jd_text=jd_text,
        )
        try:
            payload, cache_hit, meta = self._call_with_meta(
                kind=PROFILE_KIND,
                system=JD_EXTRACT_SYSTEM,
                user=user,
                schema_name=PROFILE_KIND,
                json_schema=JD_PROFILE_SCHEMA,
                cache_payload=jd_text,
            )
            profile = JDProfile.from_dict(payload)
            return ProfileOutcome(
                profile=profile,
                cache_hit=cache_hit,
                model=meta.get("model", ""),
                token_in=meta.get("token_in", 0),
                token_out=meta.get("token_out", 0),
                status="ok",
            )
        except (LLMError, ValueError) as exc:
            # 单条失败不应中断整批分析 —— 记下来，让用户看到失败率
            return ProfileOutcome(
                profile=JDProfile(job_title=job_title),
                model=getattr(self.provider, "model_name", self.settings.extraction_model),
                status="failed",
                error=str(exc)[:500],
            )

    # ------------------------------------------------------------------
    def _call(
        self,
        *,
        kind: str,
        system: str,
        user: str,
        schema_name: str,
        json_schema: dict[str, Any],
        cache_payload: str,
    ) -> dict[str, Any]:
        payload, _, _ = self._call_with_meta(
            kind=kind,
            system=system,
            user=user,
            schema_name=schema_name,
            json_schema=json_schema,
            cache_payload=cache_payload,
        )
        return payload

    def _call_with_meta(
        self,
        *,
        kind: str,
        system: str,
        user: str,
        schema_name: str,
        json_schema: dict[str, Any],
        cache_payload: str,
    ) -> tuple[dict[str, Any], bool, dict[str, Any]]:
        model = self.settings.extraction_model
        model_name = getattr(self.provider, "model_name", model)
        key = make_cache_key(
            kind=kind,
            prompt_version=self.settings.cache_namespace,
            model=f"{self.provider.name}:{model_name}",
            payload=cache_payload,
        )

        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                return cached, True, {"model": model_name, "cache_hit": True}

        response = self.provider.complete_json(
            system=system,
            user=user,
            schema_name=schema_name,
            json_schema=json_schema,
        )

        if self.cache is not None:
            self.cache.put(
                key,
                kind=kind,
                model=model_name,
                prompt_version=self.settings.cache_namespace,
                payload=response.data,
            )

        return (
            response.data,
            False,
            {
                "model": response.model or model_name,
                "token_in": response.token_in,
                "token_out": response.token_out,
            },
        )
