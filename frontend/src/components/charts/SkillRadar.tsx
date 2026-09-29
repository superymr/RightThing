/** 技能族雷达图：把细碎技能按 `category` 聚合成「族」，回答
 *  「我在这个方向上，是语言弱、还是工程工具弱、还是领域知识弱」。
 *
 *  两条线：市场要求的权重总量 vs 我已经覆盖的权重总量（同一量纲）。
 *  刻意**不**画成雷达图的常见误用（两套不同量纲的指数）——
 *  那样两条线的差距没有可解释的含义。 */

import type { EChartsOption } from 'echarts'
import { useChart } from './useChart'
import { ChartFailure } from './ChartFailure'
import { EmptyState } from '../ui'
import type { DirectionReport } from '../../api/types'

interface FamilyRow {
  name: string
  market: number
  covered: number
}

export function SkillRadar({ direction }: { direction: DirectionReport }) {
  const market = new Map<string, number>()
  const covered = new Map<string, number>()

  for (const stat of [
    ...direction.languages,
    ...direction.hard_skills,
    ...direction.domain_knowledge,
    ...direction.soft_skills,
  ]) {
    const family = stat.category || '其他'
    market.set(family, (market.get(family) ?? 0) + stat.weighted_score)
  }
  for (const stat of direction.gap.have) {
    const family = stat.category || '其他'
    covered.set(family, (covered.get(family) ?? 0) + stat.weighted_score)
  }

  const families: FamilyRow[] = [...market.entries()]
    .map(([name, value]) => ({ name, market: value, covered: covered.get(name) ?? 0 }))
    .sort((a, b) => b.market - a.market)
    .slice(0, 8)

  const max = Math.max(...families.map((f) => f.market), 1)

  const option: EChartsOption = {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { color: '#64748b', fontSize: 11 } },
    radar: {
      indicator: families.map((f) => ({ name: f.name, max: Math.ceil(max) })),
      radius: '62%',
      splitLine: { lineStyle: { color: '#e2e8f0' } },
      splitArea: { areaStyle: { color: ['#ffffff', '#f8fafc'] } },
      axisName: { color: '#475569', fontSize: 11 },
    },
    series: [
      {
        type: 'radar',
        data: [
          {
            name: '市场要求权重',
            value: families.map((f) => Number(f.market.toFixed(2))),
            areaStyle: { color: 'rgba(79, 70, 229, 0.14)' },
            lineStyle: { color: '#4f46e5' },
            itemStyle: { color: '#4f46e5' },
          },
          {
            name: '我已覆盖',
            value: families.map((f) => Number(f.covered.toFixed(2))),
            areaStyle: { color: 'rgba(16, 185, 129, 0.2)' },
            lineStyle: { color: '#10b981' },
            itemStyle: { color: '#10b981' },
          },
        ],
      },
    ],
  }

  const [ref, error] = useChart(option, [direction])

  // ★ 根因修复：空方向必须在这里就返回，绝不能把空 indicator 交给 ECharts。
  // radar 拿到空 indicator 会抛 TypeError，而异常发生在 useEffect 里 ——
  // 没有错误边界时会让整棵组件树卸载，用户看到的就是一个全白页面。
  // （真实模型推荐出样例数据没覆盖的方向时，这是必然发生的，不是偶发。）
  if (families.length === 0) {
    return (
      <EmptyState
        title="该方向没有可用样本"
        hint="样例数据只覆盖部分岗位方向；这个方向一条 JD 都没采到，因此无法画出技能族分布。"
      />
    )
  }
  if (error) return <ChartFailure message={error} />
  return <div ref={ref} className="h-[320px] w-full" />
}
