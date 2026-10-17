"""규칙 기반 검수 (모델 없이 즉시 확인 가능한 항목)."""

from __future__ import annotations

import difflib
import random
import re
from collections import Counter
from typing import Any

from .hwpx_writer import strip_markup


_SYMBOL_SETS = ("①②③④⑤⑥⑦⑧⑨⑩", "❶❷❸❹❺❻❼❽❾❿", "ⓐⓑⓒⓓⓔⓕⓖⓗⓘⓙ", "ⒶⒷⒸⒹⒺ",
                "㉠㉡㉢㉣㉤㉥㉦㉧㉨㉩", "㉮㉯㉰㉱㉲㉳㉴㉵㉶㉷", "abcde", "ABCDE")


def answer_index(answer: object) -> int | None:
    """정답 표기를 번호로: '3', '③', '❸', 'ⓒ', '(3)', 'c' → 3. 알 수 없으면 None.
    (주의: 파이썬은 '❹'.isdigit()을 참으로 보지만 int('❹')는 실패한다.)"""

    a = re.sub(r"[\s()\[\].번]", "", str(answer or ""))
    if a.isascii() and a.isdigit():
        return int(a)
    if len(a) == 1:
        for symbols in _SYMBOL_SETS:
            if a in symbols:
                return symbols.index(a) + 1
    return None


def answer_plan(n: int, choices: int = 5, seed: int | None = None) -> list[int]:
    """정답 번호가 고르게 분포하고 같은 번호가 3번 연속되지 않는 순서를 만든다."""

    rng = random.Random(seed)
    base = [(i % choices) + 1 for i in range(n)]
    for _ in range(500):
        rng.shuffle(base)
        if all(not (base[i] == base[i - 1] == base[i - 2]) for i in range(2, n)):
            return base
    return base


def is_essay(q: dict[str, Any]) -> bool:
    return q.get("kind") == "서술형" or (not q.get("kind") and not q.get("choices"))


_STRIP = re.compile(r"\*\*|__|==|[①-⑩]|\(\s*[A-C]\s*\)|_{3,}|\[[^\]]{0,20}\]")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", _STRIP.sub(" ", text or "").lower())


def similarity(a: str, b: str) -> float:
    """두 영어 지문의 단어 순서 기준 유사도 (0~1)."""

    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio()


# 양식 모드: 문항이 가리키는 표시가 공통 지문(passage)에 실제로 있는지
_MARKER_RULES = (
    ("❶", "❶❷❸❹❺", "삽입 위치 ( ❶ )~( ❺ )"),
    ("㉠", "㉠㉡㉢㉣㉤", "어법 밑줄 ㉠~㉤"),
    ("ⓐ", "ⓐⓑⓒⓓⓔ", "어휘 표시 ⓐ~ⓔ"),
)
_SPLIT_PASSAGE = re.compile(r"전용 지문|문항용 본문|독립된 시험지|제시 단위|분리 출제|별도 회차")


def _check_set_markers(sets: list[dict[str, Any]], items: list[dict[str, Any]], add: Any) -> None:
    for st in sets:
        passage = st.get("passage") or ""
        for it in st.get("items") or []:
            n = next((q.get("number", 0) for q in items if q.get("set") == st.get("index") and q.get("segment_id") == it.get("segment_id")), 0)
            text = " ".join([it.get("instruction") or "", *(it.get("choices") or [])])
            for key, symbols, name in _MARKER_RULES:
                missing = [s for s in symbols if s not in passage]
                if key in text and missing:
                    add(n, "high", "서식", f"{st.get('index')}번 지문에 {name} 표시가 없습니다 (빠진 기호: {''.join(missing)}).",
                        "문항이 가리키는 표시를 모두 공통 지문 안에 넣으세요.")
                order = [c for c in passage if c in symbols]
                if key in text and not missing and order[: len(symbols)] != list(symbols):
                    add(n, "high", "서식", f"{st.get('index')}번 지문의 {name} 기호가 지문에 보이는 순서와 다릅니다 ({''.join(order)}).",
                        "지문을 위에서부터 읽을 때 기호가 차례대로 나오도록 다시 붙이세요.")
            if "빈칸" in (it.get("type") or "") and "_____" not in passage:
                add(n, "high", "서식", f"{st.get('index')}번 지문에 빈칸(__________)이 없습니다.", "빈칸을 공통 지문 안에 표시하세요.")
            if "순서" in (it.get("type") or "") and not all(f"({c})" in passage for c in "ABCD"):
                add(n, "high", "서식", f"{st.get('index')}번 지문이 (A)~(D) 문단으로 나뉘어 있지 않습니다.", "공통 지문을 (A) 다음 섞인 (B)(C)(D) 문단으로 제시하세요.")
            if _SPLIT_PASSAGE.search(it.get("extra") or ""):
                add(n, "high", "서식", f"{st.get('index')}번 지문: 추가 정보에 문항 전용 지문이나 시험지 분리 지시가 있습니다 (출력되지 않음).",
                    "전용 지문과 편성 지시를 지우고 공통 지문 하나에 모든 표시를 넣으세요.")


def run_checks(
    questions: dict[str, Any] | None,
    spec: dict[str, Any] | None,
    analysis: dict[str, Any] | None,
    passages: dict[int, dict[str, Any]] | None = None,
    other_usage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    items = (questions or {}).get("questions") or []
    spec = spec or {}

    def add(number: int, severity: str, category: str, message: str, suggestion: str = "") -> None:
        issues.append({"number": number, "severity": severity, "category": category, "message": message, "suggestion": suggestion, "source": "rule"})

    form_mode = bool(items) and all("set" in q for q in items)
    target = None if form_mode else spec.get("question_count")
    if target and len(items) != int(target):
        add(0, "high", "지침", f"문항 수가 {len(items)}개입니다 (목표 {target}개).")

    essay_target = int(spec.get("essay_count") or 0)
    essays = [q for q in items if is_essay(q)]
    if target and len(essays) != essay_target:
        add(0, "medium", "지침", f"서술형이 {len(essays)}문항입니다 (목표 {essay_target}개).")

    answers: list[int] = []
    answer_numbers: list[int] = []
    for q in items:
        n = q.get("number", 0)
        choices = q.get("choices") or []
        if not strip_markup(q.get("instruction", "")).strip():
            add(n, "high", "기타", "발문이 비어 있습니다.")
        if is_essay(q):
            if choices:
                add(n, "medium", "서식", "서술형인데 선택지가 있습니다.")
            if not strip_markup(str(q.get("answer", ""))).strip():
                add(n, "high", "정답", "서술형 모범답안이 비어 있습니다.")
            if not form_mode and not (q.get("rubric") or "").strip():  # 양식에는 채점 기준 칸이 없다
                add(n, "medium", "정답", "서술형 채점 기준이 비어 있습니다.", "부분 점수를 포함한 채점 기준을 적으세요.")
        elif not choices and not form_mode:
            add(n, "high", "서식", "객관식인데 선택지가 없습니다.")
        if choices:
            if len(choices) != 5:
                add(n, "high", "서식", f"선택지가 {len(choices)}개입니다 (5개 필요).")
            norm = [strip_markup(c).strip().lower() for c in choices]
            dup = [c for c, k in Counter(norm).items() if k > 1 and c]
            if dup:
                add(n, "high", "정답", f"중복된 선택지가 있습니다: {dup[0][:30]}")
            a = str(q.get("answer", "")).strip()
            idx = answer_index(a)
            if idx is None or not 1 <= idx <= len(choices):
                add(n, "high", "정답", f"정답 표기 '{a}'가 1~{len(choices)} 범위가 아닙니다.")
            else:
                answers.append(idx)
                answer_numbers.append(n)
        if not (q.get("explanation") or "").strip():
            add(n, "low", "기타", "해설이 비어 있습니다.")
        for field in ("instruction", "passage", *[f"choices[{i}]" for i in range(len(choices))]):
            value = q.get(field) if not field.startswith("choices") else choices[int(field[8:-1])]
            for token, name in (("**", "굵게"), ("__", "밑줄"), ("==", "형광펜")):
                n_tok = len(re.findall(r"(?<!_)__(?!_)", value)) if value and token == "__" else (value.count(token) if value else 0)
                if n_tok % 2:
                    add(n, "medium", "서식", f"{name} 표시({token})가 닫히지 않았습니다 ({field}).")

    dist = Counter(answers)
    distribution = {str(i): dist.get(i, 0) for i in range(1, 6)}
    if len(answers) >= 5:
        hi, lo = max(distribution.values()), min(distribution.values())
        if hi - lo > max(1, len(answers) // 10):
            add(0, "medium", "정답", f"정답 번호 분포가 고르지 않습니다: {distribution}", "선택지 순서를 바꿔 1~5번이 고르게 나오도록 조정하세요.")
    for i in range(2, len(answers)):
        if answers[i] == answers[i - 1] == answers[i - 2]:
            add(answer_numbers[i], "low", "정답", f"정답 {answers[i]}번이 3문항 연속입니다.")

    wanted = {t["name"]: int(t.get("count") or 0) for t in spec.get("types") or [] if t.get("name")}
    if wanted:
        got = Counter(q.get("type") for q in items)
        for name, cnt in wanted.items():
            if cnt and got.get(name, 0) != cnt:
                add(0, "medium", "지침", f"'{name}' 유형이 {got.get(name, 0)}문항입니다 (목표 {cnt}).")

    if form_mode:
        _check_set_markers((questions or {}).get("sets") or [], items, add)

    # 여러 문항이 같은 지문을 그대로 쓰는지 (다른 포인트를 묻는 건 괜찮지만 확인용)
    seen: dict[str, int] = {}
    for q in items:
        key = re.sub(r"\s+", " ", strip_markup(q.get("passage") or "")).strip()[:120].lower()
        if len(key) >= 60:
            if key in seen:
                add(q.get("number", 0), "low", "기타", f"{seen[key]}번과 같은 지문을 사용합니다.", "출제 포인트가 겹치지 않는지 확인하세요.")
            else:
                seen[key] = q.get("number", 0)

    # 지정 본문의 '지문 사용 방식' 준수 / 다른 세트와 같은 본문·같은 유형 재사용
    used_elsewhere = {(u["passage_id"], (u.get("type") or "").replace(" ", "")): u.get("workbook", "") for u in other_usage or []}
    for q in items:
        pid = q.get("passage_id")
        p = (passages or {}).get(pid) if pid else None
        if not p:
            continue
        n = q.get("number", 0)
        mode = p.get("use_mode") or "adapt"
        if q.get("passage") and mode in ("verbatim", "paraphrase"):
            r = similarity(q["passage"], p["text"])
            if mode == "verbatim" and r < 0.75:
                add(n, "medium", "지침", f"'{p['label']}' 본문은 '원문 그대로' 써야 하는데 원문과 {r:.0%}만 일치합니다.", "문항 형식에 필요한 표시 외에는 원문 문장을 유지하세요.")
            if mode == "paraphrase" and r > 0.85:
                add(n, "medium", "지침", f"'{p['label']}' 본문은 패러프레이징해야 하는데 원문과 {r:.0%} 일치합니다.", "어휘와 문장 구조를 바꿔 다시 쓰세요.")
            if mode == "paraphrase":
                from .materials import word_count, word_target

                target = word_target(p.get("paraphrase"), word_count(p["text"]))
                got = len(_words(q["passage"]))
                if target and not (target[0] * 0.9 <= got <= target[1] * 1.1):
                    add(n, "medium", "지침", f"패러프레이징 지문이 {got}단어입니다 (목표 {target[0]}~{target[1]}단어).", "분량 규칙에 맞게 늘리거나 줄이세요.")
        key = (pid, (q.get("type") or "").replace(" ", ""))
        if key in used_elsewhere:
            add(n, "medium", "지침", f"'{p['label']}' 본문이 '{used_elsewhere[key]}'에서 같은 유형({q.get('type')})으로 이미 출제되었습니다.", "다른 유형으로 바꾸거나 본문 배정을 다시 하세요.")

    fmt = (analysis or {}).get("format_facts") or {}
    if not form_mode and fmt.get("highlights") and items and not any("==" in (q.get("passage") or "") for q in items):
        add(0, "low", "서식", "샘플은 형광펜을 사용하지만 제작 문항에는 형광펜 표시가 없습니다.")

    return {"issues": issues, "answer_distribution": distribution, "question_count": len(items)}
