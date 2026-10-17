import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { api } from '../../api'
import { Badge, Button, Field, Input, Modal, Select, Spinner, cx, useAsync } from '../../components/ui'

const COMMON_TYPES = ['주제', '제목', '요지', '빈칸 추론', '어법', '어휘', '글의 순서', '문장 삽입', '무관한 문장', '요약문 완성', '내용 일치', '함축 의미']

export function SetGroupModal({ projectId, passageCount, onClose, onCreated }: { projectId: number; passageCount: number; onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [sets, setSets] = useState(3)
  const [mc, setMc] = useState(25)
  const [essay, setEssay] = useState(5)
  const [difficulty, setDifficulty] = useState('')
  const [types, setTypes] = useState<{ name: string; count: number }[]>([])
  const [newType, setNewType] = useState(COMMON_TYPES[0])
  const { busy, run } = useAsync()

  const total = mc + essay
  const typed = types.reduce((s, t) => s + t.count, 0)
  const avg = passageCount ? (total * sets) / passageCount : 0

  const create = () =>
    run('create', async () => {
      await api.post(`/projects/${projectId}/set-groups`, {
        name: name.trim(),
        set_count: sets,
        spec: { question_count: total, essay_count: essay, difficulty, types: types.filter((t) => t.count > 0), title: name.trim() },
      })
      onCreated()
    }, `세트 ${sets}개를 만들었습니다.`)

  return (
    <Modal open wide onClose={onClose} title="모의고사 세트 만들기" footer={
      <>
        <Button variant="ghost" onClick={onClose}>취소</Button>
        <Button variant="primary" disabled={!name.trim() || sets < 1 || total < 1} loading={busy === 'create'} onClick={create}>세트 {sets}개 만들기</Button>
      </>
    }>
      <div className="space-y-5">
        <div className="grid grid-cols-[1fr_120px] gap-3">
          <Field label="그룹 이름" hint="세트 이름은 '그룹 이름 1세트', '2세트'…로 붙습니다.">
            <Input autoFocus value={name} placeholder="예: 기말 대비 모의고사" onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="세트 수"><Input type="number" min={1} max={20} value={sets} onChange={(e) => setSets(Number(e.target.value))} /></Field>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Field label="세트당 객관식"><Input type="number" min={0} value={mc} onChange={(e) => setMc(Math.max(0, Number(e.target.value)))} /></Field>
          <Field label="세트당 서술형"><Input type="number" min={0} value={essay} onChange={(e) => setEssay(Math.max(0, Number(e.target.value)))} /></Field>
          <Field label="목표 난이도">
            <Select value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
              <option value="">샘플과 비슷하게</option>
              {['하', '중하', '중', '중상', '상'].map((d) => <option key={d}>{d}</option>)}
            </Select>
          </Field>
        </div>

        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[13px] font-medium text-slate-700">객관식 유형별 문항 수 (선택)</span>
            <span className={cx('text-xs', typed > mc ? 'text-rose-600' : 'text-slate-400')}>
              지정 {typed} / 객관식 {mc} {typed < mc && `· 나머지 ${mc - typed}문항은 본문에 맞는 유형으로 자동 배정`}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {types.map((t, i) => (
              <div key={i} className="flex items-center gap-1 rounded-lg border border-slate-200 bg-slate-50 py-1 pr-1 pl-3 text-sm">
                {t.name}
                <input type="number" min={0} className="ml-1 h-7 w-12 rounded-md border border-slate-200 bg-white text-center" value={t.count}
                  onChange={(e) => setTypes(types.map((x, j) => (j === i ? { ...x, count: Number(e.target.value) } : x)))} />
                <button className="rounded p-1 text-slate-300 hover:text-rose-500" onClick={() => setTypes(types.filter((_, j) => j !== i))}><Trash2 className="size-3.5" /></button>
              </div>
            ))}
            <div className="flex items-center gap-1">
              <Select className="!h-9 w-36" value={newType} onChange={(e) => setNewType(e.target.value)}>
                {COMMON_TYPES.filter((t) => !types.some((x) => x.name === t)).map((t) => <option key={t}>{t}</option>)}
              </Select>
              <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={() => newType && setTypes([...types, { name: newType, count: 1 }])}>추가</Button>
            </div>
          </div>
        </div>

        <div className={cx('rounded-lg px-4 py-3 text-[13px]', !passageCount ? 'bg-amber-50 text-amber-800' : passageCount < total ? 'bg-amber-50 text-amber-800' : 'bg-slate-50 text-slate-600')}>
          {!passageCount ? (
            <>아직 본문 목록이 없습니다. 세트는 지금 만들어 두고, 자료실에서 ‘본문 나누기’를 한 뒤 ‘본문 자동 배정’을 누르세요.</>
          ) : (
            <>
              본문 {passageCount}개로 세트 {sets}개 × {total}문항 = {sets * total}문항을 만듭니다. 본문 하나당 평균 <b>{avg.toFixed(1)}회</b> 쓰이고,
              같은 본문은 세트마다 다른 유형으로 나옵니다.
              {passageCount < total && <> 다만 본문이 세트당 문항 수보다 적어 한 세트 안에서 일부 본문이 다른 유형으로 다시 쓰입니다.</>}
            </>
          )}
        </div>
      </div>
    </Modal>
  )
}

interface Coverage {
  sets: { id: number; name: string; set_index: number }[]
  rows: { id: number; label: string; file_name: string; excluded: boolean; cells: Record<string, string[]> }[]
}

export function CoverageModal({ groupId, onClose }: { groupId: number; onClose: () => void }) {
  const [data, setData] = useState<Coverage | null>(null)
  useEffect(() => { api.get<Coverage>(`/set-groups/${groupId}/coverage`).then(setData) }, [groupId])
  const counts = data?.rows.map((r) => Object.values(r.cells).flat().length) || []
  return (
    <Modal open wide onClose={onClose} title="본문 사용표">
      {!data ? <Spinner /> : (
        <>
          <p className="mb-3 text-xs text-slate-500">
            각 칸은 그 세트에서 본문을 어떤 유형으로 썼는지 보여 줍니다. 본문당 사용 횟수: 최소 {Math.min(...counts.filter((_, i) => !data.rows[i].excluded))}회 · 최대 {Math.max(...counts)}회
          </p>
          <div className="overflow-x-auto rounded-lg border border-slate-100">
            <table className="w-full text-[12.5px]">
              <thead className="bg-slate-50 text-left text-slate-500">
                <tr>
                  <th className="px-3 py-2 font-medium">자료</th>
                  <th className="px-3 py-2 font-medium">본문</th>
                  {data.sets.map((s) => <th key={s.id} className="px-3 py-2 text-center font-medium">{s.set_index}세트</th>)}
                  <th className="px-3 py-2 text-center font-medium">합계</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr key={r.id} className={cx('border-t border-slate-100', r.excluded && 'opacity-40')}>
                    <td className="px-3 py-1.5 whitespace-nowrap text-slate-500">{r.file_name.replace(/\.[^.]+$/, '')}</td>
                    <td className="px-3 py-1.5 text-slate-800">{r.label}</td>
                    {data.sets.map((s) => (
                      <td key={s.id} className="px-2 py-1.5 text-center">
                        {(r.cells[String(s.id)] || []).map((t, k) => <Badge key={k} color={t.includes('서술') ? 'sky' : 'brand'} className="m-0.5">{t}</Badge>)}
                      </td>
                    ))}
                    <td className={cx('px-3 py-1.5 text-center font-medium', counts[i] === 0 && !r.excluded ? 'text-amber-600' : 'text-slate-600')}>{counts[i]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Modal>
  )
}
