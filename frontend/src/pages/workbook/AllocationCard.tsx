import { useEffect, useState } from 'react'
import { AlertTriangle, Shuffle, Undo2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, USE_MODES, type Allocation, type AllocItem, type Passage, type Workbook } from '../../api'
import { Badge, Button, Card, Input, Select, confirmDialog, cx, useAsync } from '../../components/ui'

/** 이 세트의 '문항 번호 → 본문·유형' 배정표. 배정표가 있으면 출제 계획 없이 이대로 제작한다. */
export default function AllocationCard({ wb, reload }: { wb: Workbook; reload: () => Promise<void> }) {
  const [passages, setPassages] = useState<Passage[]>([])
  const [items, setItems] = useState<AllocItem[]>(wb.allocation?.items || [])
  const { busy, run } = useAsync()
  useEffect(() => { api.get<{ passages: Passage[] }>(`/projects/${wb.project_id}/materials`).then((d) => setPassages(d.passages)) }, [wb.project_id, wb.allocation?.at])
  useEffect(() => setItems(wb.allocation?.items || []), [wb.allocation?.at]) // eslint-disable-line react-hooks/exhaustive-deps

  const alloc = wb.allocation
  const dirty = JSON.stringify(items) !== JSON.stringify(alloc?.items || [])
  const otherUse = (x: Passage) => x.usage.filter((u) => u.workbook_id !== wb.id).map((u) => u.type)
  const usable = passages.filter((p) => !p.excluded && p.file_scope === 'range' && p.located)
  const expected = wb.form ? (wb.spec.passage_count || wb.form.block_count) : wb.spec.question_count
  const unit = wb.form ? '지문' : '문항'
  const sizeMismatch = alloc && alloc.items.length !== expected

  if (!wb.passage_count) {
    return (
      <Card className="flex items-center gap-3 border-dashed p-4 text-[13px] text-slate-500">
        <Shuffle className="size-4 shrink-0" />
        <span className="flex-1">프로젝트 자료실에서 ‘본문 나누기’를 하면, 문항마다 쓸 본문을 정해(다른 세트와 겹치지 않게) 제작할 수 있습니다.</span>
        <Link to={`/projects/${wb.project_id}?tab=materials`}><Button size="sm" variant="ghost">자료실로 →</Button></Link>
      </Card>
    )
  }

  const save = () => run('save', async () => { const r = await api.put<Allocation>(`/workbooks/${wb.id}/allocation`, { items }); await reload(); return r }, '배정표를 저장했습니다.')

  return (
    <Card className="p-5">
      <div className="mb-1 flex items-center gap-2">
        <h3 className="font-semibold text-slate-900">본문 배정</h3>
        {alloc ? <Badge color="green">배정됨 · {unit} {alloc.items.length}개</Badge> : <Badge>배정 안 함</Badge>}
        {alloc?.edited && <Badge color="amber">직접 수정</Badge>}
        <div className="ml-auto flex gap-2">
          {alloc && (
            <Button size="sm" variant="ghost" icon={<Undo2 className="size-3.5" />} onClick={() =>
              confirmDialog('배정을 해제할까요? 해제하면 Codex가 출제 계획을 세워 자료 전체에서 자유롭게 출제합니다.') &&
              run('clear', async () => { await api.del(`/workbooks/${wb.id}/allocation`); await reload() })}>
              배정 해제
            </Button>
          )}
          <Button size="sm" icon={<Shuffle className="size-3.5" />} loading={busy === 'auto'} onClick={() =>
            run('auto', async () => { await api.post(`/workbooks/${wb.id}/allocate`); await reload() }, '다른 세트의 사용 기록을 피해 본문을 배정했습니다.')}>
            {alloc ? '자동으로 다시 배정' : '자동 배정'}
          </Button>
          {alloc && <Button size="sm" variant={dirty ? 'primary' : 'secondary'} disabled={!dirty} loading={busy === 'save'} onClick={save}>저장</Button>}
        </div>
      </div>
      <p className="mb-3 text-xs text-slate-500">
        배정표가 있으면 출제 계획 없이 이 표대로 제작합니다. 같은 본문은 한 세트에서 한 번만, 다른 세트에서는 다른 유형으로 쓰이도록 배정됩니다.
      </p>

      {sizeMismatch && (
        <div className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-[13px] text-amber-800">
          {unit} 수({expected})가 배정표({alloc!.items.length})와 다릅니다. ‘자동으로 다시 배정’을 눌러 주세요.
        </div>
      )}
      {!!alloc?.warnings.length && (
        <div className="mb-3 space-y-1 rounded-lg bg-amber-50 px-3 py-2 text-[13px] text-amber-800">
          {alloc.warnings.map((w, i) => <div key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{w}</div>)}
        </div>
      )}

      {alloc && (
        <div className="scroll-thin max-h-[420px] overflow-y-auto rounded-lg border border-slate-100">
          <table className="w-full text-[13px]">
            <thead className="sticky top-0 bg-slate-50 text-left text-slate-500">
              <tr>
                <th className="w-12 px-3 py-2 font-medium">번호</th>
                <th className="w-40 px-3 py-2 font-medium">유형</th>
                <th className="px-3 py-2 font-medium">본문</th>
                <th className="w-32 px-3 py-2 font-medium">지문 사용</th>
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => {
                const p = passages.find((x) => x.id === it.passage_id)
                const dup = items.filter((x) => x.passage_id === it.passage_id).length > 1
                return (
                  <tr key={it.number} className="border-t border-slate-100">
                    <td className="px-3 py-1.5 text-slate-600">{it.kind === '서술형' ? <Badge color="sky" className="whitespace-nowrap">서{i + 1 - items.filter((x) => x.kind !== '서술형').length}</Badge> : it.number}</td>
                    <td className="px-2 py-1.5">
                      <Input className="!h-8 text-[13px]" value={it.type} onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)))} />
                    </td>
                    <td className="px-2 py-1.5">
                      <Select className={cx('!h-8 text-[13px]', dup && '!border-amber-400')} value={it.passage_id}
                        onChange={(e) => setItems(items.map((x, j) => (j === i ? { ...x, passage_id: Number(e.target.value) } : x)))}>
                        {usable.map((x) => (
                          <option key={x.id} value={x.id}>
                            {x.file_name.replace(/\.[^.]+$/, '')} · {x.label}{otherUse(x).length ? ` (다른 세트: ${otherUse(x).join(', ')})` : ''}
                          </option>
                        ))}
                      </Select>
                    </td>
                    <td className="px-3 py-1.5 text-xs text-slate-500">{p ? USE_MODES[p.use_mode] : '-'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
