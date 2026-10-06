/** ③ 分析看板。
 *
 *  组织原则：**先给结论，再给证据**。
 *  从上到下依次是「我缺什么」→「市场要什么」→「各方向的差异」→「招聘方偏好」→「原始岗位」。
 *  任何一个技能标签都能点开右侧回溯栏，看到它在哪些 JD 里出现、原文怎么写的。 */

import { useMemo, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'

import { useSession } from '../api/hooks'
import { apiUrl } from '../api/client'
import type { DirectionReport, PreferenceStat, SkillStat } from '../api/types'
import { BarRanking } from '../components/charts/BarRanking'
import { GapSwimlane } from '../components/charts/GapSwimlane'
import { SkillHeatmap } from '../components/charts/SkillHeatmap'
import { SkillRadar } from '../components/charts/SkillRadar'
import { SkillDrawer } from '../components/SkillDrawer'
import { ErrorBoundary } from '../components/ErrorBoundary'
import { Badge, Button, Card, EmptyState, ErrorNotice, Spinner, StatTile, percent } from '../components/ui'

function allSkills(direction: DirectionReport): SkillStat[] {
  return [
    ...direction.languages,
    ...direction.hard_skills,
    ...direction.domain_knowledge,
    ...direction.soft_skills,
  ].sort((a, b) => b.weighted_score - a.weighted_score)
}

function PreferenceList({
  title,
  hint,
  items,
  color = 'slate',
}: {
  title: string
  hint?: string
  items: PreferenceStat[]
  color?: 'slate' | 'violet' | 'sky' | 'amber'
}) {
  if (items.length === 0) return null
  const max = Math.max(...items.map((item) => item.count), 1)
  return (
    <div>
      <h4 className="text-sm font-medium text-slate-700">{title}</h4>
      {hint && <p className="mt-0.5 text-xs text-slate-400">{hint}</p>}
      <div className="mt-2 space-y-1.5">
        {items.slice(0, 8).map((item) => (
          <div key={item.label} className="flex items-center gap-2">
            <span className="w-40 shrink-0 truncate text-xs text-slate-600" title={item.label}>
              {item.label}
            </span>
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
              <span
                className="block h-full rounded-full bg-slate-400"
                style={{ width: `${(item.count / max) * 100}%` }}
              />
            </span>
            <Badge color={color}>{percent(item.coverage)}</Badge>
          </div>
        ))}
      </div>
    </div>
  )
}

/** 没有样本的方向。
 *
 *  这不是异常路径，而是**当前数据条件下的必然结果**：真模型会推荐出内置
 *  样例数据没有覆盖的方向，采集层拿不到任何 JD（PLAN 遗留问题 #1）。
 *
 *  所以这里不能只丢一句「无数据」了事 —— 那是个死胡同。至少要把
 *  「为什么空」和「我能做什么」说清楚，否则用户只会以为产品坏了。
 */
function EmptyDirection({ direction }: { direction: DirectionReport }) {
  return (
    <div className="space-y-5">
      <Card>
        <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-5 py-6">
          <p className="text-sm font-medium text-slate-700">
            这个方向一条 JD 都没采到，因此没有可统计的东西。
          </p>
          <div className="mt-3 space-y-2 text-xs leading-relaxed text-slate-500">
            <p>
              <strong className="text-slate-600">为什么：</strong>
              这是大模型推荐的岗位方向，但本次在线数据源没有召回仍在招聘的职位。
              这表示<strong className="text-slate-600">当前来源未命中</strong>，不代表市场上没有岗位。
            </p>
            <p>
              <strong className="text-slate-600">怎么办：</strong>
              扩大城市范围、增加每方向岗位数，或直接导入公开职位 URL。
            </p>
          </div>

          {direction.keywords.length > 0 && (
            <div className="mt-4">
              <p className="text-xs text-slate-500">
                模型给这个方向生成的检索词（可用于你自己去招聘网站搜索）：
              </p>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {direction.keywords.map((keyword) => (
                  <Badge key={keyword} color="slate">
                    {keyword}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      </Card>

      {direction.gap.marginal.length > 0 && (
        <Card title="你的技能">
          {/* 刻意**不**叫「边缘技能」：边缘技能 = M − R，而这里 R 是空的
              （一条 JD 都没有），所以 M − R 就等于整个 M。把用户会的 C++、ROS
              说成「这个方向用不上的边缘技能」是拿缺数据当结论 —— 那是误导，
              不是发现。没有样本就只能说「无法判断」。 */}
          <p className="mb-3 text-xs leading-relaxed text-slate-500">
            没有任何 JD 样本，因此<strong className="text-slate-600">无法判断</strong>
            下面这些技能在该方向上是优势还是边缘。等这个方向有了样本，
            它们会自动落到「已具备 / 需补齐 / 边缘技能」里。
          </p>
          <div className="flex flex-wrap gap-1.5">
            {direction.gap.marginal.map((name) => (
              <Badge key={name} color="slate">
                {name}
              </Badge>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

function DirectionPanel({
  direction,
  directions,
  onSelectSkill,
}: {
  direction: DirectionReport
  directions: DirectionReport[]
  onSelectSkill: (skill: SkillStat) => void
}) {
  const skills = useMemo(() => allSkills(direction), [direction])

  if (direction.ok_jobs === 0) return <EmptyDirection direction={direction} />

  return (
    <div className="space-y-5">
      <Card title={direction.sample_quality?.preliminary ?? direction.ok_jobs < 20 ? '初步观察 · 样本有限' : '本次样本说明'}>
        <p className="text-sm text-slate-600">
          成功解析 {direction.ok_jobs} 条岗位，来自 {direction.sample_quality?.company_count ?? new Set(direction.jobs.map(job => job.company).filter(Boolean)).size} 家公司。
          {direction.sample_quality?.note ?? '统计仅代表本次采集样本，不代表整个招聘市场。'}
        </p>
        <p className="mt-2 text-xs text-slate-500">
          {Object.entries(direction.sample_quality?.source_counts ?? {}).map(([source, count]) => `${source}：${count} 条`).join(' · ')}
        </p>
      </Card>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="样本量（JD 条数）" value={direction.ok_jobs} hint={`采集 ${direction.total_jobs} 条`} />
        <StatTile
          label="要求权重覆盖率"
          value={percent(direction.gap.coverage_score, 1)}
          hint="你的技能覆盖了市场多少要求权重"
          tone="emerald"
        />
        <StatTile
          label={direction.ok_jobs < 20 ? '优先关注技能' : '高频硬性要求'}
          value={direction.gap.must_learn.length}
          hint="覆盖率 ≥ 40% 且必须占比 ≥ 60%"
          tone="red"
        />
        <StatTile
          label="已具备"
          value={direction.gap.have.length}
          hint="市场要、你也有"
          tone="emerald"
        />
      </div>

      <GapSwimlane gap={direction.gap} onSelect={onSelectSkill} />

      <Card
        title="技能排行"
        subtitle="按加权分排序（硬性要求 × 1.0 + 加分项 × 0.4）。颜色区分「多数岗位当作硬要求」与「多数当作加分项」。"
      >
        {skills.length === 0 ? (
          <EmptyState title="没有可用样本" hint="该方向下所有 JD 都抽取失败了" />
        ) : (
          <BarRanking stats={skills} top={20} onSelect={onSelectSkill} />
        )}
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card
          title="技能族雷达"
          subtitle="把细碎技能按技能族聚合，回答「我是语言弱、工具弱，还是领域知识弱」。两条线同一量纲，可直接比较。"
        >
          <SkillRadar direction={direction} />
        </Card>

        <Card
          title="招聘方偏好"
          subtitle="学历 / 专业 / 经验 / 证书 / 加分项 —— 这些决定了「同样的技能，你能不能过筛」。"
        >
          <div className="grid gap-5 sm:grid-cols-2">
            <PreferenceList title="学历" items={direction.education} color="violet" />
            <PreferenceList title="经验年限" items={direction.experience} color="violet" />
            <PreferenceList title="专业偏好" items={direction.majors} color="sky" />
            <PreferenceList title="职级" items={direction.seniority} color="sky" />
            <PreferenceList title="证书" items={direction.certificates} color="amber" />
            <div className="sm:col-span-2">
              <PreferenceList
                title="优先考虑对象"
                hint="JD 里「优先/加分」的原话，措辞已做归一化合并"
                items={direction.preferred_qualifications}
                color="amber"
              />
            </div>
          </div>
          {direction.education.length === 0 &&
            direction.majors.length === 0 &&
            direction.preferred_qualifications.length === 0 && (
              <EmptyState title="样例 JD 中没有结构化的偏好信息" />
            )}
        </Card>
      </div>

      {directions.length > 1 && (
        <Card
          title="各方向都在要求哪些技能？"
          subtitle="按真实 JD 计数横向比较：优先补多个目标方向都经常出现的技能，投入更容易复用。"
        >
          <SkillHeatmap directions={directions} top={16} onSelect={(name) => {
            const stat = skills.find((item) => item.canonical === name)
            if (stat) onSelectSkill(stat)
          }} />
        </Card>
      )}
    </div>
  )
}

function JobsPanel({ direction }: { direction: DirectionReport }) {
  return (
    <Card
      title={`岗位明细（${direction.jobs.length} 条）`}
      subtitle="每一次抽取都能回到真实岗位原文；点击“查看”可进入对应招聘页面。"
    >
      <div className="overflow-hidden rounded-lg border border-slate-200">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left font-medium">岗位</th>
              <th className="px-3 py-2 text-left font-medium">公司</th>
              <th className="px-3 py-2 text-left font-medium">城市</th>
              <th className="px-3 py-2 text-left font-medium">来源</th>
              <th className="px-3 py-2 text-left font-medium">抽取状态</th>
              <th className="px-3 py-2 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {direction.jobs.map((job) => (
              <tr key={job.job_id} className="border-t border-slate-100 hover:bg-slate-50/60">
                <td className="px-3 py-2 font-medium text-slate-700">{job.title}</td>
                <td className="px-3 py-2 text-slate-500">{job.company}</td>
                <td className="px-3 py-2 text-slate-500">{job.city}</td>
                <td className="px-3 py-2 text-slate-400">{job.source}</td>
                <td className="px-3 py-2">
                  {job.status === 'ok' ? (
                    <Badge color="emerald">成功</Badge>
                  ) : (
                    <Badge color="red">{job.status}</Badge>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  <div className="flex flex-wrap justify-end gap-x-3 gap-y-1">
                    <Link className="text-sky-600 hover:underline" to={`/jobs/${job.job_id}`}>
                      查看分析证据
                    </Link>
                    {job.url ? (
                      <a
                        className="font-medium text-emerald-700 hover:underline"
                        href={job.url}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        打开真实岗位 ↗
                      </a>
                    ) : (
                      <span className="text-slate-300">样例数据</span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

export function DashboardPage() {
  const { sessionId } = useParams()
  const id = Number(sessionId)
  const [params, setParams] = useSearchParams()
  const { data, isLoading, error } = useSession(Number.isFinite(id) ? id : null)
  const [tab, setTab] = useState<'board' | 'jobs'>('board')
  const [selected, setSelected] = useState<SkillStat | null>(null)

  // 当前方向放进 URL（?dir=<direction_id>）而不是只用组件内部 state：
  // 刷新不丢、能分享、浏览器后退可用，也让「空方向」这类特定路径可以被直接打开。
  const requested = Number(params.get('dir') ?? '')
  const found = data?.directions.findIndex((d) => d.direction_id === requested) ?? -1
  const activeIndex = Math.max(0, found)

  const selectDirection = (directionId: number) => {
    const next = new URLSearchParams(params)
    next.set('dir', String(directionId))
    setParams(next, { replace: true })
  }

  if (isLoading) return <Spinner label="正在读回看板…" />
  if (error) return <ErrorNotice error={error} />
  if (!data) return <EmptyState title="没有这个会话" />

  const direction = data.directions[activeIndex] ?? data.directions[0]

  if (!direction) {
    return (
      <Card title={`会话 #${data.session_id}`}>
        <EmptyState
          title="这个会话没有产生任何方向"
          hint="可能是方向推荐失败，或采集阶段没有拿到任何 JD。"
        />
      </Card>
    )
  }

  return (
    <div className="space-y-5">
      {data.provider === 'mock' && (
        <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-semibold">
            ⚠ 这次分析用的是本地规则引擎（mock），<u>没有调用任何大模型</u>。
          </p>
          <p className="mt-1 text-xs leading-relaxed">
            结果是「词表匹配 + 规则」从 JD 原文里捞出来的，确定性、零成本、可离线复现 ——
            适合验证流程与回归测试，但**不具备大模型的理解能力**（识别不了词表没收录的说法、
            也读不懂语序与否定）。
            要得到真实模型的结果，请在项目根目录 <code className="rounded bg-amber-100 px-1">.env</code> 里配置{' '}
            <code className="rounded bg-amber-100 px-1">LLM_PROVIDER=openai</code> 与{' '}
            <code className="rounded bg-amber-100 px-1">LLM_API_KEY</code>，然后重新分析。
          </p>
          <p className="mt-1 text-xs text-amber-700">
            判据：真实模型记录的 model 是具体模型名（如 deepseek-flash），且每条 JD 的 token 用量不为 0；
            mock 记为 mock-rule-engine，token 恒为 0。
          </p>
        </div>
      )}

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-indigo-500">
              RightThing 分析报告
            </p>
            <h1 className="text-xl font-bold tracking-[-0.02em] text-slate-900">
              报告 #{data.session_id}
              <span className="ml-2 text-sm font-normal text-slate-400">
                {data.provider} · {data.model}
              </span>
            </h1>
            <p className="mt-1 text-xs text-slate-500">
              创建于 {new Date(data.created_at).toLocaleString()} · 共 {data.total_jobs} 条 JD ·{' '}
              城市 {data.city || '不限'}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <span className="text-xs text-slate-400">输入技能：</span>
              {data.canonical_skills.map((skill) => (
                <Badge key={skill} color="slate">
                  {skill}
                </Badge>
              ))}
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant={tab === 'board' ? 'primary' : 'secondary'} onClick={() => setTab('board')}>
              看板
            </Button>
            <Button variant={tab === 'jobs' ? 'primary' : 'secondary'} onClick={() => setTab('jobs')}>
              岗位明细
            </Button>
            {/* 走浏览器原生下载：后端用 Content-Disposition 指定文件名，
                报告内容与看板同源（同一个 load_session payload） */}
            <a
              href={apiUrl(`/api/sessions/${data.session_id}/report.md`)}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 shadow-sm transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700"
            >
              导出 Markdown
            </a>
          </div>
        </div>

        {data.directions.length > 1 && (
          <div className="mt-4 flex flex-wrap gap-2 border-t border-slate-100 pt-4">
            {data.directions.map((item, index) => {
              const empty = item.ok_jobs === 0
              const active = index === activeIndex
              return (
                <button
                  key={item.direction_id}
                  type="button"
                  onClick={() => selectDirection(item.direction_id)}
                  // 没有样本的方向必须**在点进去之前**就能看出来。
                  // 否则用户点过去只会看到一页空面板，以为产品坏了。
                  title={empty ? '该方向没有采集到任何 JD，看板无法统计' : undefined}
                  className={`rounded-lg border px-3 py-1.5 text-sm transition ${
                    active
                      ? empty
                        ? 'border-slate-400 border-dashed bg-slate-500 text-white'
                        : 'border-indigo-600 bg-indigo-600 text-white shadow-sm shadow-indigo-200'
                      : empty
                        ? 'border-dashed border-slate-300 text-slate-400 hover:border-slate-400'
                        : 'border-slate-200 bg-white text-slate-600 hover:border-indigo-300 hover:text-indigo-700'
                  }`}
                >
                  {item.title}
                  <span className="ml-2 text-xs opacity-70">
                    {empty ? '无样本' : `${item.ok_jobs} 条`}
                  </span>
                </button>
              )
            })}
          </div>
        )}

        <p className="mt-3 text-xs leading-relaxed text-slate-400">
          {direction.ok_jobs > 0 ? (
            <>
              样本量为 {direction.ok_jobs} 条，统计口径：覆盖率 = 提到该技能的岗位数 / 样本量；
              加权分 = 硬性要求数 × 1.0 + 加分项数 × 0.4。样本不代表全市场，请结合覆盖率而非绝对次数解读。
            </>
          ) : (
            <>这个方向没有拿到任何 JD 样本，因此没有可统计的口径 —— 下方说明的是原因与下一步。</>
          )}
        </p>
      </Card>

      {/* 每个面板各自兜底：一个图表画不出来，不该把整页带走。
          图表内部的 setOption 已经在 useChart 里 try/catch 了，
          这里挡的是渲染期的意外（例如某个字段形状与预期不符）。 */}
      <ErrorBoundary label={tab === 'board' ? '分析看板' : '岗位明细'}>
        {tab === 'board' ? (
          <DirectionPanel
            direction={direction}
            directions={data.directions}
            onSelectSkill={setSelected}
          />
        ) : (
          <JobsPanel direction={direction} />
        )}
      </ErrorBoundary>

      <SkillDrawer skill={selected} direction={direction} onClose={() => setSelected(null)} />
    </div>
  )
}
