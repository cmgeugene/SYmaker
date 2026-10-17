import { useCallback, useEffect, useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { BookMarked, ChevronDown, ChevronRight, FolderOpen, Home, Settings2, Sparkles, TriangleAlert } from 'lucide-react'
import { api, type Project } from './api'
import { cx } from './components/ui'
import HomePage from './pages/HomePage'
import ProjectPage from './pages/ProjectPage'
import WorkbookPage from './pages/WorkbookPage'
import GuidelinesPage from './pages/GuidelinesPage'
import SettingsPage from './pages/SettingsPage'

export type Refresh = () => Promise<void>

export default function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [codexOk, setCodexOk] = useState<boolean | null>(null)
  const location = useLocation()

  const refresh = useCallback(async () => {
    setProjects(await api.get<Project[]>('/projects'))
  }, [])

  useEffect(() => {
    refresh()
    api.get<{ codex: boolean }>('/health').then((h) => setCodexOk(h.codex)).catch(() => setCodexOk(false))
  }, [refresh])

  useEffect(() => {
    refresh()
  }, [location.pathname, refresh])

  return (
    <div className="flex h-full">
      <Sidebar projects={projects} codexOk={codexOk} />
      <main className="scroll-thin flex-1 overflow-y-auto">
        <Routes>
          <Route path="/" element={<HomePage projects={projects} refresh={refresh} />} />
          <Route path="/projects/:pid" element={<ProjectPage refresh={refresh} />} />
          <Route path="/workbooks/:wid" element={<WorkbookPage refreshSidebar={refresh} />} />
          <Route path="/guidelines" element={<GuidelinesPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  )
}

function Sidebar({ projects, codexOk }: { projects: Project[]; codexOk: boolean | null }) {
  const groups = new Map<number, Project[]>()
  projects.forEach((p) => groups.set(p.year, [...(groups.get(p.year) || []), p]))
  const [closed, setClosed] = useState<Record<number, boolean>>({})

  const link = ({ isActive }: { isActive: boolean }) =>
    cx(
      'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors',
      isActive ? 'bg-brand-50 font-medium text-brand-700' : 'text-slate-600 hover:bg-slate-100',
    )

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="flex items-center gap-2.5 px-5 py-5">
        <div className="flex size-8 items-center justify-center rounded-lg bg-brand-600 text-white">
          <Sparkles className="size-4" />
        </div>
        <div>
          <div className="text-[15px] leading-tight font-bold text-slate-900">SYmaker</div>
          <div className="text-[11px] text-slate-400">영어 문제지 제작 도우미</div>
        </div>
      </div>

      <nav className="space-y-0.5 px-3">
        <NavLink to="/" end className={link}>
          <Home className="size-4" /> 전체 프로젝트
        </NavLink>
        <NavLink to="/guidelines" className={link}>
          <BookMarked className="size-4" /> 출제 지침
        </NavLink>
        <NavLink to="/settings" className={link}>
          <Settings2 className="size-4" /> 모델 설정
        </NavLink>
      </nav>

      <div className="mt-6 px-5 text-[11px] font-semibold tracking-wide text-slate-400">프로젝트</div>
      <div className="scroll-thin mt-2 flex-1 overflow-y-auto px-3 pb-4">
        {[...groups.entries()].map(([year, list]) => (
          <div key={year} className="mb-1">
            <button
              onClick={() => setClosed((c) => ({ ...c, [year]: !c[year] }))}
              className="flex w-full items-center gap-1 rounded-md px-2 py-1.5 text-[13px] font-semibold text-slate-500 hover:bg-slate-50"
            >
              {closed[year] ? <ChevronRight className="size-3.5" /> : <ChevronDown className="size-3.5" />}
              {year}년
            </button>
            {!closed[year] &&
              list.map((p) => (
                <NavLink key={p.id} to={`/projects/${p.id}`} className={({ isActive }) => cx(link({ isActive }), 'py-1.5 pl-7')}>
                  <FolderOpen className="size-3.5 shrink-0" />
                  <span className="truncate">{p.name}</span>
                  <span className="ml-auto shrink-0 text-[11px] text-slate-400">{p.semester}</span>
                </NavLink>
              ))}
          </div>
        ))}
        {projects.length === 0 && <p className="px-2 text-xs text-slate-400">아직 프로젝트가 없습니다.</p>}
      </div>

      {codexOk === false && (
        <div className="m-3 flex gap-2 rounded-lg bg-amber-50 p-3 text-xs text-amber-800">
          <TriangleAlert className="size-4 shrink-0" />
          codex CLI를 찾을 수 없습니다. 분석·제작·검수 기능을 쓰려면 codex를 설치하고 로그인하세요.
        </div>
      )}
    </aside>
  )
}
