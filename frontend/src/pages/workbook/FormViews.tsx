import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, LayoutTemplate, Paintbrush } from 'lucide-react'
import { FORM_STYLE_DEFAULT, type Align, type FormSegment, type FormSet, type FormStyle, type Question, type Workbook } from '../../api'
import { Badge, Button, Card, Field, Input, Select, cx } from '../../components/ui'
import { CIRCLED, Markup } from '../../components/Markup'
import { QuestionCard } from '../../components/QuestionCard'

const USAGE: Record<FormSegment['usage'], string> = {
  use: '사용',
  skip: '사용 안 함',
  'pick-A': '택1 묶음 A',
  'pick-B': '택1 묶음 B',
}

/** 내부 칸 주소(b4~b8, f.head 등)를 사람이 읽기 쉬운 말로 바꾼다 */
function readable(text: string) {
  return text
    .replace(/f\.head/g, '머리 칸').replace(/f\.body/g, '아래 칸')
    .replace(/\bb\d+(\.t\d+\.r\d+c\d+)?(\s*~\s*b\d+)?\s*(의|에|에는)?\s*/g, '')
    .replace(/\s{2,}/g, ' ').trim()
}

/** 분석 단계: 양식의 하위 문항 구성과 사용 여부 */
export function FormSegmentsCard({ wb, onSave, saving }: { wb: Workbook; onSave: (segs: FormSegment[]) => void; saving: boolean }) {
  const saved = wb.analysis?.form_segments || []
  const [segs, setSegs] = useState<FormSegment[]>(saved)
  useEffect(() => setSegs(saved), [JSON.stringify(saved)]) // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = JSON.stringify(segs) !== JSON.stringify(saved)
  const instr = (id: string) => wb.form?.segments.find((s) => s.id === id)?.instruction || ''

  return (
    <Card className="p-5">
      <div className="mb-1 flex items-center justify-between">
        <div className="flex items-center gap-2 text-[13px] font-medium text-slate-500">
          <LayoutTemplate className="size-4" /> 양식 구성 — 지문 세트형
        </div>
        <Button size="sm" variant={dirty ? 'primary' : 'secondary'} disabled={!dirty} loading={saving} onClick={() => onSave(segs)}>저장</Button>
      </div>
      <p className="mb-4 text-xs leading-relaxed text-slate-500">
        이 샘플은 <b>지문 1개 + 하위 문항</b> 블록이 {wb.form?.block_count}번 반복되는 양식입니다. 양식은 그대로 두고 칸만 채워 출력합니다.
        {wb.form?.front_boxes ? ` 앞쪽에 지문별 박스 ${wb.form.front_boxes}개가 있습니다${wb.analysis?.front_usage ? ` — ${readable(wb.analysis.front_usage)}` : ''}.` : ''}
        <br />‘택1 묶음’은 지문마다 그중 하나만 출제합니다(예: 순서 또는 삽입). 화살표로 문항 순서를 바꾸면 출력 순서도 바뀝니다.
      </p>
      <div className="divide-y divide-slate-100 rounded-lg border border-slate-100">
        {segs.map((s, i) => (
          <div key={s.segment_id} className={cx('flex items-start gap-3 px-3 py-2.5', s.usage === 'skip' && 'opacity-50')}>
            <div className="flex shrink-0 flex-col">
              <button title="위로" disabled={i === 0} className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                onClick={() => { const n = [...segs]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; setSegs(n) }}><ArrowUp className="size-3.5" /></button>
              <button title="아래로" disabled={i === segs.length - 1} className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-30"
                onClick={() => { const n = [...segs]; [n[i + 1], n[i]] = [n[i], n[i + 1]]; setSegs(n) }}><ArrowDown className="size-3.5" /></button>
            </div>
            <span className="w-7 shrink-0 pt-1 text-xs text-slate-400">{i + 1}번</span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-sm font-medium text-slate-800">{s.type}</span>
                <Badge color={s.kind === '서술형' ? 'sky' : 'slate'}>{s.kind}</Badge>
                {s.five_way && <Badge>정답 5지 분포 관리</Badge>}
              </div>
              <p className="mt-0.5 truncate text-xs text-slate-500">{instr(s.segment_id)}</p>
              {s.answer_format && <p className="mt-0.5 text-[11px] text-slate-400">정답 표기: {readable(s.answer_format)}</p>}
            </div>
            <div className="w-32 shrink-0">
              <Select className="!h-8 text-xs" value={s.usage} onChange={(e) => setSegs(segs.map((x, j) => (j === i ? { ...x, usage: e.target.value as FormSegment['usage'] } : x)))}>
                {Object.entries(USAGE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

const ALIGNS: Record<Align, string> = { '': '양식 그대로', LEFT: '왼쪽', CENTER: '가운데', RIGHT: '오른쪽', JUSTIFY: '양쪽' }
const HIDDEN: [FormStyle['hidden_style'][number], string][] = [['highlight', '형광펜'], ['bold', '굵게'], ['underline', '밑줄'], ['white', '흰 글씨']]

/** 분석 단계: 양식 출력 서식 (정답 표시 서식, 정렬, 글자 크기, 문항 간격) */
export function FormStyleCard({ wb, onSave, saving }: { wb: Workbook; onSave: (st: FormStyle) => void; saving: boolean }) {
  const saved: FormStyle = { ...FORM_STYLE_DEFAULT, ...(wb.analysis?.form_style || {}),
    front_body: { ...FORM_STYLE_DEFAULT.front_body, ...(wb.analysis?.form_style?.front_body || {}) } }
  const [st, setSt] = useState<FormStyle>(saved)
  useEffect(() => setSt(saved), [JSON.stringify(saved)]) // eslint-disable-line react-hooks/exhaustive-deps
  const dirty = JSON.stringify(st) !== JSON.stringify(saved)
  const segIndex = (id: string | null) => (wb.analysis?.form_segments || []).findIndex((s) => s.segment_id === id) + 1

  return (
    <Card className="p-5">
      <div className="mb-1 flex items-center justify-between">
        <div className="flex items-center gap-2 text-[13px] font-medium text-slate-500"><Paintbrush className="size-4" /> 출력 서식</div>
        <Button size="sm" variant={dirty ? 'primary' : 'secondary'} disabled={!dirty} loading={saving} onClick={() => onSave(st)}>저장</Button>
      </div>
      <p className="mb-4 text-xs text-slate-500">HWPX로 출력할 때의 표시 방식입니다. 바꾼 뒤 출력 단계에서 다시 만들면 반영됩니다.</p>
      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-brand-600" checked={st.header_highlight} onChange={(e) => setSt({ ...st, header_highlight: e.target.checked })} />
            블록 머리의 출처 표기(예: [올림포스 …] Unit 11 Analysis)에 형광펜
          </label>
          <div>
            <div className="mb-1.5 text-[13px] font-medium text-slate-700">숨긴 정답 서식 <span className="font-normal text-slate-400">(서술형 답, 바르게 고치기 답, Logic Flow 핵심어 등)</span></div>
            <div className="flex flex-wrap gap-3 text-sm">
              {HIDDEN.map(([k, label]) => (
                <label key={k} className="flex items-center gap-1.5">
                  <input type="checkbox" className="size-4 accent-brand-600" checked={st.hidden_style.includes(k)}
                    onChange={(e) => setSt({ ...st, hidden_style: e.target.checked ? [...st.hidden_style, k] : st.hidden_style.filter((x) => x !== k) })} />
                  {label}
                </label>
              ))}
            </div>
            <p className="mt-1 text-[11px] text-slate-400">교사용에만 적용됩니다. 학생용에서는 숨긴 정답이 빈칸으로 나옵니다.</p>
          </div>
          <Field label="하위 문항 사이 빈 줄">
            <Select value={st.gap_lines === null ? 'keep' : String(st.gap_lines)} onChange={(e) => setSt({ ...st, gap_lines: e.target.value === 'keep' ? null : Number(e.target.value) })}>
              <option value="keep">양식 그대로</option>
              {[0, 1, 2, 3].map((n) => <option key={n} value={n}>{n}줄</option>)}
            </Select>
          </Field>
        </div>
        <div className="space-y-4">
          {!!wb.form?.front_boxes && (
            <div className="rounded-lg border border-slate-100 p-3">
              <div className="mb-2 text-[13px] font-medium text-slate-700">앞쪽 지문별 박스 내용 (Logic Flow 등)</div>
              <div className="grid grid-cols-2 gap-2">
                <Field label="글자 크기(pt)">
                  <Input type="number" step="0.5" min={6} max={20} placeholder="양식 그대로" value={st.front_body.size ?? ''}
                    onChange={(e) => setSt({ ...st, front_body: { ...st.front_body, size: e.target.value ? Number(e.target.value) : null } })} />
                </Field>
                <Field label="정렬">
                  <Select value={st.front_body.align} onChange={(e) => setSt({ ...st, front_body: { ...st.front_body, align: e.target.value as Align } })}>
                    {Object.entries(ALIGNS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </Select>
                </Field>
              </div>
              <label className="mt-2 flex items-center gap-2 text-sm">
                <input type="checkbox" className="size-4 accent-brand-600" checked={st.front_body.keyword_mark}
                  onChange={(e) => setSt({ ...st, front_body: { ...st.front_body, keyword_mark: e.target.checked } })} />
                각 줄의 핵심어를 숨긴 정답 서식으로 (학생용은 빈칸 채우기)
              </label>
            </div>
          )}
          <div className="rounded-lg border border-slate-100 p-3">
            <div className="mb-2 text-[13px] font-medium text-slate-700">상자 안 내용 정렬 <span className="font-normal text-slate-400">(제목 줄 제외)</span></div>
            <div className="space-y-1.5">
              {(wb.form?.boxes || []).map((bx) => (
                <div key={bx.slot} className="flex items-center gap-2 text-[13px]">
                  <span className="min-w-0 flex-1 truncate text-slate-600" title={bx.segment_instruction}>
                    {bx.segment ? `${segIndex(bx.segment)}번 문항 · ` : ''}{bx.label === '내용 상자' && bx.segment_instruction ? bx.segment_instruction.slice(0, 18) + '… 상자' : bx.label}
                  </span>
                  <div className="w-28 shrink-0">
                    <Select className="!h-8 text-xs" value={st.box_align[bx.slot] || ''}
                      onChange={(e) => setSt({ ...st, box_align: { ...st.box_align, [bx.slot]: e.target.value as Align } })}>
                      {Object.entries(ALIGNS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                    </Select>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Card>
  )
}

/** 제작 단계: 지문 세트 결과 보기 (지문 → Logic Flow → 하위 문항) */
export function FormSetsView({ sets, questions, onSave }: { sets: FormSet[]; questions: Question[]; onSave?: (q: Question) => void }) {
  const [open, setOpen] = useState<Record<number, boolean>>({ [sets[0]?.index]: true })
  return (
    <div className="space-y-3">
      {sets.map((st) => {
        const qs = questions.filter((q) => q.set === st.index)
        const isOpen = !!open[st.index]
        return (
          <Card key={st.index} className="overflow-hidden">
            <button className="flex w-full items-center gap-3 px-5 py-3.5 text-left hover:bg-slate-50" onClick={() => setOpen({ ...open, [st.index]: !isOpen })}>
              {isOpen ? <ChevronDown className="size-4 text-slate-400" /> : <ChevronRight className="size-4 text-slate-400" />}
              <span className="text-[15px] font-bold text-slate-900">[{st.index}]</span>
              <span className="truncate text-sm font-medium text-slate-700"><Markup text={st.label.replace(/^\s*\[\s*\d+\s*\]\s*/, '')} /></span>
              <span className="ml-auto flex shrink-0 gap-1">
                {qs.map((q) => <Badge key={q.number} color="brand" className="!px-1.5 !text-[10px]">{q.type}</Badge>)}
              </span>
            </button>
            {isOpen && (
              <div className="space-y-4 border-t border-slate-100 bg-slate-50/40 p-5">
                <div className="grid gap-4 lg:grid-cols-3">
                  <div className="lg:col-span-2">
                    <div className="mb-1.5 text-xs font-medium text-slate-500">변형 지문</div>
                    <div className="prose-q rounded-lg border border-slate-200 bg-white px-4 py-3 font-serif text-[14px] leading-[1.75] text-slate-800">
                      <Markup text={st.passage} />
                    </div>
                  </div>
                  <div>
                    <div className="mb-1.5 text-xs font-medium text-slate-500">Logic Flow</div>
                    <div className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-[13px] leading-relaxed text-slate-700">
                      {st.logic_flow.map((l, i) => (
                        <div key={i}>
                          {i > 0 && <div className="py-0.5 text-center text-slate-300">↓</div>}
                          <div>{l}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="grid gap-3">
                  {qs.map((q) => <QuestionCard key={`${q.number}-${q.answer}`} q={q} all={questions} onSave={onSave} />)}
                </div>
              </div>
            )}
          </Card>
        )
      })}
    </div>
  )
}

/** 화면용 간단 미리보기 */
export function FormPreview({ sets, questions }: { sets: FormSet[]; questions: Question[] }) {
  return (
    <div className="mx-auto max-w-[620px] space-y-8 bg-white px-10 py-10 font-serif shadow-sm">
      {sets.map((st) => (
        <div key={st.index} className="prose-q text-[13px] leading-[1.7]">
          <p className="mb-2 font-bold">[{st.index}] <Markup text={st.label.replace(/^\s*\[\s*\d+\s*\]\s*/, '')} /></p>
          <div className="mb-3 border border-slate-300 px-3 py-2"><Markup text={st.passage} /></div>
          {questions.filter((q) => q.set === st.index).map((q, k) => (
            <div key={q.number} className="mb-3">
              <p className="font-medium">{k + 1}. <Markup text={q.instruction} /></p>
              {q.choices.map((c, i) => <div key={i}>{CIRCLED[i]} <Markup text={c} /></div>)}
              {!q.choices.length && q.extra && <div className="mt-1 text-[12px] whitespace-pre-wrap text-slate-500">{q.extra}</div>}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}
