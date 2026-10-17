import { useEffect, useState } from 'react'
import { ArrowRight, Gauge, LayoutTemplate, Microscope, Plus, Shapes, Type } from 'lucide-react'
import { api, type Analysis } from '../../api'
import { Badge, Button, Card, Empty, Field, SectionTitle, Select, cx, useAsync } from '../../components/ui'
import { RunControl } from '../../components/jobs'
import type { StepProps } from '../WorkbookPage'
import { FormSegmentsCard, FormStyleCard } from './FormViews'

const ROLES: { key: string; label: string; help: string }[] = [
  { key: 'preamble_end', label: '머리 영역 끝', help: '이 문단 앞까지(학교명·제목·이름 칸 등)는 그대로 유지' },
  { key: 'title', label: '제목', help: '문제지 제목 문단' },
  { key: 'instruction', label: '발문', help: '"1. 다음 글의 주제로…" 문단' },
  { key: 'passage', label: '지문', help: '영어 지문 문단 (박스/표 포함 가능)' },
  { key: 'choice', label: '선택지', help: '① ~ ⑤ 한 줄' },
  { key: 'answer', label: '정답', help: '정답 표기 문단' },
  { key: 'explanation', label: '해설', help: '해설 문단' },
]

export default function AnalyzeStep({ wb, startJob, jobRunning, goto, reload }: StepProps) {
  const a = wb.analysis
  const hasSample = wb.files.some((f) => f.kind === 'sample') || wb.project_materials.some((f) => f.kind === 'sample' && f.scope !== 'exclude')
  const { busy, run } = useAsync()

  const runControl = (
    <RunControl
      stage="analyze"
      label={a ? '다시 분석' : '샘플 분석 시작'}
      icon={<Microscope className="size-4" />}
      disabled={!hasSample || jobRunning}
      busy={jobRunning}
      onRun={(o) => startJob('analyze', o)}
    />
  )

  return (
    <div className="space-y-6">
      <SectionTitle
        title="2. 샘플 분석"
        desc="Codex가 샘플의 문제 유형, 난이도, 서식(글머리표·번호·형광펜)을 분석하고, 출력 템플릿으로 쓸 문단을 찾습니다."
        right={
          <>
            {runControl}
            {a && (
              <Button variant="soft" icon={<ArrowRight className="size-4" />} onClick={() => goto('generate')}>
                다음: 문제 제작
              </Button>
            )}
          </>
        }
      />

      {!a ? (
        <Empty
          icon={<Microscope className="size-6" />}
          title={hasSample ? '분석을 시작해 보세요' : '먼저 샘플 문제지를 올려 주세요'}
          desc={hasSample ? '보통 1~3분 정도 걸립니다. 진행 상황이 위에 표시됩니다.' : '자료 등록 단계에서 샘플을 올리면 분석할 수 있어요.'}
          action={!hasSample && <Button onClick={() => goto('materials')}>자료 등록으로 이동</Button>}
        />
      ) : (
        <>
          <Card className="p-5">
            <div className="mb-2 text-[13px] font-medium text-slate-500">요약</div>
            <p className="text-[15px] leading-relaxed text-slate-800">{a.summary}</p>
          </Card>

          <div className="grid gap-6 lg:grid-cols-3">
            <Card className="p-5">
              <Head icon={<Gauge className="size-4" />} title="난이도" />
              <div className="flex items-baseline gap-2">
                <span className="text-2xl font-bold text-slate-900">{a.difficulty.level}</span>
                {a.difficulty.cefr && <Badge color="sky">CEFR {a.difficulty.cefr}</Badge>}
              </div>
              <p className="mt-2 text-[13px] leading-relaxed text-slate-600">{a.difficulty.rationale}</p>
            </Card>
            <Card className="p-5 lg:col-span-2">
              <Head icon={<Type className="size-4" />} title="서식" />
              <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-[13px] sm:grid-cols-2">
                {([
                  ['글머리 기호', a.format_notes.bullets],
                  ['글머리 번호', a.format_notes.numbering],
                  ['형광펜', a.format_notes.highlight],
                  ['선택지', a.format_notes.choices],
                  ['지문', a.format_notes.passage],
                  ['기타', a.format_notes.other],
                ] as const).map(([k, v]) => (
                  <div key={k}>
                    <dt className="font-medium text-slate-500">{k}</dt>
                    <dd className="text-slate-700">{v || '-'}</dd>
                  </div>
                ))}
              </dl>
              {a.format_facts?.highlights?.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2 border-t border-slate-100 pt-3">
                  {a.format_facts.highlights.map((h: any) => (
                    <span key={h.color} className="flex items-center gap-1.5 rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-600">
                      <span className="inline-block size-3 rounded-sm ring-1 ring-black/10" style={{ background: h.color }} />
                      형광펜 {h.color} ({h.count}회)
                    </span>
                  ))}
                </div>
              )}
            </Card>
          </div>

          <Card className="p-5">
            <Head icon={<Shapes className="size-4" />} title={`문제 유형 (${a.question_types.length}종)`} />
            <div className="overflow-hidden rounded-lg border border-slate-100">
              <table className="w-full text-[13px]">
                <thead className="bg-slate-50 text-left text-slate-500">
                  <tr>
                    <th className="px-3 py-2 font-medium">유형</th>
                    <th className="px-3 py-2 font-medium">샘플 문항 수</th>
                    <th className="px-3 py-2 font-medium">발문 예시</th>
                    <th className="px-3 py-2 font-medium">특징</th>
                  </tr>
                </thead>
                <tbody>
                  {a.question_types.map((t) => (
                    <tr key={t.name} className="border-t border-slate-100 align-top">
                      <td className="px-3 py-2 font-medium whitespace-nowrap text-slate-800">{t.name}</td>
                      <td className="px-3 py-2 text-slate-600">{t.count_in_sample}</td>
                      <td className="px-3 py-2 text-slate-600">{t.instruction_example}</td>
                      <td className="px-3 py-2 text-slate-600">{t.features || t.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {wb.form ? (
            <>
              <FormSegmentsCard wb={wb} saving={busy === 'segs'} onSave={(form_segments) =>
                run('segs', async () => { await api.put(`/workbooks/${wb.id}`, { analysis: { ...a, form_segments } }); await reload() }, '양식 구성을 저장했습니다.')} />
              <FormStyleCard wb={wb} saving={busy === 'style'} onSave={(form_style) =>
                run('style', async () => { await api.put(`/workbooks/${wb.id}`, { analysis: { ...a, form_style } }); await reload() }, '출력 서식을 저장했습니다.')} />
            </>
          ) : <RoleMapEditor analysis={a} templateId={wb.template_file_id} templateUrl={wb.template_source === 'project' ? `/project-files/${wb.template_file_id}` : `/files/${wb.template_file_id}`} onSave={(role_map, choice_marker) =>
            run('save', async () => { await api.put(`/workbooks/${wb.id}`, { analysis: { ...a, role_map, choice_marker } }); await reload() }, '템플릿 설정을 저장했습니다.')
          } />}

          {a.suggested_guideline && (
            <Card className="p-5">
              <div className="mb-2 flex items-center justify-between">
                <div className="text-[13px] font-medium text-slate-500">샘플에서 뽑은 지침 초안</div>
                <Button size="sm" variant="soft" icon={<Plus className="size-3.5" />} onClick={() =>
                  run('g', async () => {
                    const custom = [wb.custom_guideline, a.suggested_guideline].filter(Boolean).join('\n\n')
                    await api.put(`/workbooks/${wb.id}`, { custom_guideline: custom })
                    await reload()
                  }, '문제집 전용 지침에 추가했습니다.')
                }>
                  이 문제집 지침에 추가
                </Button>
              </div>
              <pre className="font-sans text-[13px] leading-relaxed whitespace-pre-wrap text-slate-700">{a.suggested_guideline}</pre>
            </Card>
          )}
        </>
      )}
    </div>
  )
}

function Head({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="mb-3 flex items-center gap-2 text-[13px] font-medium text-slate-500">
      {icon} {title}
    </div>
  )
}

function RoleMapEditor({ analysis, templateId, templateUrl, onSave }: { analysis: Analysis; templateId: number | null; templateUrl: string; onSave: (m: Record<string, number>, marker: string) => void }) {
  const [paras, setParas] = useState<any[] | null>(null)
  const [map, setMap] = useState<Record<string, number>>(analysis.role_map || {})
  const [marker, setMarker] = useState(analysis.choice_marker || 'circled')
  useEffect(() => setMap(analysis.role_map || {}), [analysis.role_map])
  useEffect(() => {
    if (templateId) api.get<{ format: any }>(templateUrl).then((f) => setParas(f.format?.paragraphs || []))
  }, [templateId, templateUrl])

  if (!templateId) {
    return (
      <Card className="p-5 text-[13px] text-slate-500">
        <Head icon={<LayoutTemplate className="size-4" />} title="출력 템플릿" />
        HWP/HWPX 샘플이 없어서 기본 서식으로 출력합니다. 샘플 서식을 그대로 쓰려면 HWP/HWPX 샘플을 올리고 다시 분석하세요.
      </Card>
    )
  }
  const dirty = JSON.stringify(map) !== JSON.stringify(analysis.role_map) || marker !== analysis.choice_marker
  const preview = (i: number) => paras?.find((p) => p.index === i)

  return (
    <Card className="p-5">
      <div className="mb-1 flex items-center justify-between">
        <Head icon={<LayoutTemplate className="size-4" />} title="출력 템플릿 — 샘플의 어느 문단 모양을 따를까요?" />
        <Button size="sm" variant={dirty ? 'primary' : 'secondary'} disabled={!dirty} onClick={() => onSave(map, marker)}>
          저장
        </Button>
      </div>
      <p className="mb-4 text-xs text-slate-500">분석이 자동으로 골랐습니다. 출력물이 어색하면 여기서 바꿔 주세요. 고른 문단의 글꼴·문단 번호·들여쓰기·박스가 그대로 복제됩니다.</p>
      <div className="grid gap-3 md:grid-cols-2">
        {ROLES.map((r) => (
          <div key={r.key} className="rounded-lg border border-slate-100 p-3">
            <Field label={r.label} hint={r.help}>
              <Select value={map[r.key] ?? -1} onChange={(e) => setMap({ ...map, [r.key]: Number(e.target.value) })}>
                <option value={r.key === 'preamble_end' ? 0 : -1}>{r.key === 'preamble_end' ? '머리 영역 없음' : '(지정 안 함 — 기본값 사용)'}</option>
                {(paras || []).map((p) => (
                  <option key={p.index} value={p.index}>
                    #{p.index} {(p.text || '(빈 줄)').slice(0, 50)}
                  </option>
                ))}
              </Select>
            </Field>
            {preview(map[r.key]) && (
              <div className={cx('mt-2 truncate rounded bg-slate-50 px-2 py-1 text-xs text-slate-500')}>
                {preview(map[r.key]).heading && <Badge className="mr-1">{preview(map[r.key]).heading}</Badge>}
                {preview(map[r.key]).container && <Badge color="sky" className="mr-1">{preview(map[r.key]).container === 'table' ? '표/박스' : '글상자'}</Badge>}
                {preview(map[r.key]).text}
              </div>
            )}
          </div>
        ))}
        <div className="rounded-lg border border-slate-100 p-3">
          <Field label="선택지 번호 방식">
            <Select value={marker} onChange={(e) => setMarker(e.target.value)}>
              <option value="circled">① ② ③ (원문자)</option>
              <option value="paren">(1) (2) (3)</option>
              <option value="digit">1. 2. 3.</option>
              <option value="numbering">한글 문단 번호 기능 사용</option>
            </Select>
          </Field>
        </div>
      </div>
    </Card>
  )
}
