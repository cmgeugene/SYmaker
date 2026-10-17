import { useEffect, useState } from 'react'
import { BookMarked, Check, MessageSquareText, Send, Trash2, Wand2 } from 'lucide-react'
import { api, qLabel, SCOPES, USE_MODES, type Guideline, type Job, type Paraphrase, type Scope, type UseMode } from '../../api'
import { Badge, Button, Card, Empty, SectionTitle, Textarea, cx, useAsync, useToast } from '../../components/ui'
import { RunControl } from '../../components/jobs'
import { QuestionCard } from '../../components/QuestionCard'
import { QuestionPicker } from '../../components/QuestionPicker'
import type { StepProps } from '../WorkbookPage'

interface Proposal {
  guideline_id: number
  title: string
  category: string
  new_content: string
  reason: string
}

export default function FeedbackStep({ wb, startJob, jobRunning, reload, lastJob }: StepProps) {
  const qs = wb.questions?.questions || []
  const [qn, setQn] = useState<string>('')
  const [text, setText] = useState('')
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [focus, setFocus] = useState<number | null>(null)
  const { busy, run } = useAsync()
  const toast = useToast()
  const [toGroup, setToGroup] = useState(false)
  const siblings = (wb.group?.sets || []).filter((x) => x.id !== wb.id)

  const label = (n: number) => { const q = qs.find((x) => x.number === n); return q ? qLabel(q, qs) : `${n}번` }
  const open = wb.feedback.filter((f) => f.status === 'open')
  const done = wb.feedback.filter((f) => f.status !== 'open')
  useEffect(() => setPicked(new Set(open.map((f) => f.id))), [wb.feedback.length]) // eslint-disable-line react-hooks/exhaustive-deps

  // 가장 최근의 '지침 업데이트 제안' 결과
  const guideJob = (lastJob?.stage === 'guideline' && lastJob.status === 'done' ? lastJob : null) || null
  const [proposalJob, setProposalJob] = useState<Job | null>(null)
  useEffect(() => {
    const j = wb.jobs.find((x) => x.stage === 'guideline' && x.status === 'done')
    if (guideJob) setProposalJob(guideJob)
    else if (j) api.get<Job>(`/jobs/${j.id}`).then(setProposalJob)
  }, [wb.jobs, guideJob?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const add = () =>
    run('add', async () => {
      await api.post(`/workbooks/${wb.id}/feedback`, { question_number: qn ? Number(qn) : null, text })
      setText('')
      await reload()
    })

  return (
    <div className="space-y-6">
      <SectionTitle
        title="6. 피드백 반영"
        desc="출력물을 보고 고칠 점을 적어 주세요. 문제 수정에 바로 반영하거나, 다음에도 계속 적용되도록 출제 지침이나 자료 설정(지문 사용 방식·패러프레이징 규칙)에 반영할 수 있습니다. 세트 그룹이면 다른 세트에도 함께 반영할 수 있어요."
      />

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-6 lg:col-span-2">
          <Card className="p-5">
            <h3 className="mb-3 font-semibold text-slate-900">피드백 남기기</h3>
            <div className="space-y-2">
              <QuestionPicker questions={qs} value={qn ? Number(qn) : null} onChange={(n) => { setQn(n ? String(n) : ''); setFocus(n) }} />
              <Textarea rows={4} value={text} placeholder="예: 오답 선택지가 너무 쉽게 배제됨. 지문 길이를 더 길게. 형광펜은 주제문에만." onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && text.trim()) add() }} />
              <div className="flex justify-end">
                <Button variant="primary" size="sm" icon={<Send className="size-3.5" />} disabled={!text.trim()} loading={busy === 'add'} onClick={add}>추가 (⌘↵)</Button>
              </div>
            </div>
          </Card>

          <Card className="p-5">
            <div className="mb-3 flex items-center gap-2">
              <h3 className="font-semibold text-slate-900">처리 대기</h3>
              <Badge color="sky">{open.length}</Badge>
            </div>
            {open.length === 0 ? <p className="text-sm text-slate-400">처리할 피드백이 없습니다.</p> : (
              <div className="space-y-2">
                {open.map((f) => (
                  <label key={f.id} className={cx('flex cursor-pointer gap-2 rounded-lg border p-3 text-sm', picked.has(f.id) ? 'border-brand-200 bg-brand-50/40' : 'border-slate-100')}>
                    <input type="checkbox" className="mt-0.5 size-4 accent-brand-600" checked={picked.has(f.id)} onChange={() => setPicked((s) => { const n = new Set(s); n.has(f.id) ? n.delete(f.id) : n.add(f.id); return n })} />
                    <div className="min-w-0 flex-1">
                      <span className="mr-1 font-medium text-slate-500" onClick={(e) => { e.preventDefault(); f.question_number && setFocus(f.question_number) }}>{f.question_number ? label(f.question_number) : '전체'}</span>
                      <span className="text-slate-700">{f.text}</span>
                      {f.guideline_at && <Badge color="sky" className="ml-1.5">지침·자료 반영됨</Badge>}
                    </div>
                    <button className="self-start text-slate-300 hover:text-rose-500" onClick={(e) => { e.preventDefault(); run('del', async () => { await api.del(`/feedback/${f.id}`); await reload() }) }}><Trash2 className="size-3.5" /></button>
                  </label>
                ))}
              </div>
            )}
            <div className="mt-4 space-y-3 border-t border-slate-100 pt-4">
              <div className="flex flex-col items-stretch gap-2">
                <span className="text-xs leading-relaxed text-slate-500">선택한 피드백으로 문제를 고칩니다.</span>
                <RunControl stage="revise" label="문제에 반영" icon={<Wand2 className="size-4" />} disabled={!picked.size || jobRunning}
                  onRun={async (o) => {
                    const general = open.filter((f) => picked.has(f.id) && !f.question_number)
                    await startJob('revise', { ...o, use_feedback: true, feedback_ids: [...picked] })
                    if (toGroup && siblings.length && general.length) {
                      await run('group', async () => {
                        const r = await api.post<{ started: number[]; skipped: { reason: string }[] }>(`/set-groups/${wb.group!.id}/run/revise`, {
                          ...o,
                          workbook_ids: siblings.map((x) => x.id),
                          requests: general.map((f) => `[전체] (${wb.name}에서 받은 피드백) ${f.text}`),
                        })
                        toast(r.skipped.length ? 'err' : 'ok', `다른 세트 ${r.started.length}개에서도 수정을 시작했습니다.${r.skipped.length ? ` (${r.skipped.length}개 건너뜀: ${r.skipped[0].reason})` : ''}`)
                      })
                    }
                  }} />
              </div>
              {siblings.length > 0 && (
                <label className="-mt-1 flex cursor-pointer items-start gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">
                  <input type="checkbox" className="mt-0.5 size-3.5 accent-brand-600" checked={toGroup} onChange={(e) => setToGroup(e.target.checked)} />
                  <span>
                    같은 그룹의 다른 세트 {siblings.length}개({siblings.map((x) => `${x.set_index}세트`).join(', ')})에도 반영
                    <span className="block text-slate-400">‘문제지 전체’ 피드백만 함께 보냅니다. 문항 번호를 지정한 피드백은 세트마다 문항이 달라 이 세트에만 반영됩니다.</span>
                  </span>
                </label>
              )}
              <div className="flex flex-col items-stretch gap-2">
                <span className="text-xs leading-relaxed text-slate-500">계속 적용할 원칙은 지침으로, 자료 쓰는 방식은 자료 설정으로 제안합니다.</span>
                <RunControl stage="guideline" label="지침·자료 설정 제안" icon={<BookMarked className="size-4" />} disabled={!picked.size || jobRunning}
                  onRun={(o) => startJob('guideline', { ...o, feedback_ids: [...picked] })} />
              </div>
            </div>
          </Card>

          {proposalJob?.result && (
            <Proposals job={proposalJob} workbookId={wb.id} projectId={wb.project_id} onApplied={reload} />
          )}

          {done.length > 0 && (
            <Card className="p-5">
              <h3 className="mb-3 text-sm font-semibold text-slate-500">반영 완료 ({done.length})</h3>
              <div className="space-y-1.5">
                {done.map((f) => (
                  <div key={f.id} className="flex gap-2 text-[13px] text-slate-400">
                    <Check className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
                    <span>{f.question_number ? `${label(f.question_number)} · ` : ''}{f.text}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>

        <div className="lg:col-span-3">
          {qs.length === 0 ? <Empty icon={<MessageSquareText className="size-6" />} title="아직 문제가 없습니다" /> : (
            <div className="scroll-thin grid max-h-[calc(100vh-220px)] gap-4 overflow-y-auto pr-1">
              {qs.map((q) => (
                <QuestionCard key={`${q.number}-${wb.versions[0]?.id}`} q={q} all={qs} highlight={focus === q.number}
                  onFeedback={(x) => { setQn(String(x.number)); setFocus(x.number); window.scrollTo({ top: 0, behavior: 'smooth' }) }} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

interface MaterialProposal {
  file_ref: string
  scope: '' | Scope
  use_mode: '' | UseMode
  paraphrase_length: '' | Paraphrase['length']
  paraphrase_min_words: number
  paraphrase_max_words: number
  paraphrase_level: string
  paraphrase_note: string
  note: string
  reason: string
}

interface MaterialNow { name: string; where: string; scope: Scope; use_mode: UseMode; paraphrase: Paraphrase; note: string }

const LENGTH_LABEL: Record<string, string> = { same: '원문과 비슷하게', shorter: '짧게', longer: '길게', custom: '단어 수 지정' }
const levelLabel = (l: string) => ({ same: '원문 수준', easier: '원문보다 쉽게', harder: '원문보다 어렵게' } as Record<string, string>)[l] || l.replace('-', ' ')

/** [항목, 현재, 제안] 목록 — 바뀌는 것만 */
function materialDiff(m: MaterialProposal, now: MaterialNow): [string, string, string][] {
  const out: [string, string, string][] = []
  if (m.scope && m.scope !== now.scope) out.push(['범위', SCOPES[now.scope], SCOPES[m.scope]])
  if (m.use_mode && m.use_mode !== now.use_mode) out.push(['지문 사용', USE_MODES[now.use_mode], USE_MODES[m.use_mode]])
  if (m.paraphrase_length && m.paraphrase_length !== now.paraphrase.length)
    out.push(['분량', LENGTH_LABEL[now.paraphrase.length], LENGTH_LABEL[m.paraphrase_length] + (m.paraphrase_length === 'custom' ? ` (${m.paraphrase_min_words}~${m.paraphrase_max_words}단어)` : '')])
  if (m.paraphrase_level && m.paraphrase_level !== now.paraphrase.level) out.push(['난이도', levelLabel(now.paraphrase.level), levelLabel(m.paraphrase_level)])
  if (m.paraphrase_note && m.paraphrase_note !== now.paraphrase.note) out.push(['패러프레이징 메모', now.paraphrase.note, m.paraphrase_note])
  if (m.note && m.note !== now.note) out.push(['자료 메모', now.note, m.note])
  return out
}

function Proposals({ job, workbookId, projectId, onApplied }: { job: Job; workbookId: number; projectId: number; onApplied: () => Promise<void> }) {
  const updates: Proposal[] = job.result?.updates || []
  const current: Record<string, MaterialNow> = job.result?.materials || {}
  const mats: MaterialProposal[] = (job.result?.material_updates || []).filter((m: MaterialProposal) => current[m.file_ref] && materialDiff(m, current[m.file_ref]).length)
  const [chosen, setChosen] = useState<Set<number>>(new Set(updates.map((_, i) => i)))
  const [chosenMats, setChosenMats] = useState<Set<number>>(new Set(mats.map((_, i) => i)))
  const [guides, setGuides] = useState<Guideline[]>([])
  const [scopes, setScopes] = useState<Record<number, 'project' | 'default'>>({})
  const [appliedJob, setAppliedJob] = useState<number | null>(null)
  const { busy, run } = useAsync()
  useEffect(() => { api.get<Guideline[]>(`/guidelines?project_id=${projectId}`).then(setGuides) }, [projectId])
  if (appliedJob === job.id) return null

  const feedbackIds: number[] = job.result?.feedback_ids || []
  if (job.result?.applied) return null

  return (
    <Card className="border-brand-200 p-5">
      <h3 className="mb-1 font-semibold text-slate-900">지침 · 자료 설정 수정 제안</h3>
      <p className="mb-3 text-xs text-slate-500">{job.result?.summary || '승인할 항목을 고르세요.'}</p>
      {updates.length === 0 && mats.length === 0 ? <p className="text-sm text-slate-400">지침이나 자료 설정에 반영할 일반 원칙이 없다고 판단했습니다.</p> : (
        <div className="space-y-3">
          {mats.map((m, i) => (
            <label key={`m${i}`} className={cx('block cursor-pointer rounded-lg border p-3', chosenMats.has(i) ? 'border-violet-200 bg-violet-50/40' : 'border-slate-100')}>
              <div className="flex items-center gap-2">
                <input type="checkbox" className="size-4 accent-brand-600" checked={chosenMats.has(i)} onChange={() => setChosenMats((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n })} />
                <Badge color="sky">자료 설정</Badge>
                <span className="truncate text-sm font-medium">{current[m.file_ref].name}</span>
                <span className="shrink-0 text-[11px] text-slate-400">{current[m.file_ref].where}</span>
              </div>
              <p className="mt-1.5 text-xs text-slate-500">{m.reason}</p>
              <div className="mt-2 space-y-1 rounded bg-white p-2 text-xs ring-1 ring-slate-100">
                {materialDiff(m, current[m.file_ref]).map(([k, a, b]) => (
                  <div key={k} className="flex gap-2"><span className="w-20 shrink-0 text-slate-400">{k}</span><span className="text-slate-400 line-through">{a || '없음'}</span><span>→</span><span className="font-medium text-slate-800">{b}</span></div>
                ))}
              </div>
            </label>
          ))}
          {updates.map((u, i) => {
            const old = guides.find((g) => g.id === u.guideline_id)
            return (
              <label key={i} className={cx('block cursor-pointer rounded-lg border p-3', chosen.has(i) ? 'border-brand-200 bg-brand-50/40' : 'border-slate-100')}>
                <div className="flex items-center gap-2">
                  <input type="checkbox" className="size-4 accent-brand-600" checked={chosen.has(i)} onChange={() => setChosen((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n })} />
                  <Badge color={u.guideline_id ? 'amber' : 'green'}>{u.guideline_id ? '수정' : '새 지침'}</Badge>
                  <span className="text-sm font-medium">{old?.title || u.title}</span>
                </div>
                <p className="mt-1.5 text-xs text-slate-500">{u.reason}</p>
                <div className="mt-2 flex items-center gap-1 text-xs" onClick={(e) => e.preventDefault()}>
                  <span className="mr-1 text-slate-500">반영 범위</span>
                  {(['project', 'default'] as const).map((sc) => (
                    <button key={sc} onClick={() => setScopes({ ...scopes, [i]: sc })}
                      className={cx('rounded-md px-2 py-1', (scopes[i] || 'project') === sc ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50')}>
                      {sc === 'project' ? '이 프로젝트만' : '기본 지침 (모든 프로젝트)'}
                    </button>
                  ))}
                </div>
                {scopes[i] === 'default' && (
                  <p className="mt-1.5 rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-800">
                    모든 프로젝트의 문제집에 적용됩니다. 특정 양식·학년에만 해당하는 규칙이면 ‘이 프로젝트만’을 고르세요.
                  </p>
                )}
                <pre className="mt-2 max-h-40 overflow-y-auto rounded bg-white p-2 font-sans text-xs whitespace-pre-wrap text-slate-700 ring-1 ring-slate-100">{u.new_content}</pre>
              </label>
            )
          })}
          <Button className="w-full" variant="primary" disabled={!chosen.size && !chosenMats.size} loading={busy === 'apply'} onClick={async () => {
            const toDefault = updates.filter((_, i) => chosen.has(i) && scopes[i] === 'default')
            if (toDefault.length) {
              const n = (await api.get<unknown[]>('/projects')).length
              if (!window.confirm(`기본 지침 ${toDefault.length}건을 바꾸면 이 프로젝트뿐 아니라 모든 프로젝트(${n}개)의 문제집에 적용됩니다.\n특정 양식·학년에만 해당하는 규칙이라면 '이 프로젝트만'을 고르세요.\n\n그래도 기본 지침을 바꿀까요?`)) return
            }
            run('apply', async () => {
              await api.post('/guidelines/apply', {
                updates: updates.map((u, i) => ({ ...u, scope: scopes[i] || 'project' })).filter((_, i) => chosen.has(i)),
                material_updates: mats.filter((_, i) => chosenMats.has(i)),
                workbook_id: workbookId, feedback_ids: feedbackIds, job_id: job.id,
              })
              setAppliedJob(job.id)
              await onApplied()
            }, '선택한 제안을 반영했습니다.')
          }}>
            선택한 {chosen.size + chosenMats.size}건 반영
          </Button>
        </div>
      )}
    </Card>
  )
}
