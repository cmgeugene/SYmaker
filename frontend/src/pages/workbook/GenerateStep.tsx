import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, BookMarked, History, Plus, Sparkles, Trash2, Wand2 } from 'lucide-react'
import { api, type Guideline, type Question, type Spec } from '../../api'
import { Badge, Button, Card, Empty, Field, Input, Modal, SectionTitle, Select, Textarea, cx, useAsync } from '../../components/ui'
import { RunControl, useSettings } from '../../components/jobs'
import { QuestionCard } from '../../components/QuestionCard'
import { SCOPE_BADGE } from '../GuidelinesPage'
import AllocationCard from './AllocationCard'
import { FormSetsView } from './FormViews'
import type { StepProps } from '../WorkbookPage'

export default function GenerateStep({ wb, startJob, jobRunning, goto, reload }: StepProps) {
  const [spec, setSpec] = useState<Spec>(wb.spec)
  const [guides, setGuides] = useState<Guideline[]>([])
  const [selected, setSelected] = useState<number[]>(wb.guideline_ids)
  const [custom, setCustom] = useState(wb.custom_guideline)
  const [history, setHistory] = useState(false)
  const [newType, setNewType] = useState('')
  const { busy, run } = useAsync()
  const { settings } = useSettings()

  useEffect(() => { api.get<Guideline[]>(`/guidelines?project_id=${wb.project_id}`).then(setGuides) }, [wb.project_id])
  useEffect(() => { setSpec(wb.spec); setSelected(wb.guideline_ids); setCustom(wb.custom_guideline) }, [wb.spec, wb.guideline_ids, wb.custom_guideline])

  const typeTotal = spec.types.reduce((s, t) => s + (Number(t.count) || 0), 0)
  const dirty = JSON.stringify(spec) !== JSON.stringify(wb.spec) || JSON.stringify(selected) !== JSON.stringify(wb.guideline_ids) || custom !== wb.custom_guideline
  const saveSettings = () => api.put(`/workbooks/${wb.id}`, { spec, guideline_ids: selected, custom_guideline: custom })

  const qs = wb.questions?.questions || []
  const saveQuestion = (q: Question) =>
    run('q', async () => {
      const next = { ...wb.questions!, questions: qs.map((x) => (x.number === q.number ? q : x)) }
      await api.put(`/workbooks/${wb.id}`, { questions: next, version_note: `${q.number}번 직접 편집` })
      await reload()
    }, '저장했습니다.')

  const byCat = guides.reduce<Record<string, Guideline[]>>((acc, g) => ({ ...acc, [g.category || '기타']: [...(acc[g.category || '기타'] || []), g] }), {})

  return (
    <div className="space-y-6">
      <SectionTitle
        title="3. 문제 제작"
        desc="제작 설정과 지침을 고른 뒤 실행하면 Codex가 문제를 만듭니다. 결과는 바로 아래에서 확인·편집할 수 있어요."
        right={
          <>
            <RunControl
              stage="generate"
              label={qs.length ? '새로 제작' : '문제 제작 시작'}
              icon={<Sparkles className="size-4" />}
              disabled={jobRunning}
              busy={jobRunning}
              onRun={async (o) => {
                if (qs.length && !window.confirm('현재 문제를 새로 만든 문제로 바꿀까요? (이전 버전은 기록에 남습니다)')) return
                if (dirty) await saveSettings()
                await startJob('generate', o)
              }}
            />
            {qs.length > 0 && <Button variant="soft" icon={<ArrowRight className="size-4" />} onClick={() => goto('review')}>다음: 검수</Button>}
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="p-5 lg:col-span-3">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-semibold text-slate-900">제작 설정</h3>
            <Button size="sm" variant={dirty ? 'primary' : 'secondary'} disabled={!dirty} loading={busy === 'spec'} onClick={() => run('spec', async () => { await saveSettings(); await reload() }, '설정을 저장했습니다.')}>
              설정 저장
            </Button>
          </div>
          {wb.form ? (
            <div className="grid gap-4">
              <Field label="문제지 제목"><Input value={spec.title} onChange={(e) => setSpec({ ...spec, title: e.target.value })} /></Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="지문 수 (블록 수)" hint={`양식에는 블록 ${wb.form.block_count}개${wb.form.front_boxes ? `, 앞쪽 박스 ${wb.form.front_boxes}개` : ''}가 있습니다. 지문마다 하위 문항을 모두 만듭니다.`}>
                  <Input type="number" min={1} max={wb.form.front_boxes || 30} value={spec.passage_count || wb.form.block_count}
                    onChange={(e) => setSpec({ ...spec, passage_count: Math.max(1, Number(e.target.value)) })} />
                </Field>
                <Field label="정답 번호 분포 (5지 문항)">
                  <Select value={spec.answer_weights || 'even'} onChange={(e) => setSpec({ ...spec, answer_weights: e.target.value as 'even' | '345' })}>
                    <option value="even">1~5번 고르게</option>
                    <option value="345">고르게 + 3·4·5번 조금 더 많이</option>
                  </Select>
                </Field>
              </div>
              <Field label="추가 요청 (선택)">
                <Textarea rows={3} placeholder="예: 빈칸은 마지막 문단에서, 조건 영작은 15단어 이내" value={spec.extra_instructions} onChange={(e) => setSpec({ ...spec, extra_instructions: e.target.value })} />
              </Field>
              <p className="text-xs text-slate-500">하위 문항 구성(사용·택1)은 샘플 분석 단계의 ‘양식 구성’에서 바꿉니다.</p>
            </div>
          ) : (
          <div className="grid gap-4">
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-3">
                <Field label="문제지 제목"><Input value={spec.title} onChange={(e) => setSpec({ ...spec, title: e.target.value })} /></Field>
              </div>
              <div className="col-span-3 grid grid-cols-3 gap-3">
                <Field label="객관식 문항 수"><Input type="number" min={0} max={100} value={spec.question_count - (spec.essay_count || 0)} onChange={(e) => setSpec({ ...spec, question_count: Math.max(0, Number(e.target.value)) + (spec.essay_count || 0) })} /></Field>
                <Field label="서술형 문항 수"><Input type="number" min={0} max={50} value={spec.essay_count || 0} onChange={(e) => { const essay = Math.max(0, Number(e.target.value)); setSpec({ ...spec, essay_count: essay, question_count: spec.question_count - (spec.essay_count || 0) + essay }) }} /></Field>
                <Field label="총 문항 수" hint={spec.question_count > (settings?.runner.batch_size || 5) ? `출제 계획 후 ${Math.ceil(spec.question_count / (settings?.runner.batch_size || 5))}개 묶음으로 나눠 동시 제작` : '한 번에 제작'}>
                  <div className="flex h-9 items-center rounded-lg bg-slate-50 px-3 text-sm font-semibold text-slate-700">{spec.question_count}문항</div>
                </Field>
              </div>
            </div>
            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-[13px] font-medium text-slate-700">유형별 문항 수</span>
                <span className={cx('text-xs', typeTotal && typeTotal !== spec.question_count ? 'text-amber-600' : 'text-slate-400')}>
                  합계 {typeTotal} / {spec.question_count} {typeTotal === 0 && '· 0이면 Codex가 알아서 배분'}
                </span>
              </div>
              <div className="flex flex-wrap gap-2">
                {spec.types.map((t, i) => (
                  <div key={i} className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 py-1 pr-1 pl-3 text-sm">
                    <span className="text-slate-700">{t.name}</span>
                    <input type="number" min={0} className="ml-1 h-7 w-12 rounded-md border border-slate-200 bg-white text-center text-sm" value={t.count}
                      onChange={(e) => setSpec({ ...spec, types: spec.types.map((x, j) => (j === i ? { ...x, count: Number(e.target.value) } : x)) })} />
                    <button className="rounded p-1 text-slate-300 hover:text-rose-500" onClick={() => setSpec({ ...spec, types: spec.types.filter((_, j) => j !== i) })}><Trash2 className="size-3.5" /></button>
                  </div>
                ))}
                <div className="flex items-center gap-1">
                  <Input className="!h-9 w-28" placeholder="유형 추가" value={newType} onChange={(e) => setNewType(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && newType.trim()) { setSpec({ ...spec, types: [...spec.types, { name: newType.trim(), count: 1 }] }); setNewType('') } }} />
                  <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} disabled={!newType.trim()} onClick={() => { setSpec({ ...spec, types: [...spec.types, { name: newType.trim(), count: 1 }] }); setNewType('') }} />
                </div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="목표 난이도">
                <Select value={spec.difficulty} onChange={(e) => setSpec({ ...spec, difficulty: e.target.value })}>
                  <option value="">샘플과 비슷하게</option>
                  {['하', '중하', '중', '중상', '상'].map((d) => <option key={d}>{d}</option>)}
                </Select>
              </Field>
              <Field label="정답 번호 배분">
                <Select value={spec.balance_answers ? '1' : '0'} onChange={(e) => setSpec({ ...spec, balance_answers: e.target.value === '1' })}>
                  <option value="1">1~5번 고르게 (자동 배치)</option>
                  <option value="0">Codex에 맡김</option>
                </Select>
              </Field>
            </div>
            <Field label="추가 요청 (선택)">
              <Textarea rows={3} placeholder="예: 3과 본문만 사용, 어법 문항은 관계대명사 위주로, 서술형 2문항 포함" value={spec.extra_instructions} onChange={(e) => setSpec({ ...spec, extra_instructions: e.target.value })} />
            </Field>
          </div>
          )}
        </Card>

        <Card className="p-5 lg:col-span-2">
          <h3 className="mb-1 flex items-center gap-2 font-semibold text-slate-900"><BookMarked className="size-4 text-slate-400" /> 적용할 지침</h3>
          <p className="mb-3 text-xs text-slate-500">
            이 프로젝트의 지침(기본 + 프로젝트 전용)에서 고르세요.{' '}
            <Link to={`/guidelines?project=${wb.project_id}`} className="text-brand-600 hover:underline">프로젝트 지침 관리 →</Link>
          </p>
          <div className="scroll-thin max-h-60 space-y-3 overflow-y-auto pr-1">
            {Object.entries(byCat).map(([cat, list]) => (
              <div key={cat}>
                <div className="mb-1 text-[11px] font-semibold text-slate-400">{cat}</div>
                {list.map((g) => (
                  <label key={g.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-slate-50">
                    <input type="checkbox" className="size-4 accent-brand-600" checked={selected.includes(g.id)}
                      onChange={(e) => setSelected(e.target.checked ? [...selected, g.id] : selected.filter((x) => x !== g.id))} />
                    <span className="text-slate-700">{g.title}</span>
                    {g.scope !== 'default' && <Badge color={SCOPE_BADGE[g.scope].color} className="!px-1.5 !text-[10px]">{g.scope === 'override' ? '수정본' : '프로젝트'}</Badge>}
                    <span className="ml-auto text-[11px] text-slate-300">v{g.version}</span>
                  </label>
                ))}
              </div>
            ))}
          </div>
          <div className="mt-3">
            <Field label="이 문제집 전용 지침">
              <Textarea rows={4} value={custom} placeholder="예: 지문은 원문을 80% 이상 유지, 선택지는 모두 영어로" onChange={(e) => setCustom(e.target.value)} />
            </Field>
          </div>
        </Card>
      </div>

      <AllocationCard wb={wb} reload={reload} />

      <div>
        <div className="mb-3 flex items-center gap-3">
          <h3 className="font-semibold text-slate-900">제작된 문제</h3>
          {qs.length > 0 && <Badge>{qs.length}문항</Badge>}
          {wb.questions?.title && <span className="text-sm text-slate-500">「{wb.questions.title.replace(/\*\*|__|==/g, '')}」</span>}
          {wb.versions.length > 0 && (
            <Button className="ml-auto" size="sm" variant="ghost" icon={<History className="size-3.5" />} onClick={() => setHistory(true)}>
              버전 기록 ({wb.versions.length})
            </Button>
          )}
        </div>
        {qs.length === 0 ? (
          <Empty icon={<Wand2 className="size-6" />} title="아직 제작된 문제가 없습니다" desc="오른쪽 위 ‘문제 제작 시작’을 누르면 몇 분 안에 문제가 만들어집니다." />
        ) : (
          wb.questions?.mode === 'form' && wb.questions.sets ? (
            <FormSetsView sets={wb.questions.sets} questions={qs} onSave={saveQuestion} />
          ) : (
            <div className="grid gap-4">
              {qs.map((q) => <QuestionCard key={`${q.number}-${wb.versions[0]?.id}`} q={q} all={qs} onSave={saveQuestion} />)}
            </div>
          )
        )}
      </div>

      <Modal open={history} onClose={() => setHistory(false)} title="버전 기록">
        <div className="space-y-2">
          {wb.versions.map((v, i) => (
            <div key={v.id} className="flex items-center gap-3 rounded-lg border border-slate-100 p-3">
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm text-slate-700">{v.note}</div>
                <div className="text-xs text-slate-400">{v.created_at.replace('T', ' ')}</div>
              </div>
              {i === 0 ? <Badge color="green">현재</Badge> : (
                <Button size="sm" onClick={() => run('restore', async () => { await api.post(`/workbooks/${wb.id}/versions/${v.id}/restore`); await reload(); setHistory(false) }, '이 버전으로 되돌렸습니다.')}>
                  되돌리기
                </Button>
              )}
            </div>
          ))}
        </div>
      </Modal>
    </div>
  )
}
