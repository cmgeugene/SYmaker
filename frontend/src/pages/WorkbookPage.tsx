import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Check, ChevronRight, Pencil, Trash2 } from 'lucide-react'
import { api, type Job, type StageKey, type Workbook } from '../api'
import { Button, Input, Spinner, confirmDialog, cx, useAsync, useToast } from '../components/ui'
import { JobPanel, useJobPolling } from '../components/jobs'
import { STAGES } from '../components/StageDots'
import MaterialsStep from './workbook/MaterialsStep'
import AnalyzeStep from './workbook/AnalyzeStep'
import GenerateStep from './workbook/GenerateStep'
import ReviewStep from './workbook/ReviewStep'
import ExportStep from './workbook/ExportStep'
import FeedbackStep from './workbook/FeedbackStep'

export interface StepProps {
  wb: Workbook
  reload: () => Promise<void>
  startJob: (stage: string, body?: Record<string, unknown>) => Promise<Job | undefined>
  jobRunning: boolean
  goto: (s: StageKey) => void
  lastJob: Job | null
}

export default function WorkbookPage({ refreshSidebar }: { refreshSidebar: () => Promise<void> }) {
  const { wid } = useParams()
  const [params, setParams] = useSearchParams()
  const nav = useNavigate()
  const toast = useToast()
  const [wb, setWb] = useState<Workbook | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  const [lastJob, setLastJob] = useState<Job | null>(null)
  const [editingName, setEditingName] = useState(false)
  const [name, setName] = useState('')
  const { run } = useAsync()

  const load = useCallback(async () => {
    const w = await api.get<Workbook>(`/workbooks/${wid}`)
    setWb(w)
    return w
  }, [wid])

  useEffect(() => {
    load().then((w) => {
      const active = w.jobs.find((j) => j.status === 'running' || j.status === 'queued')
      setJobId(active ? active.id : null)
    })
  }, [load])

  const job = useJobPolling(jobId, async (j) => {
    setLastJob(j)
    await load()
    if (j.status === 'done') toast('ok', '작업이 완료되었습니다.')
    else if (j.status === 'failed') toast('err', '작업이 실패했습니다. 로그를 확인하세요.')
  })

  const step = (params.get('step') as StageKey) || defaultStep(wb)
  const goto = (s: StageKey) => setParams({ step: s }, { replace: true })

  const startJob = async (stage: string, body: Record<string, unknown> = {}) => {
    try {
      const j = await api.post<Job>(`/workbooks/${wid}/run/${stage}`, body)
      setLastJob(null)
      setJobId(j.id)
      return j
    } catch (e) {
      toast('err', (e as Error).message)
    }
  }

  if (!wb) return <div className="flex h-full items-center justify-center"><Spinner /></div>

  const running = !!job && (job.status === 'running' || job.status === 'queued')
  const props: StepProps = { wb, reload: async () => void (await load()), startJob, jobRunning: running, goto, lastJob }

  return (
    <div className="flex min-h-full flex-col">
      {/* 머리 */}
      <div className="border-b border-slate-200 bg-white px-8 pt-6">
        <div className="mx-auto max-w-6xl">
          <div className="flex items-center gap-1 text-[13px] text-slate-400">
            <Link to={`/projects/${wb.project_id}`} className="hover:text-slate-600">
              {wb.project.year}년 {wb.project.semester} · {wb.project.name}
            </Link>
            <ChevronRight className="size-3.5" />
            <span>{wb.group ? wb.group.name : '문제집'}</span>
            {wb.group && (
              <div className="ml-3 flex gap-1">
                {wb.group.sets.map((s) => (
                  <Link key={s.id} to={`/workbooks/${s.id}${step ? `?step=${step}` : ''}`}
                    className={cx('rounded-md px-2 py-0.5 text-xs', s.id === wb.id ? 'bg-brand-600 font-medium text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200')}>
                    {s.set_index}세트
                  </Link>
                ))}
              </div>
            )}
          </div>
          <div className="mt-1 flex items-center gap-3">
            {editingName ? (
              <div className="flex items-center gap-2">
                <Input autoFocus className="!h-10 w-96 text-lg font-semibold" value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => {
                  if (e.key === 'Enter') run('name', async () => { await api.put(`/workbooks/${wb.id}`, { name }); await load(); setEditingName(false); refreshSidebar() })
                  if (e.key === 'Escape') setEditingName(false)
                }} />
                <Button size="sm" variant="primary" onClick={() => run('name', async () => { await api.put(`/workbooks/${wb.id}`, { name }); await load(); setEditingName(false) })}>저장</Button>
              </div>
            ) : (
              <>
                <h1 className="text-2xl font-bold text-slate-900">{wb.name}</h1>
                <button className="rounded-md p-1 text-slate-300 hover:bg-slate-100 hover:text-slate-500" onClick={() => { setName(wb.name); setEditingName(true) }}>
                  <Pencil className="size-4" />
                </button>
              </>
            )}
            <div className="ml-auto">
              <Button variant="ghost" size="sm" icon={<Trash2 className="size-3.5" />} onClick={() =>
                confirmDialog('이 문제집을 삭제할까요? 올린 파일과 출력물도 함께 삭제됩니다.') &&
                run('del', async () => { await api.del(`/workbooks/${wb.id}`); nav(`/projects/${wb.project_id}`) })
              }>삭제</Button>
            </div>
          </div>

          {/* 단계 표시 */}
          <div className="mt-5 flex">
            {STAGES.map((s, i) => {
              const st = wb.status[s.key]
              const active = step === s.key
              return (
                <button key={s.key} onClick={() => goto(s.key)} className={cx(
                  'group relative flex flex-1 items-center gap-2.5 border-b-2 px-1 pb-3 text-left transition-colors',
                  active ? 'border-brand-600' : 'border-transparent hover:border-slate-200',
                )}>
                  <span className={cx(
                    'flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                    st === 'done' ? 'bg-emerald-500 text-white' : active ? 'bg-brand-600 text-white' : st === 'stale' ? 'bg-amber-400 text-white' : st === 'open' ? 'bg-sky-500 text-white' : 'bg-slate-100 text-slate-500',
                  )}>
                    {st === 'done' ? <Check className="size-3.5" /> : i + 1}
                  </span>
                  <span className="min-w-0">
                    <span className={cx('block text-sm', active ? 'font-semibold text-slate-900' : 'text-slate-600')}>{s.label}</span>
                    <span className="block text-[11px] text-slate-400">{statusText(st)}</span>
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      </div>

      <div className="mx-auto w-full max-w-6xl flex-1 px-8 py-6">
        {(job || lastJob) && (
          <div className="mb-6">
            <JobPanel job={(job || lastJob)!} onClose={() => { setJobId(null); setLastJob(null) }} />
          </div>
        )}
        {step === 'materials' && <MaterialsStep {...props} />}
        {step === 'analyze' && <AnalyzeStep {...props} />}
        {step === 'generate' && <GenerateStep {...props} />}
        {step === 'review' && <ReviewStep {...props} />}
        {step === 'export' && <ExportStep {...props} />}
        {step === 'feedback' && <FeedbackStep {...props} />}
      </div>
    </div>
  )
}

function statusText(st: string) {
  return { done: '완료', stale: '다시 필요', open: '처리 대기', todo: '' }[st] || ''
}

function defaultStep(wb: Workbook | null): StageKey {
  if (!wb) return 'materials'
  const order: StageKey[] = ['materials', 'analyze', 'generate', 'review', 'export']
  return order.find((k) => wb.status[k] !== 'done') || 'feedback'
}
