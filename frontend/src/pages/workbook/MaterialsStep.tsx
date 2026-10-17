import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Download, Eye, FileText, Highlighter, Library, ListOrdered, Trash2, UploadCloud } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api, SCOPES, USE_MODES, type FileSummary } from '../../api'
import { Badge, Button, Card, Input, Modal, SectionTitle, Select, Spinner, confirmDialog, cx, useAsync, useToast } from '../../components/ui'
import type { StepProps } from '../WorkbookPage'
import { ParaphraseControls } from '../../components/ParaphraseControls'

const ACCEPT = '.txt,.pdf,.hwp,.hwpx,.md'

export default function MaterialsStep({ wb, reload, goto }: StepProps) {
  const samples = wb.files.filter((f) => f.kind === 'sample')
  const refs = wb.files.filter((f) => f.kind === 'reference')
  const shared = wb.project_materials.filter((f) => f.scope !== 'exclude')
  const sharedSamples = shared.filter((f) => f.kind === 'sample')
  return (
    <div className="space-y-8">
      <SectionTitle
        title="1. 자료 등록"
        desc="문제지 샘플과 참고 자료를 올려 주세요. HWP 파일은 자동으로 HWPX로 바뀌고, HWPX 샘플의 서식(형광펜·글머리표·번호)은 출력 템플릿으로 쓰입니다."
        right={
          <Button variant="primary" disabled={samples.length + sharedSamples.length === 0} icon={<ArrowRight className="size-4" />} onClick={() => goto('analyze')}>
            다음: 샘플 분석
          </Button>
        }
      />
      {shared.length > 0 && (
        <Card className="flex items-start gap-4 border-brand-100 bg-brand-50/40 p-4">
          <Library className="mt-0.5 size-5 shrink-0 text-brand-600" />
          <div className="min-w-0 flex-1 text-sm">
            <div className="font-medium text-slate-800">프로젝트 자료실의 자료 {shared.length}개가 자동으로 함께 쓰입니다</div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {shared.map((f) => (
                <Badge key={f.id} color={f.kind === 'sample' ? 'brand' : 'slate'}>
                  {f.kind === 'sample' ? '샘플' : SCOPES[f.scope]} · {f.orig_name}{f.kind === 'reference' && f.scope === 'range' ? ` · ${USE_MODES[f.use_mode]}` : ''}
                </Badge>
              ))}
            </div>
          </div>
          <Link to={`/projects/${wb.project_id}?tab=materials`}><Button size="sm" variant="ghost">자료실 관리 →</Button></Link>
        </Card>
      )}
      <div className="grid gap-6 lg:grid-cols-2">
        <UploadArea
          kind="sample"
          title="문제지 샘플"
          desc="이런 모양의 문제지를 만들고 싶어요 — 유형·서식·난이도의 기준이 됩니다. HWP/HWPX를 권장해요."
          files={samples}
          workbookId={wb.id}
          reload={reload}
          templateId={wb.template_file_id}
        />
        <UploadArea
          kind="reference"
          title="참고 자료"
          desc="지문 원문, 교과서/부교재 본문, 어휘 목록 등 문제를 만들 재료입니다."
          files={refs}
          workbookId={wb.id}
          reload={reload}
        />
      </div>
    </div>
  )
}

function UploadArea({
  kind,
  title,
  desc,
  files,
  workbookId,
  reload,
  templateId,
}: {
  kind: 'sample' | 'reference'
  title: string
  desc: string
  files: FileSummary[]
  workbookId: number
  reload: () => Promise<void>
  templateId?: number | null
}) {
  const input = useRef<HTMLInputElement>(null)
  const [drag, setDrag] = useState(false)
  const [uploading, setUploading] = useState<string[]>([])
  const toast = useToast()

  const upload = async (list: FileList | File[]) => {
    const arr = Array.from(list)
    setUploading(arr.map((f) => f.name))
    for (const f of arr) {
      const fd = new FormData()
      fd.append('kind', kind)
      fd.append('file', f)
      try {
        const r = await api.post<FileSummary>(`/workbooks/${workbookId}/files`, fd)
        toast('ok', f.name.toLowerCase().endsWith('.hwp') ? `${f.name} → HWPX 변환 완료` : `${f.name} 업로드 완료`)
        if (r.format_brief?.conversion && Object.keys(r.format_brief.conversion.unconverted || {}).length)
          toast('err', `일부 요소는 변환되지 않았습니다: ${Object.keys(r.format_brief.conversion.unconverted).join(', ')}`)
      } catch (e) {
        toast('err', `${f.name}: ${(e as Error).message}`)
      }
    }
    setUploading([])
    await reload()
  }

  return (
    <Card className="p-5">
      <div className="mb-1 flex items-center gap-2">
        <h3 className="font-semibold text-slate-900">{title}</h3>
        <Badge>{files.length}개</Badge>
      </div>
      <p className="mb-4 text-[13px] text-slate-500">{desc}</p>

      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files) }}
        onClick={() => input.current?.click()}
        className={cx(
          'flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors',
          drag ? 'border-brand-500 bg-brand-50' : 'border-slate-200 hover:border-brand-200 hover:bg-slate-50',
        )}
      >
        {uploading.length ? (
          <>
            <Spinner className="mb-2" />
            <div className="text-sm text-slate-600">{uploading.join(', ')} 처리 중…</div>
          </>
        ) : (
          <>
            <UploadCloud className="mb-2 size-7 text-slate-400" />
            <div className="text-sm font-medium text-slate-700">파일을 끌어다 놓거나 클릭해서 선택</div>
            <div className="mt-1 text-xs text-slate-400">TXT · PDF · HWP · HWPX (여러 개 가능)</div>
          </>
        )}
        <input ref={input} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => e.target.files && upload(e.target.files)} />
      </div>

      <div className="mt-4 space-y-2">
        {files.map((f) => (
          <FileRow key={f.id} f={f} reload={reload} isTemplate={templateId === f.id} />
        ))}
      </div>
    </Card>
  )
}

function FileRow({ f, reload, isTemplate }: { f: FileSummary; reload: () => Promise<void>; isTemplate: boolean }) {
  const [view, setView] = useState(false)
  const [note, setNote] = useState(f.note)
  const { run } = useAsync()
  const ext = f.orig_name.split('.').pop()?.toUpperCase()
  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50/60 p-3">
      <div className="flex items-center gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white text-[10px] font-bold text-slate-500 ring-1 ring-slate-200">
          {ext}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-medium text-slate-800">{f.orig_name}</span>
            {isTemplate && <Badge color="brand">출력 템플릿</Badge>}
            {ext === 'HWP' && f.has_hwpx && <Badge color="green">HWPX 변환됨</Badge>}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
            <span>{f.text_length.toLocaleString()}자</span>
            {f.format_brief?.highlights.map((h) => (
              <span key={h.color} className="flex items-center gap-1">
                <Highlighter className="size-3" />
                <span className="inline-block size-2.5 rounded-sm ring-1 ring-black/10" style={{ background: h.color }} />
                형광펜 {h.count}
              </span>
            ))}
            {f.format_brief?.headings.slice(0, 2).map((h) => (
              <span key={h.label} className="flex items-center gap-1">
                <ListOrdered className="size-3" /> {h.label}
              </span>
            ))}
          </div>
        </div>
        <Button size="sm" variant="ghost" icon={<Eye className="size-3.5" />} onClick={() => setView(true)}>
          보기
        </Button>
        <button
          className="rounded-md p-1.5 text-slate-400 hover:bg-white hover:text-rose-600"
          onClick={() => confirmDialog(`${f.orig_name}을(를) 삭제할까요?`) && run('del', async () => { await api.del(`/files/${f.id}`); await reload() })}
        >
          <Trash2 className="size-4" />
        </button>
      </div>
      {f.kind === 'reference' && (
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Select className="!h-8 bg-white text-xs" value={f.scope || 'range'} onChange={(e) => run('scope', async () => { await api.put(`/files/${f.id}`, { scope: e.target.value }); await reload() })}>
            {Object.entries(SCOPES).map(([k, v]) => <option key={k} value={k}>범위: {v}</option>)}
          </Select>
          <Select className="!h-8 bg-white text-xs" value={f.use_mode || 'adapt'} disabled={(f.scope || 'range') !== 'range'} onChange={(e) => run('mode', async () => { await api.put(`/files/${f.id}`, { use_mode: e.target.value }); await reload() })}>
            {Object.entries(USE_MODES).map(([k, v]) => <option key={k} value={k}>지문: {v}</option>)}
          </Select>
        </div>
      )}
      {f.kind === 'reference' && (f.scope || 'range') === 'range' && f.use_mode === 'paraphrase' && f.paraphrase && (
        <ParaphraseControls value={f.paraphrase} onChange={(paraphrase) => run('para', async () => { await api.put(`/files/${f.id}`, { paraphrase }); await reload() })} />
      )}
      <Input
        className="mt-2 !h-8 bg-white text-xs"
        placeholder="메모 (예: 3과 본문, 이 샘플의 6~10번 유형만 참고)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
        onBlur={() => note !== f.note && run('note', () => api.put(`/files/${f.id}`, { note }))}
      />
      {view && <FileViewer id={f.id} name={f.orig_name} hasHwpx={f.has_hwpx} onClose={() => setView(false)} />}
    </div>
  )
}

function FileViewer({ id, name, hasHwpx, onClose }: { id: number; name: string; hasHwpx: boolean; onClose: () => void }) {
  const [data, setData] = useState<{ text: string; format: any } | null>(null)
  const [tab, setTab] = useState<'text' | 'format'>('text')
  useEffect(() => {
    api.get<{ text: string; format: any }>(`/files/${id}`).then(setData)
  }, [id])
  return (
    <Modal open wide onClose={onClose} title={name} footer={
      <>
        {hasHwpx && (
          <a href={`/api/files/${id}/download?hwpx=true`}>
            <Button size="sm" icon={<Download className="size-3.5" />}>HWPX 받기</Button>
          </a>
        )}
        <Button size="sm" variant="primary" onClick={onClose}>닫기</Button>
      </>
    }>
      {!data ? <Spinner /> : (
        <>
          {data.format && (
            <div className="mb-3 flex gap-1 rounded-lg bg-slate-100 p-1 text-sm">
              {(['text', 'format'] as const).map((t) => (
                <button key={t} onClick={() => setTab(t)} className={cx('flex-1 rounded-md py-1.5', tab === t ? 'bg-white font-medium shadow-xs' : 'text-slate-500')}>
                  {t === 'text' ? '추출한 텍스트' : '서식 분석'}
                </button>
              ))}
            </div>
          )}
          {tab === 'text' ? (
            <pre className="rounded-lg bg-slate-50 p-4 font-sans text-[13px] leading-relaxed whitespace-pre-wrap text-slate-700">{data.text || '(텍스트 없음)'}</pre>
          ) : (
            <FormatView fmt={data.format} />
          )}
          <p className="mt-2 flex items-center gap-1 text-xs text-slate-400">
            <FileText className="size-3" /> 표기: ==형광펜==, __밑줄__, **굵게**
          </p>
        </>
      )}
    </Modal>
  )
}

function FormatView({ fmt }: { fmt: any }) {
  return (
    <div className="space-y-4 text-sm">
      <div>
        <div className="mb-1 font-medium">형광펜</div>
        {fmt.highlights.length === 0 ? <span className="text-slate-400">사용 안 함</span> : fmt.highlights.map((h: any) => (
          <div key={h.color} className="flex items-center gap-2 text-[13px]">
            <span className="inline-block size-3 rounded-sm ring-1 ring-black/10" style={{ background: h.color }} /> {h.color} · {h.count}회 · 예) {h.examples.slice(0, 3).join(', ')}
          </div>
        ))}
      </div>
      <div>
        <div className="mb-1 font-medium">글머리표 / 문단 번호</div>
        {fmt.headings.length === 0 ? <span className="text-slate-400">사용 안 함</span> : fmt.headings.map((h: any) => (
          <div key={h.label} className="text-[13px]">{h.label} — {h.count}개 문단</div>
        ))}
        <div className="mt-1 text-[13px] text-slate-500">본문 원문자(①~⑤) {fmt.circled_number_count}회</div>
      </div>
      <div>
        <div className="mb-1 font-medium">주요 글자 모양</div>
        {fmt.char_styles.map((c: any) => (
          <div key={c.id} className="text-[13px] text-slate-600">
            #{c.id} {c.font} / {c.latin_font} {c.height}pt {c.bold && '· 굵게'} {c.underline && '· 밑줄'} {c.italic && '· 기울임'} ({c.chars}자)
          </div>
        ))}
      </div>
      <div>
        <div className="mb-1 font-medium">문단 ({fmt.paragraph_count}개)</div>
        <div className="scroll-thin max-h-72 overflow-y-auto rounded-lg border border-slate-100">
          {fmt.paragraphs.map((p: any) => (
            <div key={p.index} className="flex gap-2 border-b border-slate-50 px-3 py-1.5 text-xs">
              <span className="w-8 shrink-0 text-slate-400">#{p.index}</span>
              <span className="w-28 shrink-0 truncate text-slate-400">{p.heading || p.style}{p.container ? ` [${p.container}]` : ''}</span>
              <span className="truncate text-slate-700">{p.text || '(빈 줄)'}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
