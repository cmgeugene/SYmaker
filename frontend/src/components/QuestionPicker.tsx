import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { isEssay, qLabel, type Question } from '../api'
import { cx } from './ui'

/** 피드백 대상 고르기: '문제지 전체' 또는 문항 번호. 번호 버튼 격자로 작게 펼쳐진다. */
export function QuestionPicker({ questions, value, onChange }: { questions: Question[]; value: number | null; onChange: (n: number | null) => void }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const current = questions.find((q) => q.number === value)
  const mc = questions.filter((q) => !isEssay(q))
  const essays = questions.filter(isEssay)
  const pick = (n: number | null) => { onChange(n); setOpen(false) }

  const chip = (q: Question, label: string) => (
    <button key={q.number} type="button" title={`${qLabel(q, questions)} ${q.type}`} onClick={() => pick(q.number)}
      className={cx('h-8 rounded-md text-[13px] transition-colors', value === q.number ? 'bg-brand-600 font-semibold text-white' : 'bg-slate-50 text-slate-700 hover:bg-brand-50 hover:text-brand-700')}>
      {label}
    </button>
  )

  return (
    <div ref={box} className="relative">
      <button type="button" onClick={() => setOpen(!open)}
        className={cx('flex h-9 w-full items-center justify-between rounded-lg border bg-white px-3 text-sm', open ? 'border-brand-500 ring-2 ring-brand-100' : 'border-slate-200')}>
        <span className="truncate text-slate-800">{current ? `${qLabel(current, questions)} ${current.type}` : '문제지 전체'}</span>
        <ChevronDown className={cx('size-4 shrink-0 text-slate-400 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="absolute top-full right-0 left-0 z-30 mt-1 max-h-[26rem] overflow-y-auto rounded-lg border border-slate-200 bg-white p-2 shadow-lg scroll-thin">
          <button type="button" onClick={() => pick(null)}
            className={cx('mb-2 h-8 w-full rounded-md text-[13px]', value === null ? 'bg-brand-600 font-semibold text-white' : 'bg-slate-50 text-slate-700 hover:bg-brand-50')}>
            문제지 전체
          </button>
          {mc.length > 0 && (
            <>
              <div className="mb-1 px-0.5 text-[11px] font-medium text-slate-400">객관식</div>
              <div className="grid grid-cols-6 gap-1">{mc.map((q) => chip(q, String(q.number)))}</div>
            </>
          )}
          {essays.length > 0 && (
            <>
              <div className="mt-2 mb-1 px-0.5 text-[11px] font-medium text-slate-400">서술형</div>
              <div className="grid grid-cols-6 gap-1">{essays.map((q, i) => chip(q, `서${i + 1}`))}</div>
            </>
          )}
          {current && <div className="mt-2 truncate border-t border-slate-100 px-0.5 pt-1.5 text-[11px] text-slate-500">선택: {qLabel(current, questions)} {current.type}</div>}
        </div>
      )}
    </div>
  )
}
