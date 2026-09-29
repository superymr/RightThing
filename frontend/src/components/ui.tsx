/** 一组极小的 UI 原语。刻意不引组件库：这个看板的视觉需求很窄，
 *  为几个按钮和卡片引入一整套设计系统，收益抵不过依赖成本。 */

import type { ReactNode } from 'react'
import { ApiError } from '../api/client'

export function Card({
  title,
  subtitle,
  right,
  children,
  className = '',
}: {
  title?: ReactNode
  subtitle?: ReactNode
  right?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`surface-card rounded-2xl border border-slate-200/80 bg-white p-5 sm:p-6 ${className}`}>
      {(title || right) && (
        <header className="mb-4 flex items-start justify-between gap-3">
          <div>
            {title && <h2 className="text-base font-bold tracking-[-0.01em] text-slate-900">{title}</h2>}
            {subtitle && <p className="mt-1.5 max-w-3xl text-xs leading-relaxed text-slate-500">{subtitle}</p>}
          </div>
          {right}
        </header>
      )}
      {children}
    </section>
  )
}

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

const BUTTON_STYLES: Record<ButtonVariant, string> = {
  primary: 'bg-indigo-600 text-white shadow-sm shadow-indigo-200 hover:bg-indigo-700 disabled:bg-slate-300 disabled:shadow-none',
  secondary: 'border border-slate-300 bg-white text-slate-700 shadow-sm hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700',
  ghost: 'text-slate-500 hover:bg-indigo-50 hover:text-indigo-700',
  danger: 'bg-red-600 text-white hover:bg-red-500',
}

export function Button({
  variant = 'primary',
  className = '',
  children,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-semibold transition duration-200 disabled:cursor-not-allowed disabled:opacity-60 ${BUTTON_STYLES[variant]} ${className}`}
    >
      {children}
    </button>
  )
}

export function Badge({
  children,
  color = 'slate',
  className = '',
}: {
  children: ReactNode
  color?: 'slate' | 'red' | 'amber' | 'sky' | 'emerald' | 'violet'
  className?: string
}) {
  const palette: Record<string, string> = {
    slate: 'bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200/70',
    red: 'bg-red-50 text-red-700',
    amber: 'bg-amber-50 text-amber-700',
    sky: 'bg-sky-50 text-sky-700',
    emerald: 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200/70',
    violet: 'bg-violet-50 text-violet-700',
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${palette[color]} ${className}`}
    >
      {children}
    </span>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600" />
      {label}
    </div>
  )
}

export function EmptyState({ title, hint }: { title: string; hint?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/70 px-4 py-10 text-center">
      <p className="text-sm font-medium text-slate-600">{title}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

/** 统一错误展示。503（上游依赖问题）与 500（本服务 bug）给出不同措辞 ——
 *  这不是文案讲究，而是让用户知道该去改配置还是该来提 issue。 */
export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null
  const apiError = error instanceof ApiError ? error : null
  const isUpstream = apiError?.isUpstream ?? false
  return (
    <div
      className={`rounded-lg border px-4 py-3 text-sm ${
        isUpstream ? 'border-amber-300 bg-amber-50 text-amber-900' : 'border-red-300 bg-red-50 text-red-800'
      }`}
    >
      <p className="font-medium">
        {isUpstream ? '上游依赖不可用（不是本服务的故障）' : '请求失败'}
        {apiError?.code ? ` · ${apiError.code}` : ''}
      </p>
      <p className="mt-1 whitespace-pre-wrap">
        {error instanceof Error ? error.message : String(error)}
      </p>
      {apiError?.hint && <p className="mt-1 text-xs opacity-80">提示：{apiError.hint}</p>}
    </div>
  )
}

/** 百分比展示：coverage 一类字段统一在这里格式化，避免各页面各写一套 */
export function percent(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`
}

export function StatTile({
  label,
  value,
  hint,
  tone = 'slate',
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: 'slate' | 'emerald' | 'red' | 'amber'
}) {
  const tones: Record<string, string> = {
    slate: 'text-slate-800',
    emerald: 'text-emerald-600',
    red: 'text-red-600',
    amber: 'text-amber-600',
  }
  return (
    <div className="stat-tile rounded-2xl border border-slate-200/80 bg-white px-4 py-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tones[tone]}`}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-400">{hint}</p>}
    </div>
  )
}
