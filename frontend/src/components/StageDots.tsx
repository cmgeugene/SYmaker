import type { StageKey, StageStatus } from '../api'
import { cx } from './ui'

export const STAGES: { key: StageKey; label: string; short: string }[] = [
  { key: 'materials', label: '자료 등록', short: '자료' },
  { key: 'analyze', label: '샘플 분석', short: '분석' },
  { key: 'generate', label: '문제 제작', short: '제작' },
  { key: 'review', label: '검수', short: '검수' },
  { key: 'export', label: 'HWPX 출력', short: '출력' },
  { key: 'feedback', label: '피드백', short: '피드백' },
]

export function StageDots({ status }: { status: StageStatus }) {
  return (
    <div className="flex items-center gap-1">
      {STAGES.map((s) => {
        const st = status[s.key]
        return (
          <div key={s.key} className="flex flex-col items-center gap-1" title={`${s.label}: ${label(st)}`}>
            <div
              className={cx(
                'h-1.5 w-9 rounded-full',
                st === 'done' && 'bg-emerald-500',
                st === 'stale' && 'bg-amber-400',
                st === 'open' && 'bg-sky-400',
                st === 'todo' && 'bg-slate-200',
              )}
            />
            <span className="text-[10px] text-slate-400">{s.short}</span>
          </div>
        )
      })}
    </div>
  )
}

function label(st: string) {
  return { done: '완료', stale: '다시 필요', open: '처리할 피드백 있음', todo: '대기' }[st] || st
}
