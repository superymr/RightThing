/** 技能 × 岗位方向需求矩阵。
 * 格子直接写「提到技能的 JD 数 / 有效 JD 总数」，颜色表达自然语言等级。 */

import type { EChartsOption } from 'echarts'
import { useChart } from './useChart'
import { ChartFailure } from './ChartFailure'
import type { DirectionReport } from '../../api/types'

type HeatCell = [number, number, number, string, number, number, number, number]

export function demandLevel(percent: number) {
  if (percent >= 60) return '核心需求'
  if (percent >= 30) return '常见需求'
  if (percent > 0) return '少量岗位提及'
  return '未提及'
}

export function SkillHeatmap({
  directions,
  top = 18,
  onSelect,
}: {
  directions: DirectionReport[]
  top?: number
  onSelect?: (skillName: string) => void
}) {
  const merged = new Map<string, number>()
  for (const direction of directions) {
    for (const stat of [
      ...direction.languages,
      ...direction.hard_skills,
      ...direction.domain_knowledge,
      ...direction.soft_skills,
    ]) {
      merged.set(stat.canonical, (merged.get(stat.canonical) ?? 0) + stat.weighted_score)
    }
  }
  const skills = [...merged.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, top)
    .map(([name]) => name)

  const lookup = (direction: DirectionReport, skill: string) => {
    const all = [
      ...direction.languages,
      ...direction.hard_skills,
      ...direction.domain_knowledge,
      ...direction.soft_skills,
    ]
    return all.find((item) => item.canonical === skill)
  }

  const cells: HeatCell[] = []
  skills.forEach((skill, rowIndex) => {
    directions.forEach((direction, colIndex) => {
      const stat = lookup(direction, skill)
      cells.push([
        colIndex,
        rowIndex,
        stat ? Math.round(stat.coverage * 100) : 0,
        skill,
        stat?.count ?? 0,
        direction.ok_jobs,
        stat?.required_count ?? 0,
        stat?.preferred_count ?? 0,
      ])
    })
  })

  const option: EChartsOption = {
    grid: { left: 8, right: 16, top: 10, bottom: 72, containLabel: true },
    tooltip: {
      formatter: (params: unknown) => {
        const p = params as { data: HeatCell }
        const [col, , percent, name, count, total, required, preferred] = p.data
        const direction = directions[col]?.title ?? ''
        if (!count) {
          return `<strong>${name}</strong><br/>${direction}<br/><span style="color:#64748b">${total} 份有效 JD 中未提及</span>`
        }
        return [
          `<strong>${name}</strong> · ${demandLevel(percent)}`,
          direction,
          `<strong>${count}/${total}</strong> 份有效 JD 提到（${percent}%）`,
          `其中：${required} 份列为明确要求，${preferred} 份列为加分项`,
        ].join('<br/>')
      },
    },
    xAxis: {
      type: 'category',
      data: directions.map((direction) => direction.title),
      splitArea: { show: true },
      axisLabel: { color: '#475569', interval: 0, width: 110, overflow: 'break', lineHeight: 14 },
    },
    yAxis: {
      type: 'category',
      data: skills,
      splitArea: { show: true },
      axisLabel: { color: '#475569', width: 120, overflow: 'truncate' },
    },
    visualMap: {
      type: 'piecewise',
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      dimension: 2,
      pieces: [
        { min: 60, label: '核心需求（≥60%）', color: '#2563eb' },
        { min: 30, max: 59, label: '常见需求（30–59%）', color: '#60a5fa' },
        { min: 1, max: 29, label: '少量岗位提及', color: '#bfdbfe' },
        { value: 0, label: '未提及', color: '#f1f5f9' },
      ],
      textStyle: { color: '#64748b', fontSize: 11 },
    },
    series: [
      {
        type: 'heatmap',
        data: cells,
        label: {
          show: true,
          fontSize: 11,
          color: '#1e293b',
          formatter: (params: unknown) => {
            const p = params as { data: HeatCell }
            return p.data[4] ? `${p.data[4]}/${p.data[5]}` : '—'
          },
        },
        emphasis: { itemStyle: { shadowBlur: 8, shadowColor: 'rgba(15,23,42,0.25)' } },
      },
    ],
  }

  const [ref, error] = useChart(option, [directions, top], {
    click: (params: unknown) => {
      if (!onSelect) return
      const p = params as { data: HeatCell }
      if (p.data?.[3] && p.data[4] > 0) onSelect(p.data[3])
    },
  })

  if (error) return <ChartFailure message={error} />
  const hasSmallSample = directions.some((direction) => direction.ok_jobs < 5)
  return (
    <div>
      <div className="mb-3 rounded-lg border border-sky-100 bg-sky-50 px-3 py-2 text-xs leading-relaxed text-slate-600">
        <strong className="text-slate-800">这样读：</strong>每格的 <strong>3/5</strong> 表示该方向
        5 份有效 JD 中有 3 份提到这项技能。颜色越深，说明越多岗位共同要求；“—”表示本批 JD
        没有提到。悬浮可查看硬性要求与加分项数量。
      </div>
      {hasSmallSample && (
        <p className="mb-2 text-[11px] leading-relaxed text-amber-700">
          提醒：有方向少于 5 份有效 JD，当前结果适合发现线索，不宜当作稳定的市场比例。
        </p>
      )}
      <div
        ref={ref}
        style={{ height: Math.max(340, skills.length * 26 + 115) }}
        className="w-full cursor-pointer"
        role="img"
        aria-label="各岗位方向对技能的需求矩阵，每格显示提到该技能的岗位数与有效岗位总数"
      />
    </div>
  )
}
