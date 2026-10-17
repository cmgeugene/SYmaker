import { useState } from 'react'
import { ArrowRight, ClipboardCheck, ShieldCheck, Wand2, Zap } from 'lucide-react'
import { answerIndex, api, isEssay, qLabel, type Issue, type Question } from '../../api'
import { Badge, Button, Card, Empty, SectionTitle, cx, useAsync } from '../../components/ui'
import { RunControl } from '../../components/jobs'
import { CIRCLED } from '../../components/Markup'
import type { StepProps } from '../WorkbookPage'

const SEV = {
  high: { label: '중요', color: 'rose' as const },
  medium: { label: '보통', color: 'amber' as const },
  low: { label: '참고', color: 'slate' as const },
}

export default function ReviewStep({ wb, startJob, jobRunning, goto }: StepProps) {
  const review = wb.review
  const [quick, setQuick] = useState<{ issues: Issue[]; answer_distribution: Record<string, number> } | null>(null)
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const { busy, run } = useAsync()
  const qs = wb.questions?.questions || []
  const issues = (review?.issues || []).slice().sort((a, b) => order(a.severity) - order(b.severity) || a.number - b.number)
  const stale = wb.status.review === 'stale'
  const dist = review?.answer_distribution || quick?.answer_distribution

  const toggle = (i: number) => setPicked((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n })

  const fixSelected = (o: { model: string; effort: string }) => {
    const requests = [...picked].map((i) => {
      const it = issues[i]
      return `${it.number ? `[${it.number}번 문항] ` : it.set ? `[${it.set}번 지문] ` : '[전체] '}(${it.category}) ${it.message}${it.suggestion ? ` → 제안: ${it.suggestion}` : ''}`
    })
    startJob('revise', { ...o, requests })
    setPicked(new Set())
  }

  if (!qs.length) {
    return (
      <div className="space-y-6">
        <SectionTitle title="4. 검수" />
        <Empty icon={<ClipboardCheck className="size-6" />} title="먼저 문제를 제작하세요" action={<Button onClick={() => goto('generate')}>문제 제작으로 이동</Button>} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <SectionTitle
        title="4. 검수"
        desc="규칙 검사(문항 수, 선택지 5개, 정답 번호 분포 등)와 Codex 검수(지침·서식 준수, 정답 유일성, 문법)를 함께 합니다."
        right={
          <>
            <Button icon={<Zap className="size-4" />} loading={busy === 'quick'} onClick={() => run('quick', async () => setQuick(await api.post(`/workbooks/${wb.id}/checks`)))}>
              빠른 규칙 검사
            </Button>
            <RunControl stage="review" label={review ? '다시 검수' : '검수 시작'} icon={<ShieldCheck className="size-4" />} disabled={jobRunning} busy={jobRunning} onRun={(o) => startJob('review', o)} />
          </>
        }
      />

      {stale && (
        <div className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800">
          검수 이후 문제가 바뀌었습니다. 최신 문제로 다시 검수하는 것을 권장해요.
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="p-5">
          <div className="mb-3 text-[13px] font-medium text-slate-500">종합 점수</div>
          {review ? (
            <>
              <div className="flex items-baseline gap-1">
                <span className={cx('text-4xl font-bold', review.score >= 85 ? 'text-emerald-600' : review.score >= 70 ? 'text-amber-600' : 'text-rose-600')}>{review.score}</span>
                <span className="text-slate-400">/ 100</span>
              </div>
              <SummaryText text={review.summary} />
              <p className="mt-2 text-[11px] text-slate-400">{review.at.replace('T', ' ')} · {review.model}</p>
            </>
          ) : <p className="text-sm text-slate-400">아직 검수하지 않았습니다.</p>}
        </Card>

        <Card className="p-5 lg:col-span-2">
          <div className="mb-3 text-[13px] font-medium text-slate-500">정답 번호 분포 (객관식)</div>
          {dist ? <Distribution dist={dist} /> : <p className="text-sm text-slate-400">검수 또는 빠른 규칙 검사를 실행하면 표시됩니다.</p>}
          <div className="mt-4 flex flex-wrap gap-1">
            {qs.filter((q) => !isEssay(q)).map((q) => (
              <span key={q.number} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
                {q.number}:{CIRCLED[answerIndex(q.answer) - 1] || q.answer}
              </span>
            ))}
          </div>
        </Card>
      </div>

      {quick && !review && (
        <IssueList issues={quick.issues} picked={new Set()} toggle={() => {}} selectable={false} qs={qs} />
      )}

      {review && (
        <Card className="p-5">
          <div className="mb-4 flex items-center justify-between gap-4">
            <div>
              <h3 className="font-semibold text-slate-900">발견된 문제 {issues.length}건</h3>
              <p className="text-xs text-slate-500">고칠 항목을 체크하고 ‘자동 수정’을 누르면 Codex가 반영합니다. 직접 고치려면 제작 단계에서 편집하세요.</p>
            </div>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" onClick={() => setPicked(picked.size === issues.length ? new Set() : new Set(issues.map((_, i) => i)))}>
                {picked.size === issues.length && issues.length ? '모두 해제' : '모두 선택'}
              </Button>
              <RunControl stage="revise" label={`선택 ${picked.size}건 자동 수정`} icon={<Wand2 className="size-4" />} disabled={!picked.size || jobRunning} onRun={fixSelected} />
            </div>
          </div>
          {issues.length === 0 ? (
            <div className="rounded-lg bg-emerald-50 p-4 text-sm text-emerald-700">문제가 발견되지 않았습니다. 출력 단계로 넘어가세요.</div>
          ) : (
            <IssueList issues={issues} picked={picked} toggle={toggle} selectable qs={qs} />
          )}
          <div className="mt-4 flex justify-end">
            <Button variant="soft" icon={<ArrowRight className="size-4" />} onClick={() => goto('export')}>다음: HWPX 출력</Button>
          </div>
        </Card>
      )}
    </div>
  )
}

function order(s: string) {
  return { high: 0, medium: 1, low: 2 }[s] ?? 3
}

function IssueList({ issues, picked, toggle, selectable, qs }: { issues: Issue[]; picked: Set<number>; toggle: (i: number) => void; selectable: boolean; qs: Question[] }) {
  const label = (n: number) => { const q = qs.find((x) => x.number === n); return q ? qLabel(q, qs).replace(/\.$/, '번') : `${n}번` }
  if (!issues.length) return <div className="rounded-lg bg-emerald-50 p-4 text-sm text-emerald-700">규칙 검사에서 문제가 없습니다.</div>
  return (
    <div className="divide-y divide-slate-100 rounded-lg border border-slate-100">
      {issues.map((it, i) => (
        <label key={i} className={cx('flex gap-3 px-4 py-3', selectable && 'cursor-pointer hover:bg-slate-50', picked.has(i) && 'bg-brand-50/50')}>
          {selectable && <input type="checkbox" className="mt-1 size-4 accent-brand-600" checked={picked.has(i)} onChange={() => toggle(i)} />}
          <div className="w-20 shrink-0 text-sm font-semibold text-slate-700">{it.number ? label(it.number) : it.set ? `${it.set}번 지문` : '전체'}</div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge color={SEV[it.severity]?.color || 'slate'}>{SEV[it.severity]?.label || it.severity}</Badge>
              <Badge>{it.category}</Badge>
              <Badge color={it.source === 'rule' ? 'sky' : 'brand'}>{it.source === 'rule' ? '규칙' : 'Codex'}</Badge>
            </div>
            <p className="mt-1 text-sm text-slate-800">{it.message}</p>
            {it.suggestion && <p className="mt-0.5 text-[13px] text-slate-500">→ {it.suggestion}</p>}
          </div>
        </label>
      ))}
    </div>
  )
}

function Distribution({ dist }: { dist: Record<string, number> }) {
  const max = Math.max(1, ...Object.values(dist))
  return (
    <div className="flex h-28 items-end gap-4">
      {['1', '2', '3', '4', '5'].map((k) => (
        <div key={k} className="flex flex-1 flex-col items-center gap-1">
          <span className="text-xs font-medium text-slate-600">{dist[k] || 0}</span>
          <div className="w-full rounded-t-md bg-brand-500/80" style={{ height: `${((dist[k] || 0) / max) * 72 + 2}px` }} />
          <span className="text-sm text-slate-500">{CIRCLED[Number(k) - 1]}</span>
        </div>
      ))}
    </div>
  )
}


/** 검수 평가: '[n번 지문] …' 묶음은 블록으로, 문장은 한 줄씩. 길면 접어 둔다. */
function SummaryText({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const blocks = (text || '')
    .split(/\s+\/\s+(?=\[)/)
    .map((b) => {
      const m = b.match(/^\[([^\]]+)\]\s*/)
      const body = m ? b.slice(m[0].length) : b
      return { label: m?.[1], sentences: body.split(/(?<=[.!?。])\s+(?=\S)/).filter(Boolean) }
    })
  const long = blocks.length > 2 || text.length > 400
  const shown = open || !long ? blocks : blocks.slice(0, 2)
  return (
    <div className="mt-3 text-[13px] leading-relaxed text-slate-600">
      <div className="space-y-3">
        {shown.map((b, i) => (
          <div key={i}>
            {b.label && <div className="mb-0.5 font-semibold text-slate-800">{b.label}</div>}
            <ul className="space-y-1">
              {b.sentences.map((t, j) => <li key={j}>{t}</li>)}
            </ul>
          </div>
        ))}
      </div>
      {long && (
        <button className="mt-2 text-xs font-medium text-brand-600 hover:underline" onClick={() => setOpen(!open)}>
          {open ? '접기' : `전체 보기 (${blocks.length}개)`}
        </button>
      )}
    </div>
  )
}
