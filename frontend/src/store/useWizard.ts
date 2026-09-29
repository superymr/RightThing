/**
 * 本地状态（zustand）。
 *
 * 只放**真正属于前端**的东西：用户正在输入什么、选中了哪些方向、当前任务的 id。
 * 服务端数据一律不进来 —— 那会导致「界面显示的」和「数据库里的」两份真相。
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface WizardState {
  /** 技能输入框的原始文本（保留用户原样，不在这里做清洗） */
  skillsText: string
  city: string
  maxDirections: number
  limitPerDirection: number
  /** 只分析标题匹配该关键词的方向（留空=全部） */
  directionFilter: string
  sourceMode: 'auto' | 'live'
  /** 正在跟踪的后台任务 */
  taskId: string | null
  /** 任务完成后拿到的会话 id */
  sessionId: number | null

  setSkillsText: (value: string) => void
  setCity: (value: string) => void
  setMaxDirections: (value: number) => void
  setLimitPerDirection: (value: number) => void
  setDirectionFilter: (value: string) => void
  setSourceMode: (value: WizardState['sourceMode']) => void
  startTask: (taskId: string) => void
  finishTask: (sessionId: number) => void
  reset: () => void
}

/** 把自由文本拆成技能数组。中英文逗号、换行、分号都当分隔符。 */
export function splitSkills(text: string): string[] {
  return text
    .split(/[,，;；\n\r\t]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

const DEFAULTS = {
  skillsText: '数据分析, Python, ROS, Linux, C++',
  city: '',
  maxDirections: 2,
  limitPerDirection: 35,
  directionFilter: '',
  sourceMode: 'live' as const,
  taskId: null,
  sessionId: null,
}

export const useWizard = create<WizardState>()(
  persist(
    (set) => ({
      ...DEFAULTS,
      setSkillsText: (skillsText) => set({ skillsText }),
      setCity: (city) => set({ city }),
      setMaxDirections: (maxDirections) => set({ maxDirections }),
      setLimitPerDirection: (limitPerDirection) => set({ limitPerDirection }),
      setDirectionFilter: (directionFilter) => set({ directionFilter }),
      setSourceMode: (sourceMode) => set({ sourceMode }),
      startTask: (taskId) => set({ taskId, sessionId: null }),
      finishTask: (sessionId) => set({ sessionId }),
      reset: () => set({ taskId: null, sessionId: null }),
    }),
    {
      name: 'jobradar-wizard',
      version: 3,
      migrate: (persisted) => {
        const state = persisted as Partial<WizardState>
        return {
          ...state,
          limitPerDirection: Math.max(35, state.limitPerDirection ?? 35),
        } as WizardState
      },
      // 任务 id 是进程内的，刷新后没有意义；持久化它只会让人误解
      partialize: (state) => ({
        skillsText: state.skillsText,
        city: state.city,
        maxDirections: state.maxDirections,
        limitPerDirection: state.limitPerDirection,
        sourceMode: state.sourceMode,
      }),
    },
  ),
)
