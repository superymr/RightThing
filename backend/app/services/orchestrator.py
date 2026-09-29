"""编排服务 —— 把各层串成一条完整的分析流程。

流程（对应 PLAN.md 第 2 节）：
    归一化技能 → LLM#1 推荐方向 → 采集 JD → LLM#2 结构化抽取 → 聚合统计 → 缺口分析

本模块只做「编排」：调用谁、什么顺序、并发多少、失败了怎么办。
具体逻辑一律下沉到各层，保证这里读起来就是一份流程说明书。
"""

from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from ..analytics.aggregator import AggregateResult, aggregate
from ..analytics.canonical import (
    canonical_education,
    canonical_experience,
    canonical_majors,
)
from ..analytics.gap import GapReport, compute_gap
from ..analytics.lexicon import SkillLexicon
from ..analytics.normalizer import NormalizedSkill, Normalizer
from ..config import Settings
from ..llm import build_provider
from ..llm.base import ChatProvider, LLMError
from ..llm.extractor import Extractor, ProfileOutcome
from ..llm.schemas import Direction, JDProfile, SkillItem
from ..models.db import Database
from ..sources import JobSource, ManualPasteSource, RawJob, SampleSource, SourceError, build_sources
from ..services.cache import LLMCache
from ..utils.sanitize import sanitize_text
from ..utils.timeutil import now_iso

MANUAL_DIRECTION = "手动录入岗位"

MAINLAND_LOCATION_TERMS = (
    "中国大陆", "mainland china", "china", "中国", "北京", "上海", "天津", "重庆",
    "广东", "深圳", "广州", "东莞", "佛山", "珠海", "江苏", "南京", "苏州", "无锡",
    "浙江", "杭州", "宁波", "福建", "厦门", "福州", "山东", "青岛", "济南", "四川",
    "成都", "湖北", "武汉", "湖南", "长沙", "河南", "郑州", "河北", "安徽", "合肥",
    "陕西", "西安", "辽宁", "沈阳", "大连", "吉林", "长春", "黑龙江", "哈尔滨",
    "江西", "南昌", "广西", "南宁", "云南", "昆明", "贵州", "贵阳", "海南", "海口",
    "山西", "太原", "内蒙古", "呼和浩特", "甘肃", "兰州", "宁夏", "银川", "青海",
    "西宁", "新疆", "乌鲁木齐", "西藏", "拉萨", "全国",
)
NON_MAINLAND_TERMS = (
    "香港", "hong kong", "澳门", "macao", "macau", "台湾", "taiwan", "台北", "taipei",
)
CHINA_JOB_DOMAINS = (
    "zhipin.com", "liepin.com", "51job.com", "zhaopin.com", "lagou.com", "nowcoder.com",
    "shixiseng.com", "ncss.cn", "iguopin.com",
)


def is_mainland_job(job: RawJob) -> bool:
    """只让明确属于中国大陆的自动采集岗位进入分析。"""
    text = f"{job.city} {job.title} {job.raw_text[:3000]}".lower()
    if any(term in text for term in NON_MAINLAND_TERMS):
        return False
    if job.source == "nowcoder":
        return True
    if any(domain in job.url.lower() for domain in CHINA_JOB_DOMAINS):
        return True
    location = job.city.lower().strip()
    return any(term in location for term in MAINLAND_LOCATION_TERMS)


def sanitize_jobs(jobs: list[RawJob]) -> tuple[list[RawJob], dict[str, int]]:
    """入库与抽取之前对 JD 正文脱敏，返回 (新列表, 各类命中数)。

    **为什么必须在这么靠前的位置**：抽取用的文本与存库的文本必须是同一份。
    如果先抽取再脱敏，`evidence` 就不再是「入库原文的子串」——
    而这条不变量同时支撑着前端高亮与幻觉度量，一破两个功能同时失效。
    放在最前面，它自动成立。

    返回新列表而不是就地修改：`RawJob` 是 dataclass，但样例数据是**跨会话共享**的
    单例对象（`SampleSource` 每次 search 都返回同一批实例）。就地改会污染下一次分析，
    表现为「第一次分析有脱敏、第二次原文变了」，这种状态泄漏极难排查。
    """
    if not jobs:
        return jobs, {}

    out: list[RawJob] = []
    hits: dict[str, int] = {}
    for job in jobs:
        result = sanitize_text(job.raw_text)
        if not result.changed:
            out.append(job)
            continue
        for name, count in result.hits.items():
            hits[name] = hits.get(name, 0) + count
        out.append(replace(job, raw_text=result.text))
    return out, hits


@dataclass
class AnalyzeOptions:
    skills: list[str]
    city: str = ""
    max_directions: int = 2
    limit_per_direction: int = 35
    direction_filter: str = ""
    source_mode: str = "auto"
    job_urls: list[str] = field(default_factory=list)
    jd_files: list[Path] = field(default_factory=list)
    jd_texts: list[str] = field(default_factory=list)
    persist: bool = True


@dataclass
class DirectionReport:
    direction: Direction
    jobs: list[RawJob]
    aggregate: AggregateResult
    gap: GapReport
    failed: int = 0
    cache_hits: int = 0
    token_in: int = 0
    token_out: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.jobs)

    @property
    def ok(self) -> int:
        return self.total - self.failed


@dataclass
class AnalysisReport:
    input_skills: list[str]
    normalized: list[NormalizedSkill]
    directions: list[Direction]
    reports: list[DirectionReport]
    provider: str
    model: str
    duration_sec: float = 0.0
    session_id: int = 0

    @property
    def total_jobs(self) -> int:
        return sum(r.total for r in self.reports)


@dataclass
class ProgressEvent:
    """一次进度事件。

    存在的意义是让「长任务」可以被观察：采集 + 抽取 24 条 JD 要几十秒到几分钟，
    前端必须能显示「已解析 8/24」，否则用户只会以为程序卡死了。
    """

    stage: str  # normalize | directions | collect | extract | aggregate | done
    message: str
    current: int = 0
    total: int = 0
    direction: str = ""
    at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "message": self.message,
            "current": self.current,
            "total": self.total,
            "direction": self.direction,
            "at": self.at,
        }


ProgressCallback = Callable[[ProgressEvent], None]


def _make_emitter(on_event: ProgressCallback | None):
    """把「回调可能是 None」这件事收敛到一处，业务代码里就不用到处判空。"""

    def emit(
        stage: str, message: str, current: int = 0, total: int = 0, direction: str = ""
    ) -> None:
        if on_event is None:
            return
        on_event(
            ProgressEvent(
                stage=stage,
                message=message,
                current=current,
                total=total,
                direction=direction,
            )
        )

    return emit


@dataclass
class PreparedJob:
    """一条 JD 从采集到「可聚合」的完整中间态。

    把 job / 原始抽取结果 / 归一化后的 profile 绑在一起传递，
    避免用三个平行列表互相 zip —— 那种写法一旦某处漏筛就会静默错位。
    """

    job: RawJob
    outcome: ProfileOutcome
    profile: JDProfile
    key: str


class Orchestrator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.db_path)
        self.db.init_schema()

        self.lexicon = SkillLexicon.load(settings.alias_path)
        self.normalizer = Normalizer(self.lexicon, self.db)
        self.cache = LLMCache(self.db, enabled=settings.cache_enabled)

        self.provider: ChatProvider = build_provider(settings)
        self.extractor = Extractor(self.provider, settings, self.cache)
        self.sources = build_sources(settings)
        self.sample_source = next(
            (source for source in self.sources if isinstance(source, SampleSource)),
            SampleSource(settings.sample_dir),
        )

    # ------------------------------------------------------------------
    def analyze(
        self, options: AnalyzeOptions, on_event: ProgressCallback | None = None
    ) -> AnalysisReport:
        started = time.perf_counter()
        emit = _make_emitter(on_event)

        emit("normalize", "正在归一化输入技能")
        normalized = self.normalizer.normalize_many(options.skills)
        canonical_skills = [item.canonical for item in normalized]
        emit("normalize", f"识别出 {len(normalized)} 项技能", 1, 1)

        # 会话必须先建：raw_job 需要 session_id / direction_id 外键，
        # 否则「从数据库读回一次历史分析」就无从下手（M1 遗留的缺口）。
        session_id = self._create_session(options, normalized) if options.persist else 0

        try:
            reports, grouped = self._run_directions(options, canonical_skills, session_id, emit)
        except Exception:
            if session_id:
                self._finish_session(session_id, "failed")
            raise

        if session_id:
            self._finish_session(session_id, "done")

        report = AnalysisReport(
            input_skills=list(options.skills),
            normalized=normalized,
            directions=[direction for direction, _ in grouped],
            reports=reports,
            provider=self.provider.name,
            model=getattr(self.provider, "model_name", self.settings.extraction_model),
            duration_sec=round(time.perf_counter() - started, 2),
            session_id=session_id,
        )
        emit("done", f"分析完成，共 {report.total_jobs} 条 JD", 1, 1)
        return report

    # ------------------------------------------------------------------
    def _run_directions(
        self,
        options: AnalyzeOptions,
        canonical_skills: list[str],
        session_id: int,
        emit,
    ) -> tuple[list[DirectionReport], list[tuple[Direction, list[RawJob]]]]:
        manual_jobs = self._load_manual_jobs(options)
        manual_jobs, manual_hits = sanitize_jobs(manual_jobs)
        if manual_hits:
            emit("sanitize", f"手动录入的 JD 中已脱敏 {sum(manual_hits.values())} 处个人信息")

        if manual_jobs:
            direction = Direction(
                title=MANUAL_DIRECTION,
                match_score=1.0,
                reason="用户手动粘贴的 JD，直接分析，不经过方向推荐",
                keywords=[MANUAL_DIRECTION],
            )
            grouped = [(direction, manual_jobs)]
            emit("directions", f"使用手动录入的 {len(manual_jobs)} 条 JD", 1, 1)
        else:
            emit("directions", "正在让大模型推荐岗位方向")
            directions = self.extractor.recommend_directions(canonical_skills)
            if options.direction_filter:
                needle = options.direction_filter.strip()
                directions = [
                    d
                    for d in directions
                    if needle in d.title or any(needle in k for k in d.keywords)
                ] or directions
            directions = directions[: max(1, options.max_directions)]
            emit("directions", f"确定 {len(directions)} 个岗位方向", len(directions), len(directions))

            grouped = []
            live_deadline = time.monotonic() + max(1.0, self.settings.live_source_budget)
            for direction_index, direction in enumerate(directions):
                # 一个方向不能独占整次在线预算。动态均分剩余时间：前面的方向
                # 若提前完成，省下的时间会自动留给后面的方向。
                directions_left = max(1, len(directions) - direction_index)
                now = time.monotonic()
                remaining_budget = max(0.0, live_deadline - now)
                direction_deadline = min(
                    live_deadline,
                    now + remaining_budget / directions_left,
                )
                jobs, source_errors = self._collect(
                    direction, options, emit=emit, live_deadline=direction_deadline
                )
                for message in source_errors:
                    emit("collect", message, direction=direction.title)
                jobs, hits = sanitize_jobs(jobs)
                if hits:
                    emit(
                        "sanitize",
                        f"「{direction.title}」的 JD 中已脱敏 {sum(hits.values())} 处个人信息",
                        direction=direction.title,
                    )
                emit("collect", f"「{direction.title}」采集到 {len(jobs)} 条 JD", len(jobs), len(jobs))
                grouped.append((direction, jobs))

        reports: list[DirectionReport] = []
        for index, (direction, jobs) in enumerate(grouped, 1):
            direction_id = self._save_direction(session_id, direction) if session_id else 0
            reports.append(
                self._analyze_direction(
                    direction,
                    jobs,
                    canonical_skills,
                    session_id=session_id,
                    direction_id=direction_id,
                    emit=emit,
                    index=index,
                    count=len(grouped),
                )
            )
        return reports, grouped

    # ------------------------------------------------------------------
    def _load_manual_jobs(self, options: AnalyzeOptions) -> list[RawJob]:
        """手动录入的 JD。

        这条路径不是「降级方案」，而是**最强的合规方案**：用户自己把 JD 文本给进来，
        没有任何爬取行为，也就不存在法律风险。Web 端点 POST /api/analyze 带
        jd_texts 时走的就是这里。
        """
        if not options.jd_files and not options.jd_texts and not options.job_urls:
            return []
        source = ManualPasteSource()
        jobs = source.load_files(options.jd_files) if options.jd_files else []
        for text in options.jd_texts:
            if text and text.strip():
                jobs.append(source.add_text(text))
        if options.job_urls:
            for url in options.job_urls:
                loader = next(
                    (
                        item
                        for item in self.sources
                        if callable(getattr(item, "load_url", None))
                        and callable(getattr(item, "supports_url", None))
                        and item.supports_url(url)
                    ),
                    None,
                )
                if loader is None:
                    raise SourceError(f"没有可安全导入该 URL 的采集源：{url}")
                jobs.append(loader.load_url(url))
        return jobs

    def _collect(
        self, direction: Direction, options: AnalyzeOptions, *, emit, live_deadline: float
    ) -> tuple[list[RawJob], list[str]]:
        """按方向关键词采集，跨关键词去重，并隔离单个在线源故障。"""
        collected: list[RawJob] = []
        seen: set[str] = set()
        keywords = direction.keywords or [direction.title]
        errors: list[str] = []

        sample_sources = [source for source in self.sources if source.name == "sample"]
        live_sources = [
            source
            for source in self.sources
            if source.name != "sample" and getattr(source, "supports_discovery", True)
        ]
        mode = options.source_mode.strip().lower()
        if mode == "sample":
            groups = [sample_sources]
        elif mode == "live":
            groups = [live_sources]
        elif mode == "hybrid":
            groups = [sample_sources + live_sources]
        else:  # auto：样例能覆盖就保持确定性；完全无样例时才访问在线源
            groups = [sample_sources, live_sources]

        def collect_from(sources: list[JobSource]) -> None:
            for source_index, source in enumerate(sources):
                if len(collected) >= options.limit_per_direction:
                    return
                remaining_slots = options.limit_per_direction - len(collected)
                remaining_sources = sources[source_index:]
                mainland_names = {"ncss", "shixiseng", "nowcoder"}
                mainland_left = sum(item.name in mainland_names for item in remaining_sources)
                # 中国大陆分析优先把样本名额均分给三个国内自动源；否则海外源和
                # URL 导入器会稀释配额，导致明明有岗位却每个方向只拿到几条。
                if (
                    self.settings.target_market == "cn_mainland"
                    and source.name in mainland_names
                    and mainland_left
                ):
                    effective_sources_left = mainland_left
                else:
                    effective_sources_left = max(1, len(remaining_sources))
                source_quota = max(1, math.ceil(remaining_slots / effective_sources_left))
                source_added = 0
                now = time.monotonic()
                remaining_time = max(0.0, live_deadline - now)
                source_deadline = (
                    live_deadline
                    if source.name == "sample"
                    else min(live_deadline, now + remaining_time / effective_sources_left)
                )

                for keyword in keywords:
                    if source_added >= source_quota:
                        break
                    contextual = getattr(source, "search_with_context", None)
                    budget_expired = (
                        source.name != "sample" and time.monotonic() >= source_deadline
                    )
                    # 支持 deadline 的源会先查本地真实职位缓存，因此即使在线预算
                    # 已用完也必须调用；不支持该能力的源才在这里直接停止。
                    if budget_expired and not callable(contextual):
                        break
                    try:
                        search_city = options.city or None
                        if (
                            not search_city
                            and self.settings.target_market == "cn_mainland"
                            and source.name in {"jobicy", "arbeitnow", "greenhouse_official", "brave_search"}
                        ):
                            search_city = "China"
                        source_limit = min(
                            options.limit_per_direction - len(collected),
                            source_quota - source_added,
                        )
                        if callable(contextual):
                            jobs = contextual(
                                keyword,
                                city=search_city,
                                limit=source_limit,
                                deadline=source_deadline,
                                on_progress=lambda current, total, found: emit(
                                    "collect",
                                    f"在线索引扫描 {current}/{total}，当前命中 {found} 条",
                                    current,
                                    total,
                                    direction.title,
                                ),
                            )
                        else:
                            jobs = source.search(
                                keyword,
                                city=search_city,
                                limit=source_limit,
                            )
                    except SourceError as exc:
                        errors.append(f"在线源 {source.name} 失败，已跳过：{exc}")
                        continue
                    except Exception as exc:  # 第三方页面变化不能带垮整次分析
                        errors.append(
                            f"在线源 {source.name} 出现未预期错误，已跳过："
                            f"{type(exc).__name__}: {str(exc)[:160]}"
                        )
                        continue
                    if budget_expired and not jobs and not any(
                        "时间预算" in message for message in errors
                    ):
                        errors.append(
                            "在线预算已用完；已检索本地真实职位缓存，但当前关键词仍未命中"
                        )
                    for job in jobs:
                        if (
                            self.settings.target_market == "cn_mainland"
                            and not is_mainland_job(job)
                        ):
                            continue
                        key = (
                            job.url.split("?", 1)[0].lower()
                            if job.url
                            else f"{job.source}:{job.source_job_id}"
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        collected.append(job)
                        source_added += 1
                        if len(collected) >= options.limit_per_direction:
                            return

        for index, group in enumerate(groups):
            if not group:
                if mode == "live":
                    errors.append("在线采集未启用；请设置 JOBRADAR_ENABLE_LIVE_SOURCES=1 并重启")
                continue
            collect_from(group)
            if mode == "auto" and index == 0 and collected:
                break
        return collected, errors

    def source_health(self) -> list[dict]:
        output: list[dict] = []
        for source in self.sources:
            probe = getattr(source, "health", None)
            if callable(probe):
                output.append(probe())
            else:
                output.append(
                    {
                        "name": source.name,
                        "enabled": True,
                        "status": "ok",
                        "cached_jobs": len(source.all_jobs())
                        if isinstance(source, SampleSource)
                        else 0,
                        "last_error": "",
                    }
                )
        return output

    def _analyze_direction(
        self,
        direction: Direction,
        jobs: list[RawJob],
        my_skills: list[str],
        *,
        session_id: int = 0,
        direction_id: int = 0,
        emit=None,
        index: int = 1,
        count: int = 1,
    ) -> DirectionReport:
        label = f"[{index}/{count}] {direction.title}"
        emit = emit or (lambda *a, **k: None)

        def on_progress(done: int, total: int, job: RawJob) -> None:
            emit(
                "extract",
                f"「{direction.title}」已解析 {done}/{total}：{job.title}",
                done,
                total,
                direction.title,
            )

        emit("extract", f"{label} 开始解析 {len(jobs)} 条 JD", 0, len(jobs), direction.title)
        outcomes = self._extract_all(jobs, on_progress=on_progress if jobs else None)

        prepared: list[PreparedJob] = []
        for position, (job, outcome) in enumerate(zip(jobs, outcomes)):
            if outcome.status != "ok":
                continue
            prepared.append(
                PreparedJob(
                    job=job,
                    outcome=outcome,
                    # 归一化必须发生在聚合之前 —— 见 _canonicalize 的说明
                    profile=self._canonicalize(outcome.profile),
                    key=job.source_job_id or f"{job.source}-{position}",
                )
            )

        emit("aggregate", f"{label} 正在统计 {len(prepared)} 份结构化结果", 0, len(prepared))
        result = aggregate(
            [(item.key, item.profile) for item in prepared], direction=direction.title
        )
        gap = compute_gap(my_skills, result)

        report = DirectionReport(direction=direction, jobs=jobs, aggregate=result, gap=gap)
        for outcome in outcomes:
            if outcome.status != "ok":
                report.failed += 1
                if outcome.error:
                    report.errors.append(outcome.error)
            if outcome.cache_hit:
                report.cache_hits += 1
            report.token_in += outcome.token_in
            report.token_out += outcome.token_out

        if session_id and prepared:
            self._persist_jobs(session_id, direction_id, prepared)
        return report

    def _extract_all(self, jobs: list[RawJob], on_progress=None) -> list[ProfileOutcome]:
        """并发抽取。

        并发之所以安全，是因为抽取是**无状态**的：一条 JD 的结果不依赖其他 JD。
        并发上限同时约束着 LLM 速率与目标站点压力（对应 PLAN.md 的限流要求）。

        进度回调在主线程里按**完成顺序**触发（pool.map 按输入顺序产出），
        所以不会出现多线程同时推事件导致的乱序。
        """
        if not jobs:
            return []

        workers = max(1, min(self.settings.llm_max_concurrency, len(jobs)))

        def run(job: RawJob) -> ProfileOutcome:
            try:
                return self.extractor.extract_profile(
                    job_title=job.title, company=job.company, jd_text=job.raw_text
                )
            except LLMError as exc:  # 兜底：任何异常都不应让整批分析崩掉
                return ProfileOutcome(
                    profile=JDProfile(job_title=job.title),
                    model=getattr(self.provider, "model_name", self.settings.extraction_model),
                    status="failed",
                    error=str(exc)[:500],
                )

        results: list[ProfileOutcome] = []
        if workers == 1:
            for position, job in enumerate(jobs, 1):
                results.append(run(job))
                if on_progress:
                    on_progress(position, len(jobs), job)
            return results

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for position, outcome in enumerate(pool.map(run, jobs), 1):
                results.append(outcome)
                if on_progress:
                    on_progress(position, len(jobs), jobs[position - 1])
        return results

    # ------------------------------------------------------------------
    def _canonicalize(self, profile: JDProfile) -> JDProfile:
        """把 LLM 输出的自由文本收敛为规范值。**必须在聚合之前做。**

        ★ 这是真实模型路径下最关键的一步。

        mock 返回的技能名与学历都来自词表/正则，天生规范 —— 所以少了这一步
        在 mock 路径下完全看不出问题。但真模型返回的是：

            技能  "PID控制算法" / "团队协作意识" / "嵌入式开发与单片机移植"
            学历  "硕士及以上学历" / "本科及以上学历"
            经验  "3年以上SLAM相关研发经验"

        不收敛的话，一次分析能抽出 97 个「不同」技能（mock 路径只有 36 个），
        学历被拆成三行 —— 排行榜和缺口清单同时失效。

        顺带统一分类：模型自创的分类五花八门（script / 方法论 / 工具 / 加速计算），
        词表认识的技能一律改用词表分类。
        """

        def convert(items: list[SkillItem]) -> list[SkillItem]:
            out: list[SkillItem] = []
            for item in items:
                for normalized in self.normalizer.normalize_item_names(item.name):
                    category = (
                        normalized.category
                        if normalized.known
                        else (item.category or normalized.category)
                    )
                    out.append(replace(item, name=normalized.canonical, category=category))
            return out

        return replace(
            profile,
            education=canonical_education(profile.education),
            experience_years=canonical_experience(profile.experience_years),
            major=canonical_majors(profile.major),
            programming_languages=convert(profile.programming_languages),
            hard_skills=convert(profile.hard_skills),
            domain_knowledge=convert(profile.domain_knowledge),
            soft_skills=convert(profile.soft_skills),
        )

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------
    def _create_session(self, options: AnalyzeOptions, normalized: list[NormalizedSkill]) -> int:
        """建会话，并把**规范名**一并存下来。

        只存用户的原始输入是不够的：读回看板时要算「技能缺口」，
        而缺口分析必须用规范名做集合运算。读回时再归一化会让历史结果
        随词表演进而漂移，那就不是「读回一次分析」而是「重算一次」了。
        """
        return self.db.execute(
            "INSERT INTO analysis_session "
            "(created_at, input_skills, city, llm_provider, llm_model, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                now_iso(),
                json.dumps(
                    {
                        "raw": list(options.skills),
                        "canonical": [item.canonical for item in normalized],
                    },
                    ensure_ascii=False,
                ),
                options.city or None,
                self.provider.name,
                getattr(self.provider, "model_name", self.settings.extraction_model),
                "running",
            ),
        )

    def _finish_session(self, session_id: int, status: str) -> None:
        self.db.execute(
            "UPDATE analysis_session SET status = ? WHERE id = ?", (status, session_id)
        )

    def _save_direction(self, session_id: int, direction: Direction) -> int:
        return self.db.execute(
            "INSERT INTO job_direction "
            "(session_id, title, match_score, reason, keywords, selected) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (
                session_id,
                direction.title,
                direction.match_score,
                direction.reason,
                json.dumps(direction.keywords, ensure_ascii=False),
            ),
        )

    def _persist_jobs(
        self, session_id: int, direction_id: int, prepared: list[PreparedJob]
    ) -> None:
        """落库。

        存的是**归一化之后**的 profile：这样 `GET /api/sessions/{id}` 读回来的
        数字与当时看到的一模一样，不会因为词表后续演进就悄悄变化。
        （模型的原话仍可从 llm_cache 里按 JD 文本取回，用于排查抽取问题。）
        """
        for item in prepared:
            job = item.job
            self.db.execute(
                "INSERT OR IGNORE INTO raw_job "
                "(session_id, direction_id, source, source_job_id, url, title, company, city, "
                " raw_text, fetched_at, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    direction_id,
                    job.source,
                    job.source_job_id,
                    job.url,
                    job.title,
                    job.company,
                    job.city,
                    job.raw_text,
                    job.fetched_at,
                    job.content_hash,
                ),
            )
            row = self.db.query_one(
                "SELECT id FROM raw_job WHERE source = ? AND source_job_id = ?",
                (job.source, job.source_job_id),
            )
            if row is None:
                continue
            raw_job_id = int(row["id"])

            # 同一条 JD 可能命中多个方向；每个方向各存一份抽取结果，
            # 否则其中一个方向会读到另一个方向的 profile
            profile_id = self.db.execute(
                "INSERT INTO jd_profile "
                "(raw_job_id, session_id, direction_id, prompt_version, model, profile_json, "
                " extraction_status, token_in, token_out, cache_hit, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    raw_job_id,
                    session_id,
                    direction_id,
                    self.settings.cache_namespace,
                    item.outcome.model,
                    json.dumps(item.profile.to_dict(), ensure_ascii=False),
                    item.outcome.status,
                    item.outcome.token_in,
                    item.outcome.token_out,
                    1 if item.outcome.cache_hit else 0,
                    now_iso(),
                ),
            )

            rows = [
                (
                    profile_id,
                    raw_job_id,
                    skill.name,
                    skill.name,
                    skill.category,
                    1 if skill.required else 0,
                    skill.evidence,
                    skill.confidence,
                )
                for skill in item.profile.all_skills()
            ]
            self.db.execute_many(
                "INSERT INTO jd_skill "
                "(jd_profile_id, raw_job_id, skill_canonical, skill_raw, category, "
                " required, evidence, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
