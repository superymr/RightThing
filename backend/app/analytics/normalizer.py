"""技能归一化。

用户输入是自由的（"数据分析"、"python编程"、"熟练使用ROS"），
但统计必须建立在**规范名**之上，否则 "python3" 和 "Python" 会被算成两项。

三级策略：
1. 规则清洗：剥离"熟练使用""掌握"等修饰语；
2. 查别名表：命中即返回规范名（覆盖 90% 情况）；
3. 未命中：保留原词作为规范名，并写入 skill_alias 表（source=learned），
   使系统随着使用逐渐积累词表 —— 人工维护成本随时间下降。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models.db import Database
from .lexicon import SkillLexicon

# 需要剥离的前缀/后缀修饰语
_PREFIX_PATTERNS = [
    r"^熟练(使用|掌握|运用)?",
    r"^熟悉",
    r"^掌握",
    r"^精通",
    r"^了解",
    r"^具备",
    r"^有",
    r"^良好的",
    r"^较强的",
    r"^一定的",
]
_SUFFIX_PATTERNS = [
    r"(编程|开发)?(能力|经验|技能)$",
    r"编程$",
    r"开发$",
    r"相关$",
]

_PREFIX_RE = re.compile("|".join(_PREFIX_PATTERNS))
_SUFFIX_RE = re.compile("|".join(_SUFFIX_PATTERNS))


@dataclass
class NormalizedSkill:
    raw: str
    canonical: str
    category: str
    known: bool  # True = 命中词表；False = 系统没见过，已登记


def clean(raw: str) -> str:
    """剥离修饰语与首尾标点。"""
    text = (raw or "").strip().strip("、,，;；。. \t")
    text = _PREFIX_RE.sub("", text).strip()
    text = _SUFFIX_RE.sub("", text).strip()
    return text or (raw or "").strip()


class Normalizer:
    def __init__(self, lexicon: SkillLexicon, db: Database | None = None) -> None:
        self.lexicon = lexicon
        self.db = db
        self._learned: dict[str, NormalizedSkill] = {}
        if db is not None:
            self._load_learned()

    def _load_learned(self) -> None:
        assert self.db is not None
        for row in self.db.query("SELECT canonical, alias FROM skill_alias WHERE source = 'learned'"):
            self._learned[_key(row["alias"])] = NormalizedSkill(
                raw=row["alias"],
                canonical=row["canonical"],
                category=self.lexicon.category_of(row["canonical"]),
                known=True,
            )

    # ------------------------------------------------------------------
    def normalize_one(self, raw: str, *, persist: bool = True) -> NormalizedSkill:
        cleaned = clean(raw)

        rule = self.lexicon.lookup(cleaned)
        if rule is not None:
            return NormalizedSkill(cleaned, rule.canonical, rule.category, known=True)

        learned = self._learned.get(_key(cleaned))
        if learned is not None:
            return NormalizedSkill(cleaned, learned.canonical, learned.category, known=True)

        # 没见过的词：以自身为规范名登记，后续可人工合并（"数据分析" → "数据分析"）
        result = NormalizedSkill(cleaned, cleaned, "其他", known=False)
        self._learned[_key(cleaned)] = result
        if persist and self.db is not None:
            self._persist(cleaned, cleaned)
        return result

    def normalize_many(self, raws: list[str], *, persist: bool = True) -> list[NormalizedSkill]:
        out: list[NormalizedSkill] = []
        seen: set[str] = set()
        for raw in raws:
            if not raw or not raw.strip():
                continue
            item = self.normalize_one(raw, persist=persist)
            if item.canonical in seen:
                continue
            seen.add(item.canonical)
            out.append(item)
        return out

    # ------------------------------------------------------------------
    def normalize_item_names(self, raw: str, *, persist: bool = True) -> list[NormalizedSkill]:
        """把一个（可能来自大模型的）技能名收敛为**一个或多个**规范名。

        精确别名查找对自由文本远远不够。真模型会给出：

        - 带修饰的名：`PID控制算法`、`团队协作意识`、`Gazebo等仿真环境`
        - 复合名：    `嵌入式开发与单片机移植`

        若只做精确匹配，这些会全部落空并各记一项 —— 一次分析能抽出 97 个
        「不同」技能，排行榜彻底失效。因此增加包含匹配作为兜底：

        - 命中一个 → 替换（`PID控制算法` → `PID控制`）
        - 命中多个 → **拆分**（`嵌入式开发与单片机移植` → `嵌入式开发` + `单片机`）

        拆分是正确语义：那句话本来就要求两项技能。
        """
        if not raw or not raw.strip():
            return []

        rule = self.lexicon.lookup(clean(raw))
        if rule is not None:
            return [NormalizedSkill(clean(raw), rule.canonical, rule.category, known=True)]

        matches = self.lexicon.find_in_text(raw)
        if matches:
            return [
                NormalizedSkill(raw=raw, canonical=m.canonical, category=m.category, known=True)
                for m in matches
            ]

        return [self.normalize_one(raw, persist=persist)]

    def _persist(self, canonical: str, alias: str) -> None:
        assert self.db is not None
        from ..utils.timeutil import now_iso

        self.db.execute(
            "INSERT OR IGNORE INTO skill_alias (canonical, alias, source, created_at) "
            "VALUES (?, ?, 'learned', ?)",
            (canonical, alias, now_iso()),
        )


def _key(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())
