"""报告导出（Markdown）。

**关键设计：导出消费的是看板的那份 payload，不是自己重算一遍。**

`services/dashboard.py :: load_session()` 返回的字典同时喂给前端和这里。
如果导出自己走 `report.to_dict()` 或重新聚合，就会出现「网页上说 C++ 83%，
导出的 md 里写 92%」这种最伤信任的问题 —— 而且这类不一致往往几个月后
才被用户发现。同源是唯一稳妥的做法。

导出格式选 Markdown 而不是 PDF：Markdown 能被 Git 管理、能贴进笔记、
能 diff，而且不引入任何依赖（本项目的核心链路至今仍零第三方依赖）。
"""

from __future__ import annotations

from typing import Any

from ..analytics.gap import MUST_COVERAGE, MUST_REQUIRED_RATIO
from ..analytics.gap import SHOULD_COVERAGE, SHOULD_REQUIRED_RATIO, MIN_JOBS

TIER_LABEL = {"must": "优先关注", "should": "建议学", "nice": "加分项"}


def _pct(value: float, digits: int = 0) -> str:
    return f"{value * 100:.{digits}f}%"


def _escape(text: Any) -> str:
    """转义 Markdown 表格里会破坏结构的字符。

    JD 标题里出现 `|` 很常见（"算法工程师｜感知"），不转义会把表格列数冲乱，
    渲染出来是一张错位的表 —— 属于「不报错但结果明显不对」的那类问题。
    """
    return str(text or "").replace("|", "\\|").replace("\n", " ")


def _skill_table(stats: list[dict[str, Any]], *, top: int) -> list[str]:
    if not stats:
        return ["_（无）_", ""]
    lines = [
        "| # | 技能 | 技能族 | 岗位数 | 覆盖率 | 必须占比 | 加权分 |",
        "|---:|---|---|---:|---:|---:|---:|",
    ]
    for index, stat in enumerate(stats[:top], 1):
        lines.append(
            f"| {index} | {_escape(stat['canonical'])} | {_escape(stat['category'])} "
            f"| {stat['count']} | {_pct(stat['coverage'])} | {_pct(stat['required_ratio'])} "
            f"| {stat['weighted_score']} |"
        )
    if len(stats) > top:
        lines.append(f"| | _… 另有 {len(stats) - top} 项，详见看板_ | | | | | |")
    lines.append("")
    return lines


def _pref_table(title: str, stats: list[dict[str, Any]], *, top: int = 8) -> list[str]:
    if not stats:
        return []
    lines = [f"**{title}**", "", "| 项 | 次数 | 覆盖率 |", "|---|---:|---:|"]
    for stat in stats[:top]:
        lines.append(f"| {_escape(stat['label'])} | {stat['count']} | {_pct(stat['coverage'])} |")
    lines.append("")
    return lines


def _all_skills(direction: dict[str, Any]) -> list[dict[str, Any]]:
    merged = [
        *direction["languages"],
        *direction["hard_skills"],
        *direction["domain_knowledge"],
        *direction["soft_skills"],
    ]
    return sorted(merged, key=lambda s: (-s["weighted_score"], -s["count"], s["canonical"]))


def render_markdown(payload: dict[str, Any], *, top: int = 20) -> str:
    lines: list[str] = []
    lines.append(f"# RightThing 正事 · 分析报告（会话 #{payload['session_id']}）")
    lines.append("")
    lines.append(
        f"- 生成时间：{payload.get('created_at', '')}\n"
        f"- 抽取后端：`{payload.get('provider', '')}` / `{payload.get('model', '')}`\n"
        f"- 样本总量：{payload.get('total_jobs', 0)} 条 JD\n"
        f"- 城市过滤：{payload.get('city') or '不限'}"
    )
    lines.append("")

    raw_skills = payload.get("input_skills") or []
    canonical = payload.get("canonical_skills") or []
    if raw_skills or canonical:
        lines.append("## 输入技能")
        lines.append("")
        lines.append(f"- 你输入的：{'、'.join(raw_skills) or '（无）'}")
        lines.append(f"- 归一化后：{'、'.join(canonical) or '（无）'}")
        lines.append("")

    for direction in payload.get("directions", []):
        lines.extend(_render_direction(direction, top=top))

    lines.append("---")
    lines.append("")
    lines.append("## 口径与免责声明")
    lines.append("")
    lines.append(
        "- **覆盖率** = 提到该技能的岗位数 / 样本量；**加权分** = 硬性要求数 × 1.0 + 加分项数 × 0.4。\n"
        f"- **优先关注**：覆盖率 ≥ {_pct(MUST_COVERAGE)} 且必须占比 ≥ {_pct(MUST_REQUIRED_RATIO)}；"
        f"**建议学**：覆盖率 ≥ {_pct(SHOULD_COVERAGE)} 或必须占比 ≥ {_pct(SHOULD_REQUIRED_RATIO)}。\n"
        f"- 只被 {MIN_JOBS - 1} 个岗位提到的技能一律降级为「加分项」—— 那是噪音，不是市场信号。\n"
        "- 所有数字都由确定性代码从结构化抽取结果中统计得出，可点回原始 JD 核对。\n"
        "- 样本量有限，**不代表全市场**；请结合覆盖率而非绝对次数解读。\n"
        "- 内置样例为合成数据，不含真实公司信息。"
    )
    lines.append("")
    return "\n".join(lines)


def _render_direction(direction: dict[str, Any], *, top: int) -> list[str]:
    lines: list[str] = []
    lines.append(f"## 方向：{direction['title']}")
    lines.append("")
    lines.append(
        f"- 匹配度（AI 估计，仅作排序参考）：**{direction.get('match_score', 0):.2f}**\n"
        f"- 理由：{direction.get('reason', '')}\n"
        f"- 有效样本：{direction.get('ok_jobs', 0)}/{direction.get('total_jobs', 0)} 条"
        + (
            f"（解析失败 {direction['failed_jobs']} 条）"
            if direction.get("failed_jobs")
            else ""
        )
    )
    keywords = direction.get("keywords") or []
    quality = direction.get("sample_quality") or {}
    if quality:
        lines.append(f"- 独立公司：{quality.get('company_count', 0)} 家；来源分布：" +
                     "、".join(f"{name} {count} 条" for name, count in quality.get('source_counts', {}).items()))
        lines.append("> " + ("初步观察。" if quality.get("preliminary") else "") + quality.get("note", ""))
    if keywords:
        lines.append(f"- 检索关键词：{'、'.join(keywords)}")
    lines.append("")

    gap = direction.get("gap") or {}
    if not direction.get("ok_jobs"):
        lines.append("> 该方向没有可用样本（样例数据未覆盖），无法统计。")
        lines.append("")
        return lines

    lines.append("### 技能缺口")
    lines.append("")
    lines.append(
        f"你的技能覆盖了该方向 **{_pct(gap.get('coverage_score', 0), 1)}** 的岗位要求权重。"
    )
    lines.append("")

    have = gap.get("have") or []
    if have:
        lines.append(f"**✅ 已具备（{len(have)} 项）** —— 简历与面谈里应当优先展开")
        lines.append("")
        for stat in have[:12]:
            lines.append(
                f"- {_escape(stat['canonical'])}（该方向 {_pct(stat['coverage'])} 岗位要求，"
                f"必须占比 {_pct(stat['required_ratio'])}）"
            )
        lines.append("")

    for key in ("must_learn", "should_learn", "nice_to_have"):
        items = gap.get(key) or []
        if not items:
            continue
        tier = items[0].get("tier", "")
        lines.append(f"**{'🔥' if key == 'must_learn' else '📘' if key == 'should_learn' else '➕'} "
                     f"{TIER_LABEL.get(tier, tier)}（{len(items)} 项）**")
        lines.append("")
        for item in items[:15]:
            lines.append(
                f"- {_escape(item['canonical'])} — {_pct(item['coverage'])} 岗位要求，"
                f"必须占比 {_pct(item['required_ratio'])}，加权分 {item['weighted_score']}"
            )
        if len(items) > 15:
            lines.append(f"- _… 另有 {len(items) - 15} 项_")
        lines.append("")

    marginal = gap.get("marginal") or []
    if marginal:
        lines.append(f"**本次样本暂未提及（不代表没有价值）**：{'、'.join(marginal)}")
        lines.append("")

    lines.append(f"### 技能排行（Top {top}）")
    lines.append("")
    lines.extend(_skill_table(_all_skills(direction), top=top))

    lines.append("### 招聘方偏好")
    lines.append("")
    lines.extend(_pref_table("学历", direction.get("education") or []))
    lines.extend(_pref_table("专业偏好", direction.get("majors") or []))
    lines.extend(_pref_table("经验年限", direction.get("experience") or []))
    lines.extend(_pref_table("职级", direction.get("seniority") or []))
    lines.extend(_pref_table("证书", direction.get("certificates") or []))
    lines.extend(_pref_table("★ 优先考虑对象", direction.get("preferred_qualifications") or []))

    jobs = direction.get("jobs") or []
    if jobs:
        lines.append(f"### 岗位清单（{len(jobs)} 条）")
        lines.append("")
        lines.append("| 岗位 | 公司 | 城市 | 来源 | 抽取状态 |")
        lines.append("|---|---|---|---|---|")
        for job in jobs:
            lines.append(
                f"| {_escape(job.get('title'))} | {_escape(job.get('company'))} "
                f"| {_escape(job.get('city'))} | {_escape(job.get('source'))} "
                f"| {_escape(job.get('status'))} |"
            )
        lines.append("")
    return lines
