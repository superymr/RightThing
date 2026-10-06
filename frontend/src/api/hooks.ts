/**
 * 数据层：所有服务端状态都走 TanStack Query，本地状态走 zustand（见 store/）。
 *
 * 这里刻意**不缓存分析结果到本地状态里**：看板的权威来源永远是
 * `GET /api/sessions/{id}`（后端从数据库读回），前端只负责展示。
 * 一旦把结果拷进 store，就会和「服务重启后历史仍可查」这条设计对着干。
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { api, ApiError, subscribeTaskEvents } from './client'
import type {
  AnalysisSummary,
  DirectionOption,
  HealthInfo,
  JobDetail,
  NormalizedSkill,
  ProgressEvent,
  SessionBrief,
  SessionReport,
  TaskStarted,
  TaskState,
} from './types'

export const queryKeys = {
  health: ['health'] as const,
  directions: ['directions'] as const,
  sessions: ['sessions'] as const,
  session: (id: number) => ['session', id] as const,
  job: (id: number) => ['job', id] as const,
}

export function useHealth(): UseQueryResult<HealthInfo> {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: () => api.get<HealthInfo>('/api/health'),
    staleTime: 30_000,
  })
}

export function useDirections(): UseQueryResult<DirectionOption> {
  return useQuery({
    queryKey: queryKeys.directions,
    queryFn: () => api.get<DirectionOption>('/api/directions'),
    staleTime: 5 * 60_000,
  })
}

export function useSessions(limit = 30, enabled = true): UseQueryResult<{ sessions: SessionBrief[] }> {
  return useQuery({
    queryKey: [...queryKeys.sessions, limit],
    queryFn: () => api.get<{ sessions: SessionBrief[] }>(`/api/sessions?limit=${limit}`),
    enabled,
  })
}

export function useSession(sessionId: number | null): UseQueryResult<SessionReport> {
  return useQuery({
    queryKey: queryKeys.session(sessionId ?? -1),
    queryFn: () => api.get<SessionReport>(`/api/sessions/${sessionId}`),
    enabled: sessionId !== null && sessionId > 0,
  })
}

export function useJob(jobId: number | null): UseQueryResult<JobDetail> {
  return useQuery({
    queryKey: queryKeys.job(jobId ?? -1),
    queryFn: () => api.get<JobDetail>(`/api/jobs/${jobId}`),
    enabled: jobId !== null && jobId > 0,
  })
}

/** 归一化预览：跑分析**之前**先让用户确认「系统是怎么理解我的输入的」 */
export function useNormalizeSkills() {
  return useMutation({
    mutationFn: (skills: string[]) =>
      api.post<{ items: NormalizedSkill[] }>('/api/skills/normalize', { skills }),
  })
}

export interface AnalyzeInput {
  skills: string[]
  city?: string
  max_directions?: number
  limit_per_direction?: number
  direction_filter?: string
  source_mode?: 'auto' | 'sample' | 'live' | 'hybrid'
  jd_texts?: string[]
  job_urls?: string[]
}

/** 启动一次分析，返回 task_id（后端默认异步） */
export function useStartAnalysis() {
  return useMutation({
    mutationFn: (input: AnalyzeInput) => api.post<TaskStarted>('/api/analyze', input),
  })
}

export interface TaskProgress {
  events: ProgressEvent[]
  last: ProgressEvent | null
  /** 归一化 → 抽取 的总体进度（0~1），无法判断时为 null */
  ratio: number | null
  status: string
  result: AnalysisSummary | null
  error: string
  finished: boolean
}

/**
 * 跟踪一个后台任务。
 *
 * 双通道设计（与后端的两个接口一一对应）：
 * - **SSE**：实时进度，事件由后端回放历史，晚连也不丢步骤；
 * - **轮询**：每 3 秒查一次任务状态 —— 反向代理掐断 SSE 时这是唯一兜底，
 *   而且它同时负责判定「任务真的结束了」，避免前端靠猜。
 */
export function useTaskProgress(taskId: string | null): TaskProgress {
  const [events, setEvents] = useState<ProgressEvent[]>([])
  const [task, setTask] = useState<TaskState | null>(null)
  const finishedRef = useRef(false)

  useEffect(() => {
    if (!taskId) return
    finishedRef.current = false
    setEvents([])
    setTask(null)

    const stop = subscribeTaskEvents(taskId, {
      onEvent: (raw) => {
        const event = raw as unknown as ProgressEvent
        setEvents((prev) => [...prev, event])
        if (event.stage === 'done' || event.stage === 'failed' || event.stage === 'error') {
          finishedRef.current = true
        }
      },
    })

    let timer: number | undefined
    const poll = async () => {
      try {
        const state = await api.get<TaskState>(`/api/tasks/${taskId}`)
        setTask(state)
        if (['done', 'failed', 'canceled', 'interrupted'].includes(state.status)) {
          finishedRef.current = true
          stop()
          if (timer) window.clearInterval(timer)
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          setTask({ task_id: taskId, kind: 'analyze', status: 'interrupted',
            created_at: '', started_at: '', finished_at: '', event_count: 0,
            last_event: null, result: null,
            error: '任务已不存在，请重新发起分析或查看历史报告。' })
          stop()
          if (timer) window.clearInterval(timer)
        }
      }
    }
    void poll()
    timer = window.setInterval(poll, 3000)

    return () => {
      stop()
      if (timer) window.clearInterval(timer)
    }
  }, [taskId])

  const last = events.length ? events[events.length - 1] : (task?.last_event ?? null)
  const extractEvent = [...events].reverse().find((e) => e.stage === 'extract' && e.total)
  const ratio = extractEvent && extractEvent.total ? extractEvent.current! / extractEvent.total : null

  return {
    events,
    last,
    ratio,
    status: task?.status ?? 'running',
    result: task?.result ?? null,
    error: task?.error ?? '',
    finished: ['done', 'failed', 'canceled', 'interrupted'].includes(task?.status ?? ''),
  }
}

/** 分析完成后让历史列表与看板缓存失效，避免看到旧数据 */
export function useInvalidateAfterAnalyze() {
  const client = useQueryClient()
  return () => {
    void client.invalidateQueries({ queryKey: queryKeys.sessions })
  }
}
