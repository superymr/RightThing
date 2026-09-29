/**
 * 兜底：单个面板渲染失败时，不让整个页面消失。
 *
 * 这是一个**实际踩过的坑**：某个图表在空数据下抛异常，而异常发生在
 * `useEffect` 里 —— 没有错误边界时 React 会卸载整棵组件树，用户看到的是
 * 一个全白页面，既不知道哪里错了，也不知道是不是自己点错了。
 *
 * 白屏是最糟的失败形态：它把「一个面板画不出来」放大成了「整个产品坏了」。
 * 有了边界，其余面板与所有统计数字都还能正常使用。
 *
 * 注意 React 的错误边界**抓不到**的东西：事件处理器、`setTimeout` 等异步回调、
 * 服务端渲染。图表那条路径已经在 `useChart` 里单独 try/catch 了，
 * 这里负责的是渲染期的意外。
 */

import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  /** 出问题时展示的内容；不给则用默认文案 */
  fallback?: ReactNode
  /** 面板名字，用于提示里指明是哪里失败 */
  label?: string
  children: ReactNode
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 控制台留一份完整堆栈，便于排查；界面上只给一行可读信息
    console.error('[RightThing 正事] 面板渲染失败', this.props.label ?? '', error, info)
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children
    if (this.props.fallback) return this.props.fallback

    return (
      <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-6 text-center">
        <p className="text-sm font-medium text-red-800">
          这个面板没能渲染出来{this.props.label ? `：${this.props.label}` : ''}
        </p>
        <p className="mt-1 text-xs text-red-700">
          页面其余部分不受影响。下方的错误信息可以直接贴出来定位问题。
        </p>
        <p className="mt-2 break-all font-mono text-[11px] text-red-600">{error.message}</p>
        <button
          type="button"
          onClick={() => this.setState({ error: null })}
          className="mt-3 rounded-lg border border-red-300 bg-white px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100"
        >
          重试
        </button>
      </div>
    )
  }
}
