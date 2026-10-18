export type StageKey = 'materials' | 'analyze' | 'generate' | 'review' | 'export' | 'feedback'
export type StageStatus = Record<StageKey, 'todo' | 'done' | 'stale' | 'open'>

export interface WorkbookSummary {
  id: number
  project_id: number
  name: string
  description: string
  updated_at: string
  question_count: number
  status: StageStatus
  group_id: number | null
  set_index: number | null
  has_allocation: boolean
}

export interface SetGroup {
  id: number
  project_id: number
  name: string
  spec: Spec
  created_at: string
}

export type UseMode = 'verbatim' | 'paraphrase' | 'adapt'
export type Scope = 'range' | 'reference' | 'exclude'
export const USE_MODES: Record<UseMode, string> = { verbatim: '원문 그대로', paraphrase: '패러프레이징', adapt: '일부 변형 허용' }
export const SCOPES: Record<Scope, string> = { range: '출제 범위', reference: '참고만', exclude: '제외' }

export interface Paraphrase {
  length: 'same' | 'shorter' | 'longer' | 'custom'
  min_words: number
  max_words: number
  /** same | easier | harder | 고1-하 … 고3-상 | 수능 */
  level: string
  note: string
}

export interface ProjectFile {
  id: number
  kind: 'sample' | 'reference'
  orig_name: string
  note: string
  scope: Scope
  use_mode: UseMode
  paraphrase: Paraphrase
  has_hwpx: boolean
  text_length: number
  preview: string
  segmented_at: string | null
  passage_count: number
  excluded_count: number
  unlocated_count: number
  created_at: string
}

export interface Passage {
  id: number
  file_id: number
  seq: number
  label: string
  text: string
  summary: string
  suitable_types: string[]
  excluded: number
  located: number
  file_name: string
  use_mode: UseMode
  file_scope: Scope
  usage: { workbook_id: number; workbook: string; type: string }[]
}

export interface AllocItem {
  number: number
  kind: '객관식' | '서술형'
  type: string
  passage_id: number
  label: string
  file_name: string
  use_mode: UseMode
}

export interface Allocation {
  items: AllocItem[]
  warnings: string[]
  at: string
  edited?: boolean
}

export interface Project {
  id: number
  name: string
  year: number
  semester: string
  description: string
  created_at: string
  workbooks: WorkbookSummary[]
  groups?: SetGroup[]
  material_count?: number
  passage_count?: number
}

export interface FileSummary {
  id: number
  kind: 'sample' | 'reference'
  orig_name: string
  note: string
  scope?: Scope
  use_mode?: UseMode
  paraphrase?: Paraphrase
  has_hwpx: boolean
  text_length: number
  preview: string
  format_brief: {
    highlights: { color: string; count: number; examples: string[] }[]
    headings: { label: string; count: number }[]
    paragraph_count: number
    conversion?: { unconverted: Record<string, number>; dropped: Record<string, number> }
  } | null
  created_at: string
}

export interface Question {
  number: number
  type: string
  difficulty: string
  instruction: string
  passage: string
  kind?: '객관식' | '서술형'
  choices: string[]
  answer: string
  explanation: string
  points?: number
  rubric?: string
  source: string
  /** 양식 모드: 몇 번째 지문 세트의 어느 하위 문항인지 */
  set?: number
  segment_id?: string
  extra?: string
}

export interface FormItem {
  segment_id: string
  type: string
  kind: '객관식' | '서술형'
  instruction: string
  choices: string[]
  answer: string
  explanation: string
  points: number
  extra: string
}

export interface FormSet {
  index: number
  passage_id: number
  label: string
  passage: string
  logic_flow: string[]
  items: FormItem[]
  layout?: { hash: string }
}

export type Align = '' | 'LEFT' | 'CENTER' | 'RIGHT' | 'JUSTIFY'

/** 양식 출력 서식 설정 (분석 결과에 저장) */
export interface FormStyle {
  header_highlight: boolean
  hidden_style: ('highlight' | 'bold' | 'underline' | 'white')[]
  gap_lines: number | null
  front_body: { size: number | null; align: Align; keyword_mark: boolean; hide_order: boolean }
  box_align: Record<string, Align>
  box_line_spacing: Record<string, number> // 칸 주소 → 줄간격 %
  box_title_font: Record<string, boolean> // 칸 주소 → 내용 줄 글꼴을 제목 줄 글꼴로
  fix_points: Record<string, number> // 하위 문항 id → '바르게 고치기' 배점
  passage_answer_mark: boolean // 교사용: 지문 안 정답 위치(삽입·어법·어휘)에 형광펜
}

export const FORM_STYLE_DEFAULT: FormStyle = {
  header_highlight: true,
  hidden_style: ['highlight', 'bold', 'white'],
  gap_lines: 1,
  front_body: { size: null, align: '', keyword_mark: false, hide_order: true },
  box_align: {},
  box_line_spacing: {},
  box_title_font: {},
  fix_points: {},
  passage_answer_mark: false,
}

export interface FormSegment {
  segment_id: string
  type: string
  kind: '객관식' | '서술형'
  usage: 'use' | 'skip' | 'pick-A' | 'pick-B'
  five_way: boolean
  answer_format: string
  notes: string
}

const SYMBOL_SETS = ['①②③④⑤⑥⑦⑧⑨⑩', '❶❷❸❹❺❻❼❽❾❿', 'ⓐⓑⓒⓓⓔⓕⓖⓗⓘⓙ', 'ⒶⒷⒸⒹⒺ', '㉠㉡㉢㉣㉤㉥㉦㉧㉨㉩', '㉮㉯㉰㉱㉲㉳㉴㉵㉶㉷', 'abcde', 'ABCDE']

/** 정답 표기를 번호로: '3', '③', '❸', 'ⓒ' → 3. 알 수 없으면 NaN */
export function answerIndex(answer: string): number {
  const a = String(answer ?? '').replace(/[\s()[\].번]/g, '')
  if (/^\d+$/.test(a)) return Number(a)
  if ([...a].length === 1) for (const s of SYMBOL_SETS) { const i = [...s].indexOf(a); if (i >= 0) return i + 1 }
  return NaN
}

export const isEssay = (q: Question) => q.kind === '서술형' || (!q.kind && q.choices.length === 0)

/** 객관식은 '7.', 서술형은 서술형끼리 번호를 매겨 '[서술형 2]' */
export function qLabel(q: Question, all: Question[]) {
  if (!isEssay(q)) return `${q.number}.`
  return `[서술형 ${all.filter(isEssay).indexOf(q) + 1}]`
}

export interface Questions {
  title: string
  questions: Question[]
  mode?: 'form'
  sets?: FormSet[]
}

export interface Analysis {
  summary: string
  question_types: { name: string; description: string; instruction_example: string; count_in_sample: number; features: string }[]
  difficulty: { level: string; cefr: string; rationale: string }
  format_notes: { bullets: string; numbering: string; highlight: string; choices: string; passage: string; other: string }
  role_map: Record<string, number>
  choice_marker: string
  suggested_guideline: string
  form_segments?: FormSegment[]
  form_style?: FormStyle
  front_usage?: string
  highlight_color?: string
  template_file_id?: number | null
  format_facts?: any
}

export interface Issue {
  number: number
  severity: 'high' | 'medium' | 'low'
  category: string
  message: string
  suggestion: string
  source: 'rule' | 'model'
  set?: number | string // 양식 모드: 지문 세트 전체 지적이면 그 지문 번호
}

export interface Review {
  summary: string
  score: number
  issues: Issue[]
  answer_distribution: Record<string, number>
  version_id: number
  at: string
  model: string
}

export interface Spec {
  question_count: number
  essay_count?: number
  passage_count?: number
  answer_weights?: 'even' | '345'
  types: { name: string; count: number }[]
  difficulty: string
  extra_instructions: string
  balance_answers: boolean
  title: string
}

export interface Job {
  id: number
  workbook_id: number
  stage: string
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  model: string
  effort: string
  log?: string
  result?: any
  error?: string | null
  progress?: { done: number; total: number; label: string } | null
  created_at: string
  finished_at?: string | null
}

export interface Feedback {
  id: number
  workbook_id: number
  question_number: number | null
  text: string
  status: 'open' | 'applied' | 'dismissed'
  guideline_at?: string | null
  created_at: string
}

export interface Workbook {
  id: number
  project_id: number
  name: string
  description: string
  spec: Spec
  analysis: Analysis | null
  questions: Questions | null
  review: Review | null
  guideline_ids: number[]
  custom_guideline: string
  project: Project
  files: FileSummary[]
  feedback: Feedback[]
  exports: { id: number; kind: string; path: string; name: string; created_at: string }[]
  versions: { id: number; note: string; created_at: string }[]
  jobs: Job[]
  status: StageStatus
  template_file_id: number | null
  template_source: 'project' | 'workbook' | null
  group_id: number | null
  set_index: number | null
  group: { id: number; name: string; sets: { id: number; name: string; set_index: number }[] } | null
  form: {
    block_count: number
    segments: { id: string; instruction: string; choices: number }[]
    front_boxes: number
    boxes: { slot: string; label: string; segment: string | null; segment_instruction: string }[]
  } | null
  allocation: Allocation | null
  project_materials: ProjectFile[]
  passage_count: number
  updated_at: string
}

export interface Guideline {
  id: number
  title: string
  category: string
  content: string
  version: number
  updated_at: string
  project_id: number | null
  base_id: number | null
  /** default: 기본 지침, project: 프로젝트 전용, override: 기본 지침의 프로젝트 수정본 */
  scope: 'default' | 'project' | 'override'
  override_count?: number
}

export interface ModelInfo {
  id: string
  name: string
  description: string
  efforts: string[]
  default_effort: string
}

export interface Settings {
  stages: Record<string, { model: string; effort: string }>
  stage_labels: Record<string, string>
  models: ModelInfo[]
  effort_labels: Record<string, string>
  runner: { ignore_user_config: boolean; timeout_minutes: number; batch_size: number; concurrency: number }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body instanceof FormData) init.body = body
  else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { 'content-type': 'application/json' }
  }
  const res = await fetch('/api' + url, init)
  if (!res.ok) {
    let msg = `요청 실패 (${res.status})`
    try {
      const data = await res.json()
      if (data.detail) msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
  return res.json()
}

export const api = {
  get: <T>(url: string) => request<T>('GET', url),
  post: <T>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  put: <T>(url: string, body: unknown) => request<T>('PUT', url, body),
  del: <T>(url: string) => request<T>('DELETE', url),
}

export const SEMESTERS = ['1학기', '여름방학', '2학기', '겨울방학']
