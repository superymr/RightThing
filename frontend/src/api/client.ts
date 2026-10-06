/**
 * HTTP 客户端。
 *
 * 只做三件事：拼 URL、解统一错误契约、把 4xx/5xx 变成可判断的异常。
 * **不在这里做业务判断** —— 与后端 `api/` 层的分工保持一致。
 */

const BASE = import.meta.env.VITE_API_BASE ?? ''

export interface ApiErrorBody {
  code: string
  message: string
  detail?: unknown
}

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly detail: unknown

  constructor(status: number, body: ApiErrorBody) {
    super(body.message || `请求失败（HTTP ${status}）`)
    this.name = 'ApiError'
    this.code = body.code || 'unknown'
    this.status = status
    this.detail = body.detail
  }

  /**
   * 上游依赖问题（没配 Key / 调用失败）在后端是 503 而非 500，
   * 前端据此给出「去改配置」而不是「重试」的提示 —— 这是 503/500 分开的意义。
   */
  get isUpstream(): boolean {
    return this.code === 'llm_not_configured' || this.code === 'llm_unavailable'
  }

  /** 把 detail.hint 之类的补充信息拼成可展示的一行 */
  get hint(): string {
    const detail = this.detail
    if (detail && typeof detail === 'object' && 'hint' in detail) {
      const hint = (detail as { hint?: unknown }).hint
      if (typeof hint === 'string') return hint
    }
    return ''
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody = { code: 'unknown', message: `HTTP ${response.status}` }
  try {
    const payload = await response.json()
    if (payload && typeof payload === 'object' && 'error' in payload) {
      body = (payload as { error: ApiErrorBody }).error
    } else if (payload && typeof payload === 'object' && 'detail' in payload) {
      // FastAPI 自带的参数校验错误（例如 422）走的是 {"detail": ...}
      body = { code: 'validation_error', message: '请求参数不合法', detail: payload.detail }
    }
  } catch {
    // 响应体不是 JSON（例如代理返回的 502 页面），保留状态码即可
  }
  return new ApiError(response.status, body)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch (cause) {
    throw new ApiError(0, {
      code: 'network_error',
      message: '无法连接到后端服务，请确认它已启动（python -m app.cli serve）',
      detail: String(cause),
    })
  }
  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
}

export function cancelTask(taskId: string): Promise<{ cancel_requested: boolean }> {
  return api.post(`/api/tasks/${taskId}/cancel`, {})
}

/**
 * 拼一个可直接放进 `href` 的地址。
 *
 * 导出报告走的是浏览器原生下载（Content-Disposition: attachment），
 * 用 fetch 取回来再造 Blob 反而会把文件名和编码都搞复杂。所以这里只需要
 * 把 base 拼对，剩下的交给浏览器。
 */
export function apiUrl(path: string): string {
  return `${BASE}${path}`
}

/**
 * 订阅 SSE 进度流。
 *
 * 后端会**回放历史事件**，所以晚连也能看到已经发生过的步骤；
 * 这里只需要忠实转发，不做去重或状态推断。
 */
export function subscribeTaskEvents(
  taskId: string,
  handlers: {
    onEvent: (event: Record<string, unknown>) => void
    onDone?: () => void
    onError?: (error: unknown) => void
  },
): () => void {
  const source = new EventSource(`${BASE}/api/tasks/${taskId}/events`)
  const forward = (name: string) => (raw: MessageEvent) => {
    try {
      handlers.onEvent({ event: name, ...JSON.parse(raw.data) })
    } catch {
      handlers.onEvent({ event: name, message: raw.data })
    }
  }

  // 事件名就是 ProgressEvent.stage（见 tasks.py :: _format_sse）。
  // 这里必须逐个注册具名事件 —— SSE 的 event: 字段不会触发 onmessage。
  const STAGES = [
    'normalize',
    'directions',
    'sanitize',
    'collect',
    'extract',
    'aggregate',
    'done',
    'failed',
    'canceled',
    'interrupted',
    'error',
  ]
  for (const stage of STAGES) {
    source.addEventListener(stage, forward(stage) as EventListener)
  }

  source.onerror = (error) => {
    // EventSource 会自动重连；只有在流已结束时才需要通知调用方
    if (source.readyState === EventSource.CLOSED) {
      handlers.onError?.(error)
      handlers.onDone?.()
    }
  }

  return () => source.close()
}
