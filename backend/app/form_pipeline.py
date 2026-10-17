"""양식(지문 세트형) 모드의 프롬프트·스키마·데이터 변환.

문제집 데이터 (questions_json)
    {"mode": "form", "title": ..., "sets": [세트...], "questions": [평탄화한 문항...]}
세트
    {"index": 1, "passage_id": 12, "label": "...", "passage": "변형 지문(표시 포함)", "logic_flow": ["...", ...],
     "items": [{"segment_id": "s1", "type", "kind", "instruction", "choices", "answer", "explanation", "points", "extra"}],
     "layout": {"hash": ..., "fills": {...}, "remove_segments": [...]}}
문항 화면·검수·피드백은 기존처럼 평탄화한 questions를 쓰고, 저장할 때 세트로 되돌린다.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from typing import Any

from . import db
from .pipeline import MARKUP_RULES, _analysis_text, _guideline_text, _materials, _strict, _clip, form_of, template_file

S = lambda: {"type": "string"}  # noqa: E731

ITEM = {
    "type": "object",
    "properties": {
        "segment_id": S(),
        "type": S(),
        "kind": {"type": "string", "enum": ["객관식", "서술형"]},
        "instruction": S(),
        "choices": {"type": "array", "items": S()},
        "answer": S(),
        "explanation": S(),
        "points": {"type": "number"},
        "extra": S(),
    },
}

SET_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "label": S(),
        "passage": S(),
        "logic_flow": {"type": "array", "items": S()},
        "items": {"type": "array", "items": ITEM},
        "change_log": {"type": "array", "items": S()},
    },
})

LAYOUT_SCHEMA = _strict({
    "type": "object",
    "properties": {
        "fills": {"type": "array", "items": {"type": "object", "properties": {"slot": S(), "text": S()}}},
    },
})


# ---------------------------------------------------------------- 양식 정보

def form_context(wb: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """(양식 구조, 분석에서 정한 하위 문항 설정 목록)."""

    form = form_of(template_file(wb["id"]))
    segs = ((wb.get("analysis") or {}).get("form_segments") or []) if form else []
    if form and not segs:
        segs = [{"segment_id": s["id"], "type": s["instruction"][:20], "kind": "객관식" if s["choice_slots"] else "서술형",
                 "usage": "use", "five_way": len(s["choice_slots"]) == 5, "answer_format": "", "notes": ""} for s in form["segments"]]
    return form, segs


def is_form(wb: dict[str, Any]) -> bool:
    return bool(form_context(wb)[0])


def used_segments(segs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in segs if s.get("usage") != "skip"]


def answer_plan(n_sets: int, segs: list[dict[str, Any]], weights: list[float] | None, seed: int | None = None) -> list[dict[str, int]]:
    """세트마다 {segment_id: 정답 번호}. 5개 중 하나를 고르는 문항(택1 묶음 제외)에 대해 가중치대로 고르게 배치."""

    targets = [s["segment_id"] for s in segs if s.get("usage") == "use" and s.get("five_way")]
    total = n_sets * len(targets)
    if not total:
        return [{} for _ in range(n_sets)]
    w = weights or [1, 1, 1, 1, 1]
    raw = [total * x / sum(w) for x in w]
    counts = [int(r) for r in raw]
    for i in sorted(range(5), key=lambda i: raw[i] - counts[i], reverse=True)[: total - sum(counts)]:
        counts[i] += 1
    seq = [i + 1 for i in range(5) for _ in range(counts[i])]
    rng = random.Random(seed)
    for _ in range(300):
        rng.shuffle(seq)
        if all(not (seq[i] == seq[i - 1] == seq[i - 2]) for i in range(2, len(seq))):
            break
    it = iter(seq)
    return [{sid: next(it) for sid in targets} for _ in range(n_sets)]


WEIGHT_PRESETS = {"even": [1, 1, 1, 1, 1], "345": [1, 1, 1.25, 1.25, 1.25]}


# ---------------------------------------------------------------- 평탄화 / 되돌리기

def flatten(sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    n = 0
    for st in sets:
        for it in st.get("items", []):
            n += 1
            out.append({
                "number": n,
                "set": st["index"],
                "segment_id": it.get("segment_id"),
                "type": it.get("type", ""),
                "difficulty": it.get("difficulty", ""),
                "kind": it.get("kind", "객관식"),
                "instruction": it.get("instruction", ""),
                "passage": "",
                "choices": it.get("choices") or [],
                "answer": it.get("answer", ""),
                "explanation": it.get("explanation", ""),
                "points": it.get("points", 0),
                "rubric": it.get("extra", ""),
                "extra": it.get("extra", ""),
                "source": st.get("label", ""),
                "passage_id": st.get("passage_id"),
            })
    return out


def sync_sets(data: dict[str, Any]) -> dict[str, Any]:
    """화면에서 고친 평탄 문항(questions)을 세트(items)에 되돌려 반영한다."""

    sets = data.get("sets") or []
    by_set: dict[int, list[dict[str, Any]]] = {}
    for q in data.get("questions") or []:
        by_set.setdefault(int(q.get("set") or 0), []).append(q)
    for st in sets:
        qs = by_set.get(st["index"], [])
        if not qs:
            continue
        st["items"] = [{
            "segment_id": q.get("segment_id"),
            "type": q.get("type", ""),
            "kind": q.get("kind", "객관식"),
            "instruction": q.get("instruction", ""),
            "choices": q.get("choices") or [],
            "answer": q.get("answer", ""),
            "explanation": q.get("explanation", ""),
            "points": q.get("points", 0),
            "extra": q.get("extra") if q.get("extra") is not None else q.get("rubric", ""),
        } for q in qs]
    data["questions"] = flatten(sets)
    return data


LAYOUT_RULES_VERSION = 3  # 배치 규칙이 바뀌면 올려서 기존 배치를 다시 만들게 한다


def content_hash(st: dict[str, Any], style: dict[str, Any] | None = None) -> str:
    """배치(Codex)를 다시 해야 하는지 판단하는 값 — 내용과, 배치 프롬프트에 영향을 주는 서식 설정만 포함."""

    s = style or {}
    keep = {k: st.get(k) for k in ("label", "passage", "logic_flow", "items", "index")} | {
        "v": LAYOUT_RULES_VERSION, "hh": s.get("header_highlight"), "kw": (s.get("front_body") or {}).get("keyword_mark")}
    return hashlib.sha1(json.dumps(keep, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- 프롬프트

FORM_MARKUP = """[지문·선택지 표기 규칙]
- 형광펜 ==텍스트==, 밑줄 __텍스트__, 굵게 **텍스트**. 문단 구분은 줄바꿈(\\n).
- 빈칸은 밑줄 10개 '__________'. 순서 문항이 있으면 지문을 (A) 문단 다음 (B)(C)(D) 문단으로 섞어 제시하고 각 문단 앞에 (A)~(D)를 붙인다.
- 삽입 위치는 ( ❶ )~( ❺ ), 어휘는 ⓐ~ⓔ 를 해당 단어 바로 앞에, 어법 밑줄은 ㉠__단어__ 처럼, 어법 선택은 (1)[A / B] 처럼 지문 안에 표시한다.
- 선택지 문자열에 ①, (1) 같은 번호를 붙이지 않는다 (양식의 자동 번호가 붙는다).
- 정답 표시(형광펜·흰 글씨 등)는 이 단계에서 절대 하지 않는다. 지침의 '정답 표시' 규칙은 나중에 양식에 배치할 때 적용한다.
  지문·선택지·answer·extra 어디에도 ==정답== 처럼 정답을 드러내는 표시를 넣지 않는다. 정답은 answer(와 필요하면 extra)에 평문으로만 적는다."""

ANSWER_MARK = re.compile(r"==|\*\*|!!")


def clean_item(it: dict[str, Any]) -> dict[str, Any]:
    """정답이 내용에 표시돼 새어 나가지 않도록 answer/extra/choices의 형광펜·굵게 표시를 지운다."""

    it["answer"] = ANSWER_MARK.sub("", str(it.get("answer", "")))
    # 선택지가 5개인 문항은 정답을 '1'~'5' 숫자로 통일한다 (㉣, ❹, ⓒ 등 기호로 와도)
    from .checks import answer_index

    idx = answer_index(it["answer"])
    if len(it.get("choices") or []) == 5 and idx and 1 <= idx <= 5:
        it["answer"] = str(idx)
    it["extra"] = ANSWER_MARK.sub("", it.get("extra", ""))
    it["choices"] = [c.replace("==", "") for c in it.get("choices") or []]
    return it


def clean_passage(text: str) -> str:
    """지문 안 어법 선택 [A / B] 속 형광펜(정답 표시)을 지운다."""

    return re.sub(r"\[[^\]\n]*\]", lambda m: m.group(0).replace("==", "").replace("**", ""), text or "")


def _segment_spec(form: dict[str, Any], segs: list[dict[str, Any]]) -> str:
    from .hwpx_form import skeleton_text

    used = used_segments(segs)
    lines = []
    for s in used:
        usage = {"use": "반드시 출제", "pick-A": "택1 묶음 A (묶음에서 하나만 출제)", "pick-B": "택1 묶음 B (묶음에서 하나만 출제)"}[s["usage"]]
        lines.append(f"- {s['segment_id']} | {s['type']} | {s['kind']} | {usage} | 정답 표기: {s.get('answer_format', '')} | {s.get('notes', '')}")
    return "\n".join(lines) + "\n\n[양식 블록 구조 — 참고용]\n" + skeleton_text(form, [s["segment_id"] for s in used])


def prompt_set(wb: dict[str, Any], form: dict[str, Any], segs: list[dict[str, Any]], passage: dict[str, Any], index: int, answers: dict[str, int], others: list[str]) -> tuple[str, dict[str, Any]]:
    from .materials import USE_MODE_RULES, USE_MODES, paraphrase_rule, word_count

    mode = passage.get("use_mode") or "adapt"
    rule = USE_MODE_RULES[mode] + (f"\n패러프레이징 규칙 — {paraphrase_rule(passage.get('paraphrase'), word_count(passage['text']))}" if mode == "paraphrase" else "")
    plan = ", ".join(f"{k}→{v}번" for k, v in answers.items()) or "(지정 없음)"
    samples, _ = _materials(wb["id"])
    prompt = f"""당신은 한국 고등학교 영어 내신 자료(KSC 등) 출제 전문가입니다.
아래 '지문 1개'로 양식의 하위 문항들을 모두 만들어 JSON으로만 답하세요. 파일을 만들거나 명령을 실행할 필요는 없습니다.
이 문제지의 {index}번째 지문 세트입니다.

[작업 순서]
1. 지침과 '지문 사용 방식'에 따라 지문을 변형한다(passage). 이때 아래 하위 문항에 필요한 표시를 지문 하나에 모두 설계해 넣는다
   (빈칸, 삽입 위치, ⓐ~ⓔ, ㉠~㉤, (1)[A / B], (A)~(D) 문단 등). 문항끼리 힌트를 주지 않게 배치한다.
2. logic_flow: 양식 앞쪽 박스에 넣을 지문의 흐름(지침에 언어·형식이 정해져 있으면 따른다). 한 줄에 한 단계, 화살표는 넣지 않는다.
3. items: 아래 하위 문항마다 하나씩(택1 묶음은 묶음에서 하나만). segment_id에 그 문항의 id를 넣는다.
   - instruction: 양식의 발문 문구를 그대로 쓰되 빈 자리(예: '(1) ~ ()', '총 점')만 채운다.
   - choices: 선택지가 ①~⑤ 칸인 문항만 5개, 나머지는 [].
   - answer: 정답(객관식은 '1'~'5' 또는 정답 기호, 서술형은 모범답안). 정답 번호 지정이 있으면 반드시 따른다.
   - extra: 문항에 딸린 나머지 내용(삽입할 주어진 문장, <조건> 목록, <보기> 단어, 바르게 고치기 정답, 어법 선택 각 번호의 정답 등)을 사람이 읽을 수 있게.
   - explanation: 한국어 해설. points: 양식에 적힌 배점(없으면 0).
4. label: 블록 머리에 넣을 출처 표기(예: '[올림포스 영어독해 기본2] Unit 11-01 Analysis'처럼 양식 머리 문구 형식을 따름).
change_log는 [].

[정답 번호 지정 — 5개 중 하나를 고르는 문항]
{plan}

[하위 문항 목록]
{_segment_spec(form, segs)}

[출제 지침]
{_guideline_text(wb)}

[샘플 분석]
{_analysis_text(wb.get('analysis'))}

{FORM_MARKUP}

[원문 지문 — {passage.get('file_name', '')} · {passage['label']}]
지문 사용 방식: {USE_MODES[mode]} — {rule}
<<<
{passage['text']}
>>>

[같은 문제지의 다른 지문 — 겹치지 않게 참고만]
{chr(10).join('- ' + o for o in others) or '(없음)'}

[샘플 양식 텍스트 — 참고용]
{_clip(samples, 6000)}
"""
    return prompt, SET_SCHEMA


def style_of(wb: dict[str, Any]) -> dict[str, Any]:
    from .hwpx_form import form_style

    return form_style((wb.get("analysis") or {}).get("form_style"))


def segment_order(wb: dict[str, Any]) -> list[str]:
    """분석의 '양식 구성' 목록 순서 = 출력할 하위 문항 순서."""

    return [s["segment_id"] for s in ((wb.get("analysis") or {}).get("form_segments") or [])]


def prompt_layout(wb: dict[str, Any], form: dict[str, Any], segs: list[dict[str, Any]], st: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from .hwpx_form import skeleton_text

    used_ids = [it["segment_id"] for it in st.get("items", [])]
    style = style_of(wb)
    header_rule = ("양식처럼 출처 부분에 형광펜(==...==)을 쓴다." if style["header_highlight"]
                   else "형광펜(==)은 쓰지 않는다(출처 표기에 형광펜 금지).")
    keyword_rule = ("\n  각 단계 줄에서 핵심어(1~3개 낱말)를 {{!핵심어}} 로 감싼다(교사용은 정답 서식, 학생용은 빈칸이 되어 채우기 활동이 된다). '↓' 줄은 감싸지 않는다."
                    if style["front_body"].get("keyword_mark") else "")
    prompt = f"""당신은 한글(HWPX) 양식에 문제 내용을 배치하는 편집자입니다. 아래 '지문 세트' 내용을 양식 블록의 칸에 넣을 텍스트를 JSON으로만 답하세요.
fills에는 바꿀 칸만 {{"slot": 칸 주소, "text": 넣을 텍스트}}로 넣습니다. 적지 않은 칸은 양식 문구가 그대로 남습니다.

[배치 규칙]
- b0(블록 머리): 양식 머리 문구 형식을 유지해 '[{st['index']}] ' + 출처 표기로 바꾼다. {header_rule}
- 지문 상자 칸: 변형 지문 전체(문단은 줄바꿈). 지문 안의 표기(빈칸, ❶~❺, ⓐ~ⓔ, ㉠__ __, (1)[A / B], (A)~(D))는 그대로.
  어법 선택 (1)[A / B] 의 정답 쪽은 지문 안에서 {{{{정답}}}} 으로 감싼다(예: (1)[{{{{was}}}} / were]).
- 발문 칸: 문항의 instruction (양식 문구와 같으면 생략 가능).
- 정답 표시는 세 가지다. 학생용 출력에서는 {{{{?…}}}}, {{{{!…}}}} 안의 내용이 지워지므로 정답이 새지 않게 정확히 구분한다.
  {{{{…}}}}  : 학생에게도 인쇄되는 내용 중 정답 (정답 선택지 텍스트, ❶~❺·ⓐ~ⓔ·'① 1개' 줄의 정답 기호, 지문 속 [A / B]의 정답 쪽)
  {{{{?…}}}} : 학생이 써 넣어야 하는 답 (순서 답 칸, 바르게 고치기 답, 어법 선택 답란 등) — 학생용에서는 빈칸이 된다
  {{{{!…}}}} : 써 넣는 답 중 지침이 흰 글씨 등으로 숨기라고 한 것(논술형·서술형 모범답안, 바르게 고치기 답 등)
    — 출력 서식(형광펜·굵게·밑줄·흰 글씨 조합)은 앱 설정이 정하므로 따로 표시하지 않는다
- 선택지 칸(자동 번호): 선택지 텍스트만, 번호 없이. 정답 선택지는 {{{{정답 텍스트}}}} 로 감싼다.
- 답 칸: 양식 문구('( A ) ⇒', '바르게 고치기 :', '(2점)', '⇒' 등)는 그대로 두고 답만 {{{{?…}}}} 또는 {{{{!…}}}} 로 감싸 넣는다.
  괄호·화살표 같은 양식 기호는 감싸지 않는다. 예: '( A ) ⇒ ( {{{{?B}}}} ) ⇒ ( {{{{?D}}}} ) ⇒ ( {{{{?C}}}} )'
  답의 일부라도(예: '틀린 단어 → 고친 단어'의 틀린 단어) 학생에게 보이면 안 되는 내용은 모두 감싼다.
  ❶~❺ / ⓐ~ⓔ / '① 1개 …' 처럼 기호가 나열된 줄은 기호는 그대로 두고 정답 기호만 {{{{기호}}}} 로 감싼다.
- 서술형 질문 문장처럼 학생이 봐야 하는 내용은 감싸지 않는다.
- 삽입 문항의 주어진 문장 상자, <조 건>/<보 기> 상자: 첫 줄의 제목(**<조 건>** 등)을 유지하고 다음 줄부터 내용.
- f.head: 앞쪽 박스 머리. 양식 예시처럼 '[{st['index']}] ' + 짧은 출처{'' if style['header_highlight'] else ' (형광펜 없이)'}. f.body: logic_flow를 한 줄씩, 단계 사이에 '↓' 줄을 넣어.{keyword_rule}
- 텍스트 서식 표기: {MARKUP_RULES.splitlines()[1]} / {MARKUP_RULES.splitlines()[2]} / {MARKUP_RULES.splitlines()[3]}

[출제 지침 — 정답 표시 규칙 확인용]
{_guideline_text(wb)}

[양식 블록 구조 (이 세트에서 쓰는 하위 문항만)]
{skeleton_text(form, used_ids)}

[지문 세트 내용]
{json.dumps({k: st.get(k) for k in ('index', 'label', 'passage', 'logic_flow', 'items')}, ensure_ascii=False, indent=1)}
"""
    return prompt, LAYOUT_SCHEMA


def prompt_set_revise(wb: dict[str, Any], form: dict[str, Any], segs: list[dict[str, Any]], st: dict[str, Any], requests: list[str], source_text: str) -> tuple[str, dict[str, Any]]:
    prompt = f"""당신은 영어 내신 자료 출제 전문가입니다. 아래 지문 세트를 수정 요청에 따라 고쳐 '세트 전체'를 JSON으로 다시 출력하세요.
요청과 무관한 부분은 바꾸지 않습니다. 지문을 고치면 그 지문을 쓰는 다른 문항(빈칸, 표시 위치 등)도 맞게 고칩니다.
5개 중 하나를 고르는 문항의 정답 번호는 요청이 없는 한 유지합니다. change_log에는 고친 내용을 한 줄씩 적습니다.

[수정 요청]
{chr(10).join('- ' + r for r in requests)}

[하위 문항 목록]
{_segment_spec(form, segs)}

[출제 지침]
{_guideline_text(wb)}

{FORM_MARKUP}

[현재 세트]
{json.dumps({k: st.get(k) for k in ('label', 'passage', 'logic_flow', 'items')}, ensure_ascii=False, indent=1)}

[원문 지문 — 참고]
{source_text or '(없음)'}
"""
    return prompt, SET_SCHEMA


def prompt_set_review(wb: dict[str, Any], form: dict[str, Any], segs: list[dict[str, Any]], st: dict[str, Any], numbers: dict[str, int], rule_result: dict[str, Any], source_text: str) -> tuple[str, dict[str, Any]]:
    from .pipeline import REVIEW_SCHEMA

    prompt = f"""당신은 영어 내신 자료 검수 전문가입니다. 아래 지문 세트(지문 1개 + 하위 문항)를 꼼꼼히 검수하고 JSON으로만 답하세요.
- 지침 준수, 지문 변형 정도, 정답의 유일성·정확성, 오답의 타당성, 문항 간 힌트 노출, 지문 안 표시(빈칸·❶~❺·ⓐ~ⓔ·㉠~㉤ 등)와 문항의 일치,
  영어 문법·자연스러움, 해설 정확성을 본다.
- issues의 number는 아래 '문항 번호' 표의 번호를 쓴다(세트 전체 문제는 0). score는 0~100.
- 정답 표시(형광펜·흰 글씨 등 지침의 '정답 표시' 규칙)와 양식 칸 배치는 출력 단계에서 자동으로 적용되므로 검수하지 않는다.
  이 단계의 내용에는 정답 표시가 없는 것이 정상이다.

[문항 번호]
{json.dumps(numbers, ensure_ascii=False)}

[하위 문항 목록]
{_segment_spec(form, segs)}

[출제 지침]
{_guideline_text(wb)}

[규칙 기반 검사 결과]
{json.dumps(rule_result, ensure_ascii=False)}

[세트]
{json.dumps({k: st.get(k) for k in ('label', 'passage', 'logic_flow', 'items')}, ensure_ascii=False, indent=1)}

[원문 지문]
{source_text or '(없음)'}
"""
    return prompt, REVIEW_SCHEMA


def passage_row(pid: int | None) -> dict[str, Any] | None:
    if not pid:
        return None
    return db.query_one(
        "SELECT p.*, f.orig_name AS file_name, f.use_mode AS use_mode, f.paraphrase_json AS paraphrase_json "
        "FROM passages p JOIN project_files f ON f.id = p.file_id WHERE p.id = ?", (pid,)
    )
