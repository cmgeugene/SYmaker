"""프로젝트 자료실: 출제 범위 파일, 본문(지문) 목록, Codex 본문 나누기.

본문 구분 방식(“Lesson 3”, “01번”, “[본문 a]” …)은 자료마다 다르므로 규칙으로 자르지 않는다.
Codex는 각 본문의 '시작 문구'와 '끝 문구'만 알려 주고, 실제 본문 텍스트는 원본 파일에서
그대로 잘라 온다. 그래서 본문 내용이 모델 때문에 바뀌지 않는다.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

from . import codex, db, hwpx_io

SCOPES = {"range": "출제 범위", "reference": "참고만", "exclude": "제외"}
USE_MODES = {
    "verbatim": "원문 그대로",
    "paraphrase": "패러프레이징",
    "adapt": "일부 변형 허용",
}
USE_MODE_RULES = {
    "verbatim": "본문을 원문 그대로 쓴다. 문항 형식에 필요한 표시(빈칸, 밑줄 번호, 삽입 위치, 형광펜)와 순서 문항의 단락 나누기 외에는 단어·문장을 바꾸지 않는다.",
    "paraphrase": "본문의 내용과 논리 흐름은 유지하되 어휘와 문장 구조를 바꿔 패러프레이징한 지문을 쓴다. 원문 문장을 그대로 옮기지 않는다.",
    "adapt": "본문을 기반으로 하되 문항에 맞게 일부 생략·축약·변형할 수 있다.",
}

# ---------------------------------------------------------------- 패러프레이징 규칙

PARAPHRASE_DEFAULT = {"length": "same", "min_words": 0, "max_words": 0, "level": "same", "note": ""}
PARAPHRASE_LENGTHS = {
    "same": ("원문과 비슷하게", 0.9, 1.1),
    "shorter": ("짧게 (약 70~85%)", 0.7, 0.85),
    "longer": ("길게 (약 115~130%)", 1.15, 1.3),
    "custom": ("단어 수 직접 지정", None, None),
}

_TIERS = {
    "하": "그 학년 지문 중 쉬운 편: 기본·고빈도 어휘, 짧고 단순한 문장, 구체적인 내용",
    "중": "그 학년 지문의 평균 수준: 교육과정 어휘 중심, 적당한 길이의 문장과 기본적인 복문",
    "상": "그 학년 지문 중 어려운 편: 추상적·학술적 어휘, 관계절·분사구문·도치 등 복잡한 구문, 함축적 표현",
}
_GRADES = {
    "고1": "고1 교과서·전국연합학력평가(모의고사)", "고2": "고2 교과서·전국연합학력평가(모의고사)",
    "고3": "고3 전국연합학력평가·수능 모의평가",
}
PARAPHRASE_LEVELS: dict[str, tuple[str, str]] = {
    "same": ("원문 수준", "어휘와 구문 난이도를 원문과 비슷하게 유지한다."),
    "easier": ("원문보다 쉽게", "고빈도 기본 어휘로 바꾸고, 긴 문장은 나누며, 관계절·분사구문·도치 같은 복잡한 구문을 줄인다."),
    "harder": ("원문보다 어렵게", "더 정교하고 추상적인 어휘를 쓰고, 문장을 결합해 관계절·분사구문·도치·명사구 등 복잡한 구문을 늘린다."),
}
for _g, _src in _GRADES.items():
    for _t, _desc in _TIERS.items():
        PARAPHRASE_LEVELS[f"{_g}-{_t}"] = (f"{_g} {_t}", f"{_src} 지문 기준으로 {_desc}.")
PARAPHRASE_LEVELS["수능"] = ("수능", "대학수학능력시험 영어 독해 지문 수준: 학술적 어휘, 추상적 논지, 복잡한 구문과 긴 문장.")


def paraphrase_cfg(raw: dict[str, Any] | None) -> dict[str, Any]:
    return {**PARAPHRASE_DEFAULT, **(raw or {})}


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def word_target(cfg: dict[str, Any] | None, original_words: int | None) -> tuple[int, int] | None:
    """패러프레이징 지문의 목표 단어 수 범위."""

    cfg = paraphrase_cfg(cfg)
    if cfg["length"] == "custom":
        lo, hi = int(cfg.get("min_words") or 0), int(cfg.get("max_words") or 0)
        return (lo, hi) if hi >= lo > 0 else None
    if not original_words:
        return None
    _, a, b = PARAPHRASE_LENGTHS.get(cfg["length"], PARAPHRASE_LENGTHS["same"])
    return round(original_words * a), round(original_words * b)


def paraphrase_rule(cfg: dict[str, Any] | None, original_words: int | None = None) -> str:
    """프롬프트에 넣을 패러프레이징 분량·난이도 규칙."""

    cfg = paraphrase_cfg(cfg)
    target = word_target(cfg, original_words)
    if target:
        length = f"분량: {target[0]}~{target[1]}단어" + (f" (원문 {original_words}단어)" if original_words else "")
    else:
        label, a, b = PARAPHRASE_LENGTHS.get(cfg["length"], PARAPHRASE_LENGTHS["same"])
        length = f"분량: 원문의 약 {round(a * 100)}~{round(b * 100)}%" if a else f"분량: {label}"
    level_label, level_rule = PARAPHRASE_LEVELS.get(cfg["level"], PARAPHRASE_LEVELS["same"])
    rule = f"{length} / 난이도: {level_label} — {level_rule}"
    if (cfg.get("note") or "").strip():
        rule += f" / 추가 지시: {cfg['note'].strip()}"
    return rule


DEFAULT_TYPES = [
    "주제", "제목", "요지", "목적", "주장", "빈칸 추론", "어법", "어휘", "글의 순서", "문장 삽입",
    "무관한 문장", "요약문 완성", "내용 일치", "함축 의미", "지칭 추론", "심경 변화", "서술형",
]

ACCEPT = (".txt", ".pdf", ".hwp", ".hwpx", ".md")


async def ingest(stored: Path) -> tuple[str, Path | None, dict[str, Any] | None]:
    """파일에서 텍스트를 뽑고, HWP면 HWPX로 바꾸고, HWPX면 서식을 분석한다."""

    ext = stored.suffix.lower()
    hwpx_path: Path | None = None
    fmt: dict[str, Any] | None = None
    try:
        if ext in (".txt", ".md"):
            text = hwpx_io.extract_txt(stored)
        elif ext == ".pdf":
            text = await asyncio.to_thread(hwpx_io.extract_pdf, stored)
        else:
            conversion = None
            if ext == ".hwp":
                hwpx_path = stored.with_suffix(".hwpx")
                conversion = await asyncio.to_thread(hwpx_io.convert_hwp_to_hwpx, stored, hwpx_path)
            else:
                hwpx_path = stored
            text = await asyncio.to_thread(hwpx_io.hwpx_plain_text, hwpx_path)
            fmt = await asyncio.to_thread(hwpx_io.analyze_hwpx, hwpx_path)
            if conversion:
                fmt["conversion"] = conversion
            from .hwpx_form import detect_form

            fmt["form"] = await asyncio.to_thread(detect_form, hwpx_path)
    except Exception:
        stored.unlink(missing_ok=True)
        if hwpx_path and hwpx_path != stored:
            hwpx_path.unlink(missing_ok=True)
        raise
    return text, hwpx_path, fmt


# ---------------------------------------------------------------- 본문 위치 찾기

_MARK = re.compile(r"\*\*|__|==|^\s*│ ", re.M)


def _norm_with_map(text: str) -> tuple[str, list[int]]:
    """공백·서식 표시를 정리한 소문자 문자열과, 각 글자의 원문 위치 목록."""

    out: list[str] = []
    pos: list[int] = []
    i = 0
    prev_space = True
    while i < len(text):
        m = _MARK.match(text, i)
        if m and m.end() > i:
            i = m.end()
            continue
        ch = text[i]
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                pos.append(i)
            prev_space = True
        else:
            out.append(ch.lower())
            pos.append(i)
            prev_space = False
        i += 1
    return "".join(out), pos


def _norm(s: str) -> str:
    return _norm_with_map(s)[0].strip()


def locate(text: str, start: str, end: str, from_pos: int = 0) -> tuple[int, int] | None:
    """원문에서 시작 문구~끝 문구 구간을 찾는다 (공백·대소문자·서식 표시 무시)."""

    norm, pos = _norm_with_map(text)
    begin_at = next((k for k, p in enumerate(pos) if p >= from_pos), len(pos))

    def find(needle: str, after: int) -> int:
        n = _norm(needle)
        if not n:
            return -1
        idx = norm.find(n, after)
        if idx < 0:  # 앞부분만으로 다시 시도
            words = n.split(" ")
            for k in (8, 5, 3):
                if len(words) > k:
                    idx = norm.find(" ".join(words[:k]), after)
                    if idx >= 0:
                        break
        return idx

    s = find(start, begin_at)
    if s < 0:
        return None
    n_end = _norm(end)
    e = norm.find(n_end, s) if n_end else -1
    if e >= 0:
        e_end = e + len(n_end)
    else:  # 끝 문구의 뒷부분만으로 다시 시도
        words = n_end.split(" ")
        e_end = -1
        for k in (8, 5, 3):
            if len(words) > k:
                tail = " ".join(words[-k:])
                e2 = norm.find(tail, s)
                if e2 >= 0:
                    e_end = e2 + len(tail)
                    break
        if e_end < 0:
            return None
    return pos[s], pos[min(e_end, len(pos)) - 1] + 1


def clean_passage(raw: str) -> str:
    """원문에서 잘라 온 본문 정리: 표 칸 표시와 원자료의 형광펜·굵게·밑줄 표시를 없앤다.
    (강의노트는 정답을 형광펜으로 칠해 두는 경우가 많아, 그대로 두면 새 문항에 정답 표시가 따라간다.)"""

    lines = [re.sub(r"^\s*│ ", "", ln) for ln in raw.splitlines()]
    text = re.sub(r"\*\*|(?<!_)__(?!_)|==", "", "\n".join(lines))
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# ---------------------------------------------------------------- Codex 본문 나누기

SEGMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["passages"],
    "properties": {
        "passages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "start", "end", "summary", "suitable_types"],
                "properties": {
                    "label": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "summary": {"type": "string"},
                    "suitable_types": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}

WINDOW = 70_000


def windows(text: str, size: int = WINDOW) -> list[tuple[int, str]]:
    """긴 자료를 줄 경계에서 잘라 여러 구간으로 나눈다."""

    out: list[tuple[int, str]] = []
    i = 0
    while i < len(text):
        j = min(len(text), i + size)
        if j < len(text):
            cut = text.rfind("\n\n", i + size // 2, j)
            j = cut if cut > 0 else j
        out.append((i, text[i:j]))
        i = j
    return out


def prompt_segment(f: dict[str, Any], chunk: str, part: str, types: list[str]) -> str:
    return f"""당신은 영어 시험 출제용 자료를 정리하는 조교입니다.
아래 자료에서 시험 지문으로 쓸 수 있는 '영어 본문'을 하나씩 찾아 JSON으로만 답하세요. 파일을 만들거나 명령을 실행할 필요는 없습니다.

규칙
- 자료마다 본문 구분 방식이 다릅니다(예: Lesson 3, 01번, [본문 a], 제목, 번호, 쪽 구분 등). 자료의 구조를 보고 판단하세요.
- 본문이 아닌 것은 제외합니다: 한국어 해석, 어휘 목록, 기존 문제의 발문·선택지·정답·해설, 목차, 머리말.
  단, 기존 문제 안에 들어 있는 영어 지문은 본문으로 봅니다(발문과 선택지는 제외).
- 강의노트·분석 자료처럼 같은 본문이 여러 번 나오면(문제 형태 + 분석/필기 형태), 원문이 온전하고 깨끗한 '첫 번째' 것만 한 번 넣습니다.
  어휘 풀이, [A / B] 고르기, 빈칸·첫 글자 힌트, 괄호 속 한국어 뜻이 끼어 있는 필기 형태는 쓰지 않습니다.
  빈칸 문제 형태에 정답이 빈칸 자리에 채워져 있으면 그것이 원문이므로 그대로 씁니다.
- 본문 번호(예: 11-01)와 함께 '동일 소재 기출' 같은 보충 지문이 있으면 label에 그 성격이 드러나게 적습니다(예: "11-02 동일 소재 기출 (2022 고2 11월 31번)").
- label: 사람이 알아볼 수 있는 이름. 자료의 표기를 살려서. 예: "Lesson 3 · Reading 1", "12번 지문", "본문 a".
- start: 본문의 첫 문장을 원문 그대로 앞부분 8~12단어. end: 본문의 마지막 문장을 원문 그대로 끝부분 8~12단어.
  철자·구두점까지 자료와 똑같이 적습니다(앱이 이 문구로 원문에서 본문을 잘라 옵니다).
- summary: 한국어 한 문장 요약.
- suitable_types: 이 본문으로 출제하기 좋은 유형(아래 목록에서 고르되, 필요하면 새 이름 가능). 예: 도표가 없으면 '도표 이해' 제외,
  논리 전개가 약하면 '글의 순서'·'문장 삽입' 제외, 서사·일화면 '심경 변화' 가능.
  유형 목록: {", ".join(types)}
- 자료에 나온 순서대로 나열합니다.

[자료: {f['orig_name']}{(' — 메모: ' + f['note']) if f.get('note') else ''}{(' — ' + part) if part else ''}]
{chunk}
"""


async def segment_job(job_id: int, project_id: int, file_ids: list[int], model: str, effort: str, types: list[str]) -> None:
    from . import stages

    def log(m: str) -> None:
        line = f"[{__import__('datetime').datetime.now().strftime('%H:%M:%S')}] {m}\n"
        db.execute("UPDATE jobs SET log = COALESCE(log, '') || ? WHERE id = ?", (line, job_id))

    ctx = stages.Ctx(job_id=job_id, wb={}, model=model, effort=effort, log=log)
    try:
        files = [db.query_one("SELECT * FROM project_files WHERE id = ?", (i,)) for i in file_ids]
        files = [f for f in files if f]
        tasks = []
        for f in files:
            parts = windows(f["text"] or "")
            for k, (offset, chunk) in enumerate(parts):
                label = f"{Path(f['orig_name']).stem}" + (f" {k + 1}/{len(parts)}" if len(parts) > 1 else "")
                part = f"{k + 1}/{len(parts)} 구간" if len(parts) > 1 else ""
                tasks.append((f, offset, chunk, label, part))

        async def run_one(f: dict[str, Any], offset: int, chunk: str, label: str, part: str) -> list[dict[str, Any]]:
            out = await ctx.call(prompt_segment(f, chunk, part, types), SEGMENT_SCHEMA, sub=label)
            found = []
            cursor = 0
            for p in out.get("passages", []):
                span = locate(chunk, p["start"], p["end"], cursor)
                if span:
                    cursor = span[1]
                    text = clean_passage(chunk[span[0] : span[1]])
                    found.append({**p, "text": text, "located": 1, "pos": offset + span[0]})
                else:
                    log(f"[{label}] '{p['label']}' 위치를 원문에서 찾지 못했습니다 — 직접 확인이 필요합니다.")
                    found.append({**p, "text": f"{p['start']} … {p['end']}", "located": 0, "pos": offset + cursor})
            return found

        results = await stages.gather_limited(
            ctx, [(t[3], (lambda t=t: run_one(*t))) for t in tasks], "본문 나누기"
        )
        by_file: dict[int, list[dict[str, Any]]] = {}
        failed = []
        for t, r in zip(tasks, results):
            if isinstance(r, Exception):
                failed.append(t[3])
                continue
            by_file.setdefault(t[0]["id"], []).extend(r)

        total = 0
        for fid, items in by_file.items():
            items.sort(key=lambda x: x["pos"])
            db.execute("DELETE FROM passages WHERE file_id = ?", (fid,))
            for seq, p in enumerate(items, 1):
                db.execute(
                    "INSERT INTO passages(project_id, file_id, seq, label, text, summary, suitable_types_json, located, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (project_id, fid, seq, p["label"], p["text"], p["summary"], db.dumps(p["suitable_types"]), p["located"], db.now()),
                )
            db.execute("UPDATE project_files SET segmented_at = ? WHERE id = ?", (db.now(), fid))
            total += len(items)
            log(f"{next(f['orig_name'] for f in files if f['id'] == fid)}: 본문 {len(items)}개")

        if failed:
            err = f"일부 구간 실패: {', '.join(failed)}"
            db.execute("UPDATE jobs SET status='failed', error=?, finished_at=? WHERE id=?", (err, db.now(), job_id))
        else:
            db.execute("UPDATE jobs SET status='done', result_json=?, finished_at=? WHERE id=?", (db.dumps({"passages": total}), db.now(), job_id))
            log(f"완료: 본문 {total}개")
    except Exception as exc:  # noqa: BLE001
        status = "cancelled" if codex.is_cancelled(job_id) else "failed"
        db.execute("UPDATE jobs SET status=?, error=?, finished_at=? WHERE id=?", (status, str(exc), db.now(), job_id))


# ---------------------------------------------------------------- 조회 도우미

def project_files(project_id: int) -> list[dict[str, Any]]:
    return db.query("SELECT * FROM project_files WHERE project_id = ? ORDER BY id", (project_id,))


def passages(project_id: int, include_excluded: bool = True) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT p.*, f.orig_name AS file_name, f.use_mode AS use_mode, f.scope AS file_scope, f.paraphrase_json AS paraphrase_json "
        "FROM passages p JOIN project_files f ON f.id = p.file_id WHERE p.project_id = ? ORDER BY p.file_id, p.seq",
        (project_id,),
    )
    if not include_excluded:
        rows = [r for r in rows if not r["excluded"] and r["file_scope"] == "range"]
    return rows


def usage(project_id: int, exclude_workbooks: set[int] | None = None) -> list[dict[str, Any]]:
    """프로젝트 안 세트들의 본문 사용 기록 [(workbook, passage_id, type)]."""

    out = []
    for w in db.query("SELECT id, name, set_index, group_id, allocation_json FROM workbooks WHERE project_id = ?", (project_id,)):
        if exclude_workbooks and w["id"] in exclude_workbooks:
            continue
        for it in (w.get("allocation") or {}).get("items", []):
            if it.get("passage_id"):
                out.append({"workbook_id": w["id"], "workbook": w["name"], "passage_id": it["passage_id"], "type": it.get("type") or ""})
    return out
