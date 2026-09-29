/** ① 技能录入页。
 *
 *  两步式（先归一化预览、再跑分析）不是 UI 装饰：归一化错了，后面所有统计都是错的。
 *  让用户在花钱调模型之前先确认「系统是怎么理解我的输入的」，是成本最低的一道校验。 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { useDirections, useHealth, useNormalizeSkills, useStartAnalysis } from '../api/hooks'
import type { NormalizedSkill } from '../api/types'
import { splitSkills, useWizard } from '../store/useWizard'
import { Badge, Button, Card, ErrorNotice, Spinner } from '../components/ui'

const EXAMPLES: Array<{ label: string; skills: string }> = [
  { label: '机器人算法', skills: 'ROS, C++, Linux, SLAM, 运动规划' },
  { label: '数据分析', skills: 'Python, SQL, Excel, 数据可视化, 统计学' },
  { label: '转行试探', skills: '数据分析, Python, ROS, Linux, C++' },
]

export function SkillInputPage() {
  const navigate = useNavigate()
  const wizard = useWizard()
  const health = useHealth()
  const directions = useDirections()
  const normalize = useNormalizeSkills()
  const start = useStartAnalysis()
  const [preview, setPreview] = useState<NormalizedSkill[] | null>(null)
  const [jobUrlsText, setJobUrlsText] = useState('')

  const skills = splitSkills(wizard.skillsText)
  const jobUrls = jobUrlsText.split(/\s+/).map((item) => item.trim()).filter(Boolean)
  const canAnalyze = skills.length > 0 || jobUrls.length > 0
  const isMock = health.data?.provider === 'mock'

  const runPreview = () => {
    if (!canAnalyze) return
    normalize.mutate(skills, { onSuccess: (data) => setPreview(data.items) })
  }

  const runAnalysis = () => {
    if (skills.length === 0) return
    start.mutate(
      {
        skills,
        city: wizard.city,
        max_directions: wizard.maxDirections,
        limit_per_direction: wizard.limitPerDirection,
        source_mode: wizard.sourceMode,
        job_urls: jobUrls,
      },
      {
        onSuccess: (task) => {
          wizard.startTask(task.task_id)
          navigate(`/analyze?task=${task.task_id}`)
        },
      },
    )
  }

  return (
    <>
      <section className="mb-6 overflow-hidden rounded-3xl border border-indigo-100/80 bg-gradient-to-br from-indigo-600 via-indigo-600 to-violet-700 px-6 py-7 text-white shadow-xl shadow-indigo-200/40 sm:px-8 sm:py-9">
        <div className="max-w-3xl">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-indigo-200">
            RightThing · 做职业选择这件正事
          </p>
          <h1 className="mt-3 break-words text-2xl font-bold tracking-[-0.03em] sm:text-3xl">
            别只看“我会什么”，看看市场真正要什么
          </h1>
          <p className="mt-3 max-w-2xl break-words text-sm leading-7 text-indigo-100">
            输入你的技能，RightThing 会从中国大陆真实岗位中寻找对口方向，统计共同要求，
            再把下一步该补什么说清楚。
          </p>
          <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-xs text-indigo-100">
            <span>✓ 真实招聘岗位</span>
            <span>✓ 每条结论可回溯</span>
            <span>✓ 只统计中国大陆职位</span>
          </div>
        </div>
      </section>

      <div className="grid min-w-0 gap-5 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-5">
        <Card
          title="先说说，你会什么？"
          subtitle="逗号、分号或换行分隔。写得越具体，方向推荐与缺口分析越准；用日常叫法即可，系统会做别名归一化。"
        >
          <textarea
            value={wizard.skillsText}
            onChange={(event) => {
              wizard.setSkillsText(event.target.value)
              setPreview(null)
            }}
            rows={5}
            spellCheck={false}
            placeholder="例如：Python, SQL, ROS, Linux, C++"
            className="max-w-full resize-y rounded-xl border border-slate-300 px-4 py-3 text-sm leading-relaxed outline-none transition focus:border-indigo-400 focus:ring-4 focus:ring-indigo-100"
          />

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-500">试试：</span>
            {EXAMPLES.map((example) => (
              <button
                key={example.label}
                type="button"
                onClick={() => {
                  wizard.setSkillsText(example.skills)
                  setPreview(null)
                }}
                className="rounded-full border border-slate-200 bg-slate-50/70 px-3 py-1 text-xs text-slate-600 transition hover:border-indigo-200 hover:bg-indigo-50 hover:text-indigo-700"
              >
                {example.label}
              </button>
            ))}
            <span className="ml-auto text-xs text-slate-400">已识别 {skills.length} 项</span>
          </div>

          {skills.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {skills.map((skill) => (
                <Badge key={skill} color="slate">
                  {skill}
                </Badge>
              ))}
            </div>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant="secondary" onClick={runPreview} disabled={normalize.isPending || skills.length === 0}>
              {normalize.isPending ? '归一化中…' : '预览归一化结果'}
            </Button>
            <Button onClick={runAnalysis} disabled={start.isPending || !canAnalyze}>
              {start.isPending ? '正在启动…' : '开始分析'}
            </Button>
            {isMock && (
              <span className="self-center text-xs text-slate-400">
                当前是 mock 规则引擎：零成本、完全确定性，适合先跑通流程
              </span>
            )}
          </div>

          <div className="mt-3 space-y-2">
            <ErrorNotice error={normalize.error} />
            <ErrorNotice error={start.error} />
          </div>
        </Card>

        {preview && (
          <Card
            title="归一化预览"
            subtitle="左边是你写的，右边是系统实际用于统计的规范名。列出的「新词」会以自身为规范名登记，词表随使用逐渐变准。"
          >
            <div className="overflow-hidden rounded-lg border border-slate-200">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">你的输入</th>
                    <th className="px-3 py-2 text-left font-medium">系统理解</th>
                    <th className="px-3 py-2 text-left font-medium">技能族</th>
                    <th className="px-3 py-2 text-left font-medium">词表</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.map((item, index) => (
                    <tr key={`${item.raw}-${index}`} className="border-t border-slate-100">
                      <td className="px-3 py-2 text-slate-600">{item.raw}</td>
                      <td className="px-3 py-2 font-medium text-slate-800">{item.canonical}</td>
                      <td className="px-3 py-2 text-slate-500">{item.category}</td>
                      <td className="px-3 py-2">
                        {item.known ? (
                          <Badge color="emerald">已收录</Badge>
                        ) : (
                          <Badge color="amber">新词</Badge>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </div>

      <div className="min-w-0 space-y-5">
        <Card title="设置分析范围" subtitle="样本量越大结论越稳，但分析耗时也会相应增加。">
          <div className="space-y-4">
            <label className="block">
              <span className="text-xs text-slate-500">岗位数据源</span>
              <select
                value={wizard.sourceMode}
                onChange={(event) =>
                  wizard.setSourceMode(event.target.value as typeof wizard.sourceMode)
                }
                className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
              >
                <option value="auto">自动选择真实岗位源</option>
                <option value="live" disabled={!directions.data?.live_sources_enabled}>
                  仅在线岗位{directions.data?.live_sources_enabled ? '' : '（后端未启用）'}
                </option>
              </select>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
                在线源遵守站点 robots.txt，只读取公开 sitemap 和岗位详情；首次检索较慢，之后命中本地缓存。
              </p>
            </label>

            <label className="block">
              <span className="text-xs text-slate-500">直接导入实际岗位 URL（可选）</span>
              <textarea
                value={jobUrlsText}
                onChange={(event) => setJobUrlsText(event.target.value)}
                rows={3}
                placeholder="每行一个公开 HTTPS 岗位页，例如实习僧、国聘、智联、前程无忧或企业招聘官网"
                className="mt-1 w-full resize-y rounded-lg border border-slate-300 px-3 py-2 text-xs leading-relaxed outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
              />
              <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
                URL 导入会直接读取真实 JD，不再等待 sitemap；优先解析标准 JobPosting 数据，并拒绝内网地址。
              </p>
            </label>

            <label className="block">
              <span className="text-xs text-slate-500">中国大陆城市（可选；留空则全国）</span>
              <input
                value={wizard.city}
                onChange={(event) => wizard.setCity(event.target.value)}
                placeholder="如：深圳"
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500 focus:ring-2 focus:ring-slate-200"
              />
            </label>

            <label className="block">
              <span className="text-xs text-slate-500">
                最多分析几个方向：<strong className="text-slate-700">{wizard.maxDirections}</strong>
              </span>
              <input
                type="range"
                min={1}
                max={5}
                value={wizard.maxDirections}
                onChange={(event) => wizard.setMaxDirections(Number(event.target.value))}
                className="mt-2 w-full"
              />
            </label>

            <label className="block">
              <span className="text-xs text-slate-500">
                每个方向最多取多少条 JD：
                <strong className="text-slate-700">{wizard.limitPerDirection}</strong>
              </span>
              <input
                type="range"
                min={5}
                max={80}
                step={5}
                value={wizard.limitPerDirection}
                onChange={(event) => wizard.setLimitPerDirection(Number(event.target.value))}
                className="mt-2 w-full"
              />
              <span className="mt-1 block text-[11px] leading-relaxed text-slate-400">
                这是目标上限；实际数量取决于当前公开且仍在招聘的岗位。数量越大，分析耗时越长。
              </span>
            </label>
          </div>
        </Card>

        <Card title="它是怎么算的" subtitle="一条贯穿全局的红线，决定了结果为什么可信。">
          <ol className="space-y-3 text-sm text-slate-600">
            <li>
              <strong className="text-slate-800">1. LLM 只做抽取</strong>
              <p className="mt-0.5 text-xs leading-relaxed text-slate-500">
                大模型负责读懂 JD、抽出结构化字段，并强制给出原文依据（evidence）。
              </p>
            </li>
            <li>
              <strong className="text-slate-800">2. 代码做统计</strong>
              <p className="mt-0.5 text-xs leading-relaxed text-slate-500">
                排行榜、覆盖率、加权分全部由确定性代码算出 —— 可单元测试、可复现。
              </p>
            </li>
            <li>
              <strong className="text-slate-800">3. 每个数字都能点回原文</strong>
              <p className="mt-0.5 text-xs leading-relaxed text-slate-500">
                点看板上的任意技能，右侧会列出所有相关 JD 并高亮证据句。这是对抗幻觉的防线。
              </p>
            </li>
          </ol>
        </Card>

        {directions.data && (
          <Card
            title="实际岗位数据源"
            subtitle="自动采集国家大学生就业服务平台、实习僧、牛客及企业官网；也可导入其他公开职位 URL。"
          >
            <p className="mt-3 text-xs leading-relaxed text-slate-500">
              在线源{directions.data.live_sources_enabled ? '已启用' : '未启用'}；内置样例
              {directions.data.sample_source_enabled ? '仅用于开发测试' : '已关闭'}。
              在线采集没有命中时可直接粘贴职位 URL，不会用样例数据填充统计。
            </p>
          </Card>
        )}

        {health.isLoading && <Spinner label="正在检查后端服务…" />}
        {health.data && !health.data.llm_ready && (
          <ErrorNotice
            error={new Error(
              `后端已就绪，但大模型未配置：${health.data.detail || '请在 .env 中填写 LLM_API_KEY'}`,
            )}
          />
        )}
      </div>
      </div>
    </>
  )
}
