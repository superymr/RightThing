"""技能词表（Lexicon）—— 从别名表加载，并对文本做边界安全的技能匹配。

这个模块是「词典」这一层能力，被两处复用：
1. `analytics/normalizer.py`：把用户输入的技能名归一化；
2. `llm/mock_provider.py`：无 API Key 时用同一份词表做规则抽取。

同一份词表、同一套匹配规则 —— 保证 mock 结果与真实模型结果在结构上可比。

匹配的两个关键细节：
- **边界安全**：`C` 不能匹配到 `C++`，`SQL` 不能匹配到 `MySQL`（用 `(?<![A-Za-z0-9+#])` 断言）；
- **最长优先 + 掩码**：先匹配长别名，命中后把该区段从工作文本中挖空，避免短别名重复命中同一处。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_BOUNDARY_LEFT = r"(?<![A-Za-z0-9+#])"
_BOUNDARY_RIGHT = r"(?![A-Za-z0-9+#])"


@dataclass(frozen=True)
class SkillRule:
    canonical: str
    category: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class LexMatch:
    """文本中的一次技能命中。"""

    canonical: str
    category: str
    alias: str


def _compile(alias: str) -> re.Pattern[str]:
    return re.compile(_BOUNDARY_LEFT + re.escape(alias) + _BOUNDARY_RIGHT, re.IGNORECASE)


class SkillLexicon:
    def __init__(self, rules: list[SkillRule]) -> None:
        self.rules = rules
        # 精确别名 → 规则（用于用户输入的归一化）
        self._by_alias: dict[str, SkillRule] = {}
        for rule in rules:
            for alias in rule.aliases:
                self._by_alias.setdefault(_normalize_key(alias), rule)
        # 长别名优先，避免短别名抢占
        self._ordered: list[tuple[re.Pattern[str], SkillRule, str]] = []
        for rule in rules:
            for alias in rule.aliases:
                self._ordered.append((_compile(alias), rule, alias))
        self._ordered.sort(key=lambda item: len(item[2]), reverse=True)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path) -> "SkillLexicon":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rules: list[SkillRule] = []
        for entry in payload.get("skills", []):
            canonical = (entry.get("canonical") or "").strip()
            if not canonical:
                continue
            aliases = [a.strip() for a in entry.get("aliases", []) if a and a.strip()]
            # canonical 本身也是自己的别名，保证「用户直接输入规范名」能命中
            if canonical not in aliases:
                aliases.append(canonical)
            rules.append(
                SkillRule(
                    canonical=canonical,
                    category=(entry.get("category") or "其他").strip(),
                    aliases=tuple(aliases),
                )
            )
        return cls(rules)

    # ---- 用户输入归一化 ----
    def lookup(self, raw_name: str) -> SkillRule | None:
        """按别名精确查找（忽略大小写与空格）。"""
        return self._by_alias.get(_normalize_key(raw_name))

    def category_of(self, canonical: str) -> str:
        for rule in self.rules:
            if rule.canonical == canonical:
                return rule.category
        return "其他"

    # ---- 文本扫描 ----
    def find_in_text(self, text: str) -> list[LexMatch]:
        """返回文本中出现过的技能（每个技能最多一次）。"""
        if not text:
            return []
        working = text
        hits: list[LexMatch] = []
        seen: set[str] = set()

        for pattern, rule, alias in self._ordered:
            if rule.canonical in seen:
                continue
            found = pattern.search(working)
            if not found:
                continue
            seen.add(rule.canonical)
            hits.append(LexMatch(canonical=rule.canonical, category=rule.category, alias=alias))
            # 掩码：保留长度与偏移，确保后续匹配不会重复命中同一区段
            start, end = found.span()
            working = working[:start] + " " * (end - start) + working[end:]
        return hits


def _normalize_key(text: str) -> str:
    """归一化查找键：小写、去空白、去全角空格。"""
    return re.sub(r"\s+", "", (text or "").strip().lower().replace("\u3000", ""))
