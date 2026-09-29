/** 缺口泳道：已具备 / 需补齐 / 边缘技能 三列。
 *
 *  这是整个产品的价值出口 —— 排行榜只是信息，「我该学什么」才是答案。
 *  每个标签都可点击，直接跳到「哪些 JD 要它、原文怎么写的」。 */

import { Badge, Card, EmptyState, percent } from '../ui'
import type { GapItem, GapReport, SkillStat } from '../../api/types'

const TIER_META: Record<string, { label: string; color: 'red' | 'amber' | 'sky' }> = {
  must: { label: '必学', color: 'red' },
  should: { label: '建议学', color: 'amber' },
  nice: { label: '加分项', color: 'sky' },
}

function SkillChip({
  stat,
  color,
  onSelect,
}: {
  stat: SkillStat
  color: 'emerald' | 'red' | 'amber' | 'sky' | 'slate'
  onSelect?: (skill: SkillStat) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect?.(stat)}
      title={`${stat.count} 个岗位提到 · 覆盖率 ${percent(stat.coverage)} · 必须占比 ${percent(
        stat.required_ratio,
      )}`}
      className="group flex w-full items-center justify-between gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-left text-sm transition hover:border-slate-400 hover:shadow-sm"
    >
      <span className="truncate text-slate-700 group-hover:text-slate-900">{stat.canonical}</span>
      <span className="flex shrink-0 items-center gap-1.5">
        <span className="text-xs tabular-nums text-slate-400">{percent(stat.coverage)}</span>
        <Badge color={color}>{stat.count}</Badge>
      </span>
    </button>
  )
}

function Column({
  title,
  hint,
  count,
  children,
  tone,
}: {
  title: string
  hint: string
  count: number
  children: React.ReactNode
  tone: 'emerald' | 'red' | 'slate'
}) {
  const tones = {
    emerald: 'border-emerald-200 bg-emerald-50/50',
    red: 'border-red-200 bg-red-50/40',
    slate: 'border-slate-200 bg-slate-50/60',
  }
  return (
    <div className={`rounded-xl border p-3 ${tones[tone]}`}>
      <div className="mb-2 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold text-slate-700">{title}</h3>
        <span className="text-xs tabular-nums text-slate-500">{count} 项</span>
      </div>
      <p className="mb-3 text-xs leading-relaxed text-slate-500">{hint}</p>
      <div className="thin-scroll max-h-80 space-y-1.5 overflow-y-auto pr-1">{children}</div>
    </div>
  )
}

export function GapSwimlane({
  gap,
  onSelect,
}: {
  gap: GapReport
  onSelect?: (skill: SkillStat) => void
}) {
  const tiers: GapItem[][] = [gap.must_learn, gap.should_learn, gap.nice_to_have]
  const missingTotal = tiers.reduce((sum, tier) => sum + tier.length, 0)

  return (
    <Card
      title="技能缺口"
      subtitle="市场要求 − 你已会 = 要补的。分档依据是两个可解释量：覆盖率（值不值得学）与必须占比（不学行不行）。"
      right={
        <div className="text-right">
          <p className="text-xs text-slate-500">要求权重覆盖率</p>
          <p className="text-xl font-semibold tabular-nums text-slate-800">
            {percent(gap.coverage_score, 1)}
          </p>
        </div>
      }
    >
      <div className="grid gap-3 lg:grid-cols-3">
        <Column
          title="✅ 已具备"
          hint="市场要、你也有 —— 简历与面谈里应当优先展开的部分。"
          count={gap.have.length}
          tone="emerald"
        >
          {gap.have.length === 0 ? (
            <EmptyState title="暂无交集" hint="输入技能与市场要求没有对上的项" />
          ) : (
            gap.have.map((stat) => (
              <SkillChip key={stat.canonical} stat={stat} color="emerald" onSelect={onSelect} />
            ))
          )}
        </Column>

        <Column
          title="📚 需补齐"
          hint="按 必学 → 建议学 → 加分项 排序；只被 1 个岗位提到的技能会被降级为加分项。"
          count={missingTotal}
          tone="red"
        >
          {missingTotal === 0 ? (
            <EmptyState title="没有明显缺口" hint="这个方向上你已覆盖全部高频要求" />
          ) : (
            tiers.map((tier, index) =>
              tier.length === 0 ? null : (
                <div key={index} className="mb-1">
                  <p className="mb-1 mt-2 text-xs font-medium text-slate-500">
                    {TIER_META[['must', 'should', 'nice'][index]].label} · {tier.length}
                  </p>
                  <div className="space-y-1.5">
                    {tier.map((item) => (
                      <SkillChip
                        key={item.canonical}
                        stat={item}
                        color={TIER_META[item.tier]?.color ?? 'sky'}
                        onSelect={onSelect}
                      />
                    ))}
                  </div>
                </div>
              ),
            )
          )}
        </Column>

        <Column
          title="💤 边缘技能"
          hint="你有、但这个方向几乎不需要 —— 可以暂缓投入，把时间给上面的清单。"
          count={gap.marginal.length}
          tone="slate"
        >
          {gap.marginal.length === 0 ? (
            <EmptyState title="没有边缘技能" hint="你的技能都落在这个方向的需求范围内" />
          ) : (
            gap.marginal.map((name) => (
              <div
                key={name}
                className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-500"
              >
                {name}
              </div>
            ))
          )}
        </Column>
      </div>
    </Card>
  )
}
