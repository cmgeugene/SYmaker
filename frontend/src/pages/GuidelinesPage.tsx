import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { BookMarked, Copy, FolderOpen, Globe, History, Info, Plus, RotateCcw, Save, Trash2 } from 'lucide-react'
import { api, type Guideline, type Project } from '../api'
import { Badge, Button, Card, Empty, Field, Input, Modal, Select, Textarea, confirmDialog, cx, useAsync } from '../components/ui'

interface Version { id: number; version: number; content: string; note: string; created_at: string }

export const SCOPE_BADGE: Record<Guideline['scope'], { label: string; color: 'slate' | 'brand' | 'amber' }> = {
  default: { label: '기본', color: 'slate' },
  project: { label: '프로젝트', color: 'brand' },
  override: { label: '프로젝트 수정본', color: 'amber' },
}

export default function GuidelinesPage() {
  const [params, setParams] = useSearchParams()
  const projectId = params.get('project') ? Number(params.get('project')) : null
  const [projects, setProjects] = useState<Project[]>([])
  const [list, setList] = useState<Guideline[]>([])
  const [sel, setSel] = useState<number | null>(null)
  const [draft, setDraft] = useState<Partial<Guideline>>({})
  const [versions, setVersions] = useState<Version[] | null>(null)
  const { busy, run } = useAsync()

  useEffect(() => { api.get<Project[]>('/projects').then(setProjects) }, [])

  const load = useCallback(async (keep?: number | null) => {
    const l = await api.get<Guideline[]>(projectId ? `/guidelines?project_id=${projectId}` : '/guidelines')
    setList(l)
    const next = l.find((g) => g.id === keep) || l[0]
    setSel(next?.id ?? null)
    setDraft(next || {})
  }, [projectId])

  useEffect(() => { load() }, [load])

  const pick = (g: Guideline) => { setSel(g.id); setDraft(g) }
  const setScope = (pid: number | null) => setParams(pid ? { project: String(pid) } : {})

  const current = list.find((g) => g.id === sel)
  const project = projects.find((p) => p.id === projectId)
  const readOnly = !!projectId && current?.scope === 'default'
  const dirty = current && !readOnly && (draft.title !== current.title || draft.category !== current.category || draft.content !== current.content)
  const cats = [...new Set(list.map((g) => g.category || '기타'))]

  return (
    <div className="mx-auto flex h-full max-w-6xl flex-col px-8 py-8">
      <div className="mb-5 flex items-end justify-between gap-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">출제 지침</h1>
          <p className="mt-1 text-sm text-slate-500">
            <b className="font-medium text-slate-700">기본 지침</b>은 모든 프로젝트에 적용됩니다. 프로젝트마다 기본 지침을 고쳐 쓰거나, 그 프로젝트만의 지침을 추가할 수 있어요.
          </p>
        </div>
        <Button variant="primary" icon={<Plus className="size-4" />} onClick={() =>
          run('new', async () => {
            const g = await api.post<Guideline>('/guidelines', { title: '새 지침', category: '유형', content: '- ', project_id: projectId })
            await load(g.id)
          })
        }>
          {projectId ? '프로젝트 지침 추가' : '기본 지침 추가'}
        </Button>
      </div>

      {/* 범위 선택 */}
      <div className="mb-5 flex items-center gap-2">
        <button onClick={() => setScope(null)} className={cx('flex h-9 items-center gap-2 rounded-lg border px-3 text-sm', !projectId ? 'border-brand-200 bg-brand-50 font-medium text-brand-700' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50')}>
          <Globe className="size-4" /> 기본 지침
        </button>
        <div className={cx('flex items-center gap-2 rounded-lg border pl-3', projectId ? 'border-brand-200 bg-brand-50' : 'border-slate-200 bg-white')}>
          <FolderOpen className={cx('size-4', projectId ? 'text-brand-700' : 'text-slate-400')} />
          <Select className="!h-9 w-64 !border-0 !bg-transparent !ring-0" value={projectId ?? ''} onChange={(e) => setScope(e.target.value ? Number(e.target.value) : null)}>
            <option value="">프로젝트별 지침 보기…</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.year}년 {p.semester} · {p.name}</option>)}
          </Select>
        </div>
        {project && <span className="text-xs text-slate-500">이 프로젝트의 문제집에서 실제로 쓰이는 지침입니다.</span>}
      </div>

      {list.length === 0 ? (
        <Empty icon={<BookMarked className="size-6" />} title="지침이 없습니다" />
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[280px_1fr] gap-6">
          <Card className="scroll-thin overflow-y-auto p-2">
            {cats.map((c) => (
              <div key={c} className="mb-2">
                <div className="px-3 pt-2 pb-1 text-[11px] font-semibold text-slate-400">{c}</div>
                {list.filter((g) => (g.category || '기타') === c).map((g) => (
                  <button key={g.id} onClick={() => pick(g)} className={cx('flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm', sel === g.id ? 'bg-brand-50 font-medium text-brand-700' : 'text-slate-700 hover:bg-slate-50')}>
                    <span className="truncate">{g.title}</span>
                    <span className="ml-auto flex shrink-0 items-center gap-1">
                      {projectId && g.scope !== 'default' && <Badge color={SCOPE_BADGE[g.scope].color} className="!px-1.5 !text-[10px]">{g.scope === 'override' ? '수정본' : '전용'}</Badge>}
                      <span className="text-[11px] text-slate-400">v{g.version}</span>
                    </span>
                  </button>
                ))}
              </div>
            ))}
          </Card>

          {current && (
            <Card className="scroll-thin flex min-h-0 flex-col overflow-y-auto p-5">
              <ScopeNotice
                g={current}
                projectId={projectId}
                busy={busy}
                onCustomize={() => run('custom', async () => {
                  const g = await api.post<Guideline>(`/projects/${projectId}/guidelines/${current.id}/customize`)
                  await load(g.id)
                }, '이 프로젝트용 수정본을 만들었습니다. 이제 자유롭게 고치세요.')}
                onRevert={() => confirmDialog('프로젝트 수정본을 지우고 기본 지침으로 되돌릴까요?') && run('revert', async () => {
                  await api.del(`/guidelines/${current.id}`)
                  await load(current.base_id)
                }, '기본 지침으로 되돌렸습니다.')}
                onOpenDefault={() => setScope(null)}
              />
              <div className="grid grid-cols-[1fr_180px] gap-3">
                <Field label="제목"><Input disabled={readOnly} value={draft.title || ''} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></Field>
                <Field label="분류"><Input disabled={readOnly} list="cats" value={draft.category || ''} onChange={(e) => setDraft({ ...draft, category: e.target.value })} /></Field>
                <datalist id="cats">{cats.map((c) => <option key={c} value={c} />)}</datalist>
              </div>
              <div className="mt-4 flex min-h-0 flex-1 flex-col">
                <span className="mb-1.5 text-[13px] font-medium text-slate-700">내용</span>
                <Textarea readOnly={readOnly} className={cx('min-h-[240px] flex-1 font-mono text-[13px]', readOnly && 'bg-slate-50 text-slate-600')} value={draft.content || ''} onChange={(e) => setDraft({ ...draft, content: e.target.value })} />
              </div>
              <div className="mt-4 flex items-center gap-2">
                <Badge>버전 {current.version}</Badge>
                <span className="text-xs text-slate-400">{current.updated_at.replace('T', ' ')} 수정</span>
                <Button size="sm" variant="ghost" icon={<History className="size-3.5" />} onClick={async () => setVersions(await api.get<Version[]>(`/guidelines/${current.id}/versions`))}>기록</Button>
                {!readOnly && (
                  <div className="ml-auto flex gap-2">
                    {current.scope !== 'override' && (
                      <Button variant="danger" size="sm" icon={<Trash2 className="size-3.5" />} onClick={() =>
                        confirmDialog(current.scope === 'default'
                          ? `기본 지침 '${current.title}'을(를) 삭제할까요? 모든 프로젝트에서 사라집니다.${current.override_count ? ` (이를 고친 프로젝트 수정본 ${current.override_count}개는 프로젝트 전용 지침으로 남습니다)` : ''}`
                          : `'${current.title}' 지침을 삭제할까요?`) &&
                        run('del', async () => { await api.del(`/guidelines/${current.id}`); await load() })
                      }>삭제</Button>
                    )}
                    <Button variant="primary" size="sm" icon={<Save className="size-3.5" />} disabled={!dirty} loading={busy === 'save'} onClick={() => run('save', async () => { const g = await api.put<Guideline>(`/guidelines/${current.id}`, draft); await load(g.id) }, '저장했습니다.')}>저장</Button>
                  </div>
                )}
              </div>
            </Card>
          )}
        </div>
      )}

      <Modal open={!!versions} onClose={() => setVersions(null)} title="변경 기록" wide>
        <div className="space-y-3">
          {versions?.map((v) => (
            <div key={v.id} className="rounded-lg border border-slate-100 p-3">
              <div className="mb-1 flex items-center gap-2 text-xs text-slate-500">
                <Badge>v{v.version}</Badge> {v.created_at.replace('T', ' ')} · {v.note}
                {current && !readOnly && v.version !== current.version && (
                  <Button size="sm" variant="ghost" className="ml-auto" onClick={() => { setDraft({ ...draft, content: v.content }); setVersions(null) }}>이 내용 불러오기</Button>
                )}
              </div>
              <pre className="font-sans text-xs whitespace-pre-wrap text-slate-700">{v.content}</pre>
            </div>
          ))}
        </div>
      </Modal>
    </div>
  )
}

function ScopeNotice({ g, projectId, busy, onCustomize, onRevert, onOpenDefault }: {
  g: Guideline
  projectId: number | null
  busy: string | null
  onCustomize: () => void
  onRevert: () => void
  onOpenDefault: () => void
}) {
  if (!projectId) {
    return g.override_count ? (
      <Notice tone="slate">
        모든 프로젝트에 적용되는 기본 지침입니다. 단, {g.override_count}개 프로젝트는 이 지침을 고친 수정본을 쓰고 있어 여기서 바꿔도 그 프로젝트에는 반영되지 않습니다.
      </Notice>
    ) : (
      <Notice tone="slate">모든 프로젝트에 적용되는 기본 지침입니다.</Notice>
    )
  }
  if (g.scope === 'default') {
    return (
      <Notice tone="slate" action={
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={onOpenDefault}>기본 지침에서 편집</Button>
          <Button size="sm" variant="primary" icon={<Copy className="size-3.5" />} loading={busy === 'custom'} onClick={onCustomize}>이 프로젝트용으로 수정</Button>
        </div>
      }>
        기본 지침을 그대로 쓰고 있습니다. 이 프로젝트에서만 다르게 쓰려면 수정본을 만드세요.
      </Notice>
    )
  }
  if (g.scope === 'override') {
    return (
      <Notice tone="amber" action={<Button size="sm" icon={<RotateCcw className="size-3.5" />} loading={busy === 'revert'} onClick={onRevert}>기본으로 되돌리기</Button>}>
        기본 지침을 이 프로젝트에 맞게 고친 수정본입니다. 이 프로젝트에서는 기본 지침 대신 이 내용이 쓰입니다.
      </Notice>
    )
  }
  return <Notice tone="brand">이 프로젝트에서만 쓰는 지침입니다.</Notice>
}

function Notice({ tone, children, action }: { tone: 'slate' | 'amber' | 'brand'; children: React.ReactNode; action?: React.ReactNode }) {
  const cls = { slate: 'bg-slate-50 text-slate-600', amber: 'bg-amber-50 text-amber-800', brand: 'bg-brand-50 text-brand-700' }[tone]
  return (
    <div className={cx('mb-4 flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13px]', cls)}>
      <Info className="size-4 shrink-0" />
      <span className="flex-1">{children}</span>
      {action}
    </div>
  )
}
