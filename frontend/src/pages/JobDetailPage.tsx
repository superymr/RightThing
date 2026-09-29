/** ⑤ 单条岗位详情：JD 原文 + 结构化结果 + 证据高亮。
 *
 *  这是「信任」的最终落点 —— 用户不是在看一份被加工过的结论，
 *  而是看着原文，逐条核对模型抽出的每一项。 */

import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { useJob } from '../api/hooks'
import type { SkillItem } from '../api/types'
import { segmentByEvidence } from '../utils/highlight'
import { Badge, Card, EmptyState, ErrorNotice, Spinner, percent } from '../components/ui'

function SkillGroup({
  title,
  items,
  onHover,
}: {
  title: string
  items: SkillItem[]
  onHover: (evidence: string) => void
}) {
  if (items.length === 0) return null
  return (
    <div>
      <h4 className="text-sm font-medium text-slate-700">
        {title} <span className="text-xs text-slate-400">{items.length}</span>
      </h4>
      <div className="mt-2 space-y-1">
        {items.map((item, index) => (
          <div
            key={`${item.name}-${index}`}
            onMouseEnter={() => onHover(item.evidence)}
            onMouseLeave={() => onHover('')}
            className="cursor-help rounded-lg border border-slate-200 px-2.5 py-1.5"
            title={item.evidence}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-slate-700">{item.name}</span>
              <span className="flex items-center gap-1">
                <Badge color={item.required ? 'red' : 'sky'}>
                  {item.required ? '硬性' : '加分'}
                </Badge>
                <span className="text-xs tabular-nums text-slate-400">
                  {percent(item.confidence)}
                </span>
              </span>
            </div>
            {item.evidence && (
              <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-400">
                {item.evidence}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

export function JobDetailPage() {
  const { jobId } = useParams()
  const id = Number(jobId)
  const { data, isLoading, error } = useJob(Number.isFinite(id) ? id : null)
  const [activeEvidence, setActiveEvidence] = useState('')

  const profile = data?.profile ?? null
  const allItems: SkillItem[] = useMemo(() => {
    if (!profile) return []
    return [
      ...profile.programming_languages,
      ...profile.hard_skills,
      ...profile.domain_knowledge,
      ...profile.soft_skills,
    ]
  }, [profile])

  const evidences = useMemo(
    () => allItems.map((item) => item.evidence).filter(Boolean),
    [allItems],
  )

  const segments = useMemo(() => {
    if (!data) return []
    return segmentByEvidence(data.raw_text, evidences, activeEvidence)
  }, [data, evidences, activeEvidence])

  if (isLoading) return <Spinner label="正在读取岗位详情…" />
  if (error) return <ErrorNotice error={error} />
  if (!data) return <EmptyState title="岗位不存在" />

  const orphanCount = evidences.filter((evidence) => !data.raw_text.includes(evidence)).length

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-slate-800">{data.title}</h1>
            <p className="mt-1 text-xs text-slate-500">
              {data.company} · {data.city} · 来源 {data.source} · 抽取模型 {data.model ?? '—'}
              {data.cache_hit && <span className="ml-2 text-emerald-600">缓存命中</span>}
            </p>
          </div>
          <div className="flex gap-2 text-sm">
            {data.session_id && (
              <Link className="text-sky-600 hover:underline" to={`/sessions/${data.session_id}`}>
                ← 返回看板
              </Link>
            )}
          </div>
        </div>

        {/* 幻觉度量：evidence 必须是原文子串。这是这个项目特有的、可量化的质量指标。 */}
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-slate-50 px-3 py-2 text-xs">
          <span className="text-slate-500">
            证据合法率（evidence 必须是原文子串）：
            <strong className="ml-1 text-slate-800">
              {evidences.length === 0
                ? '—'
                : percent((evidences.length - orphanCount) / evidences.length, 0)}
            </strong>
          </span>
          {orphanCount > 0 ? (
            <Badge color="red">{orphanCount} 条证据不在原文中</Badge>
          ) : (
            <Badge color="emerald">全部可回溯</Badge>
          )}
        </div>
      </Card>

      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <Card
          title="JD 原文"
          subtitle="黄色高亮 = 模型给出的证据句所在位置。把鼠标移到右侧技能上，会高亮对应的那一句。"
        >
          <div className="thin-scroll max-h-[70vh] overflow-y-auto rounded-lg bg-slate-50 p-4">
            <p className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-slate-700">
              {segments.map((segment, index) =>
                segment.evidence ? (
                  <mark
                    key={index}
                    className={segment.active ? 'evidence evidence-active' : 'evidence'}
                  >
                    {segment.text}
                  </mark>
                ) : (
                  <span key={index}>{segment.text}</span>
                ),
              )}
            </p>
          </div>
        </Card>

        <div className="space-y-5">
          <Card
            title="结构化抽取结果"
            subtitle="校验失败的字段一律丢弃，所以这里出现的都是通过了契约检查的。"
          >
            {!profile ? (
              <EmptyState
                title="这条 JD 没有抽取成功"
                hint={`抽取状态：${data.extraction_status ?? '未知'}`}
              />
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div className="rounded-lg bg-slate-50 px-3 py-2">
                    <p className="text-slate-400">学历</p>
                    <p className="text-slate-700">{profile.education || '—'}</p>
                  </div>
                  <div className="rounded-lg bg-slate-50 px-3 py-2">
                    <p className="text-slate-400">经验</p>
                    <p className="text-slate-700">{profile.experience_years || '—'}</p>
                  </div>
                  <div className="rounded-lg bg-slate-50 px-3 py-2">
                    <p className="text-slate-400">职级</p>
                    <p className="text-slate-700">{profile.seniority || '—'}</p>
                  </div>
                  <div className="rounded-lg bg-slate-50 px-3 py-2">
                    <p className="text-slate-400">专业</p>
                    <p className="text-slate-700">{profile.major.join('、') || '—'}</p>
                  </div>
                </div>

                <SkillGroup
                  title="编程语言"
                  items={profile.programming_languages}
                  onHover={setActiveEvidence}
                />
                <SkillGroup
                  title="硬技能"
                  items={profile.hard_skills}
                  onHover={setActiveEvidence}
                />
                <SkillGroup
                  title="领域知识"
                  items={profile.domain_knowledge}
                  onHover={setActiveEvidence}
                />
                <SkillGroup
                  title="软技能"
                  items={profile.soft_skills}
                  onHover={setActiveEvidence}
                />

                {profile.preferred_qualifications.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-slate-700">优先考虑对象</h4>
                    <ul className="mt-1 space-y-1 text-xs leading-relaxed text-slate-500">
                      {profile.preferred_qualifications.map((text) => (
                        <li key={text}>· {text}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {profile.responsibilities.length > 0 && (
                  <div>
                    <h4 className="text-sm font-medium text-slate-700">岗位职责</h4>
                    <ul className="mt-1 space-y-1 text-xs leading-relaxed text-slate-500">
                      {profile.responsibilities.map((text) => (
                        <li key={text}>· {text}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
