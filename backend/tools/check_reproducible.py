"""可复现性校验工具。

用法：
    python tools/check_reproducible.py "数据分析,Python,SQL"          # 强制 mock 基线
    python tools/check_reproducible.py "数据分析,Python,SQL" --real    # 用 .env 里配置的真实模型

作用：连续跑两次完整分析，比较**除时间/会话号之外**的所有结果是否逐字节一致，
并确认第二次运行全部命中缓存。

这是产品级的硬约束：分析类工具如果同一个输入给出两个答案，用户会立刻失去信任。
CI 里应当把它作为一道门禁（改动聚合逻辑或 Prompt 后必须仍然通过）。

默认强制 mock，是因为它作为**回归基线**必须不依赖网络与模型漂移；
要验证真实模型的确定性（缓存是否真的生效），加 --real。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.services.orchestrator import AnalyzeOptions, Orchestrator  # noqa: E402

# 这些字段描述的是「我们怎么得到答案的」，不是「答案是什么」，
# 因此天然会在两次运行间不同，必须从一致性比较中剔除。
# 注意：剔除它们不等于忽略它们 —— 缓存命中率由下面的断言单独检查。
VOLATILE = {"duration_sec", "session_id", "cache_hits", "token_in", "token_out"}


def normalize(payload):
    """递归剔除易变字段，只留下「分析结论」本身。"""
    if isinstance(payload, dict):
        return {k: normalize(v) for k, v in payload.items() if k not in VOLATILE}
    if isinstance(payload, list):
        return [normalize(item) for item in payload]
    return payload


def first_difference(a, b, path: str = "$") -> str | None:
    """定位第一个不一致的位置，方便排查（比一句「不一致」有用得多）。"""
    if type(a) is not type(b):
        return f"{path}: 类型不同 {type(a).__name__} vs {type(b).__name__}"
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                return f"{path}.{key}: 仅第二次运行存在"
            if key not in b:
                return f"{path}.{key}: 仅第一次运行存在"
            found = first_difference(a[key], b[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: 长度不同 {len(a)} vs {len(b)}"
        for index, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, f"{path}[{index}]")
            if found:
                return found
        return None
    if a != b:
        return f"{path}: {a!r} vs {b!r}"
    return None


def run_once(settings: Settings, skills: list[str]) -> dict:
    options = AnalyzeOptions(skills=skills, max_directions=2, limit_per_direction=12)
    report = Orchestrator(settings).analyze(options)
    from app import report as report_module

    return report_module.to_dict(report)


def main(argv: list[str]) -> int:
    use_real = "--real" in argv
    positional = [a for a in argv[1:] if not a.startswith("--")]
    skills = [s.strip() for s in (positional[0] if positional else "数据分析,Python,SQL").split(",")]

    settings = Settings.load()
    if not use_real:
        # 回归基线必须与外部服务解耦
        settings.llm_provider = "mock"

    from app.llm import build_provider

    try:
        provider = build_provider(settings)
    except Exception as exc:  # noqa: BLE001 - CLI 边界
        print(f"[!] 无法构造 provider：{exc}")
        print("    加 --real 需要先在 .env 里配好 LLM_API_KEY。")
        return 2

    print(f"provider = {provider.name} / {provider.model_name}")
    print(f"database = {settings.db_path}")

    first = run_once(settings, skills)
    second = run_once(settings, skills)

    failures: list[str] = []

    for direction in second["directions"]:
        if direction["cache_hits"] != direction["total_jobs"]:
            failures.append(
                f"第二次运行未全部命中缓存：{direction['title']} "
                f"{direction['cache_hits']}/{direction['total_jobs']}"
            )
        if direction["failed_jobs"]:
            failures.append(f"{direction['title']} 有 {direction['failed_jobs']} 条解析失败")

    if normalize(first) != normalize(second):
        detail = first_difference(normalize(first), normalize(second))
        failures.append(f"两次运行的结果不一致（缓存没有保证确定性）：{detail}")

    print(
        f"方向数 = {len(second['directions'])}，"
        f"总样本 = {sum(d['total_jobs'] for d in second['directions'])}"
    )
    for direction in second["directions"]:
        top = ", ".join(s["canonical"] for s in direction["languages"][:3])
        print(
            f"  · {direction['title']}: {direction['total_jobs']} 条，"
            f"缓存命中 {direction['cache_hits']}，覆盖率 {direction['gap']['coverage_score']:.0%}，"
            f"Top 语言 [{top}]"
        )

    if failures:
        print("\n[FAIL]")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("\n[OK] 两次运行结果完全一致，且第二次全部命中缓存（结果已写入 JSON 校验通过）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
