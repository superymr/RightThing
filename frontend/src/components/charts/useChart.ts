/**
 * ECharts 的 React 封装。
 *
 * 要点有三个，漏掉任何一个都会产生难查的问题：
 *
 * 1. **实例必须 dispose**：图表挂在 flex 布局里，组件卸载后实例不销毁会持续持有 DOM；
 * 2. **resize 必须监听**：侧栏折叠/窗口变化时 canvas 不会自己跟着变，
 *    表现是「图表被拉伸变形」，而且只在特定窗口尺寸下复现；
 * 3. **setOption 必须被 try/catch 包住** —— 这条是踩坑之后补的，见下。
 *
 * ---
 * 关于第 3 点：ECharts 在某些空数据下会**直接抛异常**。已确认的一例是
 * radar 拿到空 `indicator` 数组时抛 `TypeError: Cannot read properties of
 * undefined (reading 'push')`。
 *
 * 这个异常发生在 `useEffect` 里，而 React 会把 effect 里的异常交给最近的
 * 错误边界 —— 没有错误边界时，**整棵组件树会被卸载，页面直接白屏**。
 * 用户看到的是一个全白的页面，既不知道哪里错了，也不知道是不是自己点错了。
 *
 * 一个图表因为数据为空而画不出来，绝不该让整个看板消失。所以这里把异常
 * 收在组件内部，通过返回值交给调用方渲染一个局部占位。
 */

import * as echarts from 'echarts'
import { useEffect, useRef, useState } from 'react'

export type ChartRef = React.RefObject<HTMLDivElement>

export function useChart(
  option: echarts.EChartsOption,
  deps: unknown[] = [],
  onEvents?: Record<string, (params: unknown) => void>,
): [ChartRef, string] {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)
  const [error, setError] = useState('')
  const eventsRef = useRef(onEvents)
  eventsRef.current = onEvents

  useEffect(() => {
    if (!containerRef.current) return
    const chart = echarts.init(containerRef.current, undefined, { renderer: 'canvas' })
    chartRef.current = chart

    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(containerRef.current)

    return () => {
      observer.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    try {
      // notMerge=true：排行/筛选切换时条目数会变，合并会把上一次的多余数据留下来
      chart.setOption(option, true)
      setError('')
    } catch (cause) {
      // 画不出来就说清楚画不出来，而不是把整页带走
      setError(cause instanceof Error ? cause.message : String(cause))
      return
    }
    const handlers = eventsRef.current
    if (handlers) {
      for (const [name, handler] of Object.entries(handlers)) {
        chart.off(name)
        chart.on(name, (params: unknown) => handler(params))
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return [containerRef, error]
}
