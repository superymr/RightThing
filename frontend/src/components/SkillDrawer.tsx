/** 技能 → 原始 JD 回溯侧栏。
 *
 *  「任何一个统计数字都要能点回原文」是本项目的核心交互约束（PLAN 第 4.7 节）。
 *  没有它，用户只能相信数字；有了它，用户能自己判断数字对不对，
 *  也能顺手看出模型有没有编造（evidence 不在原文里的抽取是可见的错误）。
 */

import { useEffect, useMemo, useState } from 'react'

import { useJob } from '../api/hooks'
import type { DirectionReport, JobBrief, SkillStat } from '../api/types'
import { excerptAround, segmentByEvidence } from '../utils/highlight'
import { Badge, Button, EmptyState, Spinner, percent } from './ui'

function EvidenceText({
  rawText,
  evidences,
  onlyEvidence,
}: {
  rawText: string
  evidences: string[]
  onlyEvidence: boolean
}) {
  const body = useMemo(() => {
    if (!onlyEvidence) return rawText
    return evidences.map((item) => excerptAround(rawText, item)).join('\n\n———\n\n')
  }, [rawText, evidences, onlyEvidence])

  const segments = useMemo(() => segmentByEvidence(body, evidences), [body, evidences])

  return (
    <p className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-slate-600">
      {segments.map((segment, index) =>
        segment.evidence ? (
          <mark key={index} className="evidence">
            {segment.text}
          </mark>
        ) : (
          <span key={index}>{segment.text}</span>
        ),
      )}
    </p>
  )
}

function JobEvidenceCard({
  job,
  skillName,
  defaultOpen,
}: {
  job: JobBrief
  skillName: string
  defaultOpen: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const [onlyEvidence, setOnlyEvidence] = useState(false)
  const { data, isLoading, error } = useJob(open ? job.job_id : null)

  const matches = useMemo(() => {
    if (!data?.profile) return []
    const target = skillName.trim().toLowerCase()
    const all = [
      ...data.profile.programming_languages,
      ...data.profile.hard_skills,
      ...data.profile.domain_knowledge,
      ...data.profile.soft_skills,
    ]
    return all.filter((item) => item.name.trim().toLowerCase() === target)
  }, [data, skillName])

  const evidences = matches.map((item) => item.evidence).filter(Boolean)

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start justify-between gap-2 px-3 py-2.5 text-left hover:bg-slate-50"
      >
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-slate-800">{job.title}</p>
          <p className="truncate text-xs text-slate-500">
            {job.company} · {job.city} · {job.source}
          </p>
        </div>
        <span className="shrink-0 text-xs text-slate-400">{open ? '收起' : '展开'}</span>
      </button>

      {open && (
        <div className="border-t border-slate-100 px-3 py-3">
          {isLoading && <Spinner label="正在读取 JD 原文…" />}
          {error != null && (
            <p className="text-xs text-red-600">读取失败：{String(error)}</p>
          )}
          {data && (
            <>
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                {matches.map((item, index) => (
                  <Badge key={index} color={item.required ? 'red' : 'sky'}>
                    {item.required ? '硬性要求' : '加分项'} · {item.category || '未分类'}
                  </Badge>
                ))}
                <label className="ml-auto flex cursor-pointer items-center gap-1 text-slate-500">
                  <input
                    type="checkbox"
                    checked={onlyEvidence}
                    onChange={(event) => setOnlyEvidence(event.target.checked)}
                  />
                  只看证据句
                </label>
                {data.url && (
                  <a
                    className="text-sky-600 hover:underline"
                    href={data.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    原始链接
                  </a>
                )}
              </div>
              <div className="thin-scroll max-h-64 overflow-y-auto rounded-md bg-slate-50 p-3">
                <EvidenceText
                  rawText={data.raw_text}
                  evidences={evidences}
                  onlyEvidence={onlyEvidence}
                />
              </div>
              {evidences.length === 0 && (
                <p className="mt-1 text-xs text-amber-600">
                  该 JD 的抽取结果里没有带出证据句（可能是缓存中的旧版本数据）。
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

export function SkillDrawer({
  skill,
  direction,
  onClose,
}: {
  skill: SkillStat | null
  direction: DirectionReport
  onClose: () => void
}) {
  // Esc 关闭：侧栏是覆盖式面板，不给键盘出口会让人以为界面卡住了
  useEffect(() => {
    if (!skill) return
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [skill, onClose])

  if (!skill) return null

  const related = direction.jobs.filter((job) => skill.job_ids.includes(job.id))

  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <button
        type="button"
        aria-label="关闭"
        onClick={onClose}
        className="flex-1 bg-slate-900/30 backdrop-blur-[1px]"
      />
      <aside className="thin-scroll flex h-full w-full max-w-xl flex-col overflow-y-auto bg-slate-50 shadow-2xl">
        <header className="sticky top-0 z-10 border-b border-slate-200 bg-white px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-800">{skill.canonical}</h2>
              <p className="mt-1 text-xs text-slate-500">
                {skill.category} · 方向：{direction.title}
              </p>
            </div>
            <Button variant="ghost" onClick={onClose}>
              关闭
            </Button>
          </div>
          <div className="mt-3 grid grid-cols-4 gap-2 text-center">
            {[
              { label: '岗位数', value: String(skill.count) },
              { label: '覆盖率', value: percent(skill.coverage) },
              { label: '必须占比', value: percent(skill.required_ratio) },
              { label: '加权分', value: String(skill.weighted_score) },
            ].map((item) => (
              <div key={item.label} className="rounded-lg bg-slate-100 py-2">
                <p className="text-xs text-slate-500">{item.label}</p>
                <p className="text-sm font-semibold tabular-nums text-slate-800">{item.value}</p>
              </div>
            ))}
          </div>
        </header>

        <div className="flex-1 space-y-2 p-5">
          <p className="text-xs text-slate-500">
            以下 {related.length} 个岗位提到了它，证据句已在下文高亮。
          </p>
          {related.length === 0 ? (
            <EmptyState
              title="没有找到相关岗位"
              hint="该技能的 job_ids 与当前方向的岗位列表没有交集（可能是历史数据）"
            />
          ) : (
            related.map((job, index) => (
              <JobEvidenceCard
                key={job.job_id}
                job={job}
                skillName={skill.canonical}
                defaultOpen={index === 0}
              />
            ))
          )}
        </div>
      </aside>
    </div>
  )
}
