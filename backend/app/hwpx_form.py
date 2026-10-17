"""양식(폼) 템플릿: '지문 1개 + 하위 문항 여러 개' 블록이 반복되는 문제지(KSC 등)를 다룬다.

샘플을 흉내 내 새로 쓰는 대신, 양식을 그대로 두고 빈칸만 채운다.

구조 인식(결정론적)
- 블록: 어떤 구역에서 '[1]', '[2]' … 로 시작하는 문단이 2개 이상이면 그 사이를 블록으로 본다.
- 블록 안에서
    머리(header)     : 블록 첫 문단
    지문 상자(passage): 첫 발문 앞에 있는 표(1칸)
    하위 문항(segment): 자동 번호 발문 문단부터 다음 발문 전까지. 원문자 자동 번호 문단은 선택지 칸.
- 앞쪽 표(front): '[n] …' 머리 칸과 그 아래 칸 쌍 (Logic Flow 등 지문별 박스)

칸(slot) 주소
    b{k}            블록 안 k번째 최상위 문단
    b{k}.t{j}.r{r}c{c}  블록 안 k번째 문단의 j번째 표, r행 c열 칸 (여러 줄 → 칸 안 문단 여러 개)
    f.head / f.body  앞쪽 표에서 이 지문 번호의 머리 칸 / 아래 칸

채우기 마크업: hwpx_writer와 같음(==형광펜==, **굵게**, __밑줄__, !!흰 글씨!!) + 정답 표시
    {{텍스트}}   인쇄되는 내용 중 정답 (선택지·기호) — 교사용: 형광펜, 학생용: 표시 없이 그대로
    {{?텍스트}}  써 넣는 정답 — 교사용: 형광펜, 학생용: 지움(빈칸)
    {{!텍스트}}  써 넣는 정답(숨김 스타일) — 교사용: 형광펜+굵게+흰 글씨, 학생용: 지움
"""

from __future__ import annotations

import copy
import re
from collections import Counter
from pathlib import Path
from typing import Any

from lxml import etree

from .hwpx_io import HP, HwpxPackage, NUM_FORMAT_LABELS, describe_heading, paragraph_text, parse_header
from .hwpx_writer import Builder

BLOCK_START = re.compile(r"^\s*\[\s*(\d+)\s*\]")
CHOICE_FORMATS = {"CIRCLED_DIGIT", "CIRCLED_LATIN_SMALL", "CIRCLED_HANGUL_SYLLABLE", "CIRCLED_HANGUL_JAMO"}


def _plain(p: etree._Element, hdr: dict[str, Any]) -> str:
    return re.sub(r"\*\*|__|==", "", paragraph_text(p, hdr, Counter())).strip()


def _heading_format(p: etree._Element, hdr: dict[str, Any]) -> str | None:
    pp = hdr["para_prs"].get(p.get("paraPrIDRef"))
    if not pp or pp["heading_type"] not in ("NUMBER", "OUTLINE"):
        return None
    levels = hdr["numberings"].get(pp["heading_id"] or "", [])
    lvl = next((l for l in levels if l["level"] == pp["heading_level"] + 1), levels[0] if levels else None)
    return lvl["format"] if lvl else "DIGIT"


def _direct_tables(p: etree._Element) -> list[etree._Element]:
    """문단에 직접 들어 있는 표 (중첩 표 제외)."""

    out = []
    for run in p.findall(HP + "run"):
        out.extend(run.findall(HP + "tbl"))
    return out


def _cells(tbl: etree._Element) -> list[tuple[int, int, etree._Element]]:
    out = []
    for tc in tbl.iter(HP + "tc"):
        if tc.getparent().getparent() is not tbl:
            continue
        addr = tc.find(HP + "cellAddr")
        out.append((int(addr.get("rowAddr", 0)), int(addr.get("colAddr", 0)), tc))
    return out


def _cell_paras(tc: etree._Element) -> list[etree._Element]:
    sub = tc.find(HP + "subList")
    return sub.findall(HP + "p") if sub is not None else []


# ---------------------------------------------------------------- 구조 인식

def detect_form(path: Path | str) -> dict[str, Any] | None:
    pkg = HwpxPackage.open(path)
    hdr = parse_header(pkg.xml("Contents/header.xml"))
    sections = pkg.section_names()

    best: tuple[str, list[int]] | None = None
    for name in sections:
        tops = pkg.xml(name).findall(HP + "p")
        starts = [i for i, p in enumerate(tops) if BLOCK_START.match(_plain(p, hdr)) and not _direct_tables(p)]
        # 블록 안에 발문(자동 번호)이 있어야 문제 블록으로 본다
        if len(starts) >= 2 and any(_heading_format(p, hdr) and _heading_format(p, hdr) not in CHOICE_FORMATS for p in tops[starts[0]:starts[1]]):
            if best is None or len(starts) > len(best[1]):
                best = (name, starts)
    if not best:
        return None

    name, starts = best
    tops = pkg.xml(name).findall(HP + "p")
    bounds = [(s, (starts[k + 1] if k + 1 < len(starts) else len(tops))) for k, s in enumerate(starts)]
    proto_index = 1 if len(bounds) > 1 else 0
    b0, b1 = bounds[proto_index]
    block = tops[b0:b1]

    paras: list[dict[str, Any]] = []
    for k, p in enumerate(block):
        fmt = _heading_format(p, hdr)
        kind = "plain"
        if k == 0:
            kind = "header"
        elif fmt and fmt in CHOICE_FORMATS:
            kind = "choice"
        elif fmt:
            kind = "instruction"
        tables = []
        for j, tbl in enumerate(_direct_tables(p)):
            cells = [
                {"slot": f"b{k}.t{j}.r{r}c{c}", "row": r, "col": c, "text": " / ".join(_plain(q, hdr) for q in _cell_paras(tc)).strip(" /")}
                for r, c, tc in _cells(tbl)
            ]
            tables.append({"rows": int(tbl.get("rowCnt", 1)), "cols": int(tbl.get("colCnt", 1)), "cells": cells})
        if tables and kind == "plain":
            kind = "table"
        paras.append({"slot": f"b{k}", "kind": kind, "text": _plain(p, hdr), "tables": tables,
                      "numbering": NUM_FORMAT_LABELS.get(fmt, fmt) if fmt else None})

    first_instr = next((i for i, p in enumerate(paras) if p["kind"] == "instruction"), len(paras))
    passage_slot = None
    for p in paras[1:first_instr]:
        for t in p["tables"]:
            if t["rows"] * t["cols"] == 1:
                passage_slot = t["cells"][0]["slot"]
                break
        if passage_slot:
            break

    segments = []
    instr = [i for i, p in enumerate(paras) if p["kind"] == "instruction"]
    for n, i in enumerate(instr):
        end = instr[n + 1] if n + 1 < len(instr) else len(paras)
        seg_paras = paras[i:end]
        segments.append({
            "id": f"s{n + 1}",
            "start": i,
            "end": end,
            "instruction": paras[i]["text"],
            "choice_slots": [p["slot"] for p in seg_paras if p["kind"] == "choice"],
            "slots": [p["slot"] for p in seg_paras],
        })

    front = _detect_front(pkg, hdr, exclude=name)
    return {
        "section": name,
        "block_count": len(bounds),
        "block_bounds": bounds,
        "proto_index": proto_index,
        "paragraphs": paras,
        "passage_slot": passage_slot,
        "segments": segments,
        "front": front,
    }


def _detect_front(pkg: HwpxPackage, hdr: dict[str, Any], exclude: str) -> dict[str, Any] | None:
    """'[n] …' 머리 칸과 그 아래 칸이 짝을 이루는 표들 (지문별 박스)."""

    for name in pkg.section_names():
        if name == exclude:
            continue
        boxes: dict[str, dict[str, Any]] = {}
        sample_text = ""
        for t_i, tbl in enumerate(pkg.xml(name).iter(HP + "tbl")):
            cells = {(r, c): tc for r, c, tc in _cells(tbl)}
            for (r, c), tc in cells.items():
                text = " ".join(_plain(q, hdr) for q in _cell_paras(tc)).strip()
                m = BLOCK_START.match(text)
                if m and (r + 1, c) in cells:
                    body = " / ".join(_plain(q, hdr) for q in _cell_paras(cells[(r + 1, c)])).strip(" /")
                    boxes[m.group(1)] = {"table": t_i, "head": [r, c], "body": [r + 1, c], "head_text": text}
                    if body and not sample_text:
                        sample_text = body
        if boxes:
            return {"section": name, "boxes": boxes, "example": sample_text[:600]}
    return None


def skeleton_text(form: dict[str, Any], usable: list[str] | None = None) -> str:
    """Codex에게 보여 줄 블록 구조 (칸 주소 + 현재 문구)."""

    seg_of = {}
    for s in form["segments"]:
        for slot in s["slots"]:
            seg_of[slot] = s["id"]
    lines = []
    for p in form["paragraphs"]:
        if usable is not None and seg_of.get(p["slot"]) and seg_of[p["slot"]] not in usable:
            continue
        label = {"header": "블록 머리", "instruction": "발문(자동 번호)", "choice": "선택지 칸(자동 번호 " + (p["numbering"] or "") + ")",
                 "table": "표가 든 문단", "plain": "문단"}[p["kind"]]
        seg = f" [{seg_of[p['slot']]}]" if p["slot"] in seg_of else ""
        if p["slot"] in (form.get("passage_slot") or "") or any(c["slot"] == form.get("passage_slot") for t in p["tables"] for c in t["cells"]):
            label = "지문 상자가 든 문단"
        lines.append(f"{p['slot']}{seg} ({label}) {p['text']!r}")
        for t in p["tables"]:
            for c in t["cells"]:
                tag = " ← 지문 상자" if c["slot"] == form.get("passage_slot") else ""
                lines.append(f"    {c['slot']} (표 {t['rows']}x{t['cols']} 칸){tag} {c['text']!r}")
    if form.get("front"):
        lines.append(f"f.head (앞쪽 지문별 박스의 머리 칸) 예: {next(iter(form['front']['boxes'].values()))['head_text']!r}")
        lines.append(f"f.body (그 아래 칸, 여러 줄 가능) 예시 내용: {form['front']['example']!r}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 출력 서식 설정

STYLE_DEFAULT: dict[str, Any] = {
    "header_highlight": True,          # 블록 머리의 출처 표기에 형광펜
    "hidden_style": ["highlight", "bold", "white"],   # {{!숨긴 정답}} 서식 (underline 추가 가능)
    "gap_lines": 1,                    # 하위 문항 사이 빈 줄 수 (None이면 양식 그대로)
    "front_body": {"size": None, "align": "", "keyword_mark": False},  # 앞쪽 박스 아래 칸
    "box_align": {},                   # {칸 주소: LEFT|CENTER|RIGHT|JUSTIFY} — 제목 줄 아래 내용 줄에 적용
}


def form_style(raw: dict[str, Any] | None) -> dict[str, Any]:
    st = {**STYLE_DEFAULT, **(raw or {})}
    st["front_body"] = {**STYLE_DEFAULT["front_body"], **((raw or {}).get("front_body") or {})}
    st["box_align"] = dict((raw or {}).get("box_align") or {})
    return st


def boxes(form: dict[str, Any]) -> list[dict[str, Any]]:
    """정렬을 바꿀 수 있는 상자 칸(1칸짜리 표) 목록."""

    seg_of = {slot: sg for sg in form["segments"] for slot in sg["slots"]}
    out = []
    for p in form["paragraphs"]:
        for t in p["tables"]:
            if t["rows"] * t["cols"] != 1:
                continue
            c = t["cells"][0]
            seg = seg_of.get(p["slot"])
            kind = "지문 상자" if c["slot"] == form.get("passage_slot") else (c["text"] or "내용 상자")
            out.append({"slot": c["slot"], "label": kind, "segment": seg["id"] if seg else None,
                        "segment_instruction": seg["instruction"] if seg else ""})
    return out


# ---------------------------------------------------------------- 채우기

ANSWER_RE = re.compile(r"\{\{([!?]?)(.+?)\}\}", re.S)


def render_answers(text: str, teacher: bool, hidden_style: list[str] | None = None) -> str:
    """{{정답}} / {{?써 넣는 정답}} / {{!숨긴 정답}} 표시를 교사용·학생용에 맞게 바꾼다."""

    hs = hidden_style if hidden_style is not None else STYLE_DEFAULT["hidden_style"]
    marks = {"highlight": "==", "bold": "**", "underline": "__", "white": "!!"}
    order = [k for k in ("highlight", "bold", "underline", "white") if k in hs]

    def rep(m: re.Match) -> str:
        kind, body = m.group(1), m.group(2)
        if teacher:
            if kind == "!":
                return "".join(marks[k] for k in order) + body + "".join(marks[k] for k in reversed(order))
            return f"=={body}=="
        if kind:  # 학생용: 써 넣는 정답은 지우고 빈칸만 남긴다
            return " " * min(12, max(2, len(body) // 2))
        return body

    # 중괄호를 겹쳐 쓴 경우({{{{정답}}}})도 같은 표시로 본다
    text = re.sub(r"\{{3,}", "{{", text or "")
    text = re.sub(r"\}{3,}", "}}", text)
    return ANSWER_RE.sub(rep, text)


def _uid_all(el: etree._Element, b: Builder) -> None:
    for node in el.iter(HP + "p"):
        node.set("id", b._uid())
    for node in el.iter(HP + "tbl"):
        node.set("id", b._uid())


def _has_text(p: etree._Element) -> bool:
    return any((t.text or "").strip() or len(t) for t in p.iter(HP + "t"))


def _fill_cell(tc: etree._Element, text: str, b: Builder, align: str | None = None, size_pt: float | None = None) -> None:
    """칸 내용을 줄마다 문단으로 채운다.
    양식 칸의 첫 문단에 제목(예: <조 건>)이 있으면 첫 줄은 그 모양으로, 나머지 줄은 둘째 문단 모양으로 쓴다.
    align/size_pt를 주면 (제목 줄을 뺀) 내용 줄에 적용한다."""

    from .hwpx_writer import restyle_paragraph

    paras = _cell_paras(tc)
    if not paras:
        return
    sub = paras[0].getparent()
    titled = _has_text(paras[0])
    title_proto, body_proto = paras[0], (paras[1] if len(paras) > 1 else paras[0])
    for q in paras:
        sub.remove(q)
    for i, line in enumerate(text.split("\n") if text else [""]):
        is_title = titled and i == 0
        q = copy.deepcopy(title_proto if (is_title or not titled) else body_proto)
        q.set("id", b._uid())
        b._fill_plain(q, line)
        if not is_title and (align or size_pt):
            restyle_paragraph(q, b.styles, b.para_styles, align, size_pt)
        sub.append(q)


def _is_blank(p: etree._Element) -> bool:
    return not _has_text(p) and p.find(".//" + HP + "tbl") is None and p.find(".//" + HP + "ctrl") is None


def build_form(
    *,
    template: Path,
    form: dict[str, Any],
    sets: list[dict[str, Any]],
    out_path: Path,
    teacher: bool,
    highlight_color: str = "#FFFF00",
    style: dict[str, Any] | None = None,
    order: list[str] | None = None,
) -> Path:
    """sets[i]['layout'] = {"fills": {slot: text}, "remove_segments": [...]} 를 양식에 채운다.
    order: 하위 문항 순서(segment id 목록). style: form_style()."""

    st_cfg = form_style(style)
    pkg = HwpxPackage.open(template)
    b = Builder(pkg, {}, highlight_color, "numbering")
    sec = pkg.xml(form["section"])
    tops = sec.findall(HP + "p")
    bounds = form["block_bounds"]
    p0, p1 = bounds[form["proto_index"]]
    proto = [copy.deepcopy(p) for p in tops[p0:p1]]
    first_start = bounds[0][0]
    first_header = tops[first_start]
    anchor = tops[first_start - 1] if first_start > 0 else None
    tail_anchor = tops[bounds[-1][1]] if bounds[-1][1] < len(tops) else None

    keep_runs = [copy.deepcopy(r) for r in first_header.findall(HP + "run") if r.find(HP + "secPr") is not None or r.find(HP + "ctrl") is not None]
    first_page_break = first_header.get("pageBreak", "0")
    for p in tops[bounds[0][0]:bounds[-1][1]]:
        sec.remove(p)

    segs = form["segments"]
    seg_ids = [sg["id"] for sg in segs]
    order = [sid for sid in (order or []) if sid in seg_ids] + [sid for sid in seg_ids if sid not in (order or [])]
    first_seg = segs[0]["start"] if segs else len(proto)
    blank_proto = next((copy.deepcopy(p) for k, p in enumerate(proto) if k >= first_seg and _is_blank(p)), None)
    gap = st_cfg.get("gap_lines")
    box_align = st_cfg["box_align"]

    built: list[etree._Element] = []
    for i, st in enumerate(sets):
        layout = st.get("layout") or {}
        fills = {k: render_answers(v, teacher, st_cfg["hidden_style"]) for k, v in (layout.get("fills") or {}).items()}
        removed = set(layout.get("remove_segments") or [])
        block = [copy.deepcopy(p) for p in proto]
        for k, p in enumerate(block):
            _uid_all(p, b)
            if f"b{k}" in fills:
                b._fill_plain(p, fills[f"b{k}"])
            for j, tbl in enumerate(_direct_tables(p)):
                for r, c, tc in _cells(tbl):
                    key = f"b{k}.t{j}.r{r}c{c}"
                    if key in fills:
                        _fill_cell(tc, fills[key], b, box_align.get(key) or None)

        # 머리·지문 영역 + (정한 순서대로) 하위 문항. 문항 끝 빈 줄은 정리하고 gap_lines만큼 넣는다.
        out = block[:first_seg]
        for sid in order:
            if sid in removed:
                continue
            sg = next(x for x in segs if x["id"] == sid)
            part = block[sg["start"]:sg["end"]]
            if gap is not None:
                while len(part) > 1 and _is_blank(part[-1]):
                    part.pop()
                for _ in range(int(gap)):
                    if blank_proto is not None:
                        bp = copy.deepcopy(blank_proto)
                        bp.set("id", b._uid())
                        part.append(bp)
            out.extend(part)
        if i == 0:
            out[0].set("pageBreak", first_page_break)
            for r in reversed(keep_runs):
                out[0].insert(0, r)
        built.extend(out)

    if anchor is not None:
        for p in reversed(built):
            anchor.addnext(p)
    elif tail_anchor is not None:
        for p in built:
            tail_anchor.addprevious(p)
    else:
        for p in built:
            sec.append(p)

    # 앞쪽 지문별 박스(Logic Flow 등)
    front = form.get("front")
    fb = st_cfg["front_body"]
    if front:
        fsec = pkg.xml(front["section"])
        tables = list(fsec.iter(HP + "tbl"))
        for n, box in front["boxes"].items():
            idx = int(n) - 1
            tbl = tables[box["table"]]
            cells = {(r, c): tc for r, c, tc in _cells(tbl)}
            st = sets[idx] if idx < len(sets) else None
            fills = {k: render_answers(v, teacher, st_cfg["hidden_style"]) for k, v in ((st or {}).get("layout") or {}).get("fills", {}).items()}
            head, body = cells.get(tuple(box["head"])), cells.get(tuple(box["body"]))
            if head is not None:
                _fill_cell(head, fills.get("f.head", f"**[{n}]**") if st else "", b)
            if body is not None:
                body_paras = _cell_paras(body)
                if body_paras and _has_text(body_paras[0]):
                    # 예시 내용이 든 칸: 제목 줄로 오해하지 않도록 첫 문단만 원형으로 쓴다
                    for q in body_paras[1:]:
                        q.getparent().remove(q)
                    for t in body_paras[0].iter(HP + "t"):
                        t.text, t[:] = "", []
                _fill_cell(body, fills.get("f.body", "") if st else "", b, fb.get("align") or None, fb.get("size") or None)
        pkg.files[front["section"]] = etree.tostring(fsec, xml_declaration=True, encoding="UTF-8", standalone=True)

    pkg.files[form["section"]] = etree.tostring(sec, xml_declaration=True, encoding="UTF-8", standalone=True)
    pkg.files["Contents/header.xml"] = etree.tostring(b.header, xml_declaration=True, encoding="UTF-8", standalone=True)
    pkg.files.pop("Preview/PrvImage.png", None)
    from .hwpx_writer import _drop_manifest_entry

    _drop_manifest_entry(pkg, "Preview/PrvImage.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(pkg.to_bytes())
    return out_path
