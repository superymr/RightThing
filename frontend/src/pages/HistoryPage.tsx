/** ④ 历史分析列表。
 *
 *  这里能存在的前提是「看板从数据库读回，而不是从任务对象取」：
 *  服务重启后历史依然可查，多 worker 部署也不会出现「请求打到另一个进程就查不到」。 */

import { Link } from 'react-router-dom'

import { useSessions } from '../api/hooks'
import { Badge, Card, EmptyState, ErrorNotice, Spinner } from '../components/ui'

export function HistoryPage() {
  const { data, isLoading, error } = useSessions(50)

  if (isLoading) return <Spinner label="正在读取历史分析…" />
  if (error) return <ErrorNotice error={error} />

  const sessions = data?.sessions ?? []

  return (
    <Card
      title="分析记录"
      subtitle="每一次分析的输入与结果都留在库里，读回时直接聚合 —— 不会因为词表演进而让旧报表悄悄变化。"
    >
      {sessions.length === 0 ? (
        <EmptyState
          title="还没有历史记录"
          hint={
            <>
              去 <Link className="text-sky-600 hover:underline" to="/">技能录入</Link> 跑一次分析吧。
            </>
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs text-slate-500">
              <tr>
                <th className="px-3 py-2 text-left font-medium">#</th>
                <th className="px-3 py-2 text-left font-medium">时间</th>
                <th className="px-3 py-2 text-left font-medium">输入技能</th>
                <th className="px-3 py-2 text-left font-medium">方向数</th>
                <th className="px-3 py-2 text-left font-medium">JD 数</th>
                <th className="px-3 py-2 text-left font-medium">模型</th>
                <th className="px-3 py-2 text-left font-medium">状态</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={session.session_id} className="border-t border-slate-100 hover:bg-slate-50/60">
                  <td className="px-3 py-2 tabular-nums text-slate-500">{session.session_id}</td>
                  <td className="px-3 py-2 text-slate-500">
                    {new Date(session.created_at).toLocaleString()}
                  </td>
                  <td className="px-3 py-2">
                    <span className="flex flex-wrap gap-1">
                      {session.input_skills.slice(0, 5).map((skill) => (
                        <Badge key={skill} color="slate">
                          {skill}
                        </Badge>
                      ))}
                      {session.input_skills.length > 5 && (
                        <span className="text-xs text-slate-400">
                          +{session.input_skills.length - 5}
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="px-3 py-2 tabular-nums text-slate-500">{session.direction_count}</td>
                  <td className="px-3 py-2 tabular-nums text-slate-500">{session.job_count}</td>
                  <td className="px-3 py-2 text-slate-400">
                    {session.provider} · {session.model}
                  </td>
                  <td className="px-3 py-2">
                    <Badge color={session.status === 'done' ? 'emerald' : 'amber'}>
                      {session.status}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Link
                      className="text-sky-600 hover:underline"
                      to={`/sessions/${session.session_id}`}
                    >
                      打开看板
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
