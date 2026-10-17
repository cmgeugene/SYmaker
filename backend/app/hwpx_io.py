"""HWPX 읽기: 텍스트 추출, HWP→HWPX 변환, 서식(글머리표·번호·형광펜 등) 분석.

HWPX는 ZIP + OWPML XML이다.
- Contents/header.xml : 글자모양(charPr), 문단모양(paraPr), 번호(numbering), 글머리표(bullet), 스타일
- Contents/sectionN.xml : 본문. 형광펜은 글자 배경색이 아니라 `hp:t` 안의
  `hp:markpenBegin color=".."/` ~ `hp:markpenEnd/` 쌍으로 표현된다.

본문을 사람이/모델이 읽기 쉬운 '마크업 텍스트'로 바꿀 때 아래 표기를 쓴다.
  ==형광펜==   __밑줄__   **굵게**
"""

from __future__ import annotations

import io
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from lxml import etree

NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "opf": "http://www.idpf.org/2007/opf/",
}
HP = "{%s}" % NS["hp"]
HH = "{%s}" % NS["hh"]

NUM_FORMAT_LABELS = {
    "DIGIT": "1, 2, 3",
    "CIRCLED_DIGIT": "①, ②, ③",
    "ROMAN_CAPITAL": "I, II, III",
    "ROMAN_SMALL": "i, ii, iii",
    "LATIN_CAPITAL": "A, B, C",
    "LATIN_SMALL": "a, b, c",
    "CIRCLED_LATIN_SMALL": "ⓐ, ⓑ, ⓒ",
    "HANGUL_SYLLABLE": "가, 나, 다",
    "CIRCLED_HANGUL_SYLLABLE": "㉮, ㉯, ㉰",
    "HANGUL_JAMO": "ㄱ, ㄴ, ㄷ",
    "CIRCLED_HANGUL_JAMO": "㉠, ㉡, ㉢",
    "HANJA_DIGIT": "一, 二, 三",
}

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


# ---------------------------------------------------------------- 변환 / 추출

def convert_hwp_to_hwpx(src: Path, dst: Path) -> dict[str, Any]:
    """HWP 5.0 바이너리를 HWPX로 변환한다 (python-hwpx 순수 파이썬 변환기)."""

    from hwpx.hwp5.package import convert, to_hwpx_bytes

    converted = convert(src.read_bytes())
    dst.write_bytes(to_hwpx_bytes(converted.files))
    report = converted.report
    return {
        "unconverted": dict(getattr(report, "unconverted", {}) or {}),
        "dropped": dict(getattr(report, "dropped", {}) or {}),
    }


def extract_txt(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        pages.append(f"[{i}쪽]\n{text.strip()}")
    return "\n\n".join(pages)


class HwpxPackage:
    """HWPX ZIP을 메모리에 올려 XML 파트를 다룬다."""

    def __init__(self, data: bytes):
        self.files: dict[str, bytes] = {}
        self.infos: dict[str, zipfile.ZipInfo] = {}
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                self.files[info.filename] = zf.read(info.filename)
                self.infos[info.filename] = info

    @classmethod
    def open(cls, path: Path | str) -> "HwpxPackage":
        return cls(Path(path).read_bytes())

    def xml(self, name: str) -> etree._Element:
        return etree.fromstring(self.files[name])

    def section_names(self) -> list[str]:
        names = [n for n in self.files if re.fullmatch(r"Contents/section\d+\.xml", n)]
        return sorted(names, key=lambda n: int(re.findall(r"\d+", n)[-1]))

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # mimetype은 반드시 첫 번째, 무압축
            order = ["mimetype"] + [n for n in self.files if n != "mimetype"]
            for name in order:
                if name not in self.files:
                    continue
                method = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
                zf.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), self.files[name], compress_type=method)
        return buf.getvalue()


# ---------------------------------------------------------------- 헤더 해석

def parse_header(header: etree._Element) -> dict[str, Any]:
    fonts: dict[str, dict[str, str]] = {}
    for ff in header.iter(HH + "fontface"):
        lang = ff.get("lang", "")
        fonts[lang] = {f.get("id"): f.get("face") for f in ff.iter(HH + "font")}

    char_prs: dict[str, dict[str, Any]] = {}
    for cp in header.iter(HH + "charPr"):
        ul = cp.find(HH + "underline")
        fref = cp.find(HH + "fontRef")
        char_prs[cp.get("id")] = {
            "height": int(cp.get("height", "1000")) / 100,
            "color": cp.get("textColor"),
            "shade": cp.get("shadeColor"),
            "bold": cp.find(HH + "bold") is not None,
            "italic": cp.find(HH + "italic") is not None,
            "underline": ul is not None and ul.get("type", "NONE") != "NONE",
            "font": fonts.get("HANGUL", {}).get(fref.get("hangul")) if fref is not None else None,
            "latin_font": fonts.get("LATIN", {}).get(fref.get("latin")) if fref is not None else None,
        }

    numberings: dict[str, list[dict[str, Any]]] = {}
    for num in header.iter(HH + "numbering"):
        numberings[num.get("id")] = [
            {"level": int(h.get("level", "1")), "format": h.get("numFormat"), "text": h.text or ""}
            for h in num.findall(HH + "paraHead")
        ]

    bullets: dict[str, dict[str, Any]] = {}
    for b in header.iter(HH + "bullet"):
        bullets[b.get("id")] = {"char": b.get("char"), "checked_char": b.get("checkedChar")}

    para_prs: dict[str, dict[str, Any]] = {}
    for pp in header.iter(HH + "paraPr"):
        heading = pp.find(HH + "heading")
        align = pp.find(HH + "align")
        margin = pp.find(".//" + HH + "margin")
        left = indent = 0
        if margin is not None:
            l = margin.find("{%s}left" % NS["hc"])
            i = margin.find("{%s}intent" % NS["hc"])
            left = int(l.get("value", 0)) if l is not None else 0
            indent = int(i.get("value", 0)) if i is not None else 0
        para_prs[pp.get("id")] = {
            "heading_type": heading.get("type", "NONE") if heading is not None else "NONE",
            "heading_id": heading.get("idRef") if heading is not None else None,
            "heading_level": int(heading.get("level", 0)) if heading is not None else 0,
            "align": align.get("horizontal") if align is not None else None,
            "left": left,
            "indent": indent,
        }

    styles = {s.get("id"): s.get("name") for s in header.iter(HH + "style")}
    return {
        "char_prs": char_prs,
        "para_prs": para_prs,
        "numberings": numberings,
        "bullets": bullets,
        "styles": styles,
    }


def describe_heading(pp: dict[str, Any] | None, hdr: dict[str, Any]) -> str | None:
    if not pp or pp["heading_type"] in (None, "NONE"):
        return None
    if pp["heading_type"] == "BULLET":
        b = hdr["bullets"].get(pp["heading_id"] or "", {})
        return f"글머리표 '{b.get('char', '?')}'"
    if pp["heading_type"] in ("NUMBER", "OUTLINE"):
        levels = hdr["numberings"].get(pp["heading_id"] or "", [])
        lvl = next((l for l in levels if l["level"] == pp["heading_level"] + 1), levels[0] if levels else None)
        kind = "개요 번호" if pp["heading_type"] == "OUTLINE" else "문단 번호"
        if lvl:
            return f"{kind} {lvl['text']} ({NUM_FORMAT_LABELS.get(lvl['format'], lvl['format'])})"
        return kind
    return pp["heading_type"]


# ---------------------------------------------------------------- 본문 해석

def run_markup_text(run: etree._Element, cp: dict[str, Any] | None, marks: Counter) -> str:
    """한 run의 텍스트를 마크업(==형광펜==, __밑줄__, **굵게**)으로 바꾼다."""

    parts: list[str] = []
    for t in run.findall(HP + "t"):
        buf = [t.text or ""]
        for child in t:
            tag = etree.QName(child).localname
            if tag == "markpenBegin":
                buf.append("==")
                marks[child.get("color", "#FFFF00").upper()] += 1
            elif tag == "markpenEnd":
                buf.append("==")
            elif tag == "tab":
                buf.append("\t")
            elif tag == "lineBreak":
                buf.append("\n")
            elif tag in ("nbSpace", "fwSpace"):
                buf.append(" ")
            buf.append(child.tail or "")
        parts.append("".join(buf))
    text = "".join(parts)
    if text.strip() and cp:
        if cp.get("underline"):
            text = f"__{text}__"
        if cp.get("bold"):
            text = f"**{text}**"
    return text


def paragraph_text(p: etree._Element, hdr: dict[str, Any], marks: Counter, markup: bool = True) -> str:
    out = []
    for run in p.findall(HP + "run"):
        cp = hdr["char_prs"].get(run.get("charPrIDRef")) if markup else None
        out.append(run_markup_text(run, cp, marks))
    return "".join(out)


def nested_paragraphs(p: etree._Element) -> list[etree._Element]:
    """표·글상자 안 문단들 (top-level 문단 내부)."""

    return [q for q in p.iter(HP + "p") if q is not p]


def analyze_hwpx(path: Path | str) -> dict[str, Any]:
    """HWPX 서식을 결정론적으로 분석한다. (모델 분석의 입력이자 출력 템플릿의 근거)"""

    pkg = HwpxPackage.open(path)
    hdr = parse_header(pkg.xml("Contents/header.xml"))
    marks: Counter = Counter()
    mark_examples: dict[str, list[str]] = {}
    heading_usage: Counter = Counter()
    char_usage: Counter = Counter()
    paragraphs: list[dict[str, Any]] = []

    for sec_index, name in enumerate(pkg.section_names()):
        sec = pkg.xml(name)
        for idx, p in enumerate(sec.findall(HP + "p")):
            pp_id = p.get("paraPrIDRef")
            pp = hdr["para_prs"].get(pp_id)
            heading = describe_heading(pp, hdr)
            if heading:
                heading_usage[heading] += 1
            before = Counter(marks)
            text = paragraph_text(p, hdr, marks)
            for color in marks - before:
                for m in re.findall(r"==(.+?)==", text):
                    mark_examples.setdefault(color, [])
                    if len(mark_examples[color]) < 5:
                        mark_examples[color].append(m[:60])
            runs = []
            for run in p.findall(HP + "run"):
                cp_id = run.get("charPrIDRef")
                rt = "".join(t.xpath("string()") for t in run.findall(HP + "t"))
                if rt.strip():
                    char_usage[cp_id] += len(rt)
                    runs.append({"charPr": cp_id, "text": rt[:40]})
            inner = nested_paragraphs(p)
            has_table = p.find(".//" + HP + "tbl") is not None
            has_box = p.find(".//" + HP + "drawText") is not None
            inner_texts = []
            for q in inner:
                qt = paragraph_text(q, hdr, marks)
                if qt.strip():
                    inner_texts.append(qt)
                qpp = hdr["para_prs"].get(q.get("paraPrIDRef"))
                qh = describe_heading(qpp, hdr)
                if qh:
                    heading_usage[qh] += 1
            if sec_index > 0:
                continue  # 출력 템플릿은 첫 구역만 사용
            paragraphs.append(
                {
                    "index": idx,
                    "paraPr": pp_id,
                    "style": hdr["styles"].get(p.get("styleIDRef")),
                    "heading": heading,
                    "align": pp["align"] if pp else None,
                    "text": text if not inner else (text + " " + " / ".join(inner_texts)).strip(),
                    "runs": runs[:6],
                    "container": "table" if has_table else ("box" if has_box else None),
                    "page_break": p.get("pageBreak") == "1",
                }
            )

    char_summary = []
    for cp_id, n in char_usage.most_common(8):
        cp = hdr["char_prs"].get(cp_id, {})
        char_summary.append({"id": cp_id, "chars": n, **cp})

    full_text = "\n".join(p["text"] for p in paragraphs)
    circled_choices = sum(full_text.count(c) for c in CIRCLED[:5])
    return {
        "paragraph_count": len(paragraphs),
        "paragraphs": paragraphs,
        "highlights": [
            {"color": color, "count": n, "examples": mark_examples.get(color, [])}
            for color, n in marks.most_common()
        ],
        "headings": [{"label": k, "count": v} for k, v in heading_usage.most_common()],
        "bullets_defined": list(hdr["bullets"].values()),
        "numberings_defined": [
            {"id": k, "levels": [f"{l['text']} ({NUM_FORMAT_LABELS.get(l['format'], l['format'])})" for l in v[:3]]}
            for k, v in hdr["numberings"].items()
        ],
        "char_styles": char_summary,
        "circled_number_count": circled_choices,
        "underline_used": any(c.get("underline") for c in char_summary),
        "bold_used": any(c.get("bold") for c in char_summary),
    }


def hwpx_plain_text(path: Path | str) -> str:
    pkg = HwpxPackage.open(path)
    hdr = parse_header(pkg.xml("Contents/header.xml"))
    marks: Counter = Counter()
    lines = []
    for name in pkg.section_names():
        sec = pkg.xml(name)
        for p in sec.findall(HP + "p"):
            inner = nested_paragraphs(p)
            text = paragraph_text(p, hdr, marks)
            if text.strip():
                lines.append(text)
            for q in inner:
                qt = paragraph_text(q, hdr, marks)
                if qt.strip():
                    lines.append("  │ " + qt)
            if not text.strip() and not inner:
                lines.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def format_summary_text(fmt: dict[str, Any]) -> str:
    """모델 프롬프트용 서식 요약."""

    lines = []
    if fmt.get("highlights"):
        for h in fmt["highlights"]:
            lines.append(f"- 형광펜(markpen) {h['color']}: {h['count']}회, 예) {', '.join(h['examples'][:3])}")
    else:
        lines.append("- 형광펜: 사용 안 함")
    for h in fmt.get("headings", []):
        lines.append(f"- 문단 머리: {h['label']} — {h['count']}개 문단")
    lines.append(f"- 원문자 번호(①~⑤) 텍스트 등장: {fmt.get('circled_number_count', 0)}회")
    for c in fmt.get("char_styles", [])[:5]:
        flags = ",".join(f for f, on in (("굵게", c.get("bold")), ("밑줄", c.get("underline")), ("기울임", c.get("italic"))) if on)
        lines.append(f"- 글자모양 #{c['id']}: {c.get('font')}/{c.get('latin_font')} {c.get('height')}pt {flags} ({c['chars']}자)")
    return "\n".join(lines)


def paragraph_table_text(fmt: dict[str, Any], limit: int = 160) -> str:
    """역할 지정(role map)을 위해 모델에게 보여줄 문단 목록."""

    rows = []
    for p in fmt["paragraphs"][:limit]:
        text = p["text"].replace("\n", " ⏎ ")
        if len(text) > 120:
            text = text[:120] + "…"
        meta = [f"style={p['style']}"]
        if p["heading"]:
            meta.append(p["heading"])
        if p["container"]:
            meta.append(f"[{p['container']}]")
        if p["page_break"]:
            meta.append("쪽나눔")
        rows.append(f"#{p['index']} ({'; '.join(meta)}) {text}")
    return "\n".join(rows)
