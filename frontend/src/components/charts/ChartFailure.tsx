/** 图表渲染失败时的局部占位。
 *
 *  刻意做成一个**可见的、说人话的**提示，而不是静默空白：
 *  空白会让用户以为是数据为空（那是另一回事，有各自的空状态文案），
 *  而实际上这是「图表库不认这份数据」—— 两者的处理方式完全不同。
 */

export function ChartFailure({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-6 text-center">
      <p className="text-sm font-medium text-amber-900">这张图没能渲染出来</p>
      <p className="mt-1 text-xs leading-relaxed text-amber-800">
        该面板的数据形状超出了图表库的预期（通常是某个方向没有样本）。
        <br />
        其余面板与统计数字不受影响，可以正常查看。
      </p>
      {message && (
        <p className="mt-2 break-all font-mono text-[11px] text-amber-700">{message}</p>
      )}
    </div>
  )
}
