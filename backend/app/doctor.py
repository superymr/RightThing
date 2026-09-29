"""环境自检（`jobradar doctor`）。

配置 API Key 之后，最怕的是「以为配好了，其实模型名写错 / 额度用尽 / 端点不通」，
然后对着一个含糊的报错排查半天。这个模块把常见故障点做成了一次性可执行的检查：

    1. 配置检查    —— 必填项是否齐全
    2. 连通性检查  —— 端点能否访问、模型名是否存在、鉴权与配额是否正常
    3. 质量对比    —— 用同一条 JD 分别跑 mock 基线与真实模型，并排看差异
    4. 幻觉检查    —— 统计 evidence 不在原文中的比例

第 4 项是这个项目特有的：因为我们的抽取契约强制要求每条技能给出原文依据，
所以「模型有没有编造」这件事是可以被**量化**的，而不是靠感觉。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .analytics.lexicon import SkillLexicon
from .analytics.normalizer import Normalizer
from .config import Settings
from .llm import build_provider
from .llm.base import ChatProvider, LLMError
from .llm.extractor import Extractor
from .llm.mock_provider import MockProvider
from .llm.schemas import JDProfile
from .report import WIDTH, _pad, _rule
from .sources import RawJob, SampleSource

ICONS = {"ok": "[OK]  ", "warn": "[!]   ", "fail": "[FAIL]", "skip": "[-]   "}


@dataclass
class ExtractionRun:
    label: str
    profile: JDProfile
    seconds: float
    token_in: int = 0
    token_out: int = 0
    status: str = "ok"
    error: str = ""
    evidence_total: int = 0
    evidence_valid: int = 0

    @property
    def skill_count(self) -> int:
        return len(self.profile.all_skills())

    @property
    def evidence_rate(self) -> float:
        if self.evidence_total == 0:
            return 0.0
        return self.evidence_valid / self.evidence_total


@dataclass
class DoctorReport:
    checks: list[tuple[str, str, str]] = field(default_factory=list)
    exit_code: int = 0

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.checks.append((status, name, detail))


# ----------------------------------------------------------------------
def _mask(secret: str) -> str:
    if not secret:
        return "（未配置）"
    if len(secret) <= 10:
        return secret[:2] + "…" + secret[-2:]
    return f"{secret[:6]}…{secret[-4:]}（{len(secret)} 字符）"


def _pick_job(source: SampleSource, job_id: str) -> RawJob:
    jobs = source.all_jobs()
    if not jobs:
        raise LLMError("没有可用的样例 JD，无法进行抽取质量对比")

    if job_id:
        for job in jobs:
            if job.source_job_id == job_id:
                return job
        raise LLMError(f"找不到 id={job_id!r} 的样例 JD")

    # 默认取长度中位数的那条，避免用极端样本代表整体
    ranked = sorted(jobs, key=lambda j: len(j.raw_text))
    return ranked[len(ranked) // 2]


def _run_extraction(
    label: str, provider: ChatProvider, settings: Settings, job: RawJob
) -> ExtractionRun:
    extractor = Extractor(provider, settings, cache=None)  # 自检必须真实调用，不读缓存
    started = time.perf_counter()
    outcome = extractor.extract_profile(
        job_title=job.title, company=job.company, jd_text=job.raw_text
    )
    seconds = time.perf_counter() - started

    run = ExtractionRun(
        label=label,
        profile=outcome.profile,
        seconds=seconds,
        token_in=outcome.token_in,
        token_out=outcome.token_out,
        status=outcome.status,
        error=outcome.error,
    )
    for item in outcome.profile.all_skills():
        run.evidence_total += 1
        if item.evidence and item.evidence in job.raw_text:
            run.evidence_valid += 1
    return run


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _same_concept(a: str, b: str) -> bool:
    """判断两个技能名是否指同一个概念（用于对比展示，不参与产品统计）。

    真模型常给出复合短语（"嵌入式开发与单片机移植"），规则引擎给的是规范名
    （"嵌入式开发"、"单片机"）。严格相等会把**同一件事**报成两边各自独有。

    因此采用重叠匹配，但设两道闸门防止误配：
    - ASCII 名必须至少 4 字符才允许包含匹配 —— 挡住 `SQL` ⊂ `MySQL`；
    - 含中文的短语放宽到 2 字符 —— 中文双字词（单片机、力控）本身就有意义。
    """
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if short not in long_:
        return False
    if _CJK_RE.search(short):
        return len(short) >= 2
    return len(short) >= 4


def _split_by_overlap(mock_names: set[str], real_names: set[str]) -> tuple[set[str], list[str], list[str]]:
    """返回 (达成一致的 mock 技能, 仅 mock 有, 仅真模型有)。"""
    real_sorted = sorted(real_names, key=len, reverse=True)
    matched_real: set[str] = set()
    common: set[str] = set()
    only_mock: list[str] = []

    for mock_name in sorted(mock_names):
        hit = next((r for r in real_sorted if _same_concept(mock_name, r)), None)
        if hit is None:
            only_mock.append(mock_name)
        else:
            common.add(mock_name)
            matched_real.add(hit)

    only_real = [r for r in real_sorted if r not in matched_real]
    return common, only_mock, only_real


def _bucket(profile: JDProfile, canon) -> dict[str, set[str]]:
    """canon 接受一个技能名，返回**一组**规范名（复合名会拆开）。"""

    def names(items) -> set[str]:
        out: set[str] = set()
        for item in items:
            out.update(canon(item.name))
        return out

    return {
        "编程语言": names(profile.programming_languages),
        "核心技能": names(profile.hard_skills),
        "领域知识": names(profile.domain_knowledge),
        "软技能": names(profile.soft_skills),
    }


def _is_reasoning_like(run: ExtractionRun) -> bool:
    """识别「输出 token 远超输入」且**确实很慢**的模型。

    两个条件缺一不可。只看 token 比例会误伤 flash 这类输出啰嗦但很快的模型，
    而给出「建议换个更快的模型」这种恰好相反的建议。
    """
    return run.token_out > run.token_in * 2 and run.token_out > 1500 and run.seconds > 20


def _render_cost_hint(candidate: ExtractionRun, settings: Settings) -> None:
    """把「单条耗时」换算成「一次完整分析要多久」，并识别推理模型。

    单看「60 秒」没有体感，换算成「一次分析要 5 分钟」用户才知道要不要换模型。
    """
    concurrency = max(1, min(settings.llm_max_concurrency, 24))
    total_minutes = candidate.seconds * 24 / concurrency / 60
    print(_rule())
    print(
        f"  ⏱ 按此速度：24 条 JD 在并发 {concurrency} 下约需 "
        f"{total_minutes:.1f} 分钟（单条 {candidate.seconds:.1f} 秒）"
    )
    if _is_reasoning_like(candidate):
        print(
            "     该模型输出 token 远大于输入且单条耗时高，疑似**推理型模型**：质量可能更好，\n"
            "     但慢且贵。批量抽取通常不值得，建议在 .env 里换用更快的 LLM_MODEL。"
        )


def _render_comparison(
    job: RawJob, baseline: ExtractionRun, candidate: ExtractionRun, canon, settings: Settings
) -> None:
    print(f"\n  对比样本：{job.source_job_id} · {job.title}（{job.city}）")
    print(f"  原文长度：{len(job.raw_text)} 字符")

    print(_rule())
    print(f"  {_pad('指标', 18)}{_pad('mock 基线', 22)}{_pad('真实模型', 22)}")
    print(_rule())
    rows = [
        ("总技能数", str(baseline.skill_count), str(candidate.skill_count)),
        (
            "编程语言",
            str(len(baseline.profile.programming_languages)),
            str(len(candidate.profile.programming_languages)),
        ),
        ("核心技能", str(len(baseline.profile.hard_skills)), str(len(candidate.profile.hard_skills))),
        (
            "领域知识",
            str(len(baseline.profile.domain_knowledge)),
            str(len(candidate.profile.domain_knowledge)),
        ),
        (
            "软技能",
            str(len(baseline.profile.soft_skills)),
            str(len(candidate.profile.soft_skills)),
        ),
        ("耗时", f"{baseline.seconds:.2f}s", f"{candidate.seconds:.2f}s"),
        (
            "tokens",
            f"{baseline.token_in}+{baseline.token_out}",
            f"{candidate.token_in}+{candidate.token_out}",
        ),
        (
            "evidence 合法率",
            f"{baseline.evidence_rate:.0%}",
            f"{candidate.evidence_rate:.0%}",
        ),
    ]
    for name, left, right in rows:
        print(f"  {_pad(name, 18)}{_pad(left, 22)}{_pad(right, 22)}")

    # ★ 集合比较前必须过同一套词表归一化。
    # 真模型给的是自由文本（"力控算法"、"EtherCAT总线通信"），
    # 直接和 mock 的规范名（"力控"、"EtherCAT"）做差集，会把**同一个技能**
    # 报成两边各自的独有项 —— 那种输出比不输出更误导人。
    mock_all = set().union(*_bucket(baseline.profile, canon).values())
    real_all = set().union(*_bucket(candidate.profile, canon).values())

    common, only_mock, only_real = _split_by_overlap(mock_all, real_all)

    print(_rule())
    print(f"  两边都抽到（{len(common)} 项）：{'、'.join(sorted(common)[:12])}")
    if only_real:
        print(f"  ✅ 真模型多抽到的（规则引擎漏抽）：{'、'.join(only_real[:12])}")
    if only_mock:
        print(f"  ⚠ 仅规则引擎抽到的（可能是误报，也可能是模型漏抽）：{'、'.join(only_mock[:12])}")
    if not only_real and not only_mock:
        print("  两边抽出的技能集合完全一致 —— 该样本上规则引擎已足够")

    if candidate.evidence_rate < 1.0:
        bad = [i.name for i in candidate.profile.all_skills() if i.evidence not in job.raw_text]
        print(f"  ⚠ {len(bad)} 项技能的 evidence 不在原文中（疑似幻觉）：{'、'.join(bad[:8])}")

    # 把「优先考虑对象」误当成技能，是抽取精度最常见的退化形式，单独提示
    preference_noise = [
        name
        for name in only_real
        if any(marker in name for marker in ("项目经验", "项目", "经历", "者优先"))
    ]
    if preference_noise:
        print(
            f"  ⚠ 其中 {len(preference_noise)} 项疑似把「优先考虑对象」误当成技能："
            f"{'、'.join(preference_noise[:6])}"
        )
        print("     这属于抽取精度问题（应落到 preferred_qualifications），会污染技能排行。")

    _render_cost_hint(candidate, settings)


# ----------------------------------------------------------------------
def run_doctor(settings: Settings, *, job_id: str = "") -> int:
    report = DoctorReport()

    print(_rule("="))
    print("  RightThing 正事 · 环境自检")
    print(_rule("="))

    # ---------- 1. 配置 ----------
    print("\n[1/3] 配置检查")
    print(f"  provider   : {settings.llm_provider}")
    print(f"  base_url   : {settings.llm_base_url}")
    print(f"  模型       : {settings.llm_model}")
    print(f"  强模型     : {settings.llm_model_strong or '（未设置，复用默认模型）'}")
    print(f"  API Key    : {_mask(settings.llm_api_key)}")
    print(f"  数据库     : {settings.db_path}")
    print(f"  缓存       : {'开启' if settings.cache_enabled else '关闭'}")
    print(f"  缓存命名空间: {settings.cache_namespace}")
    print(f"  样例数据   : {settings.sample_dir}")

    if settings.is_mock:
        print("\n  当前使用 mock 规则引擎：完全离线、零成本、结果确定性。")
        print("  想接真实大模型，编辑项目根目录的 .env：")
        print("      LLM_PROVIDER=openai")
        print("      LLM_API_KEY=sk-你的key")
        print("\n[OK] 离线模式本身无需自检，可直接使用：")
        print('      python -m app.cli analyze --skills "数据分析,Python,SQL"')
        return 0

    if not settings.llm_api_key:
        print("\n[FAIL] 未配置 LLM_API_KEY。")
        print("  请打开项目根目录的 .env 文件，把这行填上：")
        print("      LLM_API_KEY=sk-你的key")
        print("  保存后重新运行：python -m app.cli doctor")
        print("\n  想先用离线模式验证流程：python -m app.cli analyze --skills \"Python,SQL\" --provider mock")
        return 2

    provider = build_provider(settings)

    # ---------- 2. 连通性 ----------
    print("\n[2/3] 连通性检查")
    list_models = getattr(provider, "list_models", None)
    if callable(list_models):
        try:
            models = list_models()
            print(f"  /models 可用，共 {len(models)} 个模型")
            if settings.llm_model in models:
                print(f"  [OK]   模型名 {settings.llm_model!r} 在可用列表中")
                report.add("ok", "模型名有效")
            else:
                near = [m for m in models if settings.llm_model.split("-")[0] in m][:6]
                print(f"  [!]    模型名 {settings.llm_model!r} 不在列表中")
                if near:
                    print(f"         可选项参考：{'、'.join(near)}")
                report.add("warn", "模型名可能写错")
        except LLMError as exc:
            print(f"  [-]    /models 不可用（{exc}），跳过模型名检查")
            report.add("skip", "模型名检查")
    else:
        print("  [-]    该 provider 不支持 /models，跳过")
        report.add("skip", "模型名检查")

    try:
        started = time.perf_counter()
        actual_model = provider.check_connectivity()
        elapsed = time.perf_counter() - started
        print(f"  [OK]   最小对话调用成功（{elapsed:.2f}s，服务端返回模型 {actual_model}）")
        report.add("ok", "连通性与鉴权")
    except LLMError as exc:
        print(f"  [FAIL] 调用失败：{exc}")
        print("         常见原因：Key 错误或过期 / 余额不足 / base_url 不对 / 网络代理")
        return 1

    # ---------- 3. 质量对比 ----------
    print("\n[3/3] 抽取质量对比（同一条 JD，mock 基线 vs 真实模型）")
    source = SampleSource(settings.sample_dir)
    try:
        job = _pick_job(source, job_id)
    except LLMError as exc:
        print(f"  [FAIL] {exc}")
        return 1

    baseline = _run_extraction("mock", MockProvider(), settings, job)
    candidate = _run_extraction("real", provider, settings, job)

    if candidate.status != "ok":
        print(f"\n  [FAIL] 真实模型抽取失败：{candidate.error}")
        print("         这说明端点能通，但结构化输出没能通过校验。")
        print("         可尝试：换更强的模型、或在 .env 里把 LLM_MODEL_STRONG 设为更强模型。")
        return 1

    # 不接数据库：自检不应该往别名表里写东西
    normalizer = Normalizer(SkillLexicon.load(settings.alias_path))

    def canon(name: str) -> list[str]:
        return [n.canonical for n in normalizer.normalize_item_names(name)]

    _render_comparison(job, baseline, candidate, canon, settings)

    # ---------- 结论 ----------
    print()
    print(_rule("="))
    if candidate.skill_count == 0:
        print("  [FAIL] 真实模型没有抽到任何技能，请检查模型是否支持中文长文本。")
        return 1
    if candidate.evidence_rate < 0.8:
        print(
            f"  [!]    evidence 合法率仅 {candidate.evidence_rate:.0%}，"
            "幻觉偏多。建议改用更强的模型，或收紧 prompts/jd_extract.py 的约束。"
        )
    print("  [OK]   配置可用。接下来跑一次完整分析：")
    print('      python -m app.cli analyze --skills "数据分析,Python,ROS,Linux,C++"')
    print(_rule("="))
    return 0
