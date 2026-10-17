import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, ChevronDown, ChevronRight, Eye, EyeOff, Pencil, Plus, Scissors, Trash2, UploadCloud } from 'lucide-react'
import { api, SCOPES, USE_MODES, type Job, type Passage, type ProjectFile, type Scope, type UseMode } from '../../api'
import { Badge, Button, Card, Empty, Field, Input, Modal, Select, Spinner, Textarea, confirmDialog, cx, useAsync, useToast } from '../../components/ui'
import { JobPanel, RunControl, useJobPolling } from '../../components/jobs'
import { ParaphraseControls } from '../../components/ParaphraseControls'

interface Materials {
  files: ProjectFile[]
  passages: Passage[]
  jobs: { id: number; stage: string; status: string }[]
}

export default function MaterialsTab({ projectId, onChanged }: { projectId: number; onChanged: () => void }) {
  const [data, setData] = useState<Materials | null>(null)
  const [jobId, setJobId] = useState<number | null>(null)
  const [lastJob, setLastJob] = useState<Job | null>(null)
  const toast = useToast()

  const load = useCallback(async () => {
    const d = await api.get<Materials>(`/projects/${projectId}/materials`)
    setData(d)
    return d
  }, [projectId])

  useEffect(() => {
    load().then((d) => {
      const r = d.jobs.find((j) => j.status === 'running')
      if (r) setJobId(r.id)
    })
  }, [load])

  const job = useJobPolling(jobId, async (j) => {
    setLastJob(j)
    await load()
    onChanged()
    toast(j.status === 'done' ? 'ok' : 'err', j.status === 'done' ? '본문 나누기가 끝났습니다. 목록을 확인해 주세요.' : '본문 나누기에 실패한 부분이 있습니다.')
  })

  if (!data) return <div className="flex justify-center py-16"><Spinner /></div>
  const refs = data.files.filter((f) => f.kind === 'reference')
  const samples = data.files.filter((f) => f.kind === 'sample')
  const running = !!job && job.status === 'running'

  return (
    <div className="space-y-6">
      <p className="text-sm text-slate-500">
        여기에 올린 자료는 이 프로젝트의 모든 문제집·세트에서 함께 씁니다. 출제 범위 자료는 ‘본문 나누기’로 본문 목록을 만들면,
        세트끼리 본문이 겹치지 않고 고르게 쓰이도록 자동 배정할 수 있어요.
      </p>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="p-5 lg:col-span-3">
          <div className="mb-3 flex items-center gap-2">
            <h3 className="font-semibold text-slate-900">출제 범위 자료</h3>
            <Badge>{refs.length}개</Badge>
            <div className="ml-auto">
              <RunControl stage="segment" label={refs.some((f) => f.segmented_at) ? '본문 다시 나누기' : '본문 나누기'} icon={<Scissors className="size-4" />}
                disabled={!refs.length || running} busy={running}
                onRun={async (o) => {
                  if (data.passages.length && !window.confirm('기존 본문 목록을 새로 만듭니다. 직접 고친 내용과 기존 세트의 본문 배정은 다시 확인해야 합니다. 계속할까요?')) return
                  try {
                    const j = await api.post<Job>(`/projects/${projectId}/segment`, o)
                    setLastJob(null)
                    setJobId(j.id)
                  } catch (e) {
                    toast('err', (e as Error).message)
                  }
                }} />
            </div>
          </div>
          <Upload projectId={projectId} kind="reference" onDone={async () => { await load(); onChanged() }}
            hint="부교재, 교과서, 프린트 등. 본문 구분 방식이 달라도 Codex가 읽고 본문을 찾아요." />
          <div className="mt-3 space-y-2">
            {refs.map((f) => <FileRow key={f.id} f={f} onChanged={async () => { await load(); onChanged() }} />)}
          </div>
        </Card>

        <Card className="p-5 lg:col-span-2">
          <div className="mb-3 flex items-center gap-2">
            <h3 className="font-semibold text-slate-900">문제지 샘플 (공통)</h3>
            <Badge>{samples.length}개</Badge>
          </div>
          <Upload projectId={projectId} kind="sample" onDone={async () => { await load(); onChanged() }}
            hint="모든 세트가 이 샘플의 유형·서식을 따릅니다. HWP/HWPX 권장." />
          <div className="mt-3 space-y-2">
            {samples.map((f) => <FileRow key={f.id} f={f} onChanged={async () => { await load(); onChanged() }} />)}
          </div>
        </Card>
      </div>

      {(job || lastJob) && <JobPanel job={(job || lastJob)!} onClose={() => { setJobId(null); setLastJob(null) }} />}

      <PassageList data={data} reload={load} />
    </div>
  )
}

function Upload({ projectId, kind, onDone, hint }: { projectId: number; kind: 'reference' | 'sample'; onDone: () => Promise<void>; hint: string }) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState<string[]>([])
  const [drag, setDrag] = useState(false)
  const toast = useToast()
  const upload = async (list: FileList | File[]) => {
    const arr = Array.from(list)
    setBusy(arr.map((f) => f.name))
    for (const f of arr) {
      const fd = new FormData()
      fd.append('kind', kind)
      fd.append('file', f)
      try {
        await api.post(`/projects/${projectId}/files`, fd)
      } catch (e) {
        toast('err', `${f.name}: ${(e as Error).message}`)
      }
    }
    setBusy([])
    await onDone()
  }
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files) }}
      onClick={() => input.current?.click()}
      className={cx('flex cursor-pointer items-center gap-3 rounded-xl border-2 border-dashed px-4 py-4 transition-colors', drag ? 'border-brand-500 bg-brand-50' : 'border-slate-200 hover:border-brand-200 hover:bg-slate-50')}
    >
      {busy.length ? <Spinner /> : <UploadCloud className="size-6 shrink-0 text-slate-400" />}
      <div className="text-sm">
        <div className="font-medium text-slate-700">{busy.length ? `${busy.join(', ')} 처리 중…` : '파일을 끌어다 놓거나 클릭'}</div>
        <div className="text-xs text-slate-400">{hint} (TXT · PDF · HWP · HWPX)</div>
      </div>
      <input ref={input} type="file" multiple accept=".txt,.pdf,.hwp,.hwpx,.md" className="hidden" onChange={(e) => e.target.files && upload(e.target.files)} />
    </div>
  )
}

function FileRow({ f, onChanged }: { f: ProjectFile; onChanged: () => Promise<void> }) {
  const [note, setNote] = useState(f.note)
  const [view, setView] = useState(false)
  const { run } = useAsync()
  const save = (patch: Partial<ProjectFile>) => run('save', async () => { await api.put(`/project-files/${f.id}`, patch); await onChanged() })
  const ext = f.orig_name.split('.').pop()?.toUpperCase()
  return (
    <div className={cx('rounded-lg border p-3', f.scope === 'exclude' ? 'border-slate-100 bg-slate-50 opacity-60' : 'border-slate-100 bg-slate-50/60')}>
      <div className="flex items-center gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white text-[10px] font-bold text-slate-500 ring-1 ring-slate-200">{ext}</div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-slate-800">{f.orig_name}</div>
          <div className="text-xs text-slate-500">
            {f.text_length.toLocaleString()}자
            {f.kind === 'reference' && (f.segmented_at ? ` · 본문 ${f.passage_count}개${f.excluded_count ? ` (제외 ${f.excluded_count})` : ''}` : ' · 본문 나누기 전')}
            {!!f.unlocated_count && <span className="ml-1 text-amber-600">· 확인 필요 {f.unlocated_count}</span>}
          </div>
        </div>
        <Button size="sm" variant="ghost" icon={<Eye className="size-3.5" />} onClick={() => setView(true)}>보기</Button>
        <button className="rounded-md p-1.5 text-slate-400 hover:bg-white hover:text-rose-600"
          onClick={() => confirmDialog(`${f.orig_name}을(를) 삭제할까요? 나눈 본문도 함께 삭제됩니다.`) && run('del', async () => { await api.del(`/project-files/${f.id}`); await onChanged() })}>
          <Trash2 className="size-4" />
        </button>
      </div>
      {f.kind === 'reference' && (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Select className="!h-8 bg-white text-xs" value={f.scope} onChange={(e) => save({ scope: e.target.value as Scope })}>
            {Object.entries(SCOPES).map(([k, v]) => <option key={k} value={k}>범위: {v}</option>)}
          </Select>
          <Select className="!h-8 bg-white text-xs" value={f.use_mode} disabled={f.scope !== 'range'} onChange={(e) => save({ use_mode: e.target.value as UseMode })}>
            {Object.entries(USE_MODES).map(([k, v]) => <option key={k} value={k}>지문: {v}</option>)}
          </Select>
        </div>
      )}
      {f.kind === 'reference' && f.scope === 'range' && f.use_mode === 'paraphrase' && (
        <ParaphraseControls value={f.paraphrase} onChange={(paraphrase) => save({ paraphrase })} />
      )}
      <Input className="mt-2 !h-8 bg-white text-xs" placeholder="메모 (예: 3과·4과만 범위, 어휘 문제 위주로)" value={note}
        onChange={(e) => setNote(e.target.value)} onBlur={() => note !== f.note && save({ note })} />
      {view && <TextModal id={f.id} name={f.orig_name} onClose={() => setView(false)} />}
    </div>
  )
}

function TextModal({ id, name, onClose }: { id: number; name: string; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null)
  useEffect(() => { api.get<{ text: string }>(`/project-files/${id}`).then((f) => setText(f.text)) }, [id])
  return (
    <Modal open wide onClose={onClose} title={name}>
      {text === null ? <Spinner /> : <pre className="rounded-lg bg-slate-50 p-4 font-sans text-[13px] leading-relaxed whitespace-pre-wrap text-slate-700">{text}</pre>}
    </Modal>
  )
}

function PassageList({ data, reload }: { data: Materials; reload: () => Promise<unknown> }) {
  const [closed, setClosed] = useState<Record<number, boolean>>({})
  const [edit, setEdit] = useState<Passage | 'new' | null>(null)
  const [newFor, setNewFor] = useState<number | null>(null)
  const { run } = useAsync()
  const files = data.files.filter((f) => f.kind === 'reference')
  if (!data.passages.length) {
    return (
      <Empty icon={<Scissors className="size-6" />} title="아직 본문 목록이 없습니다"
        desc="출제 범위 자료를 올리고 ‘본문 나누기’를 누르면 Codex가 각 자료에서 영어 본문을 찾아 목록을 만듭니다. 해석·어휘 목록·기존 문제의 발문은 빠집니다." />
    )
  }
  return (
    <Card className="p-5">
      <div className="mb-1 flex items-center gap-2">
        <h3 className="font-semibold text-slate-900">본문 목록</h3>
        <Badge>{data.passages.filter((p) => !p.excluded).length}개 사용</Badge>
      </div>
      <p className="mb-4 text-xs text-slate-500">본문 텍스트는 원본 자료에서 그대로 잘라 온 것입니다. 경계가 틀렸으면 고치고, 쓰지 않을 본문은 숨기세요. 오른쪽에 세트별 사용 기록이 보입니다.</p>
      <div className="space-y-4">
        {files.map((f) => {
          const list = data.passages.filter((p) => p.file_id === f.id)
          if (!list.length) return null
          return (
            <div key={f.id}>
              <button className="mb-2 flex w-full items-center gap-2 text-left text-sm font-semibold text-slate-700" onClick={() => setClosed((c) => ({ ...c, [f.id]: !c[f.id] }))}>
                {closed[f.id] ? <ChevronRight className="size-4" /> : <ChevronDown className="size-4" />}
                {f.orig_name}
                <span className="text-xs font-normal text-slate-400">{list.length}개 · 지문 {USE_MODES[f.use_mode]}{f.scope !== 'range' ? ` · ${SCOPES[f.scope]}` : ''}</span>
                <span className="ml-auto" onClick={(e) => { e.stopPropagation(); setNewFor(f.id); setEdit('new') }}>
                  <Badge className="cursor-pointer hover:bg-slate-200"><Plus className="size-3" /> 직접 추가</Badge>
                </span>
              </button>
              {!closed[f.id] && (
                <div className="divide-y divide-slate-100 rounded-lg border border-slate-100">
                  {list.map((p) => (
                    <div key={p.id} className={cx('flex items-start gap-3 px-3 py-2.5', !!p.excluded && 'bg-slate-50 opacity-50')}>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className="text-sm font-medium text-slate-800">{p.label}</span>
                          {!p.located && <Badge color="amber"><AlertTriangle className="size-3" /> 원문 위치 확인 필요</Badge>}
                          {p.suitable_types.slice(0, 6).map((t) => <span key={t} className="rounded bg-slate-100 px-1.5 text-[11px] text-slate-500">{t}</span>)}
                        </div>
                        <p className="mt-0.5 line-clamp-1 text-[13px] text-slate-500">{p.summary || p.text.slice(0, 120)}</p>
                      </div>
                      <div className="flex max-w-[40%] shrink-0 flex-wrap justify-end gap-1">
                        {p.usage.map((u, i) => <Badge key={i} color="brand">{u.workbook.replace(/^.*?(\d+세트)$/, '$1')} · {u.type}</Badge>)}
                      </div>
                      <div className="flex shrink-0 gap-0.5">
                        <button title="편집" className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={() => setEdit(p)}><Pencil className="size-3.5" /></button>
                        <button title={p.excluded ? '다시 사용' : '사용 안 함'} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                          onClick={() => run('ex', async () => { await api.put(`/passages/${p.id}`, { excluded: p.excluded ? 0 : 1 }); await reload() })}>
                          {p.excluded ? <Eye className="size-3.5" /> : <EyeOff className="size-3.5" />}
                        </button>
                        <button title="삭제" className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-rose-600"
                          onClick={() => confirmDialog(`'${p.label}' 본문을 삭제할까요?`) && run('del', async () => { await api.del(`/passages/${p.id}`); await reload() })}>
                          <Trash2 className="size-3.5" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
      {edit && <PassageEditor p={edit === 'new' ? null : edit} fileId={newFor} onClose={() => setEdit(null)} onSaved={async () => { setEdit(null); await reload() }} />}
    </Card>
  )
}

function PassageEditor({ p, fileId, onClose, onSaved }: { p: Passage | null; fileId: number | null; onClose: () => void; onSaved: () => Promise<void> }) {
  const [label, setLabel] = useState(p?.label || '')
  const [text, setText] = useState(p?.text || '')
  const [types, setTypes] = useState((p?.suitable_types || []).join(', '))
  const { busy, run } = useAsync()
  const save = () =>
    run('save', async () => {
      const body = { label, text, suitable_types: types.split(',').map((t) => t.trim()).filter(Boolean) }
      if (p) await api.put(`/passages/${p.id}`, body)
      else await api.post(`/project-files/${fileId}/passages`, body)
      await onSaved()
    })
  return (
    <Modal open wide onClose={onClose} title={p ? '본문 편집' : '본문 직접 추가'} footer={
      <>
        <Button variant="ghost" onClick={onClose}>취소</Button>
        <Button variant="primary" loading={busy === 'save'} disabled={!text.trim()} onClick={save}>저장</Button>
      </>
    }>
      <div className="space-y-3">
        <Field label="이름"><Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="예: Lesson 3 · Reading 1" /></Field>
        <Field label="본문" hint="원문 그대로 붙여 넣으세요."><Textarea rows={12} value={text} onChange={(e) => setText(e.target.value)} /></Field>
        <Field label="적합한 유형 (쉼표로 구분)" hint="비워 두면 모든 유형에 배정될 수 있습니다."><Input value={types} onChange={(e) => setTypes(e.target.value)} /></Field>
      </div>
    </Modal>
  )
}
