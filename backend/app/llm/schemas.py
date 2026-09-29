"""结构化输出契约（Pydantic 的零依赖等价物）。

这些 dataclass 是 LLM 输出与内部代码之间的**唯一契约**：
- LLM 返回什么不重要，能通过这里校验的才算数；
- 校验失败的字段一律丢弃，绝不猜测补全（对抗幻觉的第一道闸门）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# --------------------------------------------------------------------------
# 抽取结果的 JSON Schema（发给支持结构化输出的模型）
# 结构化输出不可用时，它同样是 Prompt 里的字段说明，双份收益。
# --------------------------------------------------------------------------

JD_PROFILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "job_title",
        "programming_languages",
        "hard_skills",
        "domain_knowledge",
        "soft_skills",
        "preferred_qualifications",
        "responsibilities",
        "summary",
    ],
    "properties": {
        "job_title": {"type": "string"},
        "seniority": {"type": ["string", "null"]},
        "education": {"type": ["string", "null"]},
        "major": {"type": "array", "items": {"type": "string"}},
        "experience_years": {"type": ["string", "null"]},
        "programming_languages": {"$ref": "#/$defs/skillList"},
        "hard_skills": {"$ref": "#/$defs/skillList"},
        "domain_knowledge": {"$ref": "#/$defs/skillList"},
        "soft_skills": {"$ref": "#/$defs/skillList"},
        "certificates": {"type": "array", "items": {"type": "string"}},
        "preferred_qualifications": {"type": "array", "items": {"type": "string"}},
        "responsibilities": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
    "$defs": {
        "skillList": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "required", "evidence"],
                "properties": {
                    "name": {"type": "string"},
                    "category": {"type": ["string", "null"]},
                    "required": {
                        "type": "boolean",
                        "description": "true=硬性要求；false=加分项/优先项",
                    },
                    "evidence": {
                        "type": "string",
                        "description": "原文中支持该结论的片段，必须是原文子串",
                    },
                    "confidence": {"type": ["number", "null"]},
                },
            },
        }
    },
}

DIRECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["directions"],
    "properties": {
        "directions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "match_score", "reason", "keywords"],
                "properties": {
                    "title": {"type": "string"},
                    "match_score": {"type": "number"},
                    "reason": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "related_titles": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


# --------------------------------------------------------------------------
# 校验工具
# --------------------------------------------------------------------------

_TRUE_TOKENS = {"true", "1", "yes", "y", "required", "必须", "硬性", "要求"}
_FALSE_TOKENS = {"false", "0", "no", "n", "preferred", "加分", "优先", "nice"}


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in _TRUE_TOKENS:
            return True
        if token in _FALSE_TOKENS:
            return False
    return default


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _as_float(value: Any, default: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, number))


def _as_str_list(value: Any) -> list[str]:
    """容忍 LLM 把字符串数组写成单个字符串、或写成对象数组。"""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if not isinstance(value, dict) and isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            text = _as_str(item.get("name") if isinstance(item, dict) else item)
            if text:
                out.append(text)
        return out
    text = _as_str(value)
    return [text] if text else []


# --------------------------------------------------------------------------
# 数据类
# --------------------------------------------------------------------------


@dataclass
class SkillItem:
    """一条被抽出的技能要求。evidence 是抗幻觉的核心：必须来自原文。"""

    name: str
    category: str = ""
    required: bool = True
    evidence: str = ""
    confidence: float = 1.0

    @classmethod
    def from_dict(cls, data: Any) -> "SkillItem | None":
        if isinstance(data, str):
            name = data.strip()
            return cls(name=name) if name else None
        if not isinstance(data, dict):
            return None

        name = _as_str(data.get("name") or data.get("skill") or data.get("title"))
        if not name:
            return None

        return cls(
            name=name,
            category=_as_str(data.get("category")),
            required=_as_bool(data.get("required"), default=True),
            evidence=_as_str(data.get("evidence")),
            confidence=_as_float(data.get("confidence"), default=1.0),
        )

    @classmethod
    def list_from(cls, data: Any) -> list["SkillItem"]:
        if data is None:
            return []
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, (list, tuple, set)):
            data = [data]
        items: list[SkillItem] = []
        for entry in data:
            item = cls.from_dict(entry)
            if item is not None:
                items.append(item)
        return items


@dataclass
class JDProfile:
    """一份 JD 的结构化画像。"""

    job_title: str = ""
    seniority: str = ""
    education: str = ""
    major: list[str] = field(default_factory=list)
    experience_years: str = ""
    programming_languages: list[SkillItem] = field(default_factory=list)
    hard_skills: list[SkillItem] = field(default_factory=list)
    domain_knowledge: list[SkillItem] = field(default_factory=list)
    soft_skills: list[SkillItem] = field(default_factory=list)
    certificates: list[str] = field(default_factory=list)
    preferred_qualifications: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    summary: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JDProfile":
        if not isinstance(data, dict):
            raise ValueError("JDProfile 需要 dict 输入")
        return cls(
            job_title=_as_str(data.get("job_title")),
            seniority=_as_str(data.get("seniority")),
            education=_as_str(data.get("education")),
            major=_as_str_list(data.get("major")),
            experience_years=_as_str(data.get("experience_years")),
            programming_languages=SkillItem.list_from(data.get("programming_languages")),
            hard_skills=SkillItem.list_from(data.get("hard_skills")),
            domain_knowledge=SkillItem.list_from(data.get("domain_knowledge")),
            soft_skills=SkillItem.list_from(data.get("soft_skills")),
            certificates=_as_str_list(data.get("certificates")),
            preferred_qualifications=_as_str_list(data.get("preferred_qualifications")),
            responsibilities=_as_str_list(data.get("responsibilities")),
            summary=_as_str(data.get("summary")),
        )

    def all_skills(self) -> list[SkillItem]:
        """扁平化所有技能项，供归一化与聚合使用。

        **字段本身就是分类依据**，比模型填的 category 字符串更可靠：
        模型把 Python 放进 programming_languages 却忘了填 category 时，
        我们绝不能因此把编程语言算进「核心技能」—— 那会让整个排行榜错位。
        所以 category 为空时按来源字段兜底。
        """
        from dataclasses import replace

        out: list[SkillItem] = []
        for items, default_category in (
            (self.programming_languages, "编程语言"),
            (self.hard_skills, "硬技能"),
            (self.domain_knowledge, "领域知识"),
            (self.soft_skills, "软技能"),
        ):
            for item in items:
                out.append(item if item.category else replace(item, category=default_category))
        return out

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Direction:
    """LLM#1 推荐的岗位方向。"""

    title: str
    match_score: float = 0.0
    reason: str = ""
    keywords: list[str] = field(default_factory=list)
    related_titles: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Direction | None":
        if isinstance(data, str):
            title = data.strip()
            return cls(title=title) if title else None
        if not isinstance(data, dict):
            return None
        title = _as_str(data.get("title") or data.get("direction") or data.get("name"))
        if not title:
            return None
        keywords = _as_str_list(data.get("keywords")) or [title]
        return cls(
            title=title,
            match_score=_as_float(data.get("match_score"), default=0.5),
            reason=_as_str(data.get("reason")),
            keywords=keywords,
            related_titles=_as_str_list(data.get("related_titles")),
        )

    @classmethod
    def list_from(cls, payload: dict[str, Any]) -> list["Direction"]:
        raw = payload.get("directions") if isinstance(payload, dict) else payload
        if not isinstance(raw, list):
            raise ValueError("directions 字段必须是数组")
        out: list[Direction] = []
        for entry in raw:
            direction = cls.from_dict(entry)
            if direction is not None:
                out.append(direction)
        if not out:
            raise ValueError("LLM 未返回任何有效岗位方向")
        return out

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
