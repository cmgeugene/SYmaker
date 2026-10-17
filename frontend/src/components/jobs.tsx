import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { Bot, CheckCircle2, ChevronDown, ChevronUp, CircleSlash, Loader2, Square, XCircle } from 'lucide-react'
import { api, type Job, type Settings } from '../api'
import { Button, Select, cx } from './ui'

/* ---------------- 모델 설정 (전역 캐시) ---------------- */

const SettingsCtx = createContext<{ settings: Settings | null; reload: () => void }>({ settings: null, reload: () => {} })

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<Settings | null>(null)
  const reload = () => void api.get<Settings>('/settings').then(setSettings)
  useEffect(reload, [])
  return <SettingsCtx.Provider value={{ settings, reload }}>{children}</SettingsCtx.Provider>
}

export const useSettings = () => useContext(SettingsCtx)

/** 단계 실행 버튼 + 이번 실행에 쓸 모델/effort 선택 */
export function RunControl({
  stage,
  label,
  onRun,
  disabled,
  busy,
  icon,
  hint,
}: {
  stage: string
  label: string
  onRun: (opts: { model: string; effort: string }) => void
  disabled?: boolean
  busy?: boolean
  icon?: React.ReactNode
  hint?: string
}) {
  const { settings } = useSettings()
  const def = settings?.stages[stage]
  const [model, setModel] = useState('')
  const [effort, setEffort] = useState('')
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (def) {
      setModel(def.model)
      setEffort(def.effort)
    }
  }, [def?.model, def?.effort]) // eslint-disable-line react-hooks/exhaustive-deps

  const info = settings?.models.find((m) => m.id === model)
  const efforts = info?.efforts || ['low', 'medium', 'high']
  const effortLabel = (e: string) => settings?.effort_labels[e] || e

  return (
    <div className="flex max-w-full flex-col items-end gap-1.5">
      <div className="flex max-w-full flex-wrap items-center justify-end gap-x-2 gap-y-1.5">
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs whitespace-nowrap text-slate-500 hover:bg-slate-100"
          title="이번 실행에 사용할 모델 변경"
        >
          <Bot className="size-3.5" />
          {model || '…'} · {effortLabel(effort)}
          {open ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
        </button>
        <Button variant="primary" size="md" icon={icon} loading={busy} disabled={disabled || !model} onClick={() => onRun({ model, effort })}>
          {label}
        </Button>
      </div>
      {open && settings && (
        <div className="flex max-w-full flex-wrap items-center justify-end gap-2 rounded-lg border border-slate-200 bg-white p-2 shadow-sm">
          <Select className="!h-8 w-44 text-xs" value={model} onChange={(e) => {
            setModel(e.target.value)
            const m = settings.models.find((x) => x.id === e.target.value)
            if (m && !m.efforts.includes(effort)) setEffort(m.default_effort)
          }}>
            {settings.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </Select>
          <Select className="!h-8 w-28 text-xs" value={effort} onChange={(e) => setEffort(e.target.value)}>
            {efforts.map((e) => (
              <option key={e} value={e}>
                {effortLabel(e)}
              </option>
            ))}
          </Select>
        </div>
      )}
      {hint && <span className="text-xs text-slate-400">{hint}</span>}
    </div>
  )
}

/* ---------------- 진행 중 작업 표시 ---------------- */

const STAGE_NAMES: Record<string, string> = {
  analyze: '샘플 분석',
  generate: '문제 제작',
  review: '검수',
  revise: '문제 수정',
  guideline: '지침 업데이트 제안',
}

export function useJobPolling(jobId: number | null, onFinish: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null)
  const finishRef = useRef(onFinish)
  finishRef.current = onFinish
  useEffect(() => {
    if (!jobId) {
      setJob(null)
      return
    }
    let stop = false
    const tick = async () => {
      try {
        const j = await api.get<Job>(`/jobs/${jobId}`)
        if (stop) return
        setJob(j)
        if (j.status === 'running' || j.status === 'queued') setTimeout(tick, 1500)
        else finishRef.current(j)
      } catch {
        if (!stop) setTimeout(tick, 3000)
      }
    }
    tick()
    return () => {
      stop = true
    }
  }, [jobId])
  return job
}

export function JobPanel({ job, onClose }: { job: Job; onClose: () => void }) {
  const [expanded, setExpanded] = useState(true)
  const logRef = useRef<HTMLPreElement>(null)
  const running = job.status === 'running' || job.status === 'queued'
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [job.log])
  const started = new Date(job.created_at).getTime()
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [running])
  const secs = Math.max(0, Math.round(((running ? now : new Date(job.finished_at || now).getTime()) - started) / 1000))

  return (
    <div
      className={cx(
        'rounded-xl border p-4',
        running && 'border-brand-200 bg-brand-50/60',
        job.status === 'done' && 'border-emerald-200 bg-emerald-50/60',
        (job.status === 'failed' || job.status === 'cancelled') && 'border-rose-200 bg-rose-50/60',
      )}
    >
      <div className="flex items-center gap-3">
        {running && <Loader2 className="size-5 animate-spin text-brand-600" />}
        {job.status === 'done' && <CheckCircle2 className="size-5 text-emerald-600" />}
        {job.status === 'failed' && <XCircle className="size-5 text-rose-600" />}
        {job.status === 'cancelled' && <CircleSlash className="size-5 text-rose-500" />}
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-slate-800">
            {STAGE_NAMES[job.stage] || job.stage}{' '}
            {running ? '진행 중…' : job.status === 'done' ? '완료' : job.status === 'cancelled' ? '중단됨' : '실패'}
          </div>
          <div className="text-xs text-slate-500">
            {job.model} · {job.effort} · {Math.floor(secs / 60)}분 {secs % 60}초
            {running && ' · 이 화면을 떠나도 작업은 계속됩니다'}
          </div>
        </div>
        <button className="rounded-md p-1 text-slate-400 hover:bg-white/70" onClick={() => setExpanded(!expanded)}>
          {expanded ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
        </button>
        {running ? (
          <Button size="sm" variant="danger" icon={<Square className="size-3" />} onClick={() => api.post(`/jobs/${job.id}/cancel`)}>
            중단
          </Button>
        ) : (
          <Button size="sm" variant="ghost" onClick={onClose}>
            닫기
          </Button>
        )}
      </div>
      {job.progress && job.progress.total > 1 && (
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-xs text-slate-600">
            <span>{job.progress.label}</span>
            <span>{job.progress.done} / {job.progress.total} 단계</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-white/80 ring-1 ring-slate-200">
            <div className={cx('h-full rounded-full transition-all', running ? 'bg-brand-500' : job.status === 'done' ? 'bg-emerald-500' : 'bg-rose-400')}
              style={{ width: `${(job.progress.done / job.progress.total) * 100}%` }} />
          </div>
        </div>
      )}
      {job.error && <div className="mt-3 rounded-lg bg-white/80 p-3 text-xs whitespace-pre-wrap text-rose-700">{job.error}</div>}
      {expanded && (
        <pre ref={logRef} className="scroll-thin mt-3 max-h-48 overflow-y-auto rounded-lg bg-slate-900 p-3 text-[11.5px] leading-relaxed whitespace-pre-wrap text-slate-200">
          {job.log || '준비 중…'}
        </pre>
      )}
    </div>
  )
}
