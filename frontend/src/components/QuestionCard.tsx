import { useState } from 'react'
import { ChevronDown, ChevronUp, MessageSquarePlus, Pencil } from 'lucide-react'
import { answerIndex, isEssay, qLabel, type Question } from '../api'
import { CIRCLED, Markup } from './Markup'
import { Badge, Button, Field, Input, Select, Textarea, cx } from './ui'

export function QuestionCard({
  q,
  all,
  onSave,
  onFeedback,
  highlight,
}: {
  q: Question
  all: Question[]
  onSave?: (q: Question) => Promise<void> | void
  onFeedback?: (q: Question) => void
  highlight?: boolean
}) {
  const [edit, setEdit] = useState(false)
  const [draft, setDraft] = useState<Question>(q)
  const [showExp, setShowExp] = useState(false)
  const [saving, setSaving] = useState(false)
  const essay = isEssay(q)
  const label = qLabel(q, all)

  if (edit) {
    const set = (k: keyof Question, v: unknown) => setDraft({ ...draft, [k]: v })
    const dEssay = isEssay(draft)
    return (
      <div id={`q-${q.number}`} className="rounded-xl border-2 border-brand-200 bg-white p-5">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-800">{label} 편집</div>
        <div className="grid gap-3">
          <div className="grid grid-cols-4 gap-3">
            <Field label="유형"><Input value={draft.type} onChange={(e) => set('type', e.target.value)} /></Field>
            <Field label="난이도"><Select value={draft.difficulty} onChange={(e) => set('difficulty', e.target.value)}>{['하', '중', '상', draft.difficulty].filter((v, i, a) => v && a.indexOf(v) === i).map((d) => <option key={d}>{d}</option>)}</Select></Field>
            <Field label="배점"><Input type="number" step="0.5" min={0} value={draft.points ?? 0} onChange={(e) => set('points', Number(e.target.value))} /></Field>
            {!dEssay && (
              <Field label="정답">
                <Select value={draft.answer} onChange={(e) => set('answer', e.target.value)}>
                  {draft.choices.map((_, i) => <option key={i} value={String(i + 1)}>{CIRCLED[i]}</option>)}
                </Select>
              </Field>
            )}
          </div>
          <Field label="발문"><Textarea rows={dEssay ? 3 : 1} value={draft.instruction} onChange={(e) => set('instruction', e.target.value)} /></Field>
          <Field label="지문" hint="==형광펜==, __밑줄__, **굵게** 로 서식을 표시합니다.">
            <Textarea rows={7} value={draft.passage} onChange={(e) => set('passage', e.target.value)} />
          </Field>
          {dEssay ? (
            <>
              <Field label="모범답안"><Textarea rows={3} value={draft.answer} onChange={(e) => set('answer', e.target.value)} /></Field>
              <Field label="채점 기준" hint="부분 점수를 줄마다 적어 주세요."><Textarea rows={4} value={draft.rubric || ''} onChange={(e) => set('rubric', e.target.value)} /></Field>
            </>
          ) : (
            <div className="grid gap-2">
              <span className="text-[13px] font-medium text-slate-700">선택지</span>
              {draft.choices.map((c, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="w-5 text-center text-slate-500">{CIRCLED[i]}</span>
                  <Input value={c} onChange={(e) => set('choices', draft.choices.map((x, j) => (j === i ? e.target.value : x)))} />
                </div>
              ))}
            </div>
          )}
          <Field label="해설"><Textarea rows={3} value={draft.explanation} onChange={(e) => set('explanation', e.target.value)} /></Field>
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => { setDraft(q); setEdit(false) }}>취소</Button>
          <Button variant="primary" loading={saving} onClick={async () => { setSaving(true); await onSave?.(draft); setSaving(false); setEdit(false) }}>저장</Button>
        </div>
      </div>
    )
  }

  const ans = answerIndex(q.answer)
  return (
    <div id={`q-${q.number}`} className={cx('group rounded-xl border bg-white p-5 transition', highlight ? 'border-amber-300 ring-2 ring-amber-100' : 'border-slate-200')}>
      <div className="mb-3 flex items-center gap-2">
        <span className="text-[15px] font-bold text-slate-900">{label}</span>
        {essay && <Badge color="sky">서술형</Badge>}
        <Badge color="brand">{q.type}</Badge>
        {q.difficulty && <Badge>난이도 {q.difficulty}</Badge>}
        {!!q.points && <Badge>{q.points}점</Badge>}
        <div className="ml-auto flex gap-1 opacity-60 transition group-hover:opacity-100">
          {onFeedback && <Button size="sm" variant="ghost" icon={<MessageSquarePlus className="size-3.5" />} onClick={() => onFeedback(q)}>피드백</Button>}
          {onSave && <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" />} onClick={() => { setDraft(q); setEdit(true) }}>편집</Button>}
        </div>
      </div>
      <p className="prose-q text-[15px] leading-relaxed text-slate-800"><Markup text={q.instruction} /></p>
      {q.passage && (
        <div className="prose-q mt-3 rounded-lg border border-slate-200 bg-slate-50/50 px-4 py-3 font-serif text-[14.5px] leading-[1.75] text-slate-800">
          <Markup text={q.passage} />
        </div>
      )}
      {!essay && q.choices.length === 0 && q.extra && (
        <div className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-[13px] whitespace-pre-wrap text-slate-600">{q.extra}</div>
      )}
      {!essay && q.choices.length > 0 && (
        <ol className="mt-3 space-y-1">
          {q.choices.map((c, i) => (
            <li key={i} className={cx('prose-q flex gap-2 rounded-md px-2 py-1 text-[14px]', ans === i + 1 ? 'bg-emerald-50 font-medium text-emerald-800' : 'text-slate-700')}>
              <span className="shrink-0">{CIRCLED[i]}</span>
              <Markup text={c} />
            </li>
          ))}
        </ol>
      )}
      <button className="mt-3 flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700" onClick={() => setShowExp(!showExp)}>
        {showExp ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
        {essay ? '모범답안 · 채점 기준 · 해설' : `정답 ${Number.isNaN(ans) ? q.answer : CIRCLED[ans - 1]} · 해설`} {showExp ? '접기' : '보기'}
      </button>
      {showExp && (
        <div className="mt-2 space-y-2 rounded-lg bg-amber-50/60 px-3 py-2 text-[13px] leading-relaxed text-slate-700">
          {essay && (
            <>
              <div><b className="font-semibold">모범답안</b><div className="prose-q mt-0.5 font-serif"><Markup text={q.answer} /></div></div>
              {q.rubric && <div><b className="font-semibold">채점 기준</b><div className="mt-0.5 whitespace-pre-wrap">{q.rubric}</div></div>}
            </>
          )}
          <div>{essay && <b className="font-semibold">해설</b>}<div><Markup text={q.explanation} /></div></div>
          {q.source && <div className="text-xs text-slate-400">출처: {q.source}</div>}
        </div>
      )}
    </div>
  )
}
