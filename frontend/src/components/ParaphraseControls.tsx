import { useEffect, useState } from 'react'
import type { Paraphrase } from '../api'
import { Input, Select } from './ui'

const LENGTHS: Record<Paraphrase['length'], string> = {
  same: '분량: 원문과 비슷하게',
  shorter: '분량: 짧게 (약 70~85%)',
  longer: '분량: 길게 (약 115~130%)',
  custom: '분량: 단어 수 직접 지정',
}

const TIERS = ['하', '중', '상']
const LEVEL_GROUPS: { label: string; options: [string, string][] }[] = [
  { label: '원문 기준', options: [['same', '원문 수준'], ['easier', '원문보다 쉽게'], ['harder', '원문보다 어렵게']] },
  { label: '고등학교', options: ['고1', '고2', '고3'].flatMap((g) => TIERS.map((t) => [`${g}-${t}`, `${g} ${t}`] as [string, string])) },
  { label: '수능', options: [['수능', '수능']] },
]

function levelHint(level: string) {
  if (level === 'same') return '어휘·구문 난이도를 원문과 비슷하게'
  if (level === 'easier') return '기본 어휘로 바꾸고 긴 문장은 나누며 복잡한 구문을 줄임'
  if (level === 'harder') return '정교한 어휘와 관계절·분사구문·도치 등 복잡한 구문을 늘림'
  if (level === '수능') return '수능 독해 지문 수준의 학술적 어휘와 복잡한 구문'
  const [g, t] = level.split('-')
  const tier = { 하: '쉬운 편', 중: '평균 수준', 상: '어려운 편' }[t] || ''
  return `${g} 교과서·모의고사 지문 중 ${tier}의 어휘·구문`
}

/** '패러프레이징' 자료의 분량·난이도·메모 규칙. 바뀌면 onChange로 저장한다. */
export function ParaphraseControls({ value, onChange }: { value: Paraphrase; onChange: (p: Paraphrase) => void }) {
  const [draft, setDraft] = useState<Paraphrase>({ ...value, note: value.note || '' })
  useEffect(() => setDraft({ ...value, note: value.note || '' }), [value.length, value.level, value.min_words, value.max_words, value.note]) // eslint-disable-line react-hooks/exhaustive-deps
  const commit = (p: Paraphrase) => {
    setDraft(p)
    const sameAsSaved = p.length === value.length && p.level === value.level && p.min_words === value.min_words && p.max_words === value.max_words && (p.note || '') === (value.note || '')
    if (sameAsSaved) return
    if (p.length !== 'custom' || (p.min_words > 0 && p.max_words >= p.min_words)) onChange(p)
  }
  return (
    <div className="mt-2 rounded-md border border-violet-100 bg-violet-50/50 p-2">
      <div className="grid grid-cols-2 gap-2">
        <Select className="!h-8 bg-white text-xs" value={draft.length} onChange={(e) => commit({ ...draft, length: e.target.value as Paraphrase['length'] })}>
          {Object.entries(LENGTHS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </Select>
        <Select className="!h-8 bg-white text-xs" value={draft.level} onChange={(e) => commit({ ...draft, level: e.target.value })}>
          {LEVEL_GROUPS.map((g) => (
            <optgroup key={g.label} label={g.label}>
              {g.options.map(([k, v]) => <option key={k} value={k}>난이도: {v}</option>)}
            </optgroup>
          ))}
        </Select>
      </div>
      {draft.length === 'custom' && (
        <div className="mt-2 flex items-center gap-2 text-xs text-slate-600">
          <Input type="number" min={20} className="!h-8 w-20 bg-white text-xs" value={draft.min_words || ''} placeholder="최소"
            onChange={(e) => setDraft({ ...draft, min_words: Number(e.target.value) })} onBlur={() => commit(draft)} />
          ~
          <Input type="number" min={20} className="!h-8 w-20 bg-white text-xs" value={draft.max_words || ''} placeholder="최대"
            onChange={(e) => setDraft({ ...draft, max_words: Number(e.target.value) })} onBlur={() => commit(draft)} />
          단어
        </div>
      )}
      <Input className="mt-2 !h-8 bg-white text-xs" value={draft.note} placeholder="패러프레이징 메모 (예: 주제문은 첫 문장에, 고유명사·수치는 그대로, 대화체는 서술체로)"
        onChange={(e) => setDraft({ ...draft, note: e.target.value })} onBlur={() => commit(draft)} />
      <p className="mt-1.5 text-[11px] text-violet-700/80">
        패러프레이징 규칙 · {levelHint(draft.level)}. 문제 제작 때 이 규칙으로 지문을 새로 쓰고, 검수에서 분량을 확인합니다.
      </p>
    </div>
  )
}
