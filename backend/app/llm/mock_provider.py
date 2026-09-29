"""Mock Provider —— 本地规则抽取引擎。

**为什么需要它？**
项目要在「没有 API Key」的情况下也能被完整验证：
- 新人 clone 下来就能跑通全链路，不必先申请密钥、不必花钱；
- 单元测试需要一个**完全确定性**的基线，否则测试会随机失败。

它用与生产环境**同一份词表**（data/skill_alias.json）做匹配，
所以输出的结构与真实模型完全一致，只是覆盖面与语义理解更弱。

**它不是玩具**：规则引擎对「技能词」这类高结构化信息的抽取，
在已知词表范围内反而比小模型更稳定 —— 这也是它作为回归基线的价值。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..analytics.canonical import (
    EDU_RE,
    EXP_RE,
    canonical_seniority,
    extract_majors,
)
from ..analytics.lexicon import SkillLexicon
from ..config import DEFAULT_ALIAS_PATH, DEFAULT_SAMPLE_DIR
from .base import LLMError, LLMResponse

# ---- 章节标题 ----
RESP_HEADERS = (
    "岗位职责", "工作职责", "职位描述", "工作内容", "职责描述", "主要职责",
    "你将负责", "你需要做", "工作职责描述",
)
REQ_HEADERS = (
    "任职要求", "岗位要求", "任职资格", "职位要求", "技能要求", "我们期待",
    "任职条件", "你需要具备", "我们希望你有", "岗位任职要求",
)
PREF_HEADERS = ("加分项", "优先条件", "以下条件优先", "优先考虑")

# ---- 判定「优先/加分」的信号词 ----
PREF_MARKERS = ("优先", "加分", "更佳", "尤佳", "更好", "preferred", "plus")

# ---- 学历 / 专业 / 经验的抽取与收敛逻辑统一放在 analytics/canonical.py ----
# 真模型返回的也是同形态的自由文本，两边共用同一套规范化，
# 否则同一个概念在 mock 路径和真实路径下会统计成两行。
BULLET_RE = re.compile(r"^\s*(?:[\(（]?\d+[\)）]|\d+[\.、]|[•·▪\-*○●])\s*")

# 技能族 → 输出字段的映射
CATEGORY_TO_FIELD = {
    "编程语言": "programming_languages",
    "深度学习框架": "hard_skills",
    "数据处理": "hard_skills",
    "工具与平台": "hard_skills",
    "数据库": "hard_skills",
    "机器人/感知": "domain_knowledge",
    "机器学习": "domain_knowledge",
    "软技能": "soft_skills",
}


class MockProvider:
    name = "mock"

    def __init__(
        self,
        alias_path: Path | None = None,
        sample_dir: Path | None = None,
    ) -> None:
        self.model_name = "mock-rule-engine"
        self._lexicon: SkillLexicon | None = None
        self._alias_path = Path(alias_path or DEFAULT_ALIAS_PATH)
        self._sample_dir = Path(sample_dir or DEFAULT_SAMPLE_DIR)

    # ------------------------------------------------------------------
    @property
    def lexicon(self) -> SkillLexicon:
        if self._lexicon is None:
            self._lexicon = SkillLexicon.load(self._alias_path)
        return self._lexicon

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        if schema_name == "direction_recommendation":
            data = self._recommend_directions(user)
        elif schema_name == "jd_profile":
            data = self._extract_profile(user)
        else:
            raise LLMError(f"MockProvider 不认识的 schema_name={schema_name!r}")

        return LLMResponse(
            data=data,
            model="mock-rule-engine",
            token_in=0,
            token_out=0,
            raw_text=json.dumps(data, ensure_ascii=False),
            meta={"provider": self.name, "schema_name": schema_name},
        )

    # ------------------------------------------------------------------
    # 岗位方向推荐
    # ------------------------------------------------------------------
    def _recommend_directions(self, user: str) -> dict[str, Any]:
        skills_block = _between(user, "<skills>", "</skills>")
        raw_skills = [
            part.strip()
            for part in re.split(r"[,，、\n;；]+", skills_block)
            if part.strip()
        ]
        user_skills = {s.lower() for s in raw_skills}

        scored: list[tuple[float, dict[str, Any], list[str]]] = []
        for meta in self._load_direction_meta():
            signature = [s for s in meta.get("signature_skills", []) if s]
            if not signature:
                continue
            matched = [s for s in signature if s.lower() in user_skills]
            if not matched:
                continue
            # 覆盖率为主要因素，技能族交叉验证为次要因素
            coverage = len(matched) / len(signature)
            breadth = min(len(matched), 3) / 3
            score = round(min(0.97, coverage * 0.72 + breadth * 0.28), 2)
            scored.append((score, meta, matched))

        scored.sort(key=lambda item: item[0], reverse=True)

        directions: list[dict[str, Any]] = []
        for score, meta, matched in scored[:5]:
            directions.append(
                {
                    "title": meta["direction"],
                    "match_score": score,
                    "reason": (
                        f"你的 {'、'.join(matched)} 命中了该方向的核心技能栈"
                        f"（{len(matched)}/{len(meta.get('signature_skills', []))} 覆盖率）。"
                        f"{meta.get('description', '')}"
                    ).strip(),
                    "keywords": meta.get("keywords", [meta["direction"]]),
                    "related_titles": meta.get("related_titles", []),
                }
            )

        if not directions:
            # 兜底：词表未覆盖用户技能时，至少产出一个可检索的方向，避免流程中断
            fallback = raw_skills[0] if raw_skills else "技术"
            directions.append(
                {
                    "title": f"{fallback}相关岗位",
                    "match_score": 0.3,
                    "reason": "本地词表未覆盖这些技能，已生成兜底检索词。建议接入真实大模型获得更准确的方向推荐。",
                    "keywords": [f"{s}工程师" for s in raw_skills[:3]] or [fallback],
                    "related_titles": [],
                }
            )

        return {"directions": directions}

    def _load_direction_meta(self) -> list[dict[str, Any]]:
        metas: list[dict[str, Any]] = []
        if not self._sample_dir.is_dir():
            return metas
        for path in sorted(self._sample_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if "direction" in payload:
                metas.append(payload)
        return metas

    # ------------------------------------------------------------------
    # JD 结构化抽取
    # ------------------------------------------------------------------
    def _extract_profile(self, user: str) -> dict[str, Any]:
        jd_text = _between(user, "<jd_text>", "</jd_text>")
        if not jd_text.strip():
            raise LLMError("Prompt 中缺少 <jd_text> 内容，无法抽取")
        job_title = _between(user, "<job_title>", "</job_title>").strip()

        lines = _split_sections(jd_text)

        buckets: dict[str, list[dict[str, Any]]] = {
            "programming_languages": [],
            "hard_skills": [],
            "domain_knowledge": [],
            "soft_skills": [],
        }
        certificates: list[str] = []
        seen: dict[str, dict[str, Any]] = {}

        for section, content in lines:
            if not content:
                continue
            is_preferred = section == "preferred" or any(
                marker in content.lower() for marker in PREF_MARKERS
            )
            for match in self.lexicon.find_in_text(content):
                if match.category == "证书":
                    if match.canonical not in certificates:
                        certificates.append(match.canonical)
                    continue

                field = CATEGORY_TO_FIELD.get(match.category, "hard_skills")
                existing = seen.get(match.canonical)
                if existing is not None:
                    # 同一个技能在多处出现：只要有一处是硬性要求，就判定为硬性要求
                    if existing["required"] is False and not is_preferred:
                        existing["required"] = True
                        existing["evidence"] = content
                    continue

                item = {
                    "name": match.canonical,
                    "category": match.category,
                    "required": not is_preferred,
                    "evidence": content,
                    "confidence": 0.9 if section in ("req", "preferred") else 0.75,
                }
                seen[match.canonical] = item
                buckets[field].append(item)

        education_match = EDU_RE.search(jd_text)
        education = education_match.group(0) if education_match else ""

        experience_match = EXP_RE.search(jd_text)
        experience_years = experience_match.group(0) if experience_match else ""

        majors = extract_majors(jd_text)

        preferred = [content for section, content in lines if content and (
            section == "preferred" or any(m in content.lower() for m in PREF_MARKERS)
        )]
        responsibilities = [content for section, content in lines if section == "resp" and content]

        top_skills = [item["name"] for item in buckets["programming_languages"][:2]]
        top_skills += [item["name"] for item in buckets["hard_skills"][:2]]

        return {
            "job_title": job_title or _guess_title(jd_text),
            "seniority": canonical_seniority(jd_text, experience_years),
            "education": education,
            "major": majors,
            "experience_years": experience_years,
            "programming_languages": buckets["programming_languages"],
            "hard_skills": buckets["hard_skills"],
            "domain_knowledge": buckets["domain_knowledge"],
            "soft_skills": buckets["soft_skills"],
            "certificates": certificates,
            "preferred_qualifications": preferred[:8],
            "responsibilities": responsibilities[:10],
            "summary": (
                f"需要 {'、'.join(top_skills)} 等能力" if top_skills else "（本地规则引擎未能提炼要点）"
            ),
        }


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------


def _between(text: str, start_tag: str, end_tag: str) -> str:
    start = text.find(start_tag)
    if start == -1:
        return ""
    start += len(start_tag)
    end = text.find(end_tag, start)
    return text[start:end] if end != -1 else text[start:]


def _strip_bullet(line: str) -> str:
    return BULLET_RE.sub("", line).strip()


def _split_sections(jd_text: str) -> list[tuple[str, str]]:
    """把 JD 拆成 (section, 单条内容) 列表。

    section 取值：resp（职责） / req（要求） / preferred（加分） / other
    """
    out: list[tuple[str, str]] = []
    current = "other"

    for raw_line in jd_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        header_section = None
        remainder = line
        for header in PREF_HEADERS:
            if line.startswith(header):
                header_section, remainder = "preferred", line[len(header):]
                break
        if header_section is None:
            for header in REQ_HEADERS:
                if line.startswith(header):
                    header_section, remainder = "req", line[len(header):]
                    break
        if header_section is None:
            for header in RESP_HEADERS:
                if line.startswith(header):
                    header_section, remainder = "resp", line[len(header):]
                    break

        if header_section is not None:
            current = header_section
            remainder = remainder.lstrip("：: 　").strip()
            if not remainder:
                continue
            line = remainder

        content = _strip_bullet(line)
        if content:
            out.append((current, content))
    return out


def _guess_title(jd_text: str) -> str:
    for raw_line in jd_text.splitlines():
        line = raw_line.strip()
        if line:
            return re.sub(r"^(岗位名称|职位名称|招聘岗位)\s*[:：]\s*", "", line)[:40]
    return "未标注岗位"
