"""단계별 프롬프트와 출력 스키마, 결과 반영 로직."""

from __future__ import annotations

import json
from typing import Any

from . import checks, db, guidelines
from .hwpx_io import format_summary_text, paragraph_table_text

MARKUP_RULES = """[텍스트 서식 표기 규칙 — 반드시 지킬 것]
- 형광펜(한글 형광펜 서식): ==텍스트==
- 밑줄: __텍스트__
- 굵게: **텍스트**
- 지문의 문단 구분은 줄바꿈(\\n)으로 한다.
- 선택지 문자열에는 ①, (1) 같은 번호를 붙이지 않는다 (출력 시 자동으로 붙는다).
- 발문 앞에 문항 번호를 붙이지 않는다 (출력 시 자동으로 붙는다).
- 어법/어휘 문항에서 밑줄 친 선택 부분은 지문 안에 ①__word__ 처럼 원문자+밑줄로 표시한다."""

MAX_SAMPLE_CHARS = 30_000
MAX_REFERENCE_CHARS = 80_000


def _strict(schema: dict[str, Any]) -> dict[str, Any]:
    """OpenAI 구조화 출력 규칙: 모든 object에 required 전체 + additionalProperties false."""

    if schema.get("type") == "object":
        props = schema.get("properties", {})
        schema["required"] = list(props)
        schema["additionalProperties"] = False
        for v in props.values():
            _strict(v)
    elif schema.get("type") == "array":
        _strict(schema["items"])
    return schema


S = lambda: {"type": "string"}  # noqa: E731
I = lambda: {"type": "integer"}  # noqa: E731

QUESTION = {
    "type": "object",
    "properties": {
        "number": I(),
        "type": S(),
        "difficulty": S(),
        "instruction": S(),
        "passage": S(),
        "kind": {"type": "string", "enum": ["객관식", "서술형"]},
        "choices": {"type": "array", "items": S()},
        "answer": S(),
        "explanation": S(),
        "points": {"type": "number"},
        "rubric": S(),
        "source": S(),
    },
}


ANALYSIS_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "summary": S(),
        "question_types": {"type": "array", "items": {"type": "object", "properties": {
            "name": S(), "description": S(), "instruction_example": S(), "count_in_sample": I(), "features": S()}}},
        "difficulty": {"type": "object", "properties": {"level": S(), "cefr": S(), "rationale": S()}},
        "format_notes": {"type": "object", "properties": {
            "bullets": S(), "numbering": S(), "highlight": S(), "choices": S(), "passage": S(), "other": S()}},
        "role_map": {"type": "object", "properties": {
            "preamble_end": I(), "title": I(), "instruction": I(), "passage": I(), "choice": I(), "answer": I(), "explanation": I()}},
        "choice_marker": {"type": "string", "enum": ["circled", "paren", "digit", "numbering"]},
        "suggested_guideline": S(),
        # 양식(지문 세트형) 템플릿일 때만 채운다. 아니면 []
        "form_segments": {"type": "array", "items": {"type": "object", "properties": {
            "segment_id": S(),
            "type": S(),
            "kind": {"type": "string", "enum": ["객관식", "서술형"]},
            "usage": {"type": "string", "enum": ["use", "skip", "pick-A", "pick-B"]},
            "five_way": {"type": "boolean"},
            "answer_format": S(),
            "notes": S(),
        }}},
        "front_usage": S(),
    },
})

QUESTIONS_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "title": S(),
        "questions": {"type": "array", "items": QUESTION},
        "change_log": {"type": "array", "items": S()},
    },
})

REVIEW_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "summary": S(),
        "score": I(),
        "issues": {"type": "array", "items": {"type": "object", "properties": {
            "number": I(),
            "severity": {"type": "string", "enum": ["high", "medium", "low"]},
            "category": {"type": "string", "enum": ["지침", "서식", "정답", "난이도", "문법", "기타"]},
            "message": S(),
            "suggestion": S(),
        }}},
    },
})

PLAN_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "title": S(),
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "number": I(),
            "kind": {"type": "string", "enum": ["객관식", "서술형"]},
            "type": S(),
            "difficulty": S(),
            "source": S(),
            "point": S(),
        }}},
    },
})

GUIDELINE_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "summary": S(),
        "updates": {"type": "array", "items": {"type": "object", "properties": {
            "guideline_id": I(), "title": S(), "category": S(), "new_content": S(), "reason": S()}}},
        # 자료 설정 변경 제안 — 빈 문자열/0은 '바꾸지 않음'
        "material_updates": {"type": "array", "items": {"type": "object", "properties": {
            "file_ref": S(),
            "scope": {"type": "string", "enum": ["", "range", "reference", "exclude"]},
            "use_mode": {"type": "string", "enum": ["", "verbatim", "paraphrase", "adapt"]},
            "paraphrase_length": {"type": "string", "enum": ["", "same", "shorter", "longer", "custom"]},
            "paraphrase_min_words": I(),
            "paraphrase_max_words": I(),
            "paraphrase_level": S(),
            "paraphrase_note": S(),
            "note": S(),
            "reason": S(),
        }}},
    },
})


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n…(이하 {len(text) - limit}자 생략)"


def _files(workbook_id: int, kind: str) -> list[dict[str, Any]]:
    """문제집 자료 + 프로젝트 자료실 자료 (제외 표시한 것은 빼고)."""

    own = db.query("SELECT * FROM files WHERE workbook_id = ? AND kind = ? ORDER BY id", (workbook_id, kind))
    wb = db.query_one("SELECT project_id FROM workbooks WHERE id = ?", (workbook_id,))
    shared = db.query(
        "SELECT * FROM project_files WHERE project_id = ? AND kind = ? ORDER BY id", (wb["project_id"], kind)
    ) if wb else []
    return [f for f in own + shared if (f.get("scope") or "range") != "exclude"]


def _file_header(f: dict[str, Any], label: str) -> str:
    from .materials import SCOPES, USE_MODES

    tags = []
    if f.get("kind") == "reference":
        tags.append(SCOPES.get(f.get("scope") or "range", ""))
        tags.append(f"지문 사용: {USE_MODES.get(f.get('use_mode') or 'adapt', '')}")
        if (f.get("use_mode") or "adapt") == "paraphrase":
            from .materials import paraphrase_rule

            tags.append(f"패러프레이징 {paraphrase_rule(f.get('paraphrase'))}")
    if f.get("note"):
        tags.append(f"메모: {f['note']}")
    return f"### {label}: {f['orig_name']}" + (f" ({' / '.join(t for t in tags if t)})" if tags else "")


def template_file(workbook_id: int) -> dict[str, Any] | None:
    for f in _files(workbook_id, "sample"):
        if f.get("hwpx_path") and f.get("format"):
            return f
    return None


def form_of(tpl: dict[str, Any] | None) -> dict[str, Any] | None:
    """템플릿이 '지문 세트형 양식'이면 그 구조를 돌려준다 (예전에 올린 파일은 여기서 한 번 인식해 저장)."""

    if not tpl:
        return None
    fmt = tpl.get("format") or {}
    if "form" not in fmt:
        from .hwpx_form import detect_form

        fmt["form"] = detect_form(tpl["hwpx_path"])
        table = "project_files" if "project_id" in tpl else "files"
        db.execute(f"UPDATE {table} SET format_json = ? WHERE id = ?", (db.dumps(fmt), tpl["id"]))
    return fmt.get("form")


def _guideline_text(wb: dict[str, Any]) -> str:
    ids = guidelines.resolve_ids(wb["project_id"], wb.get("guideline_ids") or [])
    parts = []
    if ids:
        marks = ",".join("?" * len(ids))
        for g in db.query(f"SELECT * FROM guidelines WHERE id IN ({marks}) ORDER BY category, id", ids):
            parts.append(f"## [지침 #{g['id']}] {g['title']} ({g['category']})\n{g['content']}")
    if (wb.get("custom_guideline") or "").strip():
        parts.append(f"## [이 문제집 전용 지침]\n{wb['custom_guideline']}")
    return "\n\n".join(parts) or "(선택된 지침 없음 — 샘플 문제지의 스타일을 따른다)"


def _analysis_text(analysis: dict[str, Any] | None) -> str:
    if not analysis:
        return "(분석 결과 없음)"
    keep = {k: analysis.get(k) for k in ("summary", "question_types", "difficulty", "format_notes")}
    return json.dumps(keep, ensure_ascii=False, indent=1)


def _materials(workbook_id: int) -> tuple[str, str]:
    samples = "\n\n".join(f"{_file_header(f, '샘플')}\n{f['text']}" for f in _files(workbook_id, "sample"))
    refs = "\n\n".join(f"{_file_header(f, '참고자료')}\n{f['text']}" for f in _files(workbook_id, "reference"))
    return _clip(samples, MAX_SAMPLE_CHARS), _clip(refs, MAX_REFERENCE_CHARS)


def counts(spec: dict[str, Any]) -> tuple[int, int]:
    """(객관식 수, 서술형 수)"""

    total = int(spec.get("question_count") or 0)
    essay = min(int(spec.get("essay_count") or 0), total)
    return total - essay, essay


def _spec_text(spec: dict[str, Any]) -> str:
    mc, essay = counts(spec)
    lines = [f"- 총 문항 수: {spec.get('question_count') or '샘플과 비슷하게'} (객관식 {mc}, 서술형 {essay})"]
    if essay:
        lines.append(f"- 문항 순서: 객관식 1~{mc}번 다음 서술형 {mc + 1}~{mc + essay}번")
    for t in spec.get("types") or []:
        if t.get("name") and t.get("count"):
            lines.append(f"  - {t['name']}: {t['count']}문항")
    if spec.get("difficulty"):
        lines.append(f"- 목표 난이도: {spec['difficulty']}")
    if spec.get("title"):
        lines.append(f"- 문제지 제목: {spec['title']}")
    if spec.get("extra_instructions"):
        lines.append(f"- 추가 요청: {spec['extra_instructions']}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 프롬프트

def prompt_analyze(wb: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    samples, refs = _materials(wb["id"])
    tpl = template_file(wb["id"])
    fmt_part = "(HWPX 샘플이 없어 서식 정보가 없습니다. role_map은 모두 -1, preamble_end는 0으로 하세요.)"
    if tpl:
        fmt = tpl["format"]
        fmt_part = (
            f"[서식 분석 템플릿 파일: {tpl['orig_name']}]\n"
            f"자동 추출한 서식 사실:\n{format_summary_text(fmt)}\n\n"
            f"문단 목록 (#번호 = 문단 index, 형광펜은 ==, 밑줄은 __, 굵게는 **로 표시):\n{paragraph_table_text(fmt)}"
        )
    form = form_of(tpl)
    form_part = "\n[양식 여부] 이 샘플은 일반 문제지입니다. form_segments는 []로, front_usage는 \"\"로 둡니다."
    if form:
        from .hwpx_form import skeleton_text

        form_part = f"""
[양식(지문 세트형) 템플릿] 이 샘플은 '지문 1개 + 하위 문항 여러 개' 블록이 {form['block_count']}번 반복되는 빈 양식입니다.
아래는 한 블록의 구조입니다(칸 주소, 종류, 현재 문구). [s1]~[s{len(form['segments'])}]가 하위 문항입니다.
{skeleton_text(form)}

form_segments 작성 규칙 (하위 문항마다 하나씩, s1부터 순서대로)
- type: 유형명(주제/제목, 빈칸 추론, 내용 불일치, 글의 순서, 문장 삽입, 어법 선택, 어휘, 어법 오류 개수, 조건 영작 등)
- kind: 선택지 고르기·위치 고르기 등 정답이 정해진 것은 객관식, 쓰기·고치기는 서술형
- five_way: 정답이 ①~⑤, ❶~❺, ⓐ~ⓔ, ① 1개~⑤ 5개처럼 5개 중 하나이면 true (정답 번호 분포 관리 대상)
- usage: 아래 [적용 지침]을 보고 정한다. 지침에 있는 문항은 use, 지침에 없는 문항은 skip.
  지침에 'A 또는 B'처럼 둘 중 하나만 내라고 한 문항들은 같은 택1 묶음(pick-A)으로, 또 다른 택1 묶음이 있으면 pick-B로 한다.
  지침이 없으면 모두 use.
- answer_format: 정답을 양식의 어디에 어떻게 적는지 (예: '선택지 칸 중 정답에 표시', '( A ) ⇒ ( ) 칸에 순서 기호', '바르게 고치기 칸에 고친 단어')
- notes: 지문에 필요한 표시(빈칸, ❶~❺ 위치, ⓐ~ⓔ, ㉠~㉤ 밑줄, (1)[A / B] 등)와 지침의 핵심 요구
- front_usage: 앞쪽 지문별 박스(f.head/f.body)를 무엇에 쓰는지 (예: '지문별 한국어 Logic Flow'). 앞쪽 박스가 없으면 "".
- role_map은 모두 -1, preamble_end는 0으로 둡니다(양식은 칸 채우기 방식으로 출력).

[적용 지침]
{_guideline_text(wb)}
"""
    prompt = f"""당신은 한국 중·고등학교 영어 시험 문제지를 분석하는 전문가입니다.
아래 샘플 문제지를 분석해 JSON으로만 답하세요. 파일을 만들거나 명령을 실행할 필요는 없습니다.

분석할 것
1. question_types: 문제 유형(예: 주제, 제목, 요지, 빈칸, 어법, 어휘, 순서, 문장삽입, 요약, 내용일치, 함축의미 등). 유형별 발문 예시와 특징.
2. difficulty: 전체 난이도(하/중하/중/중상/상), CEFR 수준 추정, 근거(어휘·구문·지문 길이).
3. format_notes: 글머리 기호, 글머리 번호(문단 번호), 형광펜 사용 방식(무엇을 형광펜으로 표시하는지), 선택지 표기, 지문 배치, 기타 서식.
4. role_map: 출력 템플릿으로 쓸 '대표 문단'의 index. 위 문단 목록의 #번호를 사용한다. 없으면 -1.
   - preamble_end: 문제지 머리(학교명·제목·이름 칸 등)가 끝나고 첫 문항이 시작하는 문단 index. 머리 영역이 없으면 0.
   - title: 제목 문단, instruction: 발문(문항 번호+질문) 문단, passage: 지문 문단(지문이 표/박스 안에 있으면 그 [table]/[box] 문단),
     choice: 선택지 한 줄 문단, answer: 정답 표기 문단, explanation: 해설 문단.
5. choice_marker: 선택지 번호 방식. 텍스트 원문자(①)면 circled, (1)이면 paren, 1.이면 digit, 문단 번호 기능이면 numbering.
6. suggested_guideline: 이 샘플 스타일을 재현하기 위한 출제·서식 지침 초안(마크다운, 10줄 내외).
{form_part}

{fmt_part}

[샘플 본문 텍스트]
{samples or '(없음)'}

[참고자료(요약용, 앞부분만)]
{_clip(refs, 4000) or '(없음)'}
"""
    return prompt, ANALYSIS_SCHEMA


WRITING_RULES = """[문항 작성 규칙]
- 공통 필드: number(문제지 전체 번호), kind(객관식/서술형), type(유형명), difficulty(하/중/상),
  instruction(발문, 한국어), passage(지문/영문, 없으면 ""), explanation(한국어 해설),
  source(지문 출처: 참고자료 제목/쪽 등, 창작이면 "자체 제작"), points(배점, 모르면 0).
- 객관식: choices 5개, answer는 "1"~"5", rubric은 "". 정답은 유일하고 오답은 그럴듯하되 명백히 틀려야 한다.
  explanation에는 정답 근거와 주요 오답의 오류 이유를 쓴다.
- 서술형: choices는 [], answer에는 모범답안, rubric에는 채점 기준(부분 점수 포함, 줄바꿈으로 항목 구분),
  instruction에는 조건(단어 수, 사용할 어휘, 어법 조건 등)을 분명히 적는다. 모범답안이 조건을 모두 만족해야 한다.
- 참고자료가 있으면 그 지문을 활용한다. 자료마다 표시된 '지문 사용' 방식(원문 그대로/패러프레이징/일부 변형 허용)과 메모를 반드시 따른다.
  '참고만' 자료는 지문으로 쓰지 않고 배경·어휘 참고용으로만 쓴다. 참고자료의 사실과 다른 내용을 만들지 않는다.
- 샘플의 형광펜/밑줄/굵게 사용 방식을 그대로 따른다."""


def _answer_plan_text(numbers: list[int], answers: list[int]) -> str:
    if not numbers:
        return ""
    return "[정답 번호 배치 — 객관식은 이 정답 번호가 되도록 선택지를 배열]\n" + ", ".join(
        f"{n}번→{a}" for n, a in zip(numbers, answers)
    )


def prompt_generate(wb: dict[str, Any], answer_map: dict[int, int]) -> tuple[str, dict[str, Any]]:
    """문항 수가 적을 때: 한 번에 전부 제작."""

    spec = wb.get("spec") or {}
    samples, refs = _materials(wb["id"])
    nums = sorted(answer_map)
    prompt = f"""당신은 한국 중·고등학교 영어 시험 출제 전문가입니다.
아래 지침, 샘플 분석, 참고자료를 바탕으로 새 영어 문제지를 제작해 JSON으로만 답하세요.
파일을 만들거나 명령을 실행할 필요는 없습니다. change_log 에는 [] 를 넣습니다.

[제작 설정]
{_spec_text(spec)}

[출제 지침]
{_guideline_text(wb)}

[샘플 분석 결과]
{_analysis_text(wb.get('analysis'))}

{MARKUP_RULES}

{WRITING_RULES}

{_answer_plan_text(nums, [answer_map[n] for n in nums])}

[샘플 문제지 텍스트 — 스타일 참고용]
{samples or '(없음)'}

[참고자료]
{refs or '(없음 — 지침에 맞게 지문을 창작)'}
"""
    return prompt, QUESTIONS_SCHEMA


def prompt_plan(wb: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """문항 수가 많을 때: 먼저 문항별 출제 계획표를 만든다."""

    spec = wb.get("spec") or {}
    samples, refs = _materials(wb["id"])
    prompt = f"""당신은 한국 중·고등학교 영어 시험 출제 책임자입니다.
문제지 전체의 '출제 계획표'를 JSON으로만 만드세요. 실제 문항은 다른 출제자들이 이 계획표를 나눠 받아 작성합니다.
파일을 만들거나 명령을 실행할 필요는 없습니다.

계획표 작성 규칙
- items에는 1번부터 마지막 번호까지 빠짐없이 한 문항씩 넣는다.
- kind: 객관식/서술형. 제작 설정의 객관식·서술형 수와 순서를 정확히 지킨다.
- type: 유형명. 유형별 문항 수 설정이 있으면 정확히 맞춘다.
- source: 이 문항에 쓸 지문. 참고자료의 제목과 위치(과/쪽/문단)와 첫 문장 일부를 적어 출제자가 찾을 수 있게 한다.
  참고자료가 없으면 창작할 지문의 주제를 적는다. 한 지문을 여러 문항에 쓰더라도 출제 포인트는 겹치지 않게 한다.
- point: 출제 포인트(무엇을 묻는지, 오답 설계 방향, 서술형이면 조건과 평가 요소)를 1~2문장으로.
- difficulty: 하/중/상. 목표 난이도에 맞게 배분한다.
- 같은 유형이 연달아 몰리지 않게, 지문과 출제 포인트가 고르게 퍼지게 한다.

[제작 설정]
{_spec_text(spec)}

[출제 지침]
{_guideline_text(wb)}

[샘플 분석 결과]
{_analysis_text(wb.get('analysis'))}

[샘플 문제지 텍스트 — 스타일 참고용]
{_clip(samples, 12000) or '(없음)'}

[참고자료]
{refs or '(없음 — 지문을 창작)'}
"""
    return prompt, PLAN_SCHEMA


def _plan_table(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"- {it['number']}번 [{it['kind']}/{it['type']}/{it.get('difficulty', '')}] 지문: {it['source']} | 포인트: {it['point']}"
        + (f" | 정답 번호: {it['answer']}" if it.get("answer") else "")
        for it in items
    )


def _assigned_text(batch: list[dict[str, Any]]) -> str:
    from .materials import USE_MODE_RULES, USE_MODES, paraphrase_rule, word_count

    parts = []
    for it in batch:
        mode = it.get("use_mode") or "adapt"
        extra = f"\n패러프레이징 규칙 — {paraphrase_rule(it.get('paraphrase'), word_count(it['passage_text']))}" if mode == "paraphrase" else ""
        parts.append(
            f"#### {it['number']}번용 본문 — {it.get('file_name', '')} · {it['source']}\n"
            f"지문 사용 방식: {USE_MODES[mode]} — {USE_MODE_RULES[mode]}{extra}\n"
            f"<<<\n{it['passage_text']}\n>>>"
        )
    return "\n\n".join(parts)


def prompt_generate_batch(wb: dict[str, Any], plan: dict[str, Any], batch: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """계획표의 일부(묶음)만 실제 문항으로 작성한다."""

    samples, refs = _materials(wb["id"])
    assigned = all(it.get("passage_text") for it in batch)
    nums = [it["number"] for it in batch]
    prompt = f"""당신은 한국 중·고등학교 영어 시험 출제 전문가입니다.
문제지 전체 출제 계획표 중에서 **{nums[0]}~{nums[-1]}번({len(nums)}문항)**만 실제 문항으로 작성해 JSON으로만 답하세요.
questions에는 정확히 {', '.join(map(str, nums))}번 문항만 계획표 순서대로 넣습니다. title은 "{plan.get('title', '')}", change_log는 [].
파일을 만들거나 명령을 실행할 필요는 없습니다.

[내가 작성할 문항 — 계획표대로, 정답 번호도 지정대로]
{_plan_table(batch)}

[전체 계획표 — 다른 문항과 지문·포인트가 겹치지 않도록 참고만]
{_plan_table([{k: v for k, v in it.items() if k != 'answer'} for it in plan['items']])}

[출제 지침]
{_guideline_text(wb)}

[샘플 분석 결과]
{_analysis_text(wb.get('analysis'))}

{MARKUP_RULES}

{WRITING_RULES}

[샘플 문제지 텍스트 — 스타일 참고용]
{_clip(samples, 12000) or '(없음)'}

{('[지정 본문 — 각 문항은 반드시 자기 번호에 지정된 본문으로 출제]' + chr(10) + _assigned_text(batch)) if assigned else ('[참고자료]' + chr(10) + (refs or '(없음 — 계획표의 주제로 지문을 창작)'))}
"""
    return prompt, QUESTIONS_SCHEMA


def prompt_review(wb: dict[str, Any], rule_result: dict[str, Any], questions: list[dict[str, Any]] | None = None) -> tuple[str, dict[str, Any]]:
    """문항 검수. questions를 주면 그 문항들만(묶음 검수) 본다."""

    _, refs = _materials(wb["id"])
    items = questions if questions is not None else (wb.get("questions") or {}).get("questions", [])
    scope = f"{items[0]['number']}~{items[-1]['number']}번 문항" if questions is not None and items else "문제지 전체"
    prompt = f"""당신은 영어 시험 문제지 검수 전문가입니다. 아래 {scope}을(를) 꼼꼼히 검수하고 JSON으로만 답하세요.

검수 항목
1. 지침 준수: 출제 지침의 각 항목을 지켰는가 (category=지침)
2. 서식 준수: 샘플 서식(형광펜/밑줄/굵게 사용 방식, 발문 형식, 선택지 형식)을 지켰는가 (category=서식)
3. 정답: 객관식은 정답이 유일하고 맞는가, 오답이 확실히 틀렸는가.
   서술형은 모범답안이 발문의 조건을 모두 만족하는가, 채점 기준이 명확하고 배점과 맞는가 (category=정답)
4. 난이도: 목표 난이도에 맞는가 (category=난이도)
5. 영어 문법·철자·자연스러움 (category=문법)
6. 해설의 정확성, 참고자료와의 사실 일치 등 (category=기타)
문제가 없으면 issues를 비운다. number는 문항 번호(전체에 해당하면 0). score는 0~100 종합 점수.
규칙 기반 검사에서 이미 찾은 항목은 반복하지 않아도 된다.

[제작 설정]
{_spec_text(wb.get('spec') or {})}

[출제 지침]
{_guideline_text(wb)}

[샘플 분석 결과]
{_analysis_text(wb.get('analysis'))}

{MARKUP_RULES}

[규칙 기반 검사 결과]
{json.dumps(rule_result, ensure_ascii=False)}

[검수할 문항 JSON]
{json.dumps(items, ensure_ascii=False, indent=1)}

[참고자료]
{_clip(refs, 40000) or '(없음)'}
"""
    return prompt, REVIEW_SCHEMA


def prompt_review_global(wb: dict[str, Any], rule_result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """묶음 검수와 함께 도는 '문제지 전체' 점검: 문항 간 중복·배분·전체 난이도만 본다."""

    items = (wb.get("questions") or {}).get("questions", [])
    brief = "\n".join(
        f"{q['number']}. [{q.get('kind', '객관식')}/{q.get('type')}/{q.get('difficulty')}] {q.get('instruction', '')[:60]} | 지문: {(q.get('passage') or '')[:90]} | 정답: {str(q.get('answer', ''))[:30]}"
        for q in items
    )
    prompt = f"""당신은 영어 시험 문제지 총괄 검수자입니다. 개별 문항의 세부 검수는 다른 검수자가 하고 있으니,
'문제지 전체' 관점의 문제만 찾아 JSON으로만 답하세요.
- 문항 간 지문·출제 포인트·선택지 중복, 한 문항이 다른 문항의 답을 알려 주는 경우
- 유형·난이도 배분이 제작 설정과 맞는지, 전체 난이도 흐름
- summary에는 문제지 전체에 대한 종합 평가를, score에는 0~100 점수를 쓴다. number는 관련 문항 번호(전체면 0).

[제작 설정]
{_spec_text(wb.get('spec') or {})}

[규칙 기반 검사 결과]
{json.dumps(rule_result, ensure_ascii=False)}

[문항 요약]
{brief}
"""
    return prompt, REVIEW_SCHEMA


def prompt_revise(wb: dict[str, Any], requests: list[str], questions: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """수정: 주어진 문항들 중 고친 문항만 돌려받는다."""

    _, refs = _materials(wb["id"])
    nums = ", ".join(str(q["number"]) for q in questions)
    prompt = f"""당신은 영어 시험 출제 전문가입니다. 아래 문항들({nums}번)을 수정 요청에 따라 고치세요.
- questions에는 '실제로 고친 문항만' 전체 필드를 채워 넣습니다. number는 원래 번호 그대로. 고칠 것이 없으면 [].
- 요청과 무관한 부분은 바꾸지 않습니다. 객관식 정답 번호는 요청이 없는 한 유지합니다.
- change_log에는 무엇을 어떻게 고쳤는지 한 줄씩 적습니다. title은 "{(wb.get('questions') or {}).get('title', '')}".

[수정 요청]
{chr(10).join('- ' + r for r in requests)}

[출제 지침]
{_guideline_text(wb)}

{MARKUP_RULES}

{WRITING_RULES}

[대상 문항 JSON]
{json.dumps(questions, ensure_ascii=False, indent=1)}

[참고자료]
{_clip(refs, 40000) or '(없음)'}
"""
    return prompt, QUESTIONS_SCHEMA


def prompt_guideline(wb: dict[str, Any], feedback: list[str]) -> tuple[str, dict[str, Any]]:
    ids = guidelines.resolve_ids(wb["project_id"], wb.get("guideline_ids") or [])
    guides = db.query(f"SELECT * FROM guidelines WHERE id IN ({','.join('?' * len(ids))})", ids) if ids else []
    gtext = "\n\n".join(f"### guideline_id={g['id']} | {g['title']} ({g['category']})\n{g['content']}" for g in guides) or "(없음)"
    prompt = f"""당신은 영어 문제 출제 지침을 관리하는 편집자입니다.
사용자 피드백 중 '앞으로도 계속 적용해야 할 일반 원칙'을 찾아 출제 지침에 반영하는 수정안을 JSON으로 제안하세요.
- 기존 지침을 고치는 경우 guideline_id에 그 id를 넣고, new_content에는 수정된 '전체 지침 내용'을 넣습니다.
- 새 지침이 필요하면 guideline_id=0으로 하고 title/category/new_content를 채웁니다.
- 이 문제집에만 해당하는 일회성 요청은 반영하지 않습니다. 반영할 것이 없으면 updates를 비웁니다.
- reason에는 어떤 피드백 때문에 무엇을 바꿨는지 적습니다.

[사용자 피드백]
{chr(10).join('- ' + f for f in feedback)}

[현재 지침]
{gtext}

[이 문제집 전용 지침]
{wb.get('custom_guideline') or '(없음)'}

[자료 설정 — 자료를 '어떻게 쓰는지'에 대한 피드백은 지침이 아니라 여기를 바꾸도록 material_updates로 제안]
{_materials_settings_text(wb)}

material_updates 작성 규칙
- 피드백이 특정 자료의 사용 방식(원문 그대로/패러프레이징/일부 변형), 패러프레이징 분량·난이도·세부 지시, 출제 범위 포함 여부에 관한 것이면
  지침 대신(또는 지침과 함께) 해당 자료의 설정 변경을 제안합니다. file_ref는 위 목록의 [ref] 값을 그대로 씁니다.
- 바꾸지 않는 항목은 빈 문자열("") 또는 0으로 둡니다.
- 값의 의미: scope range=출제 범위, reference=참고만, exclude=제외 / use_mode verbatim=원문 그대로, paraphrase=패러프레이징, adapt=일부 변형 허용
  / paraphrase_length same=원문과 비슷하게, shorter=짧게, longer=길게, custom=단어 수 지정(paraphrase_min_words·max_words 사용)
  / paraphrase_level: same, easier, harder, 고1-하, 고1-중, 고1-상, 고2-하, 고2-중, 고2-상, 고3-하, 고3-중, 고3-상, 수능 중 하나
  / paraphrase_note: 패러프레이징 메모 전체(기존 메모를 바꿀 때만) / note: 자료 메모 전체(바꿀 때만)
- 해당 사항이 없으면 material_updates를 비웁니다.
"""
    return prompt, GUIDELINE_SCHEMA


def material_refs(wb: dict[str, Any]) -> list[dict[str, Any]]:
    """지침 제안에서 다룰 자료 목록. ref: 'p:<id>'(프로젝트 자료실) / 'w:<id>'(이 문제집 자료)"""

    out = []
    for f in db.query("SELECT * FROM project_files WHERE project_id = ? AND kind = 'reference' ORDER BY id", (wb["project_id"],)):
        out.append({**f, "ref": f"p:{f['id']}", "where": "프로젝트 자료실"})
    for f in db.query("SELECT * FROM files WHERE workbook_id = ? AND kind = 'reference' ORDER BY id", (wb["id"],)):
        out.append({**f, "ref": f"w:{f['id']}", "where": "이 문제집"})
    return out


def _materials_settings_text(wb: dict[str, Any]) -> str:
    from .materials import SCOPES, USE_MODES, paraphrase_cfg, paraphrase_rule

    rows = []
    for f in material_refs(wb):
        mode = f.get("use_mode") or "adapt"
        line = (f"- [ref={f['ref']}] {f['orig_name']} ({f['where']}) | 범위: {SCOPES.get(f.get('scope') or 'range')} | "
                f"지문 사용: {USE_MODES.get(mode)}")
        if mode == "paraphrase":
            cfg = paraphrase_cfg(f.get("paraphrase"))
            line += f" | 패러프레이징: length={cfg['length']}, level={cfg['level']} ({paraphrase_rule(cfg)})"
        if f.get("note"):
            line += f" | 메모: {f['note']}"
        rows.append(line)
    return "\n".join(rows) or "(참고자료 없음)"
