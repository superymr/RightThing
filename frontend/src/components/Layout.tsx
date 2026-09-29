/** 全局布局：品牌导航 + 服务状态。 */

import { NavLink, Outlet } from 'react-router-dom'

import { useHealth } from '../api/hooks'
import { ErrorBoundary } from './ErrorBoundary'
import { Badge } from './ui'

function HealthBadge() {
  const { data, isLoading, error } = useHealth()

  if (isLoading) return <Badge color="slate">检测服务中…</Badge>
  if (error) return <Badge color="red">后端未连接</Badge>
  if (!data) return null

  const ok = data.status === 'ok' && data.llm_ready
  return (
    <span
      className="flex items-center gap-1.5"
      title={`${data.provider} / ${data.model} · ${data.detail || '正常'}`}
    >
      <Badge color={ok ? 'emerald' : 'amber'}>
        {ok ? '● 服务正常' : '▲ 需配置'}
      </Badge>
      <span className="hidden text-xs text-slate-400 lg:inline">
        {data.provider} · {data.model}
      </span>
    </span>
  )
}

const NAV = [
  { to: '/', label: '开始分析', end: true },
  { to: '/history', label: '分析记录', end: false },
  { to: '/settings', label: 'API 设置', end: false },
]

export function Layout() {
  return (
    <div className="app-shell flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1440px] items-center gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <NavLink to="/" className="group flex items-center gap-3" aria-label="RightThing 正事首页">
            <span className="brand-mark">R</span>
            <span className="leading-none">
              <span className="block text-base font-bold tracking-[-0.02em] text-slate-950">
                RightThing
              </span>
              <span className="mt-1 block text-[10px] font-medium tracking-[0.22em] text-slate-400">
                正事 · 职业决策助手
              </span>
            </span>
          </NavLink>

          <nav className="ml-2 hidden items-center gap-1 rounded-xl bg-slate-100/80 p-1 sm:flex">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-lg px-3.5 py-1.5 text-sm font-medium transition ${
                    isActive
                      ? 'bg-white text-indigo-700 shadow-sm ring-1 ring-slate-200/70'
                      : 'text-slate-500 hover:text-slate-900'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto hidden sm:block">
            <HealthBadge />
          </div>
        </div>
      </header>

      <nav className="fixed inset-x-4 bottom-4 z-40 flex items-center justify-around rounded-2xl border border-slate-200/80 bg-white/95 p-1.5 shadow-2xl shadow-slate-300/60 backdrop-blur-xl sm:hidden">
        {NAV.map((item) => (
          <NavLink
            key={`mobile-${item.to}`}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `flex-1 rounded-xl px-3 py-2 text-center text-sm font-semibold transition ${
                isActive ? 'bg-indigo-600 text-white' : 'text-slate-500'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <main className="mx-auto w-full max-w-[1440px] flex-1 overflow-x-hidden px-4 py-6 pb-24 sm:px-6 sm:pb-6 lg:px-8 lg:py-8">
        <ErrorBoundary label="页面">
          <Outlet />
        </ErrorBoundary>
      </main>

      <footer className="border-t border-slate-200/70 bg-white/60 px-5 py-5 text-center text-xs leading-relaxed text-slate-400 backdrop-blur">
        <strong className="font-semibold text-slate-500">RightThing 正事</strong>
        <span className="mx-2 text-slate-300">·</span>
        用真实岗位回答职业选择，每个统计结果都可回溯到原始 JD 与证据句。
      </footer>
    </div>
  )
}
