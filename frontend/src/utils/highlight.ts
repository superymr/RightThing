/**
 * 证据高亮。
 *
 * 这是「把信任设计进交互里」的落点：模型抽出的每一项技能都必须给出原文片段，
 * 前端负责把它标出来，用户一眼就能判断模型有没有编造。
 *
 * 实现上刻意不用正则拼接：evidence 来自模型输出，里面可能含 `.*`、`(` 之类的
 * 正则元字符，稍不注意就会把高亮范围扩到整段文本。用 indexOf 逐条定位、
 * 再合并区间，行为是可预测的。
 */

export interface Segment {
  text: string
  /** 是否落在某条 evidence 内 */
  evidence: boolean
  /** 是否是当前选中的那条证据 */
  active: boolean
}

interface Range {
  start: number
  end: number
  source: string
}

function collectRanges(text: string, evidences: string[]): Range[] {
  const ranges: Range[] = []
  for (const raw of evidences) {
    const needle = (raw || '').trim()
    if (needle.length < 2) continue // 单字证据会把整篇文本刷满高亮，没有信息量
    let from = 0
    while (from <= text.length - needle.length) {
      const index = text.indexOf(needle, from)
      if (index < 0) break
      ranges.push({ start: index, end: index + needle.length, source: needle })
      from = index + needle.length
    }
  }
  // 长的优先，短的被包含时直接丢弃，避免同一区段被标两次
  ranges.sort((a, b) => a.start - b.start || b.end - a.end)
  const merged: Range[] = []
  for (const range of ranges) {
    const last = merged[merged.length - 1]
    if (last && range.start < last.end) {
      if (range.end > last.end) last.end = range.end
      continue
    }
    merged.push({ ...range })
  }
  return merged
}

export function segmentByEvidence(
  text: string,
  evidences: string[],
  activeEvidence = '',
): Segment[] {
  const ranges = collectRanges(text, evidences)
  if (ranges.length === 0) return [{ text, evidence: false, active: false }]

  const activeNeedle = activeEvidence.trim()
  const segments: Segment[] = []
  let cursor = 0
  for (const range of ranges) {
    if (range.start > cursor) {
      segments.push({ text: text.slice(cursor, range.start), evidence: false, active: false })
    }
    segments.push({
      text: text.slice(range.start, range.end),
      evidence: true,
      active: Boolean(activeNeedle) && range.source === activeNeedle,
    })
    cursor = range.end
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor), evidence: false, active: false })
  }
  return segments
}

/** 取证据句前后的一段上下文，用于「摘要视图」而不是整篇 JD */
export function excerptAround(text: string, evidence: string, radius = 60): string {
  const needle = (evidence || '').trim()
  const index = needle ? text.indexOf(needle) : -1
  if (index < 0) return text.slice(0, radius * 2)
  const start = Math.max(0, index - radius)
  const end = Math.min(text.length, index + needle.length + radius)
  return `${start > 0 ? '…' : ''}${text.slice(start, end)}${end < text.length ? '…' : ''}`
}
