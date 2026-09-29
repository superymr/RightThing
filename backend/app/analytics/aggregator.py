"""聚合统计。

**这是全项目唯一允许「数数」的地方。**

LLM 负责理解文本，这里负责产生一切数字。所有排行榜、覆盖率、加权分
都由本模块从结构化结果中确定性算出 —— 因此可以单元测试，也因此在
同一批数据上永远得到同一个答案。

三个指标的设计意图（对应 PLAN.md 第 4.5 节）：

| 指标              | 回答的问题                     |
|-------------------|--------------------------------|
| count             | 有多少个岗位提到了它           |
| coverage          | 它在市场中的普及度（消除样本量差异） |
| required_ratio    | 它是「必须会」还是「会更好」   |
| weighted_score    | 综合排序依据（必须=1.0，加分=0.4） |
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from ..llm.schemas import JDProfile

REQUIRED_WEIGHT = 1.0
PREFERRED_WEIGHT = 0.4


@dataclass
class SkillStat:
    canonical: str
    category: str
    count: int
    coverage: float
    required_count: int
    preferred_count: int
    weighted_score: float
    job_ids: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)  # 原文证据（去重后的前若干条）

    @property
    def required_ratio(self) -> float:
        return round(self.required_count / self.count, 3) if self.count else 0.0

    def to_dict(self) -> dict:
        return {
            "canonical": self.canonical,
            "category": self.category,
            "count": self.count,
            "coverage": self.coverage,
            "required_count": self.required_count,
            "preferred_count": self.preferred_count,
            "required_ratio": self.required_ratio,
            "weighted_score": self.weighted_score,
            "job_ids": self.job_ids,
            "examples": self.examples,
        }


@dataclass
class PreferenceStat:
    """「优先考虑对象」一类的偏好统计（学历/专业/经验/加分项）。"""

    label: str
    count: int
    coverage: float
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "count": self.count,
            "coverage": self.coverage,
            "examples": self.examples,
        }


@dataclass
class AggregateResult:
    direction: str
    total_jobs: int
    languages: list[SkillStat] = field(default_factory=list)
    hard_skills: list[SkillStat] = field(default_factory=list)
    domain_knowledge: list[SkillStat] = field(default_factory=list)
    soft_skills: list[SkillStat] = field(default_factory=list)
    education: list[PreferenceStat] = field(default_factory=list)
    majors: list[PreferenceStat] = field(default_factory=list)
    experience: list[PreferenceStat] = field(default_factory=list)
    seniority: list[PreferenceStat] = field(default_factory=list)
    certificates: list[PreferenceStat] = field(default_factory=list)
    preferred_qualifications: list[PreferenceStat] = field(default_factory=list)

    @property
    def all_skills(self) -> list[SkillStat]:
        merged = [*self.languages, *self.hard_skills, *self.domain_knowledge, *self.soft_skills]
        return sorted(merged, key=lambda s: (-s.weighted_score, -s.count, s.canonical))

    def skill_map(self) -> dict[str, SkillStat]:
        return {stat.canonical.lower(): stat for stat in self.all_skills}


# ----------------------------------------------------------------------
def aggregate(
    profiles: list[tuple[str, JDProfile]],
    *,
    direction: str = "",
) -> AggregateResult:
    """profiles: [(job_key, profile), ...]，job_key 用于按岗位去重计数。"""
    total = len(profiles)
    result = AggregateResult(direction=direction, total_jobs=total)
    if total == 0:
        return result

    # canonical(lower) -> 累积状态
    acc: dict[str, dict] = {}

    edu_counter: Counter[str] = Counter()
    major_counter: Counter[str] = Counter()
    exp_counter: Counter[str] = Counter()
    seniority_counter: Counter[str] = Counter()
    cert_counter: Counter[str] = Counter()
    pref_counter: Counter[str] = Counter()
    pref_display: dict[str, str] = {}

    for job_key, profile in profiles:
        # 同一岗位内先去重：一个技能在一条 JD 里出现多次只算一次
        per_job: dict[str, dict] = {}
        for item in profile.all_skills():
            key = item.name.strip().lower()
            if not key:
                continue
            existing = per_job.get(key)
            if existing is None:
                per_job[key] = {
                    "canonical": item.name.strip(),
                    "category": item.category or "其他",
                    "required": item.required,
                    "evidence": item.evidence,
                }
            elif item.required and not existing["required"]:
                # 只要有一处是硬性要求，就按硬性要求计
                existing["required"] = True
                if item.evidence:
                    existing["evidence"] = item.evidence

        for key, item in per_job.items():
            state = acc.setdefault(
                key,
                {
                    "canonical": item["canonical"],
                    "category": item["category"],
                    "required_count": 0,
                    "preferred_count": 0,
                    "job_ids": [],
                    "examples": [],
                },
            )
            if item["required"]:
                state["required_count"] += 1
            else:
                state["preferred_count"] += 1
            state["job_ids"].append(job_key)
            evidence = (item["evidence"] or "").strip()
            if evidence and evidence not in state["examples"] and len(state["examples"]) < 3:
                state["examples"].append(evidence)

        if profile.education:
            edu_counter[profile.education] += 1
        for major in profile.major:
            major_counter[major] += 1
        if profile.experience_years:
            exp_counter[profile.experience_years] += 1
        if profile.seniority:
            seniority_counter[profile.seniority] += 1
        for cert in profile.certificates:
            cert_counter[cert] += 1
        for text in profile.preferred_qualifications:
            normalized = _normalize_preference(text)
            if not normalized:
                continue
            pref_counter[normalized] += 1
            # 展示时用最短的等价表述，避免同一句话的冗长版本占满屏幕
            current = pref_display.get(normalized)
            if current is None or len(text.strip()) < len(current):
                pref_display[normalized] = text.strip()

    stats: list[SkillStat] = []
    for state in acc.values():
        count = state["required_count"] + state["preferred_count"]
        weighted = state["required_count"] * REQUIRED_WEIGHT + state["preferred_count"] * PREFERRED_WEIGHT
        stats.append(
            SkillStat(
                canonical=state["canonical"],
                category=state["category"],
                count=count,
                coverage=round(count / total, 3),
                required_count=state["required_count"],
                preferred_count=state["preferred_count"],
                weighted_score=round(weighted, 2),
                job_ids=state["job_ids"],
                examples=state["examples"],
            )
        )

    stats.sort(key=lambda s: (-s.weighted_score, -s.count, s.canonical))
    for stat in stats:
        bucket = _bucket_of(stat.category)
        getattr(result, bucket).append(stat)

    result.education = _prefs(edu_counter, total)
    result.majors = _prefs(major_counter, total)
    result.experience = _prefs(exp_counter, total)
    result.seniority = _prefs(seniority_counter, total)
    result.certificates = _prefs(cert_counter, total)
    result.preferred_qualifications = _prefs(pref_counter, total, display=pref_display)
    return result


# ----------------------------------------------------------------------
def _bucket_of(category: str) -> str:
    if category == "编程语言":
        return "languages"
    if category == "软技能":
        return "soft_skills"
    if category in ("机器人/感知", "机器学习", "领域知识"):
        return "domain_knowledge"
    return "hard_skills"


def _prefs(
    counter: Counter[str],
    total: int,
    *,
    display: dict[str, str] | None = None,
) -> list[PreferenceStat]:
    out: list[PreferenceStat] = []
    for label, count in counter.most_common():
        shown = (display or {}).get(label, label)
        out.append(PreferenceStat(label=shown, count=count, coverage=round(count / total, 3)))
    return out


_PUNCT_RE = re.compile(r"[\s，。；、,.;:：!！?？~～\-—()（）\[\]【】\"'“”‘’]+")


def _normalize_preference(text: str) -> str:
    """把「优先考虑对象」的表述归一化，让措辞不同的同类要求能合并计数。"""
    cleaned = _PUNCT_RE.sub("", (text or "").strip())
    return cleaned
