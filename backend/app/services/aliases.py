"""技能别名表的人工闭环。

**为什么需要这个模块**：运行时遇到词表没见过的技能时，`normalizer` 会把它
以「自身为规范名」登记进 SQLite（`source=learned`），这是系统越用越准的基础。
但这些 `learned` 条目**只躺在数据库里**，而真正被 `SkillLexicon` 读取的词表是
`data/skill_alias.json`。于是出现一个尴尬的断层：

    模型抽出「PID控制算法」→ 登记为 learned → **下次分析照样不认识它**

因为它从来没进过词表。加上真模型的抽取粒度远细于规则引擎（一次分析能出 97 个
「不同」技能），这个断层不补，长尾只会越积越多。

本模块补的就是这一环：把 learned 里的条目**提升为 manual 并写回 json**。

三个设计决定：

**1. 写入的是 `skill_alias.json`，不是数据库。**
json 是词表的单一事实来源（`SkillLexicon` 只读它）。只写数据库等于改了影子副本，
下次启动就丢了。

**2. 序列化自己写，不用 `json.dumps(indent=2)`。**
原文件是「一行一个技能」的手工可编辑格式。用通用缩进重排会把整份文件打散，
之后每一次真实改动都会淹没在几千行格式 diff 里 —— 词表是要人来维护的，
可读性就是它的可用性。

**3. 改完 json，缓存自动失效。**
`Settings.cache_namespace` 里带了词表的 sha256 指纹。所以提升别名之后，
旧的分析缓存会自然失效、不会出现「我明明改了词表，结果怎么没变」的幽灵问题。
这不是本模块实现的，但它是这条链路能安全使用的前提，测试里会把它钉住。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models.db import Database
from ..utils.timeutil import now_iso

# 一句话说明为什么需要这些 SQL：所有 SQL 只允许出现在 models/ 与 services/
# （PLAN.md 第 3 节），本模块属于 services/，所以它是合法的落点。


class AliasError(Exception):
    """用户可读的别名操作错误（CLI 直接打印 message）。"""


def _key(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower().replace("\u3000", ""))


# ----------------------------------------------------------------------
# 词表文件读写
# ----------------------------------------------------------------------
def load_skill_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AliasError(f"词表文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise AliasError(f"词表文件不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(payload, dict):
        raise AliasError(f"词表文件结构异常，顶层应为对象：{path}")
    return payload


def _compact_object(entry: dict[str, Any]) -> str:
    """把一条技能渲染成 `{ "k": v, ... }` 的单行形式。

    不写死字段名，而是遍历 entry 的键 —— 以后给词表加了新字段（比如
    `notes`、`introduced_in`），这里也不会把它静默丢掉。
    """
    pairs = ", ".join(
        f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}"
        for key, value in entry.items()
    )
    return "{ " + pairs + " }"


def dump_skill_file(payload: dict[str, Any]) -> str:
    """按「一行一个技能、按类别分组」的紧凑风格序列化。

    这两个排版约定不是装饰，是从现有词表里读出来的**既有格式**：
    技能一行一条便于手工增删；类别之间空一行便于扫读。用通用 `indent=2`
    重排会把整份文件打散，之后每一次真实改动都会淹没在几千行格式 diff 里 ——
    词表是要人来维护的，可读性就是它的可用性。

    只对已知的 `categories` / `skills` 做专门排版，其他键回落到通用缩进 ——
    万一以后加了新字段，也不会因为格式化器不认识它就把它写坏。
    """
    lines: list[str] = ["{"]
    keys = list(payload.keys())
    for index, key in enumerate(keys):
        value = payload[key]
        comma = "," if index < len(keys) - 1 else ""
        if key == "categories" and isinstance(value, list):
            lines.append('  "categories": [')
            for i, item in enumerate(value):
                tail = "," if i < len(value) - 1 else ""
                lines.append(f"    {json.dumps(item, ensure_ascii=False)}{tail}")
            lines.append(f"  ]{comma}")
        elif key == "skills" and isinstance(value, list):
            lines.append('  "skills": [')
            previous_category: Any = None
            for i, entry in enumerate(value):
                category = entry.get("category") if isinstance(entry, dict) else None
                # 类别切换处留一个空行：这是原文件的排版约定
                if previous_category is not None and category != previous_category:
                    lines.append("")
                previous_category = category
                tail = "," if i < len(value) - 1 else ""
                rendered = _compact_object(entry) if isinstance(entry, dict) else json.dumps(
                    entry, ensure_ascii=False
                )
                lines.append(f"    {rendered}{tail}")
            lines.append(f"  ]{comma}")
        else:
            rendered = json.dumps(value, ensure_ascii=False, indent=2)
            indented = "\n".join("  " + line for line in rendered.splitlines())
            lines.append(f'  "{key}": {indented.lstrip()}{comma}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def save_skill_file(path: Path, payload: dict[str, Any]) -> None:
    Path(path).write_text(dump_skill_file(payload), encoding="utf-8")


def find_entry(payload: dict[str, Any], canonical: str) -> dict[str, Any] | None:
    for entry in payload.get("skills", []):
        if _key(entry.get("canonical", "")) == _key(canonical):
            return entry
    return None


# ----------------------------------------------------------------------
# 查询
# ----------------------------------------------------------------------
@dataclass
class AliasRow:
    alias: str
    canonical: str
    source: str
    created_at: str
    jobs: int = 0  # 有多少条 JD 抽到过它

    @property
    def in_lexicon(self) -> bool:
        """是否已经进了词表 —— learned 条目的价值全看这个字段。

        `skill_alias` 表里 `alias == canonical` 的 learned 行就是「系统见过但
        还没归并」的自由文本；它们**不在** json 里，所以每次分析都还是各自算一项。
        """
        return self.source != "learned"


def usage_counts(db: Database) -> dict[str, int]:
    """每个规范名被多少条**不同**的 JD 抽到过。

    用 `COUNT(DISTINCT raw_job_id)` 而不是 `COUNT(*)`：同一条 JD 里重复提及
    不该被算成多次 —— 那正是覆盖率口径要消除的东西。
    """
    rows = db.query(
        "SELECT skill_canonical AS name, COUNT(DISTINCT raw_job_id) AS jobs "
        "FROM jd_skill GROUP BY skill_canonical"
    )
    return {_key(row["name"]): int(row["jobs"] or 0) for row in rows}


def list_aliases(
    db: Database,
    *,
    source: str = "",
    min_jobs: int = 0,
    limit: int = 0,
) -> list[AliasRow]:
    sql = "SELECT canonical, alias, source, created_at FROM skill_alias"
    params: list[Any] = []
    if source and source != "all":
        sql += " WHERE source = ?"
        params.append(source)
    sql += " ORDER BY canonical, alias"

    usage = usage_counts(db)
    rows = [
        AliasRow(
            alias=row["alias"],
            canonical=row["canonical"],
            source=row["source"],
            created_at=row["created_at"],
            jobs=usage.get(_key(row["alias"]), usage.get(_key(row["canonical"]), 0)),
        )
        for row in db.query(sql, tuple(params))
    ]
    if min_jobs:
        rows = [row for row in rows if row.jobs >= min_jobs]
    # 出现得多的排前面：这些才是真正值得花时间去归并的
    rows.sort(key=lambda row: (-row.jobs, row.canonical, row.alias))
    return rows[:limit] if limit else rows


# ----------------------------------------------------------------------
# 写入
# ----------------------------------------------------------------------
@dataclass
class PromoteResult:
    alias: str
    canonical: str
    created_entry: bool = False
    added_alias: bool = False
    removed_from: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def changed(self) -> bool:
        return self.created_entry or self.added_alias or bool(self.removed_from)

    def describe(self) -> list[str]:
        lines = [f"别名 “{self.alias}” → 规范名 “{self.canonical}”"]
        if self.created_entry:
            lines.append(f"  · 词表中新建了规范名条目 “{self.canonical}”")
        if self.added_alias:
            lines.append("  · 已加入该规范名的别名列表")
        for other in self.removed_from:
            lines.append(f"  · 已从 “{other}” 的别名列表中移除（避免一处别名指向两个规范名）")
        if not self.changed:
            lines.append("  · 词表已经是这个状态，无需改动")
        if self.dry_run and self.changed:
            lines.append("  · --dry-run：以上改动未写入")
        return lines


def promote(
    db: Database,
    alias: str,
    canonical: str,
    *,
    alias_path: Path,
    category: str = "",
    dry_run: bool = False,
) -> PromoteResult:
    """把一个别名归到指定规范名下，并写回词表文件。"""
    alias = (alias or "").strip()
    canonical = (canonical or "").strip()
    if not alias or not canonical:
        raise AliasError("别名与规范名都不能为空")
    # 只挡「字面完全相同」这一种真正的空操作。
    #
    # 刻意**不**用 `_key()` 比较：`ros2` → 新规范名 `ROS2` 只差大小写，
    # 但它是一个有意义的操作 —— 把 ros2 从「ROS」名下拆出来独立成项。
    # 用大小写无关比较会把这种合法操作误判成空操作（这是实际踩过的坑）。
    if alias == canonical:
        raise AliasError(f"“{alias}” 与目标规范名完全相同，无需提升")

    payload = load_skill_file(alias_path)
    entries: list[dict[str, Any]] = payload.setdefault("skills", [])
    if not isinstance(entries, list):
        raise AliasError("词表文件的 skills 字段不是列表")

    target = find_entry(payload, canonical)
    result = PromoteResult(alias=alias, canonical=canonical, dry_run=dry_run)
    if target is None:
        # 词表里没有这个规范名：新建。分类必须显式给，否则新条目会因为
        # category="其他" 而落到 hard_skills 桶里，影响排行榜分组。
        target = {"canonical": canonical, "category": (category or "其他").strip(), "aliases": []}
        entries.append(target)
        result.created_entry = True
    elif category and _key(target.get("category", "")) != _key(category):
        target["category"] = category.strip()

    # 先从其他条目里摘掉同一个别名，否则同一个别名会同时指向两个规范名，
    # 命中哪一个取决于加载顺序 —— 那就是一个会随机给出不同统计结果的 bug。
    for entry in entries:
        if entry is target:
            continue
        aliases = entry.get("aliases") or []
        kept = [item for item in aliases if _key(item) != _key(alias)]
        if len(kept) != len(aliases):
            entry["aliases"] = kept
            result.removed_from.append(str(entry.get("canonical", "")))

    aliases = target.setdefault("aliases", [])
    if not any(_key(item) == _key(alias) for item in aliases):
        aliases.append(alias)
        result.added_alias = True

    if result.changed and not dry_run:
        save_skill_file(alias_path, payload)
        _sync_db(db, alias, canonical)
    return result


@dataclass
class MergeResult:
    source: str
    target: str
    moved_aliases: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.moved_aliases)

    def describe(self) -> list[str]:
        lines = [f"规范名 “{self.source}” 合并进 “{self.target}”"]
        if self.moved_aliases:
            lines.append(f"  · 转移 {len(self.moved_aliases)} 个别名：{'、'.join(self.moved_aliases)}")
        else:
            lines.append("  · 没有可转移的别名")
        if self.dry_run and self.changed:
            lines.append("  · --dry-run：以上改动未写入")
        return lines


def merge(
    db: Database,
    source_canonical: str,
    target_canonical: str,
    *,
    alias_path: Path,
    dry_run: bool = False,
) -> MergeResult:
    """把一整个规范名合并到另一个：别名全部转移，原条目删除。

    典型场景：模型把同一件事抽成了两种说法（「机器人操作系统」与「ROS」），
    两者各自成项，排行榜被稀释。
    """
    source_canonical = (source_canonical or "").strip()
    target_canonical = (target_canonical or "").strip()
    if not source_canonical or not target_canonical:
        raise AliasError("源规范名与目标规范名都不能为空")
    if _key(source_canonical) == _key(target_canonical):
        raise AliasError("源与目标是同一个规范名")

    payload = load_skill_file(alias_path)
    entries: list[dict[str, Any]] = payload.get("skills", [])
    source_entry = find_entry(payload, source_canonical)
    if source_entry is None:
        raise AliasError(f"词表里找不到规范名 “{source_canonical}”")

    target_entry = find_entry(payload, target_canonical)
    if target_entry is None:
        raise AliasError(
            f"词表里找不到目标规范名 “{target_canonical}”。"
            "请先 promote 一个别名把它建出来，或检查拼写"
        )

    moved = [source_canonical, *(source_entry.get("aliases") or [])]
    result = MergeResult(source=source_canonical, target=target_canonical, dry_run=dry_run)

    deduped: list[str] = []
    seen = {_key(item) for item in (target_entry.get("aliases") or [])}
    seen.add(_key(target_canonical))
    for item in moved:
        key = _key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    result.moved_aliases = deduped
    if deduped:
        target_entry.setdefault("aliases", []).extend(deduped)

    if not dry_run:
        payload["skills"] = [entry for entry in entries if entry is not source_entry]
        save_skill_file(alias_path, payload)
        if deduped:
            _sync_db_many(db, [(target_canonical, item) for item in deduped])
        # 旧的 learned 行指向已经不存在的规范名，留着会污染 alias list
        db.execute(
            "DELETE FROM skill_alias WHERE source != 'manual' AND lower(canonical) = lower(?)",
            (source_canonical,),
        )
    return result


def _sync_db(db: Database, alias: str, canonical: str) -> None:
    _sync_db_many(db, [(canonical, alias)])


def _sync_db_many(db: Database, pairs: list[tuple[str, str]]) -> None:
    """把提升结果同步回 SQLite。

    先删掉指向别处的 learned 行，再写 manual 行 —— 否则 `alias list` 会同时
    显示「某别名 → 它自己」和「某别名 → 真正的规范名」两条互相矛盾记录。
    """
    for canonical, alias in pairs:
        db.execute(
            "DELETE FROM skill_alias WHERE source != 'manual' AND lower(alias) = lower(?)",
            (alias,),
        )
        db.execute(
            "INSERT OR IGNORE INTO skill_alias (canonical, alias, source, created_at) "
            "VALUES (?, ?, 'manual', ?)",
            (canonical, alias, now_iso()),
        )
