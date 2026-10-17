"""HWPX 출력: 샘플 문서를 템플릿으로 삼아 문항을 채운 새 HWPX를 만든다.

방식
- 샘플(또는 기본 빈 문서)의 header.xml(글꼴·글자모양·문단모양·번호 정의)을 그대로 유지한다.
- 분석 단계에서 정한 역할 지도(role_map: 발문/지문/선택지/해설 … → 샘플 문단 번호)를 따라
  해당 샘플 문단을 '복제'하고 텍스트만 바꿔 넣는다. 그래서 글머리표·문단번호·들여쓰기·
  지문 박스(표) 같은 서식이 그대로 이어진다.
- 마크업 ==형광펜== 은 한글의 형광펜 서식(hp:markpenBegin/End)으로,
  __밑줄__ / **굵게** 는 기존 글자모양을 복제해 밑줄/굵게만 바꾼 charPr로 변환한다.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from lxml import etree

from .hwpx_io import CIRCLED, HH, HP, NS, HwpxPackage, parse_header

SKELETON = Path(__file__).resolve().parent / "assets" / "Skeleton.hwpx"
ROLES = ("title", "instruction", "passage", "choice", "answer", "explanation")
# 밑줄 표시는 정확히 밑줄 2개(__)만. 빈칸 "__________"(3개 이상)은 글자 그대로 둔다.
TOKEN_RE = re.compile(r"(\*\*|(?<!_)__(?!_)|==|!!)")


def default_template() -> Path:
    if SKELETON.exists():
        return SKELETON
    import hwpx

    return Path(hwpx.__file__).parent / "data" / "Skeleton.hwpx"


# ---------------------------------------------------------------- 마크업

def parse_markup(text: str) -> list[tuple[str, frozenset[str]]]:
    """'**굵게** __밑줄__ ==형광펜==' → [(텍스트, {bold, underline, highlight})]"""

    segments: list[tuple[str, frozenset[str]]] = []
    active: set[str] = set()
    names = {"**": "bold", "__": "underline", "==": "highlight", "!!": "white"}
    for piece in TOKEN_RE.split(text):
        if piece in names:
            name = names[piece]
            active.symmetric_difference_update({name})
            continue
        if piece:
            segments.append((piece, frozenset(active)))
    return segments


def strip_markup(text: str) -> str:
    return TOKEN_RE.sub("", text)


# ---------------------------------------------------------------- 글자모양 파생

class CharStyles:
    """기존 charPr를 바탕으로 굵게/밑줄/글자색/글자 크기 변형을 찾거나 새로 만든다."""

    def __init__(self, header: etree._Element):
        self.header = header
        self.container = header.find(".//" + HH + "charProperties")
        self.cache: dict[tuple, str] = {}

    def _signature(self, cp: etree._Element) -> bytes:
        clone = copy.deepcopy(cp)
        for attr in ("id", "textColor", "height"):
            clone.attrib.pop(attr, None)
        for tag in ("bold", "underline"):
            for el in clone.findall(HH + tag):
                clone.remove(el)
        return etree.tostring(clone, method="c14n")

    def _flags(self, cp: etree._Element) -> tuple[bool, bool, str, str]:
        ul = cp.find(HH + "underline")
        return (cp.find(HH + "bold") is not None, ul is not None and ul.get("type", "NONE") != "NONE",
                (cp.get("textColor") or "#000000").upper(), cp.get("height", "1000"))

    def derive(self, base_id: str, bold: bool, underline: bool, color: str | None = None, size_pt: float | None = None) -> str:
        """굵게·밑줄은 '켜기'만 한다(원래 켜져 있으면 유지). 색·크기는 주면 바꾼다."""

        key = (base_id, bold, underline, color, size_pt)
        if key in self.cache:
            return self.cache[key]
        items = {cp.get("id"): cp for cp in self.container.findall(HH + "charPr")}
        base = items.get(base_id)
        if base is None:
            return base_id
        b_bold, b_ul, b_color, b_height = self._flags(base)
        want = (bold or b_bold, underline or b_ul, (color or b_color).upper(),
                str(int(round(size_pt * 100))) if size_pt else b_height)
        if want == (b_bold, b_ul, b_color, b_height):
            self.cache[key] = base_id
            return base_id
        sig = self._signature(base)
        for cid, cp in items.items():
            if self._flags(cp) == want and self._signature(cp) == sig:
                self.cache[key] = cid
                return cid
        new = copy.deepcopy(base)
        new_id = str(max(int(i) for i in items) + 1)
        new.set("id", new_id)
        new.set("textColor", want[2])
        new.set("height", want[3])
        for el in new.findall(HH + "bold"):
            new.remove(el)
        ul = new.find(HH + "underline")
        if ul is None:
            ul = etree.SubElement(new, HH + "underline")
        ul.set("type", "BOTTOM" if want[1] else "NONE")
        ul.set("shape", ul.get("shape", "SOLID"))
        ul.set("color", ul.get("color", "#000000"))
        if want[0]:
            ul.addprevious(etree.Element(HH + "bold"))
        self.container.append(new)
        self.container.set("itemCnt", str(len(self.container.findall(HH + "charPr"))))
        self.cache[key] = new_id
        return new_id


class ParaStyles:
    """기존 paraPr를 바탕으로 정렬만 바꾼 문단 모양을 찾거나 새로 만든다."""

    def __init__(self, header: etree._Element):
        self.container = header.find(".//" + HH + "paraProperties")
        self.cache: dict[tuple[str, str], str] = {}

    def derive(self, base_id: str, align: str) -> str:
        key = (base_id, align)
        if key in self.cache:
            return self.cache[key]
        items = {pp.get("id"): pp for pp in self.container.findall(HH + "paraPr")}
        base = items.get(base_id)
        if base is None or base.find(HH + "align") is None:
            return base_id
        if base.find(HH + "align").get("horizontal") == align:
            self.cache[key] = base_id
            return base_id
        new = copy.deepcopy(base)
        new_id = str(max(int(i) for i in items) + 1)
        new.set("id", new_id)
        new.find(HH + "align").set("horizontal", align)
        self.container.append(new)
        self.container.set("itemCnt", str(len(self.container.findall(HH + "paraPr"))))
        self.cache[key] = new_id
        return new_id


def restyle_paragraph(p: etree._Element, chars: CharStyles, paras: ParaStyles, align: str | None = None, size_pt: float | None = None) -> None:
    """문단의 정렬과 글자 크기를 바꾼다 (굵게·밑줄·색 등 다른 모양은 유지)."""

    if align:
        p.set("paraPrIDRef", paras.derive(p.get("paraPrIDRef", "0"), align))
    if size_pt:
        for run in p.findall(HP + "run"):
            run.set("charPrIDRef", chars.derive(run.get("charPrIDRef", "0"), False, False, None, size_pt))


# ---------------------------------------------------------------- 문단 채우기

class Builder:
    def __init__(self, pkg: HwpxPackage, role_map: dict[str, int], highlight_color: str, choice_marker: str):
        self.pkg = pkg
        self.header = pkg.xml("Contents/header.xml")
        self.hdr = parse_header(self.header)
        self.styles = CharStyles(self.header)
        self.para_styles = ParaStyles(self.header)
        self.section = pkg.xml("Contents/section0.xml")
        self.top = self.section.findall(HP + "p")
        self.role_map = role_map
        self.highlight_color = highlight_color or "#FFFF00"
        self.choice_marker = choice_marker or "circled"
        self.next_id = 2_000_000_000 // 2
        self.protos = {role: self._proto(role) for role in ROLES}

    def _proto(self, role: str) -> etree._Element:
        idx = self.role_map.get(role, -1)
        fallback = {"answer": "instruction", "explanation": "passage", "title": "instruction"}
        if idx is None or idx < 0 or idx >= len(self.top):
            if role in fallback and self.role_map.get(fallback[role], -1) not in (None, -1):
                return self._proto(fallback[role])
            idx = 0
        p = copy.deepcopy(self.top[idx])
        # 첫 문단의 구역 정의(secPr)·단 정의는 복제하지 않는다
        for run in p.findall(HP + "run"):
            for tag in ("secPr", "ctrl"):
                for el in run.findall(HP + tag):
                    if tag == "secPr" or el.find(HP + "colPr") is not None:
                        run.remove(el)
        p.set("pageBreak", "0")
        p.set("columnBreak", "0")
        return p

    def heading_type(self, p: etree._Element) -> str:
        pp = self.hdr["para_prs"].get(p.get("paraPrIDRef"), {})
        return pp.get("heading_type", "NONE")

    def _uid(self) -> str:
        self.next_id += 1
        return str(self.next_id)

    @staticmethod
    def _text_runs(p: etree._Element) -> list[etree._Element]:
        return [r for r in p.findall(HP + "run") if "".join(r.itertext()).strip()]

    def _fill_plain(self, p: etree._Element, text: str) -> None:
        """문단(표/글상자 없는)의 run들을 마크업 텍스트로 교체."""

        runs = p.findall(HP + "run")
        text_runs = self._text_runs(p)
        base_run = text_runs[0] if text_runs else (runs[0] if runs else None)
        base_cp = base_run.get("charPrIDRef", "0") if base_run is not None else "0"

        # 샘플이 '1. ' 같은 번호를 별도 글자모양(예: 굵게)으로 썼다면 그 모양을 따른다
        prefix_cp = None
        if len(text_runs) >= 2 and re.match(r"^\s*(\d+[.)]|[①-⑩]|\(\d+\))\s*$", "".join(text_runs[0].itertext())):
            prefix_cp = text_runs[0].get("charPrIDRef")
            base_cp = text_runs[1].get("charPrIDRef", base_cp)

        keep = [r for r in runs if any(etree.QName(c).localname not in ("t",) for c in r)]
        for r in runs:
            p.remove(r)
        for el in p.findall(HP + "linesegarray"):
            p.remove(el)
        insert_at = 0
        for r in keep:  # 컨트롤만 남긴 run(각주/필드 등)은 텍스트 제거 후 유지
            for t in r.findall(HP + "t"):
                r.remove(t)
            if len(r):
                p.insert(insert_at, r)
                insert_at += 1

        segments = parse_markup(text)
        if prefix_cp:
            m = re.match(r"^(\s*(?:\d+[.)]|[①-⑩]|\(\d+\))\s*)", strip_markup(text))
            if m and segments and segments[0][0].startswith(m.group(1)):
                first, flags = segments[0]
                segments = [(m.group(1), frozenset({"__prefix__"}))] + (
                    [(first[len(m.group(1)):], flags)] if first[len(m.group(1)):] else []
                ) + segments[1:]
        if not segments:
            segments = [("", frozenset())]

        for seg_text, flags in segments:
            if "__prefix__" in flags:
                cp = prefix_cp
            else:
                cp = self.styles.derive(base_cp, "bold" in flags, "underline" in flags, "#FFFFFF" if "white" in flags else None)
            run = etree.Element(HP + "run", charPrIDRef=str(cp))
            t = etree.SubElement(run, HP + "t")
            target = t
            if "highlight" in flags:
                etree.SubElement(t, HP + "markpenBegin", color=self.highlight_color)
            lines = seg_text.split("\n")
            for i, line in enumerate(lines):
                if i > 0:
                    target = etree.SubElement(t, HP + "lineBreak")
                    target.tail = ""
                if target is t and len(t) == 0:
                    t.text = (t.text or "") + line
                elif target is t:
                    last = t[-1]
                    last.tail = (last.tail or "") + line
                else:
                    target.tail = (target.tail or "") + line
            if "highlight" in flags:
                etree.SubElement(t, HP + "markpenEnd")
            p.append(run)

    def make(self, role: str, text: str) -> etree._Element:
        """역할 원형을 복제해 텍스트를 채운 top-level 문단을 만든다."""

        p = copy.deepcopy(self.protos[role])
        p.set("id", self._uid())
        inner = [q for q in p.iter(HP + "p") if q is not p]
        if inner:
            # 지문 박스(표/글상자): 첫 내부 문단을 원형으로 삼아 줄마다 복제
            container = inner[0].getparent()
            proto = inner[0]
            for q in inner:
                if q.getparent() is container:
                    container.remove(q)
            for line in text.split("\n"):
                q = copy.deepcopy(proto)
                q.set("id", self._uid())
                for nested in [n for n in q.iter(HP + "p") if n is not q]:
                    nested.getparent().remove(nested)
                self._fill_plain(q, line)
                container.append(q)
            for el in p.findall(HP + "linesegarray"):
                p.remove(el)
            return p
        self._fill_plain(p, text)
        return p

    def blank(self) -> etree._Element:
        return self.make("passage" if self.role_map.get("passage", -1) >= 0 and not self._has_container("passage") else "instruction", "")

    def _has_container(self, role: str) -> bool:
        p = self.protos[role]
        return any(q is not p for q in p.iter(HP + "p"))


def is_essay(q: dict[str, Any]) -> bool:
    return q.get("kind") == "서술형" or (not q.get("kind") and not q.get("choices"))


def question_label(q: dict[str, Any], items: list[dict[str, Any]]) -> str:
    """객관식은 '7.', 서술형은 서술형끼리 따로 번호를 매겨 '[서술형 2]'."""

    if is_essay(q):
        k = [x for x in items if is_essay(x)].index(q) + 1
        return f"[서술형 {k}]"
    return f"{q.get('number')}."


def _fmt_points(p: Any) -> str:
    try:
        f = float(p)
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        return str(p)


def choice_prefix(i: int, marker: str) -> str:
    if marker == "numbering":
        return ""
    if marker == "paren":
        return f"({i + 1}) "
    if marker == "digit":
        return f"{i + 1}. "
    return f"{CIRCLED[i]} "


def answer_label(answer: str) -> str:
    a = (answer or "").strip()
    if a.isascii() and a.isdigit() and 1 <= int(a) <= 10:
        return CIRCLED[int(a) - 1]
    return a


def build_hwpx(
    *,
    template: Path | None,
    role_map: dict[str, int] | None,
    questions: dict[str, Any],
    out_path: Path,
    mode: str = "questions",  # questions | answers | both
    highlight_color: str = "#FFFF00",
    choice_marker: str = "circled",
    keep_preamble: bool = True,
    essay_lines: int = 4,
) -> Path:
    template = template or default_template()
    role_map = dict(role_map or {})
    pkg = HwpxPackage.open(template)
    b = Builder(pkg, role_map, highlight_color, choice_marker)

    sec = b.section
    preamble_end = int(role_map.get("preamble_end", 0) or 0) if keep_preamble else 0
    preamble_end = max(0, min(preamble_end, len(b.top)))
    title_idx = role_map.get("title", -1)

    # 본문 비우기 (머리 영역은 유지)
    for p in b.top[max(1, preamble_end):]:
        sec.remove(p)
    first = b.top[0]
    if preamble_end == 0:
        # 첫 문단은 구역/단 정의를 갖고 있으므로 텍스트만 비우고 남긴다
        for run in first.findall(HP + "run"):
            for t in run.findall(HP + "t"):
                run.remove(t)
        for el in first.findall(HP + "linesegarray"):
            first.remove(el)
    for p in b.top[:preamble_end]:
        for el in p.iter(HP + "linesegarray"):
            el.getparent().remove(el)

    title = questions.get("title") or ""
    if title and title_idx is not None and 0 <= title_idx < preamble_end:
        tp = b.top[title_idx]
        if not any(q is not tp for q in tp.iter(HP + "p")) and tp.find(".//" + HP + "secPr") is None:
            b._fill_plain(tp, title)
        title = ""

    out: list[etree._Element] = []
    items = questions.get("questions", [])
    instr_numbered = b.heading_type(b.protos["instruction"]) in ("NUMBER", "OUTLINE")
    choice_numbered = b.heading_type(b.protos["choice"]) in ("NUMBER", "OUTLINE")
    marker = "numbering" if choice_numbered else choice_marker

    if mode in ("questions", "both"):
        if title:
            out.append(b.make("title", title))
            out.append(b.blank())
        for q in items:
            label = question_label(q, items)
            instruction = q.get("instruction", "")
            if is_essay(q) and q.get("points"):
                instruction += f" ({_fmt_points(q['points'])}점)"
            if not instr_numbered or is_essay(q):
                instruction = f"{label} {instruction}"
            out.append(b.make("instruction", instruction))
            passage = (q.get("passage") or "").strip("\n")
            if passage:
                out.append(b.make("passage", passage))
            for i, choice in enumerate(q.get("choices") or []):
                out.append(b.make("choice", choice_prefix(i, marker) + choice))
            if is_essay(q):  # 답 쓸 공간
                out.extend(b.blank() for _ in range(essay_lines))
            out.append(b.blank())

    if mode in ("answers", "both"):
        head = b.make("title", "정답 및 해설" if not questions.get("title") else f"{strip_markup(questions['title'])} — 정답 및 해설")
        if mode == "both" and out:
            head.set("pageBreak", "1")
        out.append(head)
        out.append(b.blank())
        for q in items:
            label = question_label(q, items)
            if is_essay(q):
                out.append(b.make("answer", f"{label} 모범답안"))
                out.append(b.make("explanation", str(q.get("answer", ""))))
                if q.get("rubric"):
                    pts = f" ({_fmt_points(q['points'])}점)" if q.get("points") else ""
                    out.append(b.make("explanation", f"〈채점 기준{pts}〉\n{q['rubric']}"))
            else:
                out.append(b.make("answer", f"{label} 정답 {answer_label(str(q.get('answer', '')))}"))
            if q.get("explanation"):
                out.append(b.make("explanation", q["explanation"]))
            out.append(b.blank())

    anchor = b.top[preamble_end - 1] if preamble_end > 0 else first
    for p in reversed(out):
        anchor.addnext(p)

    # 첫 구역만 사용 → 나머지 구역 제거
    extra = [n for n in pkg.section_names() if n != "Contents/section0.xml"]
    if extra:
        hpf = pkg.xml("Contents/content.hpf")
        for name in extra:
            pkg.files.pop(name, None)
            href = name.split("/", 1)[1]
            for item in hpf.iter("{%s}item" % NS["opf"]):
                if item.get("href") in (name, href):
                    item_id = item.get("id")
                    item.getparent().remove(item)
                    for ref in hpf.iter("{%s}itemref" % NS["opf"]):
                        if ref.get("idref") == item_id:
                            ref.getparent().remove(ref)
        pkg.files["Contents/content.hpf"] = etree.tostring(hpf, xml_declaration=True, encoding="UTF-8", standalone=True)
        b.header.set("secCnt", "1")

    pkg.files["Contents/header.xml"] = etree.tostring(b.header, xml_declaration=True, encoding="UTF-8", standalone=True)
    pkg.files["Contents/section0.xml"] = etree.tostring(sec, xml_declaration=True, encoding="UTF-8", standalone=True)
    pkg.files.pop("Preview/PrvImage.png", None)
    if "Preview/PrvText.txt" in pkg.files:
        preview = "\n".join(strip_markup(q.get("instruction", "")) for q in items[:20])
        pkg.files["Preview/PrvText.txt"] = preview.encode("utf-8")
    _drop_manifest_entry(pkg, "Preview/PrvImage.png")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(pkg.to_bytes())
    return out_path


def _drop_manifest_entry(pkg: HwpxPackage, name: str) -> None:
    if "Contents/content.hpf" not in pkg.files:
        return
    hpf = pkg.xml("Contents/content.hpf")
    changed = False
    for item in list(hpf.iter("{%s}item" % NS["opf"])):
        if item.get("href") == name:
            item.getparent().remove(item)
            changed = True
    if changed:
        pkg.files["Contents/content.hpf"] = etree.tostring(hpf, xml_declaration=True, encoding="UTF-8", standalone=True)
