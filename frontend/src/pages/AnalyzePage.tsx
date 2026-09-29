/** ② 方向选择页 + 长任务进度。
 *
 *  一次分析要几十秒到几分钟，所以页面必须在两件事上都给反馈：
 *  「现在进行到哪一步」和「还要多久」。后端为此提供了 SSE 事件流，
 *  这里把事件渲染成时间线，并把抽取进度画成进度条。 */

import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { useInvalidateAfterAnalyze, useTaskProgress } from '../api/hooks'
import type { ProgressEvent } from '../api/types'
import { Badge, Button, Card, EmptyState, ErrorNotice, Spinner, percent } from '../components/ui'
import { useWizard } from '../store/useWizard'
import { cancelTask } from '../api/client'

const STAGE_LABELS: Record<string, string> = {
  normalize: '归一化技能',
  directions: '推荐岗位方向',
  sanitize: '脱敏个人信息',
  collect: '采集 JD',
  extract: '结构化抽取',
  canonicalize: '收敛自由文本',
  aggregate: '聚合统计',
  done: '完成',
  failed: '失败',
  error: '出错',
  canceled: '已取消',
}

function EventRow({ event }: { event: ProgressEvent }) {
  const isProblem = event.stage === 'failed' || event.stage === 'error'
  return (
    <li className="flex gap-3">
      <span
        className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
          isProblem ? 'bg-red-500' : event.stage === 'done' ? 'bg-emerald-500' : 'bg-slate-300'
        }`}
      />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-slate-700">
          <span className="font-medium">{STAGE_LABELS[event.stage] ?? event.stage}</span>
          {event.direction && <span className="text-slate-400"> · {event.direction}</span>}
        </p>
        <p className="truncate text-xs text-slate-500">{event.message}</p>
      </div>
      {event.total != null && event.total > 0 && (
        <span className="shrink-0 self-center text-xs tabular-nums text-slate-400">
          {event.current}/{event.total}
        </span>
      )}
    </li>
  )
}

export function AnalyzePage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const wizard = useWizard()
  const invalidate = useInvalidateAfterAnalyze()
  const [canceling, setCanceling] = useState(false)

  const taskId = params.get('task') ?? wizard.taskId
  const progress = useTaskProgress(taskId)

  // 分析落库后会多出一条历史会话，让列表缓存失效即可
  useEffect(() => {
    if (progress.finished && progress.status === 'done') invalidate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [progress.finished, progress.status])

  useEffect(() => {
    if (progress.result?.session_id) wizard.finishTask(progress.result.session_id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [progress.result?.session_id])

  if (!taskId) {
    return (
      <Card title="没有正在进行的分析">
        <EmptyState
          title="还没有任务"
          hint={
            <>
              请先到 <Link className="text-sky-600 hover:underline" to="/">技能录入</Link> 发起一次分析。
            </>
          }
        />
      </Card>
    )
  }

  const summary = progress.result
  const sessionId = summary?.session_id ?? wizard.sessionId

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_1.3fr]">
      <Card
        title="分析进度"
        subtitle="进度事件由后端留档并回放，所以刷新页面或晚连都不会丢步骤。"
        right={<Badge color={progress.status === 'done' ? 'emerald' : 'slate'}>{progress.status}</Badge>}
      >
        {!progress.finished && (
          <div className="mb-4 flex justify-end">
            <Button
              variant="secondary"
              disabled={canceling}
              onClick={async () => {
                setCanceling(true)
                try {
                  await cancelTask(taskId)
                } finally {
                  setCanceling(false)
                }
              }}
            >
              {canceling ? '正在取消…' : '取消任务'}
            </Button>
          </div>
        )}
        {progress.ratio !== null && (
          <div className="mb-4">
            <div className="mb-1 flex justify-between text-xs text-slate-500">
              <span>抽取进度</span>
              <span className="tabular-nums">{percent(progress.ratio)}</span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-slate-800 transition-all"
                style={{ width: `${Math.round(progress.ratio * 100)}%` }}
              />
            </div>
          </div>
        )}

        {progress.events.length === 0 && !progress.finished && (
          <Spinner label="等待第一个进度事件…" />
        )}

        <ul className="thin-scroll max-h-[420px] space-y-3 overflow-y-auto pr-1">
          {progress.events.slice(-60).map((event, index) => (
            <EventRow key={`${event.at}-${index}`} event={event} />
          ))}
        </ul>

        {progress.error && (
          <div className="mt-3">
            <ErrorNotice error={new Error(progress.error)} />
          </div>
        )}
      </Card>

      <div className="space-y-5">
        {summary && (
          <Card
            title="推荐方向"
            subtitle="匹配度由大模型估计，仅作排序参考；真正的判断依据是右边每个方向的真实 JD 统计。"
            right={
              sessionId ? (
                <Button onClick={() => navigate(`/sessions/${sessionId}`)}>打开完整看板</Button>
              ) : undefined
            }
          >
            <div className="space-y-3">
              {summary.directions.map((direction) => (
                <div
                  key={direction.title}
                  className="rounded-xl border border-slate-200 p-4 transition hover:border-slate-300"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <h3 className="text-base font-semibold text-slate-800">{direction.title}</h3>
                    <span className="text-sm tabular-nums text-slate-500">
                      {(direction.match_score * 100).toFixed(0)}
                      <span className="ml-1 text-xs text-slate-400">AI 估计</span>
                    </span>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-slate-500">{direction.reason}</p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {direction.keywords.slice(0, 6).map((keyword) => (
                      <Badge key={keyword} color="slate">
                        {keyword}
                      </Badge>
                    ))}
                  </div>
                  <div className="mt-3 flex flex-wrap gap-4 text-xs text-slate-500">
                    <span>已采集 {direction.total_jobs} 条</span>
                    <span>解析成功 {direction.ok_jobs} 条</span>
                    {direction.failed_jobs > 0 && (
                      <span className="text-amber-600">失败 {direction.failed_jobs} 条</span>
                    )}
                    <span>要求权重覆盖率 {percent(direction.coverage_score, 1)}</span>
                  </div>
                </div>
              ))}

              <div className="flex items-center justify-between rounded-lg bg-slate-50 px-4 py-3 text-xs text-slate-500">
                <span>
                  {summary.provider} · {summary.model} · 耗时 {summary.duration_sec}s · 共{' '}
                  {summary.total_jobs} 条 JD
                </span>
                {sessionId && (
                  <Link className="text-sky-600 hover:underline" to={`/sessions/${sessionId}`}>
                    查看看板 →
                  </Link>
                )}
              </div>

              {summary.provider === 'mock' && (
                <p className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-xs leading-relaxed text-amber-900">
                  ⚠ 本次用的是本地规则引擎（mock），<strong>没有调用大模型</strong>。
                  零成本、完全确定性，适合验证流程；要看真实模型的结果，请在 <code>.env</code> 里配置{' '}
                  <code>LLM_PROVIDER=openai</code> 与 <code>LLM_API_KEY</code> 后重新分析。
                </p>
              )}
            </div>
          </Card>
        )}

        {!summary && (
          <Card title="正在准备">
            <EmptyState
              title="分析进行中"
              hint="方向推荐与统计结果会在任务完成后出现在这里；期间可以切到「历史分析」查看往期结果。"
            />
          </Card>
        )}
      </div>
    </div>
  )
}
