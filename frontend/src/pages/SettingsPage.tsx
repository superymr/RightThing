import { type FormEvent, useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import { queryKeys } from '../api/hooks'
import type { LLMSettings, LLMSettingsInput } from '../api/types'
import { Button, Card, ErrorNotice, Spinner } from '../components/ui'

const emptyForm: LLMSettingsInput = {
  provider: 'openai',
  base_url: 'https://api.deepseek.com/v1',
  model: 'deepseek-chat',
  strong_model: '',
  temperature: 0,
  timeout: 120,
  max_retries: 2,
}

const fieldClass =
  'mt-1.5 w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-900 outline-none transition placeholder:text-slate-400 focus:border-indigo-400 focus:ring-4 focus:ring-indigo-100'

export function SettingsPage() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<LLMSettingsInput>(emptyForm)
  const [apiKey, setApiKey] = useState('')
  const [keyHint, setKeyHint] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<'test' | 'save' | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')

  useEffect(() => {
    api.get<LLMSettings>('/api/settings/llm')
      .then((data) => {
        setForm({
          provider: data.provider,
          base_url: data.base_url,
          model: data.model,
          strong_model: data.strong_model,
          temperature: data.temperature,
          timeout: data.timeout,
          max_retries: data.max_retries,
        })
        setKeyHint(data.api_key_hint)
      })
      .catch(setError)
      .finally(() => setLoading(false))
  }, [])

  const payload = (): LLMSettingsInput => ({
    ...form,
    api_key: apiKey || undefined,
  })

  const testConnection = async () => {
    setBusy('test')
    setError(null)
    setNotice('')
    try {
      const result = await api.post<{ message: string }>('/api/settings/llm/test', payload())
      setNotice(result.message)
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(null)
    }
  }

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setBusy('save')
    setError(null)
    setNotice('')
    try {
      const result = await api.put<LLMSettings>('/api/settings/llm', payload())
      setApiKey('')
      setKeyHint(result.api_key_hint)
      setNotice('配置已保存并立即生效，后续分析将使用新的模型 API。')
      await queryClient.invalidateQueries({ queryKey: queryKeys.health })
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(null)
    }
  }

  if (loading) return <Spinner label="正在读取 API 配置…" />

  const external = form.provider === 'openai'
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-600">模型连接</p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-slate-950 sm:text-3xl">自定义 API</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
          接入任何支持 OpenAI Chat Completions 协议的服务。配置只保存在本机，API Key 不会回显到页面或写入分析结果。
        </p>
      </div>

      <form className="space-y-6" onSubmit={save}>
        <Card title="运行模式" subtitle="可随时切回本地规则引擎，不消耗模型额度。">
          <div className="grid gap-3 sm:grid-cols-2">
            {([
              ['openai', '自定义模型 API', '推荐 · 支持 DeepSeek、OpenAI、通义、Kimi、Ollama 等兼容接口'],
              ['mock', '本地规则引擎', '离线可用 · 零成本，但方向推荐与抽取能力较弱'],
            ] as const).map(([value, title, description]) => (
              <label
                key={value}
                className={`cursor-pointer rounded-2xl border p-4 transition ${
                  form.provider === value
                    ? 'border-indigo-400 bg-indigo-50/70 ring-2 ring-indigo-100'
                    : 'border-slate-200 hover:border-slate-300'
                }`}
              >
                <input
                  className="sr-only"
                  type="radio"
                  name="provider"
                  value={value}
                  checked={form.provider === value}
                  onChange={() => setForm({ ...form, provider: value })}
                />
                <span className="block text-sm font-bold text-slate-900">{title}</span>
                <span className="mt-1 block text-xs leading-5 text-slate-500">{description}</span>
              </label>
            ))}
          </div>
        </Card>

        {external && (
          <Card
            title="接口参数"
            subtitle="Base URL 填到版本路径即可，系统会自动追加 /chat/completions。"
          >
            <div className="grid gap-5 sm:grid-cols-2">
              <label className="sm:col-span-2 text-sm font-medium text-slate-700">
                API 地址
                <input
                  className={fieldClass}
                  type="url"
                  required
                  placeholder="https://api.example.com/v1"
                  value={form.base_url}
                  onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                />
              </label>
              <label className="text-sm font-medium text-slate-700">
                默认模型
                <input
                  className={fieldClass}
                  required
                  placeholder="例如 deepseek-chat"
                  value={form.model}
                  onChange={(event) => setForm({ ...form, model: event.target.value })}
                />
              </label>
              <label className="text-sm font-medium text-slate-700">
                强模型（可选）
                <input
                  className={fieldClass}
                  placeholder="留空则复用默认模型"
                  value={form.strong_model}
                  onChange={(event) => setForm({ ...form, strong_model: event.target.value })}
                />
              </label>
              <label className="sm:col-span-2 text-sm font-medium text-slate-700">
                API Key
                <input
                  className={fieldClass}
                  type="password"
                  autoComplete="new-password"
                  placeholder={keyHint ? `已保存 ${keyHint}；留空则保持不变` : 'sk-…'}
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                />
                <span className="mt-1.5 block text-xs font-normal text-slate-400">
                  留空保留当前密钥；更换 API 地址时必须重新填写密钥。
                </span>
              </label>
            </div>

            <details className="mt-6 rounded-xl border border-slate-200 bg-slate-50/70 p-4">
              <summary className="cursor-pointer text-sm font-semibold text-slate-700">高级设置</summary>
              <div className="mt-4 grid gap-4 sm:grid-cols-3">
                <label className="text-xs font-medium text-slate-600">
                  Temperature
                  <input className={fieldClass} type="number" min="0" max="2" step="0.1" value={form.temperature} onChange={(e) => setForm({ ...form, temperature: Number(e.target.value) })} />
                </label>
                <label className="text-xs font-medium text-slate-600">
                  超时（秒）
                  <input className={fieldClass} type="number" min="5" max="600" value={form.timeout} onChange={(e) => setForm({ ...form, timeout: Number(e.target.value) })} />
                </label>
                <label className="text-xs font-medium text-slate-600">
                  重试次数
                  <input className={fieldClass} type="number" min="0" max="10" value={form.max_retries} onChange={(e) => setForm({ ...form, max_retries: Number(e.target.value) })} />
                </label>
              </div>
            </details>
          </Card>
        )}

        <ErrorNotice error={error} />
        {notice && (
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-medium text-emerald-800">
            {notice}
          </div>
        )}

        <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" disabled={busy !== null} onClick={testConnection}>
            {busy === 'test' ? '正在测试…' : '测试连接'}
          </Button>
          <Button type="submit" disabled={busy !== null}>
            {busy === 'save' ? '正在保存…' : '保存并应用'}
          </Button>
        </div>
      </form>
    </div>
  )
}
