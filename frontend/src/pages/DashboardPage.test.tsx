import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { DirectionReport, SessionReport } from '../api/types'
import { DashboardPage } from './DashboardPage'

let session: SessionReport | undefined
let chartShouldFail = false

vi.mock('../api/hooks', () => ({
  useSession: () => ({ data: session, isLoading: false, error: null }),
}))

vi.mock('../components/charts/BarRanking', () => ({
  BarRanking: () => {
    if (chartShouldFail) throw new Error('测试图表故障')
    return <div>技能排行图</div>
  },
}))
vi.mock('../components/charts/GapSwimlane', () => ({ GapSwimlane: () => <div>缺口泳道</div> }))
vi.mock('../components/charts/SkillHeatmap', () => ({ SkillHeatmap: () => <div>技能热力图</div> }))
vi.mock('../components/charts/SkillRadar', () => ({ SkillRadar: () => <div>技能族雷达图</div> }))

function direction(overrides: Partial<DirectionReport> = {}): DirectionReport {
  return {
    direction_id: 1,
    title: '数据分析师',
    match_score: 0.9,
    reason: '技能匹配',
    keywords: ['数据分析'],
    total_jobs: 1,
    ok_jobs: 1,
    failed_jobs: 0,
    languages: [
      {
        canonical: 'Python',
        category: '编程语言',
        count: 1,
        coverage: 1,
        required_count: 1,
        preferred_count: 0,
        required_ratio: 1,
        weighted_score: 1,
        job_ids: ['sample-1'],
        examples: ['熟悉 Python'],
      },
    ],
    hard_skills: [],
    domain_knowledge: [],
    soft_skills: [],
    education: [],
    majors: [],
    experience: [],
    seniority: [],
    certificates: [],
    preferred_qualifications: [],
    gap: {
      coverage_score: 1,
      market_weight: 1,
      covered_weight: 1,
      have: [],
      must_learn: [],
      should_learn: [],
      nice_to_have: [],
      marginal: [],
    },
    jobs: [],
    ...overrides,
  }
}

function report(directions: DirectionReport[]): SessionReport {
  return {
    session_id: 7,
    created_at: '2026-09-27T08:00:00Z',
    status: 'done',
    city: '',
    provider: 'mock',
    model: 'mock-rule-engine',
    input_skills: ['Python'],
    canonical_skills: ['Python'],
    total_jobs: directions.reduce((sum, item) => sum + item.total_jobs, 0),
    directions,
  }
}

function renderDashboard(path = '/sessions/7') {
  return render(
    <MemoryRouter
      initialEntries={[path]}
      future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
    >
      <Routes>
        <Route path="/sessions/:sessionId" element={<DashboardPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  session = undefined
  chartShouldFail = false
})

describe('DashboardPage 降级路径', () => {
  it('可通过 URL 直接打开无样本方向，并解释原因与下一步', () => {
    const empty = direction({
      direction_id: 2,
      title: '机器学习工程师',
      keywords: ['机器学习', '模型部署'],
      total_jobs: 0,
      ok_jobs: 0,
      languages: [],
      gap: {
        coverage_score: 0,
        market_weight: 0,
        covered_weight: 0,
        have: [],
        must_learn: [],
        should_learn: [],
        nice_to_have: [],
        marginal: ['Python'],
      },
    })
    session = report([direction(), empty])

    renderDashboard('/sessions/7?dir=2')

    expect(screen.getByText('这个方向一条 JD 都没采到，因此没有可统计的东西。')).toBeInTheDocument()
    expect(screen.getByText('模型部署')).toBeInTheDocument()
    expect(screen.getByText('无法判断')).toBeInTheDocument()
    expect(screen.queryByText('技能族雷达图')).not.toBeInTheDocument()
  })

  it('会话完全没有方向时显示可行动的空状态', () => {
    session = report([])

    renderDashboard()

    expect(screen.getByText('这个会话没有产生任何方向')).toBeInTheDocument()
    expect(screen.getByText('可能是方向推荐失败，或采集阶段没有拿到任何 JD。')).toBeInTheDocument()
  })

  it('图表渲染异常时保留会话信息并显示局部错误', () => {
    session = report([direction()])
    chartShouldFail = true
    vi.spyOn(console, 'error').mockImplementation(() => undefined)

    renderDashboard()

    expect(screen.getByRole('heading', { name: /报告 #7/ })).toBeInTheDocument()
    expect(screen.getByText('这个面板没能渲染出来：分析看板')).toBeInTheDocument()
    expect(screen.getByText('测试图表故障')).toBeInTheDocument()
    expect(screen.getByText('导出 Markdown')).toBeInTheDocument()
  })

  it('岗位明细提供真实岗位外链和站内证据入口', async () => {
    session = report([
      direction({
        jobs: [
          {
            job_id: 42,
            profile_id: 7,
            id: 'real-42',
            source: 'nowcoder',
            title: '世界模型算法工程师',
            company: 'Example AI',
            city: '杭州',
            url: 'https://www.nowcoder.com/jobs/detail/456905',
            status: 'ok',
          },
        ],
      }),
    ])
    renderDashboard()

    await userEvent.click(screen.getByRole('button', { name: '岗位明细' }))

    expect(screen.getByRole('link', { name: '查看分析证据' })).toHaveAttribute('href', '/jobs/42')
    expect(screen.getByRole('link', { name: /打开真实岗位/ })).toHaveAttribute(
      'href',
      'https://www.nowcoder.com/jobs/detail/456905',
    )
    expect(screen.getByRole('link', { name: /打开真实岗位/ })).toHaveAttribute('target', '_blank')
  })
})
