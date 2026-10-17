import { Fragment, type ReactNode } from 'react'

/** ==형광펜==, __밑줄__, **굵게** 표기를 화면용으로 렌더링한다. */
export function Markup({ text, className }: { text: string; className?: string }) {
  const lines = (text || '').split('\n')
  return (
    <span className={className}>
      {lines.map((line, i) => (
        <Fragment key={i}>
          {i > 0 && <br />}
          {renderLine(line)}
        </Fragment>
      ))}
    </span>
  )
}

function renderLine(line: string): ReactNode[] {
  const parts = line.split(/(\*\*|(?<!_)__(?!_)|==|!!)/)
  const active = { b: false, u: false, h: false, w: false }
  const out: ReactNode[] = []
  parts.forEach((p, i) => {
    if (p === '**') return void (active.b = !active.b)
    if (p === '__') return void (active.u = !active.u)
    if (p === '==') return void (active.h = !active.h)
    if (p === '!!') return void (active.w = !active.w)
    if (!p) return
    let node: ReactNode = p
    if (active.u) node = <u>{node}</u>
    if (active.b) node = <b className="font-semibold text-slate-900">{node}</b>
    if (active.w) node = <span className="rounded bg-slate-800 px-0.5 text-white" title="인쇄 시 흰 글씨">{node}</span>
    if (active.h) node = <mark className="hl">{node}</mark>
    out.push(<Fragment key={i}>{node}</Fragment>)
  })
  return out
}

export const CIRCLED = ['①', '②', '③', '④', '⑤', '⑥', '⑦', '⑧', '⑨', '⑩']
