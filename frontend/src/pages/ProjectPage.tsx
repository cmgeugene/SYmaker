import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowRight, BookMarked, FilePlus2, Grid3x3, Layers, Library, Pencil, Plus, Shuffle, Sparkles, Trash2 } from 'lucide-react'
import { api, type Project, type SetGroup, type WorkbookSummary } from '../api'
import { Badge, Button, Card, Empty, Field, Input, Modal, Spinner, Textarea, confirmDialog, cx, useAsync, useToast } from '../components/ui'
import { STAGES, StageDots } from '../components/StageDots'
import { RunControl } from '../components/jobs'
import { ProjectModal } from './HomePage'
import MaterialsTab from './project/MaterialsTab'
import { CoverageModal, SetGroupModal } from './project/SetGroups'
import type { Refresh } from '../App'

export default function ProjectPage({ refresh }: { refresh: Refresh }) {
  const { pid } = useParams()
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'materials' ? 'materials' : 'workbooks'
  const [project, setProject] = useState<Project | null>(null)
  const [newOpen, setNewOpen] = useState(false)
  const [groupOpen, setGroupOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const { run } = useAsync()

  const load = useCallback(async () => setProject(await api.get<Project>(`/projects/${pid}`)), [pid])
  useEffect(() => {
    load()
  }, [load])

  if (!project) return <div className="flex h-full items-center justify-center"><Spinner /></div>

  const groups = project.groups || []
  const loose = project.workbooks.filter((w) => !w.group_id)

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <div className="mb-1 text-[13px] text-slate-400">
        {project.year}년 · {project.semester}
      </div>
      <div className="mb-6 flex items-start justify-between gap-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{project.name}</h1>
          {project.description && <p className="mt-1 text-sm text-slate-500">{project.description}</p>}
        </div>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" icon={<BookMarked className="size-3.5" />} onClick={() => nav(`/guidelines?project=${project.id}`)}>
            출제 지침
          </Button>
          <Button variant="ghost" size="sm" icon={<Pencil className="size-3.5" />} onClick={() => setEditOpen(true)}>
            수정
          </Button>
          <Button
            variant="ghost"
            size="sm"
            icon={<Trash2 className="size-3.5" />}
            onClick={() =>
              confirmDialog(`'${project.name}' 프로젝트와 안의 문제집·자료를 모두 삭제할까요?`) &&
              run('del', async () => {
                await api.del(`/projects/${project.id}`)
                await refresh()
                nav('/')
              })
            }
          >
            삭제
          </Button>
        </div>
      </div>

      <div className="mb-6 flex gap-1 border-b border-slate-200">
        {([
          ['workbooks', '문제집', <Layers key="i" className="size-4" />, project.workbooks.length],
          ['materials', '자료실 · 본문', <Library key="i" className="size-4" />, project.passage_count ? `본문 ${project.passage_count}` : project.material_count],
        ] as const).map(([key, label, icon, count]) => (
          <button key={key} onClick={() => setParams(key === 'workbooks' ? {} : { tab: key })}
            className={cx('-mb-px flex items-center gap-2 border-b-2 px-4 pb-2.5 text-sm', tab === key ? 'border-brand-600 font-semibold text-slate-900' : 'border-transparent text-slate-500 hover:text-slate-700')}>
            {icon} {label} {!!count && <Badge>{count}</Badge>}
          </button>
        ))}
      </div>

      {tab === 'materials' ? (
        <MaterialsTab projectId={project.id} onChanged={load} />
      ) : (
        <>
          <div className="mb-4 flex items-center justify-end gap-2">
            <Button icon={<Plus className="size-4" />} onClick={() => setNewOpen(true)}>새 문제집</Button>
            <Button variant="primary" icon={<Layers className="size-4" />} onClick={() => setGroupOpen(true)}>모의고사 세트 만들기</Button>
          </div>

          {project.workbooks.length === 0 ? (
            <Empty
              icon={<FilePlus2 className="size-6" />}
              title="이 프로젝트에 문제집을 추가하세요"
              desc="문제집 하나를 만들거나, 같은 출제 범위로 여러 세트(1세트·2세트·3세트…)를 한 번에 만들 수 있어요. 세트를 만들기 전에 ‘자료실 · 본문’에 출제 범위 자료를 올려 두세요."
              action={
                <div className="flex gap-2">
                  <Button icon={<Plus className="size-4" />} onClick={() => setNewOpen(true)}>새 문제집</Button>
                  <Button variant="primary" icon={<Layers className="size-4" />} onClick={() => setGroupOpen(true)}>모의고사 세트 만들기</Button>
                </div>
              }
            />
          ) : (
            <div className="space-y-6">
              {groups.map((g) => (
                <GroupCard key={g.id} group={g} sets={project.workbooks.filter((w) => w.group_id === g.id)} passageCount={project.passage_count || 0}
                  onChanged={load} onMaterials={() => setParams({ tab: 'materials' })} />
              ))}
              {loose.length > 0 && (
                <div className="space-y-3">
                  {groups.length > 0 && <h3 className="text-[13px] font-semibold text-slate-500">개별 문제집</h3>}
                  {loose.map((w) => <WorkbookRow key={w.id} w={w} />)}
                </div>
              )}
            </div>
          )}
        </>
      )}

      <NewWorkbookModal open={newOpen} onClose={() => setNewOpen(false)} projectId={project.id} onCreated={(id) => nav(`/workbooks/${id}`)} />
      {groupOpen && <SetGroupModal projectId={project.id} passageCount={project.passage_count || 0} onClose={() => setGroupOpen(false)} onCreated={() => { setGroupOpen(false); load(); refresh() }} />}
      {editOpen && <ProjectModal open project={project} onClose={() => setEditOpen(false)} onSaved={() => { load(); refresh() }} />}
    </div>
  )
}

function nextStep(w: WorkbookSummary) {
  const s = STAGES.find((x) => w.status[x.key] === 'todo' || w.status[x.key] === 'stale')
  return s ? s.label : '완료'
}

function WorkbookRow({ w, compact }: { w: WorkbookSummary; compact?: boolean }) {
  const nav = useNavigate()
  return (
    <Card className={cx('flex cursor-pointer items-center gap-6 px-5 transition hover:border-brand-200 hover:shadow-md', compact ? 'py-3' : 'py-4')} onClick={() => nav(`/workbooks/${w.id}`)}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[15px] font-semibold text-slate-900">{w.name}</span>
          {w.has_allocation && <Badge color="sky">본문 배정됨</Badge>}
        </div>
        <div className="mt-0.5 truncate text-[13px] text-slate-500">
          {!compact && (w.description || '설명 없음') + ' · '}문항 {w.question_count}개
        </div>
      </div>
      <StageDots status={w.status} />
      <div className="w-28 text-right text-[13px]">
        <div className="text-slate-400">다음 단계</div>
        <div className="font-medium text-brand-700">{nextStep(w)}</div>
      </div>
      <ArrowRight className="size-4 text-slate-300" />
    </Card>
  )
}

function GroupCard({ group, sets, passageCount, onChanged, onMaterials }: { group: SetGroup; sets: WorkbookSummary[]; passageCount: number; onChanged: () => void; onMaterials: () => void }) {
  const [coverage, setCoverage] = useState(false)
  const { busy, run } = useAsync()
  const toast = useToast()
  const allocated = sets.filter((s) => s.has_allocation).length
  const made = sets.filter((s) => s.question_count > 0).length

  const runAll = (stage: string, o: { model: string; effort: string }) =>
    run(stage, async () => {
      const r = await api.post<{ started: number[]; skipped: { workbook_id: number; reason: string }[] }>(`/set-groups/${group.id}/run/${stage}`, o)
      toast('ok', `${r.started.length}개 세트에서 시작했습니다.${r.skipped.length ? ` (${r.skipped.length}개 건너뜀: ${r.skipped[0].reason})` : ''}`)
      onChanged()
    })

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/60 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3 px-1">
        <Layers className="size-5 text-brand-600" />
        <div>
          <div className="font-semibold text-slate-900">{group.name}</div>
          <div className="text-xs text-slate-500">
            세트 {sets.length}개 · 세트당 {group.spec.question_count}문항(서술형 {group.spec.essay_count || 0}) · 본문 배정 {allocated}/{sets.length} · 제작 {made}/{sets.length}
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button size="sm" variant="ghost" icon={<Grid3x3 className="size-3.5" />} onClick={() => setCoverage(true)}>본문 사용표</Button>
          <Button size="sm" icon={<Shuffle className="size-3.5" />} loading={busy === 'alloc'} disabled={!passageCount}
            title={passageCount ? '' : '자료실에서 본문 나누기를 먼저 하세요'}
            onClick={() => run('alloc', async () => {
              const r = await api.post<{ allocated: number[]; warnings: Record<string, string[]> }>(`/set-groups/${group.id}/allocate`, {})
              const w = Object.values(r.warnings).flat()
              toast(w.length ? 'err' : 'ok', w.length ? `배정 완료 (주의 ${w.length}건): ${w[0]}` : `${r.allocated.length}개 세트에 본문을 배정했습니다.`)
              onChanged()
            })}>
            {allocated ? '본문 다시 배정' : '본문 자동 배정'}
          </Button>
          <RunControl stage="generate" label="전체 세트 제작" icon={<Sparkles className="size-4" />} busy={busy === 'generate'}
            onRun={(o) => {
              if (made && !window.confirm('이미 만든 세트도 새로 만듭니다. 계속할까요? (이전 버전은 기록에 남습니다)')) return
              runAll('generate', o)
            }} />
        </div>
      </div>
      {!passageCount && (
        <div className="mb-3 flex items-center justify-between rounded-lg bg-amber-50 px-3 py-2 text-[13px] text-amber-800">
          세트끼리 본문이 겹치지 않게 배정하려면 자료실에 출제 범위 자료를 올리고 ‘본문 나누기’를 하세요.
          <Button size="sm" variant="ghost" onClick={onMaterials}>자료실로 →</Button>
        </div>
      )}
      <div className="space-y-2">
        {sets.map((w) => <WorkbookRow key={w.id} w={w} compact />)}
      </div>
      <div className="mt-3 flex justify-end gap-2 px-1">
        <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={() => run('add', async () => { await api.post(`/set-groups/${group.id}/sets`, { count: 1 }); onChanged() }, '세트를 추가했습니다. 본문 배정을 해 주세요.')}>세트 추가</Button>
        <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() =>
          confirmDialog(`'${group.name}' 그룹과 세트 ${sets.length}개를 모두 삭제할까요?`) && run('del', async () => { await api.del(`/set-groups/${group.id}`); onChanged() })
        }>그룹 삭제</Button>
      </div>
      {coverage && <CoverageModal groupId={group.id} onClose={() => setCoverage(false)} />}
    </div>
  )
}

function NewWorkbookModal({ open, onClose, projectId, onCreated }: { open: boolean; onClose: () => void; projectId: number; onCreated: (id: number) => void }) {
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const { busy, run } = useAsync()
  const save = () =>
    run('save', async () => {
      const w = await api.post<{ id: number }>(`/projects/${projectId}/workbooks`, { name, description: desc })
      onCreated(w.id)
    })
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="새 문제집"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button variant="primary" loading={busy === 'save'} disabled={!name.trim()} onClick={save}>
            만들고 시작하기
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="문제집 이름" hint="문제지 제목으로도 쓰입니다. 나중에 바꿀 수 있어요.">
          <Input autoFocus value={name} placeholder="예: 중간고사 대비 실전 모의고사 1회" onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && name.trim() && save()} />
        </Field>
        <Field label="설명 (선택)">
          <Textarea rows={2} value={desc} placeholder="범위, 대상 등" onChange={(e) => setDesc(e.target.value)} />
        </Field>
      </div>
    </Modal>
  )
}
