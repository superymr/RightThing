"""把 LLM 返回的自由文本收敛为规范值。

**为什么需要这一层？**

mock 规则引擎返回的名字来自词表，天生就是规范名，所以聚合层看不出问题。
但真实大模型返回的是自由文本：

    学历     "硕士及以上学历" / "本科及以上学历" / "本科及以上"   → 同一概念三行
    经验     "3年以上" / "3年以上SLAM相关研发经验"               → 同一概念两行
    技能     "PID控制算法" / "PID控制"、 "力控算法" / "力控"      → 各算一项

不做收敛，一次分析能抽出 97 个「不同」技能，排行榜直接失效。
这一层就是「LLM 只做抽取、代码做统计」这条红线里的**接缝处理**。

与 `normalizer.py` 的分工：
- 本模块处理**结构化字段**（学历、经验、专业）—— 值域小，用正则与白名单；
- `normalizer.py` 处理**技能名** —— 值域开放，用别名表与包含匹配。
"""

from __future__ import annotations

import re

# ----------------------------------------------------------------------
# 学历
# ----------------------------------------------------------------------
EDU_RE = re.compile(r"(博士|硕士|研究生|本科|大专|专科)(及以上|以上)?")


def canonical_education(text: str) -> str:
    """「硕士及以上学历」→「硕士及以上」。

    「学历」二字不参与取值（否则「大专学历」会变成「大专学历」而不是「大专」）；
    「以上」与「及以上」对求职者是同一件事，统一成后者。
    """
    match = EDU_RE.search(text or "")
    if not match:
        return (text or "").strip()
    return f"{match.group(1)}{'及以上' if match.group(2) else ''}"


# ----------------------------------------------------------------------
# 经验年限
# ----------------------------------------------------------------------
EXP_RE = re.compile(r"(\d+)\s*[-~至到]\s*(\d+)\s*年|(\d+)\s*年以上|应届(?:生)?")


def canonical_experience(text: str) -> str:
    """「3年以上SLAM相关研发经验」→「3年以上」。"""
    match = EXP_RE.search(text or "")
    if not match:
        return (text or "").strip()
    if match.group(0).startswith("应届"):
        return "应届"
    if match.group(3):
        return f"{match.group(3)}年以上"
    if match.group(1) and match.group(2):
        return f"{match.group(1)}-{match.group(2)}年"
    return match.group(0)


# ----------------------------------------------------------------------
# 专业
# ----------------------------------------------------------------------
MAJORS: tuple[str, ...] = (
    "计算机", "软件工程", "自动化", "电子信息", "通信工程", "通信", "数学",
    "统计学", "机械工程", "机械", "控制工程", "控制", "人工智能", "车辆工程",
    "电气工程", "电气", "物理学", "模式识别", "机器人工程", "测绘", "金融工程",
    "经济学", "电子商务", "信息管理",
)

# 长名优先，避免「控制工程」被「控制」抢占后重复计入
_MAJORS_BY_LENGTH = tuple(sorted(MAJORS, key=len, reverse=True))

_MAJOR_SPLIT_RE = re.compile(r"[，,。；;、（）()\s]|相关|以及|等|和|及|与|或")


def canonical_majors(values: list[str]) -> list[str]:
    """把专业名收敛到白名单：["机械电子工程"] → ["机械"]，未知的保留原样。

    最后一步会去掉「被更具体写法包含」的条目：同时统计「机械」和「机械工程」
    等于把一个专业算了两遍，还会让排行榜显得比实际分散。
    """
    mapped: list[str] = []
    for value in values:
        text = (value or "").strip()
        if not text:
            continue
        hit = next((major for major in _MAJORS_BY_LENGTH if major in text), None)
        canonical = hit or text
        if canonical not in mapped:
            mapped.append(canonical)

    return [
        major
        for major in mapped
        if not any(major != other and major in other for other in mapped)
    ]


def extract_majors(jd_text: str) -> list[str]:
    """从 JD 原文抽取专业要求。

    难点在于中文列举：「统计学、数学、计算机相关专业」里只有最后一个词
    与「专业」相邻。所以要以「专业」为锚点向前取窗口，再按分隔符切开逐项匹配。

    窗口**必须在行边界内**。曾经为了让窗口够长而跨行，结果把上一条职责
    「性能优化与资源成本控制」里的「控制」当成了专业要求 ——
    这类错误不报错，只会让统计结果悄悄变脏。
    """
    found: list[str] = []
    for match in re.finditer("专业", jd_text):
        line_start = jd_text.rfind("\n", 0, match.start()) + 1
        window_start = max(line_start, match.start() - 40)
        window = jd_text[window_start: match.start()]
        for token in _MAJOR_SPLIT_RE.split(window):
            token = token.strip()
            if not token:
                continue
            for major in _MAJORS_BY_LENGTH:
                if major in token:
                    if major not in found:
                        found.append(major)
                    break

    if not found:
        # 兜底：全文扫描（可能写在职责而非要求里）
        found = [major for major in _MAJORS_BY_LENGTH if major in jd_text]
    return found[:6]


# ----------------------------------------------------------------------
# 职级
# ----------------------------------------------------------------------
def canonical_seniority(jd_text: str, experience_years: str) -> str:
    """归一到 应届 | 初级 | 中级 | 高级 | 专家。"""
    if "应届" in jd_text or "实习" in jd_text:
        return "应届"
    numbers = [int(n) for n in re.findall(r"(\d+)\s*年", experience_years or "")]
    if not numbers:
        return ""
    years = max(numbers)
    if years <= 1:
        return "初级"
    if years <= 3:
        return "中级"
    if years <= 6:
        return "高级"
    return "专家"
