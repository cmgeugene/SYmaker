import { useEffect, useState } from 'react'
import { Bot, Save } from 'lucide-react'
import { api, type Settings } from '../api'
import { Button, Card, Field, Input, Select, Spinner, useAsync } from '../components/ui'
import { useSettings } from '../components/jobs'

const STAGE_HELP: Record<string, string> = {
  segment: '자료에서 본문(지문)을 찾아 나눕니다. 강의노트처럼 같은 본문이 여러 번 나오는 자료는 보통(medium) 이상을 권장합니다.',
  analyze: '샘플의 유형·난이도·서식 분석. 보통(medium)이면 충분합니다.',
  generate: '문제 출제. 품질이 가장 중요하므로 높은 effort를 권장합니다.',
  review: '지침·서식·정답 검수. 꼼꼼함이 필요해 높은 effort를 권장합니다.',
  revise: '검수/피드백에 따른 수정.',
  guideline: '피드백을 지침 수정안으로 정리.',
}

export default function SettingsPage() {
  const { settings, reload } = useSettings()
  const [draft, setDraft] = useState<Settings | null>(null)
  const [health, setHealth] = useState<{ codex: boolean; codex_version: string | null } | null>(null)
  const { busy, run } = useAsync()
  useEffect(() => setDraft(settings), [settings])
  useEffect(() => { api.get<typeof health>('/health').then(setHealth) }, [])

  if (!draft) return <div className="flex h-full items-center justify-center"><Spinner /></div>
  const effortLabel = (e: string) => `${draft.effort_labels[e] || e} (${e})`

  return (
    <div className="mx-auto max-w-4xl px-8 py-8">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">모델 설정</h1>
          <p className="mt-1 text-sm text-slate-500">각 단계에서 Codex CLI가 사용할 모델과 추론 수준(effort)을 정합니다. 실행 버튼 옆에서 그때그때 바꿀 수도 있어요.</p>
        </div>
        <Button variant="primary" icon={<Save className="size-4" />} loading={busy === 'save'} onClick={() =>
          run('save', async () => { await api.put('/settings', { stages: draft.stages, runner: draft.runner }); reload() }, '설정을 저장했습니다.')
        }>저장</Button>
      </div>

      <Card className="mb-6 flex items-center gap-3 p-4 text-sm">
        <Bot className="size-5 text-slate-400" />
        {health ? (health.codex ? <span>Codex CLI 연결됨 · <span className="text-slate-500">{health.codex_version}</span></span> : <span className="text-rose-600">Codex CLI를 찾을 수 없습니다.</span>) : '확인 중…'}
      </Card>

      <Card className="divide-y divide-slate-100">
        {Object.entries(draft.stage_labels).map(([stage, label]) => {
          const cfg = draft.stages[stage]
          const model = draft.models.find((m) => m.id === cfg.model)
          return (
            <div key={stage} className="grid grid-cols-[1fr_220px_160px] items-center gap-4 px-5 py-4">
              <div>
                <div className="font-medium text-slate-800">{label}</div>
                <div className="text-xs text-slate-500">{STAGE_HELP[stage]}</div>
              </div>
              <Select value={cfg.model} onChange={(e) => {
                const m = draft.models.find((x) => x.id === e.target.value)
                const effort = m && !m.efforts.includes(cfg.effort) ? m.default_effort : cfg.effort
                setDraft({ ...draft, stages: { ...draft.stages, [stage]: { model: e.target.value, effort } } })
              }}>
                {draft.models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                {!model && <option value={cfg.model}>{cfg.model}</option>}
              </Select>
              <Select value={cfg.effort} onChange={(e) => setDraft({ ...draft, stages: { ...draft.stages, [stage]: { ...cfg, effort: e.target.value } } })}>
                {(model?.efforts || ['low', 'medium', 'high']).map((e) => <option key={e} value={e}>{effortLabel(e)}</option>)}
              </Select>
            </div>
          )
        })}
      </Card>

      <h2 className="mt-8 mb-3 font-semibold text-slate-900">실행 옵션</h2>
      <Card className="mb-4 grid grid-cols-2 gap-6 p-5">
        <Field label="묶음 크기 (문항 수)" hint="문항이 이보다 많으면 출제 계획을 먼저 세운 뒤 이 크기로 나눠 제작·검수합니다. 작을수록 품질이 고르지만 호출 수가 늘어납니다.">
          <Input type="number" min={2} max={15} value={draft.runner.batch_size} onChange={(e) => setDraft({ ...draft, runner: { ...draft.runner, batch_size: Number(e.target.value) } })} />
        </Field>
        <Field label="동시 실행 수" hint="한 번에 돌릴 Codex 세션 수. 늘리면 빨라지지만 사용량 한도에 빨리 닿을 수 있습니다.">
          <Input type="number" min={1} max={8} value={draft.runner.concurrency} onChange={(e) => setDraft({ ...draft, runner: { ...draft.runner, concurrency: Number(e.target.value) } })} />
        </Field>
      </Card>
      <Card className="grid grid-cols-2 gap-6 p-5">
        <Field label="작업 제한 시간 (분)" hint="이 시간을 넘기면 작업을 중단합니다.">
          <Input type="number" min={1} value={draft.runner.timeout_minutes} onChange={(e) => setDraft({ ...draft, runner: { ...draft.runner, timeout_minutes: Number(e.target.value) } })} />
        </Field>
        <label className="flex items-start gap-2 pt-6 text-sm">
          <input type="checkbox" className="mt-0.5 size-4 accent-brand-600" checked={draft.runner.ignore_user_config} onChange={(e) => setDraft({ ...draft, runner: { ...draft.runner, ignore_user_config: e.target.checked } })} />
          <span>
            개인 codex 설정(~/.codex/config.toml) 무시
            <span className="block text-xs text-slate-500">MCP 서버 등 불필요한 설정을 건너뛰어 더 빠르고 안정적으로 실행합니다. 로그인 정보는 그대로 사용합니다.</span>
          </span>
        </label>
      </Card>
    </div>
  )
}
