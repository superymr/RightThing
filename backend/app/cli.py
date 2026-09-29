"""命令行入口。

M1 的交付标准就是这一段能跑：
    python -m app.cli analyze --skills "数据分析,Python,ROS,Linux,C++"

不依赖任何第三方库，clone 下来即可运行。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import report as report_module
from .config import PROJECT_DIR, Settings
from .services.orchestrator import AnalyzeOptions, Orchestrator
from .sources import SampleSource

DEFAULT_SKILLS = "数据分析,Python,ROS,Linux,C++"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rightthing",
        description="RightThing 正事 —— 从真实岗位看职业方向与技能缺口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            f'  python -m app.cli analyze --skills "数据分析,Python,SQL"\n'
            f'  python -m app.cli analyze --skills "ROS,C++,Linux" --direction 机器人\n'
            f"  python -m app.cli analyze --jd-file my_jd.txt\n"
            f"  python -m app.cli doctor\n"
            f"  python -m app.cli serve --port 8000\n"
            f"  python -m app.cli directions\n"
        ),
    )
    parser.add_argument("--version", action="version", version="RightThing 正事 0.1.0")

    sub = parser.add_subparsers(dest="command")

    analyze = sub.add_parser("analyze", help="执行一次完整分析")
    _add_analyze_args(analyze)

    sub.add_parser("directions", help="列出内置样例数据覆盖的岗位方向")

    doctor = sub.add_parser("doctor", help="环境自检：配置 / 连通性 / 抽取质量对比")
    doctor.add_argument(
        "--job-id",
        default="",
        help="指定用于对比的样例 JD id（默认取长度中位数的那条，避免极端样本）",
    )

    serve = sub.add_parser("serve", help="启动 HTTP 服务（M2 的 API 层）")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true", help="代码变更自动重载（开发用）")

    alias = sub.add_parser(
        "alias",
        help="技能别名表维护：查看系统学到的自由文本，并提升进词表",
        description=(
            "运行时遇到词表没见过的技能，normalizer 会把它登记为 learned，"
            "但那只进数据库、不进词表 —— 所以下次还是不认识它。\n"
            "本命令用来把这个断层补上：把 learned 条目提升为 manual 并写回 "
            "data/skill_alias.json（词表的单一事实来源）。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    alias_sub = alias.add_subparsers(dest="alias_command")

    alias_list = alias_sub.add_parser("list", help="列出别名（默认只看 learned）")
    alias_list.add_argument(
        "--source",
        default="learned",
        choices=["learned", "manual", "llm", "all"],
        help="按来源过滤，默认 learned（这些才是待归并的）",
    )
    alias_list.add_argument("--min-jobs", type=int, default=0, help="只看至少被 N 条 JD 抽到过的")
    alias_list.add_argument("--limit", type=int, default=40)

    alias_promote = alias_sub.add_parser("promote", help="把一个别名归到某个规范名下")
    alias_promote.add_argument("alias", help="要提升的别名（通常是 learned 里的自由文本）")
    alias_promote.add_argument("--to", required=True, help="目标规范名")
    alias_promote.add_argument(
        "--category",
        default="",
        help="目标规范名不存在时，用它指定技能族（如「机器人/感知」），否则会落到「其他」",
    )
    alias_promote.add_argument("--dry-run", action="store_true", help="只预览，不写文件")

    alias_merge = alias_sub.add_parser("merge", help="把一个规范名整个合并进另一个")
    alias_merge.add_argument("source", help="被合并掉的规范名")
    alias_merge.add_argument("--into", required=True, help="保留的规范名")
    alias_merge.add_argument("--dry-run", action="store_true", help="只预览，不写文件")

    report = sub.add_parser("report", help="把某次历史分析导出成 Markdown")
    report.add_argument("session_id", type=int, help="会话 id（用 alias 无关，见 `sessions` 列表）")
    report.add_argument("--out", default="", help="输出文件路径；留空则打印到终端")
    report.add_argument("--top", type=int, default=20, help="排行榜展示前几名（默认 20）")

    # 兼容直接写参数（不带子命令）的用法
    _add_analyze_args(parser)
    return parser


def _add_analyze_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--skills",
        "-s",
        default=None,
        help=f'逗号分隔的技能列表，如 "数据分析,Python,ROS"。默认：{DEFAULT_SKILLS}',
    )
    parser.add_argument("--city", default="", help="城市过滤（样例数据支持）")
    parser.add_argument("--direction", default="", help="只分析匹配该关键词的方向")
    parser.add_argument(
        "--max-directions", type=int, default=2, help="最多分析几个岗位方向（默认 2）"
    )
    parser.add_argument(
        "--limit", type=int, default=15, help="每个方向最多采集多少条 JD（默认 15）"
    )
    parser.add_argument("--top", type=int, default=15, help="每个排行榜展示前几名（默认 15）")
    parser.add_argument(
        "--jd-file",
        action="append",
        default=[],
        help="分析手动粘贴的 JD 文本文件（可重复指定；多条 JD 用 '=== JOB ===' 分隔）",
    )
    parser.add_argument(
        "--provider",
        choices=["mock", "openai"],
        default=None,
        help="覆盖 .env 中的 LLM_PROVIDER",
    )
    parser.add_argument("--no-cache", action="store_true", help="本次运行禁用 LLM 结果缓存")
    parser.add_argument("--json", dest="json_path", default="", help="把完整结果导出为 JSON")
    parser.add_argument("--quiet", action="store_true", help="只输出 JSON（配合 --json 使用）")


def _configure_stdio() -> None:
    """保证中文在 Windows 终端不乱码。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()

    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] not in (
        "analyze",
        "directions",
        "doctor",
        "serve",
        "alias",
        "report",
        "-h",
        "--help",
        "--version",
    ):
        argv.insert(0, "analyze")

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "directions":
        return _cmd_directions()
    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "alias":
        return _cmd_alias(args)
    if args.command == "report":
        return _cmd_report(args)
    if args.command == "doctor":
        from .doctor import run_doctor

        return run_doctor(Settings.load(), job_id=args.job_id)
    if args.command != "analyze":
        parser.print_help()
        return 0

    settings = Settings.load()
    if args.provider:
        settings.llm_provider = args.provider
    if args.no_cache:
        settings.cache_enabled = False

    if settings.llm_provider == "openai" and not settings.llm_api_key:
        env_file = PROJECT_DIR / ".env"
        print(
            "[!] LLM_PROVIDER=openai 但未配置 LLM_API_KEY。\n"
            f"    请打开 {env_file}，把 LLM_API_KEY= 这一行填上。\n"
            "    填写后可运行 `python -m app.cli doctor` 自检；\n"
            "    想先用离线模式：加 --provider mock。",
            file=sys.stderr,
        )
        return 2

    raw_skills = args.skills if args.skills is not None else DEFAULT_SKILLS
    skills = [s.strip() for s in raw_skills.replace("，", ",").split(",") if s.strip()]

    jd_files = [Path(p) for p in (args.jd_file or [])]
    missing = [p for p in jd_files if not p.is_file()]
    if missing:
        print(f"[!] JD 文件不存在：{', '.join(str(p) for p in missing)}", file=sys.stderr)
        return 2

    options = AnalyzeOptions(
        skills=skills,
        city=args.city,
        max_directions=args.max_directions,
        limit_per_direction=args.limit,
        direction_filter=args.direction,
        jd_files=jd_files,
    )

    print(f"[*] 抽取后端：{settings.describe()}")
    print(f"[*] 正在分析：{'、'.join(skills) if skills else '(来自 JD 文件)'}")

    orchestrator = Orchestrator(settings)
    try:
        result = orchestrator.analyze(options)
    except NotImplementedError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI 边界，需要给出可读错误而不是堆栈
        print(f"[!] 分析失败：{exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        print()
        print(report_module.render(result, top=args.top))

    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report_module.to_json(result), encoding="utf-8")
        print(f"\n[*] 完整结果已导出：{path}")

    return 0


def _cmd_serve(args) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "[!] 未安装 API 依赖。请执行：pip install -e \".[api]\"",
            file=sys.stderr,
        )
        return 2

    from .api import create_app
    from .api.static import DEFAULT_DIST_DIR

    app = create_app()
    if (DEFAULT_DIST_DIR / "index.html").is_file():
        print(f"[*] 可视化看板： http://{args.host}:{args.port}/")
    else:
        print(
            "[*] 前端未构建（当前只有 API 与 /docs）。\n"
            "    要用看板：cd frontend && npm install && npm run build，然后重启本服务。\n"
            "    开发模式：cd frontend && npm run dev（Vite 会把 /api 代理到本服务）。"
        )
    print(f"[*] 接口文档： http://{args.host}:{args.port}/docs")
    print(f"[*] 健康检查： http://{args.host}:{args.port}/api/health")
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
    return 0


def _cmd_directions() -> int:
    settings = Settings.load()
    source = SampleSource(settings.sample_dir)
    directions = source.directions()
    print(f"内置样例数据目录：{settings.sample_dir}")
    if not directions:
        print("（未找到样例数据）")
        return 1
    print(f"共 {len(directions)} 个方向，{len(source.all_jobs())} 条 JD：")
    for direction in directions:
        print(f"  · {direction}")
    return 0


# ----------------------------------------------------------------------
def _cmd_alias(args) -> int:
    """别名表维护。业务逻辑在 services/aliases.py，这里只负责展示与退出码。"""
    from .models.db import Database
    from .services import aliases as alias_service

    settings = Settings.load()
    db = Database(settings.db_path)
    db.init_schema()

    action = getattr(args, "alias_command", None)
    if action == "list":
        return _alias_list(alias_service, db, args)
    if action is None:
        print("用法：python -m app.cli alias {list|promote|merge} ...\n")
        print("  list     查看系统学到、但还没进词表的技能")
        print("  promote  把一个别名归到某个规范名下（写回词表）")
        print("  merge    把一个规范名整个合并进另一个")
        return 0

    try:
        if action == "promote":
            before = settings.cache_namespace
            result = alias_service.promote(
                db,
                args.alias,
                args.to,
                alias_path=settings.alias_path,
                category=args.category,
                dry_run=args.dry_run,
            )
            for line in result.describe():
                print(line)
            if result.changed and not args.dry_run:
                _print_cache_notice(before)
        elif action == "merge":
            before = settings.cache_namespace
            result = alias_service.merge(
                db,
                args.source,
                args.into,
                alias_path=settings.alias_path,
                dry_run=args.dry_run,
            )
            for line in result.describe():
                print(line)
            if result.changed and not args.dry_run:
                _print_cache_notice(before)
    except alias_service.AliasError as exc:
        print(f"[!] {exc}", file=sys.stderr)
        return 2
    return 0


def _print_cache_notice(before: str) -> None:
    """词表指纹变了，旧缓存会自动失效 —— 说清楚，省掉一次「怎么结果没变」的排查。"""
    if Settings.load().cache_namespace != before:
        print("\n[*] 词表指纹已变化，旧的分析缓存会自动失效（下次分析会重新调用模型）。")


def _cmd_report(args) -> int:
    """把某次历史分析导出成 Markdown。

    数据来源与看板完全一致（`dashboard.load_session`），所以导出的内容
    永远和网页上看到的一致 —— 这是「同一个真相」而不是「两套渲染」。
    """
    from .models.db import Database
    from .services import dashboard, export

    settings = Settings.load()
    db = Database(settings.db_path)
    db.init_schema()

    payload = dashboard.load_session(db, args.session_id)
    if payload is None:
        print(f"[!] 会话 {args.session_id} 不存在。", file=sys.stderr)
        print("    历史会话 id 可在看板的「历史分析」页查看。", file=sys.stderr)
        return 2

    markdown = export.render_markdown(payload, top=args.top)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
        print(f"[*] 报告已导出：{path}")
        print(f"    {len(markdown)} 字符，{len(markdown.splitlines())} 行")
    else:
        print(markdown)
    return 0


def _alias_list(alias_service, db, args) -> int:
    # 复用 report 的显示宽度工具：中文在终端占 2 列，用 str.ljust 会让竖线歪掉
    from .report import _pad

    rows = alias_service.list_aliases(
        db, source=args.source, min_jobs=args.min_jobs, limit=args.limit
    )
    if not rows:
        if args.source == "learned":
            print("没有待归并的 learned 条目 —— 词表已经覆盖了目前见过的所有说法。")
        else:
            print(f"没有 source={args.source} 的别名记录。")
        return 0

    header = f"{_pad('别名', 30)}{_pad('规范名', 24)}{_pad('来源', 10)}{_pad('JD 数', 8, 'right')}"
    print(header)
    print("-" * 72)
    for row in rows:
        print(
            f"{_pad(row.alias, 30)}{_pad(row.canonical, 24)}"
            f"{_pad(row.source, 10)}{_pad(str(row.jobs), 8, 'right')}"
        )

    if args.source == "learned":
        print()
        print("这些是系统见过、但还没进词表的说法：条条都算作独立技能，会稀释排行榜。")
        print(f"归并它们（--dry-run 只预览，不写文件）：")
        print(f'  python -m app.cli alias promote "{rows[0].alias}" --to 你想要的规范名 --dry-run')
        print("确认无误后去掉 --dry-run 写回词表。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
