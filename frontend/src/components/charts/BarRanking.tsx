/** 技能排行（横向条形图）：按 weighted_score 排序，颜色区分「必须会」与「会更好」。
 *
 *  交互闭环的一半在这里：点任意一根条 → 上层打开「哪些 JD 提到了它」。 */

import type { EChartsOption } from 'echarts'
import { useChart } from './useChart'
import { ChartFailure } from './ChartFailure'
import type { SkillStat } from '../../api/types'

const COLORS = {
  required: '#4f46e5',
  preferred: '#14b8a6',
}

export function BarRanking({
  stats,
  top = 20,
  onSelect,
  title,
}: {
  stats: SkillStat[]
  top?: number
  onSelect?: (skill: SkillStat) => void
  title?: string
}) {
  const data = stats.slice(0, top).slice().reverse() // ECharts 的 y 轴自下而上

  const option: EChartsOption = {
    grid: { left: 8, right: 56, top: 8, bottom: 8, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => {
        const list = params as Array<{ dataIndex: number }>
        const index = list?.[0]?.dataIndex ?? 0
        const stat = data[index]
        if (!stat) return ''
        return [
          `<strong>${stat.canonical}</strong>`,
          `加权分：${stat.weighted_score}`,
          `岗位数：${stat.count}（覆盖率 ${(stat.coverage * 100).toFixed(0)}%）`,
          `硬性要求：${stat.required_count} 条 · 加分项：${stat.preferred_count} 条`,
          `必须占比：${(stat.required_ratio * 100).toFixed(0)}%`,
          '<span style="color:#94a3b8">点击可查看原始 JD 与证据句</span>',
        ].join('<br/>')
      },
    },
    xAxis: { type: 'value', splitLine: { lineStyle: { color: '#f1f5f9' } } },
    yAxis: {
      type: 'category',
      data: data.map((s) => s.canonical),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e2e8f0' } },
      axisLabel: { color: '#475569', width: 120, overflow: 'truncate' },
    },
    series: [
      {
        type: 'bar',
        barMaxWidth: 18,
        data: data.map((s) => ({
          value: s.weighted_score,
          itemStyle: {
            color: s.required_count >= s.preferred_count ? COLORS.required : COLORS.preferred,
            borderRadius: [0, 4, 4, 0],
          },
        })),
        label: {
          show: true,
          position: 'right',
          color: '#64748b',
          fontSize: 11,
          formatter: '{c}',
        },
      },
    ],
  }

  const [ref, error] = useChart(option, [stats, top], {
    click: (params: unknown) => {
      if (!onSelect) return
      const p = params as { dataIndex: number }
      const stat = data[p.dataIndex]
      if (stat) onSelect(stat)
    },
  })

  return (
    <div>
      <div
        ref={ref}
        hidden={Boolean(error)}
        style={{ height: Math.max(260, data.length * 26 + 40) }}
        className="w-full cursor-pointer"
      />
      {error && <ChartFailure message={error} />}
      <div className="mt-2 flex items-center gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1">
          <i className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: COLORS.required }} />
          以硬性要求为主
        </span>
        <span className="flex items-center gap-1">
          <i
            className="inline-block h-2.5 w-2.5 rounded-sm"
            style={{ background: COLORS.preferred }}
          />
          以加分项为主
        </span>
        {title && <span className="ml-auto text-slate-400">{title}</span>}
        <span className="text-slate-400">点条形可看原文</span>
      </div>
    </div>
  )
}
