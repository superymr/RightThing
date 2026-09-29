"""JD 文本脱敏。

`PLAN.md` 第 9 节把「个人信息」列为必须处置的风险：JD 正文里经常夹着
HR 的手机号、邮箱、微信号 —— 那是**招聘方的个人信息**，既不该落进本地库，
也不该整段发给大模型。原计划的待办就是「对手机号/邮箱做正则脱敏」。

三个设计决定：

**1. 脱敏发生在入库与抽取之前，而不是展示时。**
如果只在渲染时打码，明文仍然躺在 `raw_job.raw_text` 里，也仍然被发给了模型 ——
那就只是「看起来合规」。更关键的是：抽取用的文本必须与存库的文本**是同一份**，
否则 `evidence` 只是「原文子串」这条不变量会在脱敏后失效，前端高亮和幻觉度量
会一起崩掉。放在最前面，这条不变量自动成立。

**2. 掩码必须幂等。**
已经打过码的文本再跑一次不能发生变化。做法是让掩码字符（`*`）落在各条正则的
字符类之外：`138****1234` 再也匹配不上手机号。没有这条性质，
「重复分析同一条 JD」会得到内容不同、hash 不同的两条记录，去重就废了。
（这条有回归测试。）

**3. 保留部分信息，便于人工核对。**
手机保留前 3 后 4、邮箱保留首字母与域名：既去掉了可直接联系的信息，
又能让用户在原文回溯时看出「这里原本是一个联系方式」，而不是一堆无意义的星号。
身份证是唯一例外 —— 它含出生日期与地区，整串打码。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

MASK = "*"


@dataclass(frozen=True)
class RedactionRule:
    """一条脱敏规则。

    `pattern` 必须用前后视断言把「数字串的边界」钉死，否则会从一长串数字中间
    截一段出来打码 —— 那会把 JD 里的其他数字改得面目全非。
    """

    name: str
    label: str
    pattern: re.Pattern[str]
    replace: Callable[[re.Match[str]], str]


def _mask_phone(match: re.Match[str]) -> str:
    digits = match.group(0)
    return f"{digits[:3]}{MASK * 4}{digits[-4:]}"


def _mask_landline(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    return f"{digits[:4]}-{MASK * max(4, len(digits) - 4)}"


def _mask_email(match: re.Match[str]) -> str:
    local, _, domain = match.group(0).partition("@")
    head = local[0] if local else MASK
    return f"{head}{MASK * 3}@{domain}"


def _mask_id_card(match: re.Match[str]) -> str:
    return MASK * len(match.group(0))


def _mask_im(match: re.Match[str]) -> str:
    return f"{match.group(1)}{MASK * 3}"


def _mask_bank_card(match: re.Match[str]) -> str:
    digits = match.group(0)
    return f"{digits[:4]}{MASK * 8}{digits[-4:]}"


# 顺序有讲究：长的、更具体的先跑。
# 例如身份证必须在手机号之前 —— 否则 18 位号码可能被截出 11 位当手机号打码，
# 留下半截真实数字，比不打码更糟（看起来已处理，实际仍泄露）。
RULES: tuple[RedactionRule, ...] = (
    RedactionRule(
        "email",
        "邮箱",
        re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}"),
        _mask_email,
    ),
    RedactionRule(
        "id_card",
        "身份证号",
        re.compile(r"(?<![\dXx])\d{17}[\dXx](?![\dXx])"),
        _mask_id_card,
    ),
    RedactionRule(
        "phone",
        "手机号",
        re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
        _mask_phone,
    ),
    RedactionRule(
        "landline",
        "固定电话",
        re.compile(r"(?<!\d)0\d{2,3}[\-\s]?\d{7,8}(?!\d)"),
        _mask_landline,
    ),
    RedactionRule(
        "im",
        "微信/QQ",
        # 两个刻意收紧的地方：
        # 1. 账号限定 ASCII（含至少一位数字）——「微信小程序」「微信号可以作为加分项」
        #    这类正常表述里，前缀后面跟的是中文，天然不会命中；
        # 2. 要求至少 5 位且含数字 —— 否则 "QQ group" 这种英文短语会被误伤。
        re.compile(
            r"(微信号|微信|wechat|weixin|QQ)\s*[号:：]?\s*"
            r"(?=[A-Za-z0-9_\-]{5,20})([A-Za-z0-9_\-]*\d[A-Za-z0-9_\-]*)",
            re.IGNORECASE,
        ),
        _mask_im,
    ),
    RedactionRule(
        "bank_card",
        "银行卡号",
        re.compile(r"(?<!\d)\d{16,19}(?!\d)"),
        _mask_bank_card,
    ),
)


@dataclass
class SanitizeResult:
    text: str
    hits: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.hits.values())

    @property
    def changed(self) -> bool:
        return self.total > 0

    def describe(self) -> str:
        """给日志/进度事件用的一行摘要，不含被打码的内容本身。"""
        parts = [f"{LABELS.get(name, name)} {count}" for name, count in self.hits.items()]
        return "、".join(parts)


LABELS = {rule.name: rule.label for rule in RULES}


def sanitize_text(text: str) -> SanitizeResult:
    """对一段文本做脱敏。纯函数，不碰数据库也不碰网络。"""
    if not text:
        return SanitizeResult(text=text or "")

    current = text
    hits: dict[str, int] = {}
    for rule in RULES:
        current, count = rule.pattern.subn(rule.replace, current)
        if count:
            hits[rule.name] = hits.get(rule.name, 0) + count
    return SanitizeResult(text=current, hits=hits)


def contains_pii(text: str) -> bool:
    """是否存在未脱敏的个人信息。`doctor` 与测试用它做体检。"""
    return any(rule.pattern.search(text or "") for rule in RULES)
