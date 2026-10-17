import { useState } from 'react'
import { ArrowRight, Download, FileDown, FolderSearch, Trash2 } from 'lucide-react'
import { api, isEssay, qLabel } from '../../api'
import { Badge, Button, Card, Empty, SectionTitle, confirmDialog, cx, useAsync } from '../../components/ui'
import { CIRCLED, Markup } from '../../components/Markup'
import type { StepProps } from '../WorkbookPage'
import { RunControl } from '../../components/jobs'
import { FormPreview } from './FormViews'

const MODES = [
  { key: 'questions', label: '문제지', desc: '학생 배포용' },
  { key: 'answers', label: '정답 및 해설', desc: '교사용' },
  { key: 'both', label: '합본', desc: '문제 + 정답·해설' },
]

export default function ExportStep(props: StepProps) {
  if (props.wb.form && props.wb.questions?.mode === 'form') return <FormExport {...props} />
  return <PaperExport {...props} />
}

function FormExport({ wb, reload, goto, startJob, jobRunning }: StepProps) {
  const [modes, setModes] = useState<string[]>(['teacher', 'student'])
  const { run } = useAsync()
  const sets = wb.questions?.sets || []
  const qs = wb.questions?.questions || []
  const stale = sets.filter((st) => !st.layout).length
  const template = wb.files.find((f) => f.id === wb.template_file_id) || wb.project_materials.find((f) => f.id === wb.template_file_id)
  return (
    <div className="space-y-6">
      <SectionTitle
        title="5. HWPX 출력"
        desc="양식(샘플)은 그대로 두고 지문 세트를 칸에 채워 넣습니다. 먼저 Codex가 세트마다 어느 칸에 무엇을 넣을지 정한 뒤(양식 배치) 파일을 만듭니다."
        right={<Button variant="soft" icon={<ArrowRight className="size-4" />} onClick={() => goto('feedback')}>다음: 피드백</Button>}
      />
      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="p-5 lg:col-span-2">
          <h3 className="mb-1 font-semibold text-slate-900">출력 옵션</h3>
          <p className="mb-3 text-xs text-slate-500">양식: {template?.orig_name || '샘플'} · 지문 세트 {sets.length}개{stale ? ` · 배치 필요 ${stale}개` : ''}</p>
          <div className="space-y-2">
            {([['teacher', '교사용', '지침의 정답 표시 규칙대로 정답을 형광펜 등으로 표시'], ['student', '학생용', '정답 표시를 지우고, 써 넣는 답은 빈칸으로']] as const).map(([k, label, desc]) => (
              <label key={k} className={cx('flex cursor-pointer items-center gap-3 rounded-lg border p-3', modes.includes(k) ? 'border-brand-200 bg-brand-50/50' : 'border-slate-200')}>
                <input type="checkbox" className="size-4 accent-brand-600" checked={modes.includes(k)} onChange={(e) => setModes(e.target.checked ? [...modes, k] : modes.filter((x) => x !== k))} />
                <div>
                  <div className="text-sm font-medium text-slate-800">{label}</div>
                  <div className="text-xs text-slate-500">{desc}</div>
                </div>
              </label>
            ))}
          </div>
          <div className="mt-5">
            <RunControl stage="layout" label="양식 배치 후 HWPX 만들기" icon={<FileDown className="size-4" />} disabled={!modes.length || jobRunning} busy={jobRunning}
              onRun={(o) => startJob('layout', { ...o, modes })} />
          </div>
          <p className="mt-2 text-xs text-slate-400">바뀐 세트만 다시 배치합니다. 진행 상황은 위에 표시되고, 끝나면 아래 목록에 파일이 생깁니다.</p>

          <h3 className="mt-8 mb-2 font-semibold text-slate-900">만든 파일</h3>
          <ExportList wb={wb} reload={reload} run={run} />
        </Card>
        <Card className="p-0 lg:col-span-3">
          <div className="border-b border-slate-100 px-5 py-3 text-[13px] font-medium text-slate-500">내용 미리보기 (화면용 — 실제 배치는 한글에서 확인)</div>
          <div className="scroll-thin max-h-[70vh] overflow-y-auto bg-slate-100 p-6">
            <FormPreview sets={sets} questions={qs} />
          </div>
        </Card>
      </div>
    </div>
  )
}

function ExportList({ wb, reload, run }: { wb: StepProps['wb']; reload: StepProps['reload']; run: ReturnType<typeof useAsync>['run'] }) {
  if (wb.exports.length === 0) return <p className="text-sm text-slate-400">아직 없습니다.</p>
  return (
    <div className="space-y-2">
      {wb.exports.map((e, i) => (
        <div key={e.id} className="flex items-center gap-2 rounded-lg border border-slate-100 p-2.5">
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-medium break-all text-slate-700">{e.name}</div>
            <div className="text-[11px] text-slate-400">{e.created_at.replace('T', ' ')} {i === 0 && <Badge color="green" className="ml-1">최신</Badge>}</div>
          </div>
          <a href={`/api/exports/${e.id}/download`} title="다운로드"><Button size="sm" variant="ghost" icon={<Download className="size-3.5" />} /></a>
          <Button size="sm" variant="ghost" title="Finder에서 보기" icon={<FolderSearch className="size-3.5" />} onClick={() => api.post(`/exports/${e.id}/reveal`)} />
          <Button size="sm" variant="ghost" title="삭제" icon={<Trash2 className="size-3.5" />} onClick={() => confirmDialog('이 파일을 삭제할까요?') && run('del', async () => { await api.del(`/exports/${e.id}`); await reload() })} />
        </div>
      ))}
    </div>
  )
}

function PaperExport({ wb, reload, goto }: StepProps) {
  const [modes, setModes] = useState<string[]>(['questions', 'answers'])
  const [useTemplate, setUseTemplate] = useState(true)
  const [keepPreamble, setKeepPreamble] = useState(true)
  const { busy, run } = useAsync()
  const qs = wb.questions?.questions || []
  const template = wb.files.find((f) => f.id === wb.template_file_id)

  if (!qs.length) {
    return (
      <div className="space-y-6">
        <SectionTitle title="5. HWPX 출력" />
        <Empty icon={<FileDown className="size-6" />} title="먼저 문제를 제작하세요" action={<Button onClick={() => goto('generate')}>문제 제작으로 이동</Button>} />
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <SectionTitle
        title="5. HWPX 출력"
        desc="샘플 문제지의 서식(글꼴, 문단 번호, 형광펜, 지문 박스)을 그대로 이어받은 새 HWPX 파일을 만듭니다."
        right={<Button variant="soft" icon={<ArrowRight className="size-4" />} onClick={() => goto('feedback')}>다음: 피드백</Button>}
      />

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="p-5 lg:col-span-2">
          <h3 className="mb-3 font-semibold text-slate-900">출력 옵션</h3>
          <div className="space-y-2">
            {MODES.map((m) => (
              <label key={m.key} className={cx('flex cursor-pointer items-center gap-3 rounded-lg border p-3', modes.includes(m.key) ? 'border-brand-200 bg-brand-50/50' : 'border-slate-200')}>
                <input type="checkbox" className="size-4 accent-brand-600" checked={modes.includes(m.key)} onChange={(e) => setModes(e.target.checked ? [...modes, m.key] : modes.filter((x) => x !== m.key))} />
                <div>
                  <div className="text-sm font-medium text-slate-800">{m.label}</div>
                  <div className="text-xs text-slate-500">{m.desc}</div>
                </div>
              </label>
            ))}
          </div>
          <div className="mt-4 space-y-2 border-t border-slate-100 pt-4 text-sm">
            <label className="flex items-center gap-2">
              <input type="checkbox" className="size-4 accent-brand-600" checked={useTemplate && !!template} disabled={!template} onChange={(e) => setUseTemplate(e.target.checked)} />
              샘플 서식 사용 {template ? <span className="truncate text-xs text-slate-400">({template.orig_name})</span> : <span className="text-xs text-slate-400">(HWP/HWPX 샘플 없음 → 기본 서식)</span>}
            </label>
            <label className="flex items-center gap-2">
              <input type="checkbox" className="size-4 accent-brand-600" checked={keepPreamble} disabled={!template || !useTemplate} onChange={(e) => setKeepPreamble(e.target.checked)} />
              샘플의 머리 영역(학교명·이름 칸 등) 유지
            </label>
          </div>
          <Button className="mt-5 w-full" size="lg" variant="primary" icon={<FileDown className="size-4" />} disabled={!modes.length} loading={busy === 'export'}
            onClick={() => run('export', async () => { await api.post(`/workbooks/${wb.id}/export`, { modes, use_template: useTemplate, keep_preamble: keepPreamble }); await reload() }, 'HWPX 파일을 만들었습니다.')}>
            HWPX 만들기
          </Button>

          <h3 className="mt-8 mb-2 font-semibold text-slate-900">만든 파일</h3>
          {wb.exports.length === 0 ? <p className="text-sm text-slate-400">아직 없습니다.</p> : (
            <div className="space-y-2">
              {wb.exports.map((e, i) => (
                <div key={e.id} className="flex items-center gap-2 rounded-lg border border-slate-100 p-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-medium break-all text-slate-700">{e.name}</div>
                    <div className="text-[11px] text-slate-400">{e.created_at.replace('T', ' ')} {i === 0 && <Badge color="green" className="ml-1">최신</Badge>}</div>
                  </div>
                  <a href={`/api/exports/${e.id}/download`} title="다운로드"><Button size="sm" variant="ghost" icon={<Download className="size-3.5" />} /></a>
                  <Button size="sm" variant="ghost" title="Finder에서 보기" icon={<FolderSearch className="size-3.5" />} onClick={() => api.post(`/exports/${e.id}/reveal`)} />
                  <Button size="sm" variant="ghost" title="삭제" icon={<Trash2 className="size-3.5" />} onClick={() => confirmDialog('이 파일을 삭제할까요?') && run('del', async () => { await api.del(`/exports/${e.id}`); await reload() })} />
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card className="p-0 lg:col-span-3">
          <div className="border-b border-slate-100 px-5 py-3 text-[13px] font-medium text-slate-500">미리보기 (화면용 — 실제 서식은 한글에서 확인)</div>
          <div className="scroll-thin max-h-[70vh] overflow-y-auto bg-slate-100 p-6">
            <div className="mx-auto max-w-[620px] bg-white px-10 py-10 font-serif shadow-sm">
              {wb.questions?.title && <h2 className="mb-6 text-center text-lg font-bold"><Markup text={wb.questions.title} /></h2>}
              {qs.map((q) => (
                <div key={q.number} className="prose-q mb-6 text-[13.5px] leading-[1.7]">
                  <p className="font-medium">{qLabel(q, qs)} <Markup text={q.instruction} />{isEssay(q) && !!q.points && ` (${q.points}점)`}</p>
                  {q.passage && <div className="mt-1.5 border border-slate-300 px-3 py-2"><Markup text={q.passage} /></div>}
                  {q.choices.map((c, i) => <div key={i} className="mt-0.5">{CIRCLED[i]} <Markup text={c} /></div>)}
                  {isEssay(q) && <div className="mt-2 h-16 border-b border-dashed border-slate-300" />}
                </div>
              ))}
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
