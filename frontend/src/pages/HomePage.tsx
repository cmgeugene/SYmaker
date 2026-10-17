import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CalendarDays, FileStack, FolderPlus, Plus } from 'lucide-react'
import { api, SEMESTERS, type Project } from '../api'
import { Button, Card, Empty, Field, Input, Modal, Select, Textarea, useAsync } from '../components/ui'
import type { Refresh } from '../App'

export default function HomePage({ projects, refresh }: { projects: Project[]; refresh: Refresh }) {
  const [open, setOpen] = useState(false)
  const nav = useNavigate()

  const byYear = new Map<number, Map<string, Project[]>>()
  projects.forEach((p) => {
    const sem = byYear.get(p.year) || new Map()
    sem.set(p.semester, [...(sem.get(p.semester) || []), p])
    byYear.set(p.year, sem)
  })

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      <div className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">전체 프로젝트</h1>
          <p className="mt-1 text-sm text-slate-500">연도·학기별로 프로젝트를 만들고, 그 안에서 여러 종류의 문제집을 제작합니다.</p>
        </div>
        <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>
          새 프로젝트
        </Button>
      </div>

      {projects.length === 0 ? (
        <Empty
          icon={<FolderPlus className="size-6" />}
          title="첫 프로젝트를 만들어 보세요"
          desc="예: '2026년 2학기 고1 내신 대비'. 프로젝트 안에서 중간고사·기말고사 등 문제집을 여러 개 만들 수 있습니다."
          action={
            <Button variant="primary" icon={<Plus className="size-4" />} onClick={() => setOpen(true)}>
              새 프로젝트 만들기
            </Button>
          }
        />
      ) : (
        <div className="space-y-10">
          {[...byYear.entries()].map(([year, sems]) => (
            <section key={year}>
              <h2 className="mb-4 flex items-center gap-2 text-lg font-semibold text-slate-800">
                <CalendarDays className="size-5 text-slate-400" /> {year}년
              </h2>
              <div className="space-y-6">
                {SEMESTERS.filter((s) => sems.has(s))
                  .concat([...sems.keys()].filter((s) => !SEMESTERS.includes(s)))
                  .map((sem) => (
                    <div key={sem}>
                      <div className="mb-2 text-[13px] font-medium text-slate-500">{sem}</div>
                      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                        {sems.get(sem)!.map((p) => (
                          <ProjectCard key={p.id} p={p} onClick={() => nav(`/projects/${p.id}`)} />
                        ))}
                      </div>
                    </div>
                  ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <ProjectModal
        open={open}
        onClose={() => setOpen(false)}
        onSaved={async (p) => {
          await refresh()
          nav(`/projects/${p.id}`)
        }}
      />
    </div>
  )
}

function ProjectCard({ p, onClick }: { p: Project; onClick: () => void }) {
  const total = p.workbooks.length
  const done = p.workbooks.filter((w) => w.status.export === 'done').length
  return (
    <Card className="cursor-pointer p-5 transition hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-md" onClick={onClick}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-[15px] font-semibold text-slate-900">{p.name}</div>
          <div className="mt-0.5 line-clamp-2 text-[13px] text-slate-500">{p.description || '설명 없음'}</div>
        </div>
        <span className="shrink-0 rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{p.semester}</span>
      </div>
      <div className="mt-5 flex items-center gap-2 text-[13px] text-slate-500">
        <FileStack className="size-4" />
        문제집 {total}개
        {total > 0 && <span className="text-slate-400">· 출력 완료 {done}개</span>}
      </div>
      {total > 0 && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-emerald-500" style={{ width: `${(done / total) * 100}%` }} />
        </div>
      )}
    </Card>
  )
}

export function ProjectModal({
  open,
  onClose,
  onSaved,
  project,
}: {
  open: boolean
  onClose: () => void
  onSaved: (p: Project) => void
  project?: Project
}) {
  const year = new Date().getFullYear()
  const [form, setForm] = useState({
    name: project?.name || '',
    year: project?.year || year,
    semester: project?.semester || (new Date().getMonth() >= 6 ? '2학기' : '1학기'),
    description: project?.description || '',
  })
  const { busy, run } = useAsync()
  const save = () =>
    run('save', async () => {
      const p = project ? await api.put<Project>(`/projects/${project.id}`, form) : await api.post<Project>('/projects', form)
      onSaved(p)
      onClose()
    })

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={project ? '프로젝트 수정' : '새 프로젝트'}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            취소
          </Button>
          <Button variant="primary" loading={busy === 'save'} onClick={save} disabled={!form.name.trim()}>
            {project ? '저장' : '만들기'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="프로젝트 이름">
          <Input autoFocus value={form.name} placeholder="예: 고1 내신 대비" onChange={(e) => setForm({ ...form, name: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && form.name.trim() && save()} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="연도">
            <Select value={form.year} onChange={(e) => setForm({ ...form, year: Number(e.target.value) })}>
              {[year - 1, year, year + 1].map((y) => (
                <option key={y} value={y}>
                  {y}년
                </option>
              ))}
            </Select>
          </Field>
          <Field label="학기">
            <Select value={form.semester} onChange={(e) => setForm({ ...form, semester: e.target.value })}>
              {SEMESTERS.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="설명 (선택)">
          <Textarea rows={3} value={form.description} placeholder="대상 학년, 교재 범위 등" onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </Field>
      </div>
    </Modal>
  )
}
