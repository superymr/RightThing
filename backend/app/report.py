"""报告渲染（控制台 + JSON）。

**刻意与 orchestrator 分离**：分析逻辑与展示格式是两件会独立变化的事。
M3 阶段前端会消费同一份 JSON，而不是去解析这段控制台文本。

中英文混排对齐：中文在终端占 2 列，这里用 wcwidth 近似处理，
否则排行榜的竖线会歪掉 —— 这是个很小但很影响观感的细节。
"""

from __future__ import annotations

import json
from typing import Any

from .analytics.aggregator import AggregateResult, PreferenceStat, SkillStat
from .services.orchestrator import AnalysisReport, DirectionReport

WIDTH = 78
BAR_WIDTH = 20
GAUGE_WIDTH = 22


# ----------------------------------------------------------------------
# 显示宽度工具
# ----------------------------------------------------------------------
def _char_width(char: str) -> int:
    code = ord(char)
    if (
        0x1100 <= code <= 0x115F
        or 0x2E80 <= code <= 0xA4CF
        or 0xAC00 <= code <= 0xD7A3
        or 0xF900 <= code <= 0xFAFF
        or 0xFE30 <= code <= 0xFE6F
        or 0xFF00 <= code <= 0xFF60
        or 0xFFE0 <= code <= 0xFFE6
    ):
        return 2
    return 1


def _disp_len(text: str) -> int:
    return sum(_char_width(c) for c in text)


def _pad(text: str, width: int, align: str = "left") -> str:
    text = text or ""
    # 先按显示宽度截断，再补齐
    if _disp_len(text) > width:
        out = ""
        used = 0
        for char in text:
            cw = _char_width(char)
            if used + cw > width - 1:
                break
            out += char
            used += cw
        text = out + "…"
    space = max(0, width - _disp_len(text))
    return (text + " " * space) if align == "left" else (" " * space + text)


def _bar(value: float, max_value: float, width: int = BAR_WIDTH) -> str:
    if max_value <= 0:
        return ""
    filled = int(round(width * (value / max_value)))
    return "█" * max(0, min(width, filled))


def _rule(char: str = "-") -> str:
    return char * WIDTH


def _header(title: str) -> str:
    return f"\n{title}\n{_rule()}"


# ----------------------------------------------------------------------
def render(report: AnalysisReport, *, top: int = 15) -> str:
    lines: list[str] = []
    lines.append(_rule("="))
    lines.append("  RightThing 正事 · 分析报告")
    lines.append(_rule("="))

    lines.append(f"  输入技能   : {'、'.join(report.input_skills)}")
    lines.append(f"  归一化结果 : {'、'.join(s.canonical for s in report.normalized)}")
    if any(not s.known for s in report.normalized):
        unknown = [s.canonical for s in report.normalized if not s.known]
        lines.append(f"  词表未见   : {'、'.join(unknown)}（已登记，可后续人工合并）")
    lines.append(f"  抽取后端   : {report.provider} / {report.model}")
    lines.append(f"  样本总量   : {report.total_jobs} 条 JD")
    lines.append(f"  总耗时     : {report.duration_sec} 秒")
    if report.session_id:
        lines.append(f"  会话 ID    : {report.session_id}")

    if len(report.reports) > 1:
        lines.append(_header("推荐岗位方向"))
        lines.append(f"  {_pad('方向', 24)}{_pad('匹配度', 8)}{_pad('说明', 44)}")
        for item in report.reports:
            lines.append(
                f"  {_pad(item.direction.title, 24)}"
                f"{_pad(f'{item.direction.match_score:.2f}', 8)}"
                f"{_pad(item.direction.reason, 44)}"
            )

    for item in report.reports:
        lines.extend(_render_direction(item, top=top))

    lines.append("")
    lines.append(_rule("="))
    lines.append("  说明：所有数字均由代码从结构化抽取结果中统计得出，可回溯至原始 JD。")
    lines.append("       「加权分」= 硬性要求 ×1.0 + 加分项 ×0.4，用于综合排序。")
    lines.append(_rule("="))
    return "\n".join(lines)


def _render_direction(item: DirectionReport, *, top: int) -> list[str]:
    lines: list[str] = []
    lines.append(_header(f"方向：{item.direction.title}"))
    lines.append(
        f"  有效样本 {item.ok}/{item.total} 条"
        f"　解析失败 {item.failed} 条"
        f"　缓存命中 {item.cache_hits} 条"
        + (f"　token {item.token_in}+{item.token_out}" if item.token_in or item.token_out else "")
    )
    if item.failed:
        lines.append(f"  ⚠ 失败样例：{item.errors[0][:70] if item.errors else ''}")

    agg = item.aggregate
    if agg.total_jobs == 0:
        lines.append("  （无有效样本，无法统计）")
        return lines

    lines.extend(_render_skill_block("编程语言排行", agg.languages, agg, top))
    lines.extend(_render_skill_block("核心技能排行", agg.hard_skills, agg, top))
    lines.extend(_render_skill_block("领域知识排行", agg.domain_knowledge, agg, min(top, 12)))
    lines.extend(_render_skill_block("软技能排行", agg.soft_skills, agg, min(top, 8)))

    lines.extend(_render_pref_block("招聘方偏好 · 学历", agg.education, top))
    lines.extend(_render_pref_block("招聘方偏好 · 专业", agg.majors, min(top, 8)))
    lines.extend(_render_pref_block("招聘方偏好 · 经验年限", agg.experience, min(top, 8)))
    lines.extend(_render_pref_block("招聘方偏好 · 证书", agg.certificates, min(top, 6)))
    lines.extend(
        _render_pref_block("★ 优先考虑对象", agg.preferred_qualifications, min(top, 8))
    )

    lines.extend(_render_gap(item))
    return lines


def _render_skill_block(
    title: str, stats: list[SkillStat], agg: AggregateResult, top: int
) -> list[str]:
    if not stats:
        return []
    lines = [_header(title)]
    shown = stats[:top]
    max_score = shown[0].weighted_score or 1.0
    for index, stat in enumerate(shown, 1):
        lines.append(
            f"  {index:>2}. {_pad(stat.canonical, 20)}"
            f"{_bar(stat.weighted_score, max_score)} "
            f"{_pad(f'{stat.count}/{agg.total_jobs}', 8)}"
            f"{_pad(f'{stat.coverage:.0%}', 6)}"
            f"必须占 {stat.required_ratio:.0%}"
        )
    return lines


def _render_pref_block(title: str, stats: list[PreferenceStat], top: int) -> list[str]:
    if not stats:
        return []
    lines = [_header(title)]
    for index, stat in enumerate(stats[:top], 1):
        lines.append(
            f"  {index:>2}. {_pad(stat.label, 46)}"
            f"{_pad(f'{stat.count} 次', 8)}{stat.coverage:.0%}"
        )
    return lines


def _render_gap(item: DirectionReport) -> list[str]:
    gap = item.gap
    lines = [_header("技能缺口分析")]
    gauge = _bar(gap.coverage_score, 1.0, GAUGE_WIDTH)
    lines.append(f"  市场要求覆盖率：{gauge} {gap.coverage_score:.0%}")
    lines.append(
        f"  （你的技能覆盖了该方向 {gap.coverage_score:.0%} 的岗位要求权重；"
        f"已具备 {len(gap.have)} 项，待补齐 {len(gap.missing)} 项）"
    )

    if gap.have:
        lines.append("")
        lines.append("  ✅ 你的优势项（简历上要突出写）")
        for stat in gap.have[:10]:
            lines.append(
                f"     · {_pad(stat.canonical, 20)}{_pad(f'该方向 {stat.coverage:.0%} 岗位要求', 24)}"
                f"必须占 {stat.required_ratio:.0%}"
            )

    for tier_items, label, hint, fold_singles in (
        (gap.must_learn, "🔥 必学清单", "覆盖率高且以硬性要求为主，不学基本过不了简历关", False),
        (gap.should_learn, "📘 建议学", "有一定覆盖率，能显著提升匹配度", False),
        (gap.nice_to_have, "➕ 加分项", "少数岗位要求，性价比取决于你的目标公司", True),
    ):
        if not tier_items:
            continue
        lines.append("")
        lines.append(f"  {label}（{len(tier_items)} 项）—— {hint}")

        singles = [item for item in tier_items if item.stat.count < 2]
        listed = [item for item in tier_items if not (fold_singles and item.stat.count < 2)]
        for gap_item in listed[:12]:
            stat = gap_item.stat
            lines.append(
                f"     · {_pad(stat.canonical, 20)}{_pad(f'{stat.coverage:.0%} 岗位要求', 16)}"
                f"{_pad(stat.category, 14)}加权分 {stat.weighted_score}"
            )
        if fold_singles and len(listed) > 12:
            lines.append(f"     … 另有 {len(listed) - 12} 项，覆盖率较低，未展示")
        if fold_singles and singles:
            lines.append(
                f"     （另有 {len(singles)} 项仅在 1 个岗位出现，代表性不足，已折叠）"
            )

    if gap.marginal:
        lines.append("")
        lines.append(f"  💤 该方向用不上，可暂缓投入：{'、'.join(gap.marginal[:12])}")

    return lines


# ----------------------------------------------------------------------
def to_dict(report: AnalysisReport) -> dict[str, Any]:
    """供前端 / 导出使用的完整结构化结果（M3 的接口就是它）。"""
    return {
        "input_skills": report.input_skills,
        "normalized_skills": [
            {
                "raw": s.raw,
                "canonical": s.canonical,
                "category": s.category,
                "known": s.known,
            }
            for s in report.normalized
        ],
        "provider": report.provider,
        "model": report.model,
        "duration_sec": report.duration_sec,
        "session_id": report.session_id,
        "directions": [
            {
                "title": item.direction.title,
                "match_score": item.direction.match_score,
                "reason": item.direction.reason,
                "keywords": item.direction.keywords,
                "total_jobs": item.total,
                "ok_jobs": item.ok,
                "failed_jobs": item.failed,
                "cache_hits": item.cache_hits,
                "languages": [s.to_dict() for s in item.aggregate.languages],
                "hard_skills": [s.to_dict() for s in item.aggregate.hard_skills],
                "domain_knowledge": [s.to_dict() for s in item.aggregate.domain_knowledge],
                "soft_skills": [s.to_dict() for s in item.aggregate.soft_skills],
                "education": [p.to_dict() for p in item.aggregate.education],
                "majors": [p.to_dict() for p in item.aggregate.majors],
                "experience": [p.to_dict() for p in item.aggregate.experience],
                "seniority": [p.to_dict() for p in item.aggregate.seniority],
                "certificates": [p.to_dict() for p in item.aggregate.certificates],
                "preferred_qualifications": [
                    p.to_dict() for p in item.aggregate.preferred_qualifications
                ],
                "gap": item.gap.to_dict(),
                "jobs": [
                    {
                        "id": job.source_job_id,
                        "title": job.title,
                        "company": job.company,
                        "city": job.city,
                        "source": job.source,
                        "url": job.url,
                    }
                    for job in item.jobs
                ],
            }
            for item in report.reports
        ],
    }


def to_json(report: AnalysisReport, *, indent: int = 2) -> str:
    return json.dumps(to_dict(report), ensure_ascii=False, indent=indent)
