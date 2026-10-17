"""프로젝트 자료실·본문·세트 그룹·본문 배정 API."""

from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from . import allocation, codex, db, guidelines, materials

router = APIRouter()
PROJ_DIR = db.DATA_DIR / "projects"
_tasks: set[asyncio.Task] = set()


def _404(obj: Any, what: str) -> Any:
    if not obj:
        raise HTTPException(404, f"{what}을(를) 찾을 수 없습니다.")
    return obj


def _project(pid: int) -> dict[str, Any]:
    return _404(db.query_one("SELECT * FROM projects WHERE id = ?", (pid,)), "프로젝트")


def _pfile(fid: int) -> dict[str, Any]:
    return _404(db.query_one("SELECT * FROM project_files WHERE id = ?", (fid,)), "자료")


def file_summary(f: dict[str, Any]) -> dict[str, Any]:
    fmt = f.get("format") or {}
    n = db.query_one("SELECT COUNT(*) AS n, SUM(excluded) AS ex, SUM(1 - located) AS lost FROM passages WHERE file_id = ?", (f["id"],))
    return {
        "id": f["id"],
        "kind": f["kind"],
        "orig_name": f["orig_name"],
        "note": f.get("note") or "",
        "scope": f.get("scope") or "range",
        "use_mode": f.get("use_mode") or "adapt",
        "paraphrase": materials.paraphrase_cfg(f.get("paraphrase")),
        "has_hwpx": bool(f.get("hwpx_path")),
        "text_length": len(f.get("text") or ""),
        "preview": (f.get("text") or "")[:300],
        "segmented_at": f.get("segmented_at"),
        "passage_count": n["n"] or 0,
        "excluded_count": n["ex"] or 0,
        "unlocated_count": n["lost"] or 0,
        "format_brief": {"highlights": fmt.get("highlights", []), "headings": fmt.get("headings", [])[:5]} if fmt else None,
        "created_at": f["created_at"],
    }


# ---------------------------------------------------------------- 자료실

@router.get("/api/projects/{pid}/materials")
def get_materials(pid: int) -> dict[str, Any]:
    _project(pid)
    use = materials.usage(pid)
    by_passage: dict[int, list[dict[str, Any]]] = {}
    for u in use:
        by_passage.setdefault(u["passage_id"], []).append({"workbook_id": u["workbook_id"], "workbook": u["workbook"], "type": u["type"]})
    passages = [
        {k: v for k, v in p.items() if k not in ("project_id",)} | {"usage": by_passage.get(p["id"], [])}
        for p in materials.passages(pid)
    ]
    jobs = db.query("SELECT id, stage, status, error, created_at, finished_at FROM jobs WHERE project_id = ? ORDER BY id DESC LIMIT 10", (pid,))
    return {
        "files": [file_summary(f) for f in materials.project_files(pid)],
        "passages": passages,
        "jobs": jobs,
        "scopes": materials.SCOPES,
        "use_modes": materials.USE_MODES,
        "paraphrase_lengths": {k: v[0] for k, v in materials.PARAPHRASE_LENGTHS.items()},
        "paraphrase_levels": {k: v[0] for k, v in materials.PARAPHRASE_LEVELS.items()},
    }


@router.post("/api/projects/{pid}/files")
async def upload_project_file(pid: int, kind: str = Form("reference"), file: UploadFile = File(...)) -> dict[str, Any]:
    _project(pid)
    name = file.filename or "file"
    if Path(name).suffix.lower() not in materials.ACCEPT:
        raise HTTPException(400, "txt, pdf, hwp, hwpx 파일만 올릴 수 있습니다.")
    folder = PROJ_DIR / str(pid) / "files"
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{uuid.uuid4().hex[:8]}_{re.sub(r'[^\w.\-가-힣]', '_', name)}"
    stored.write_bytes(await file.read())
    try:
        text, hwpx_path, fmt = await materials.ingest(stored)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"파일을 읽지 못했습니다: {exc}") from exc
    fid = db.execute(
        "INSERT INTO project_files(project_id, kind, orig_name, stored_path, hwpx_path, text, format_json, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (pid, kind, name, str(stored), str(hwpx_path) if hwpx_path else None, text, db.dumps(fmt) if fmt else None, db.now()),
    )
    return file_summary(_pfile(fid))


@router.get("/api/project-files/{fid}")
def get_project_file(fid: int) -> dict[str, Any]:
    f = _pfile(fid)
    return {**file_summary(f), "text": f["text"], "format": f.get("format")}


@router.put("/api/project-files/{fid}")
def update_project_file(fid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    f = _pfile(fid)
    db.execute(
        "UPDATE project_files SET kind=?, note=?, scope=?, use_mode=?, paraphrase_json=? WHERE id=?",
        (body.get("kind", f["kind"]), body.get("note", f["note"]), body.get("scope", f["scope"]), body.get("use_mode", f["use_mode"]),
         db.dumps(materials.paraphrase_cfg(body.get("paraphrase", f.get("paraphrase")))), fid),
    )
    return file_summary(_pfile(fid))


@router.delete("/api/project-files/{fid}")
def delete_project_file(fid: int) -> dict[str, bool]:
    f = _pfile(fid)
    for p in {f["stored_path"], f.get("hwpx_path")}:
        if p:
            Path(p).unlink(missing_ok=True)
    db.execute("DELETE FROM passages WHERE file_id = ?", (fid,))
    db.execute("DELETE FROM project_files WHERE id = ?", (fid,))
    return {"ok": True}


@router.get("/api/project-files/{fid}/download")
def download_project_file(fid: int, hwpx: bool = False) -> FileResponse:
    f = _pfile(fid)
    path = f["hwpx_path"] if hwpx and f.get("hwpx_path") else f["stored_path"]
    return FileResponse(path, filename=Path(f["orig_name"]).stem + (".hwpx" if hwpx else Path(f["orig_name"]).suffix))


# ---------------------------------------------------------------- 본문

@router.post("/api/projects/{pid}/segment")
async def segment(pid: int, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    _project(pid)
    if db.query_one("SELECT id FROM jobs WHERE project_id = ? AND status IN ('queued','running')", (pid,)):
        raise HTTPException(409, "이미 본문 나누기가 진행 중입니다.")
    files = [f for f in materials.project_files(pid) if f["kind"] == "reference" and (f.get("scope") or "range") != "exclude"]
    if body.get("file_ids"):
        files = [f for f in files if f["id"] in body["file_ids"]]
    if not files:
        raise HTTPException(400, "본문을 나눌 자료가 없습니다. 출제 범위 자료를 먼저 올리세요.")
    cfg = codex.stage_settings()["segment"]
    model, effort = body.get("model") or cfg["model"], body.get("effort") or cfg["effort"]
    types = sorted({t["name"] for w in db.query("SELECT analysis_json FROM workbooks WHERE project_id = ?", (pid,)) for t in (w.get("analysis") or {}).get("question_types", [])} | set(materials.DEFAULT_TYPES))
    jid = db.execute(
        "INSERT INTO jobs(project_id, stage, status, model, effort, log, created_at) VALUES(?,?,?,?,?,?,?)",
        (pid, "segment", "running", model, effort, "", db.now()),
    )
    task = asyncio.create_task(materials.segment_job(jid, pid, [f["id"] for f in files], model, effort, types))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return db.query_one("SELECT * FROM jobs WHERE id = ?", (jid,))  # type: ignore[return-value]


@router.put("/api/passages/{ppid}")
def update_passage(ppid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    p = _404(db.query_one("SELECT * FROM passages WHERE id = ?", (ppid,)), "본문")
    db.execute(
        "UPDATE passages SET label=?, text=?, excluded=?, suitable_types_json=?, located=? WHERE id=?",
        (
            body.get("label", p["label"]),
            body.get("text", p["text"]),
            int(body.get("excluded", p["excluded"])),
            db.dumps(body.get("suitable_types", p.get("suitable_types") or [])),
            1 if "text" in body else p["located"],
            ppid,
        ),
    )
    return db.query_one("SELECT * FROM passages WHERE id = ?", (ppid,))  # type: ignore[return-value]


@router.delete("/api/passages/{ppid}")
def delete_passage(ppid: int) -> dict[str, bool]:
    db.execute("DELETE FROM passages WHERE id = ?", (ppid,))
    return {"ok": True}


@router.post("/api/project-files/{fid}/passages")
def add_passage(fid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    f = _pfile(fid)
    if not (body.get("text") or "").strip():
        raise HTTPException(400, "본문 내용을 입력하세요.")
    seq = (db.query_one("SELECT MAX(seq) AS m FROM passages WHERE file_id = ?", (fid,))["m"] or 0) + 1
    ppid = db.execute(
        "INSERT INTO passages(project_id, file_id, seq, label, text, summary, suitable_types_json, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (f["project_id"], fid, seq, body.get("label") or f"직접 추가 {seq}", body["text"].strip(), "", db.dumps(body.get("suitable_types") or []), db.now()),
    )
    return db.query_one("SELECT * FROM passages WHERE id = ?", (ppid,))  # type: ignore[return-value]


# ---------------------------------------------------------------- 세트 그룹

def _group(gid: int) -> dict[str, Any]:
    return _404(db.query_one("SELECT * FROM set_groups WHERE id = ?", (gid,)), "세트 그룹")


def group_sets(gid: int) -> list[dict[str, Any]]:
    return db.query("SELECT * FROM workbooks WHERE group_id = ? ORDER BY set_index", (gid,))


def _make_set(g: dict[str, Any], index: int, spec: dict[str, Any], guideline_ids: list[int], custom: str) -> int:
    name = f"{g['name']} {index}세트"
    s = {**spec, "title": f"{spec.get('title') or g['name']} {index}세트"}
    return db.execute(
        "INSERT INTO workbooks(project_id, name, description, spec_json, guideline_ids_json, custom_guideline, group_id, set_index, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (g["project_id"], name, f"{g['name']} 세트 그룹", db.dumps(s), db.dumps(guideline_ids), custom, g["id"], index, db.now(), db.now()),
    )


@router.post("/api/projects/{pid}/set-groups")
def create_group(pid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _project(pid)
    name = (body.get("name") or "").strip()
    count = int(body.get("set_count") or 0)
    if not name or not 1 <= count <= 20:
        raise HTTPException(400, "그룹 이름과 세트 수(1~20)를 입력하세요.")
    spec = {
        "question_count": 25, "essay_count": 0, "types": [], "difficulty": "", "extra_instructions": "",
        "balance_answers": True, "title": name, **(body.get("spec") or {}),
    }
    gid = db.execute("INSERT INTO set_groups(project_id, name, spec_json, created_at) VALUES(?,?,?,?)", (pid, name, db.dumps(spec), db.now()))
    g = _group(gid)
    ids = body.get("guideline_ids") or guidelines.default_selection(pid)
    for i in range(1, count + 1):
        _make_set(g, i, spec, ids, body.get("custom_guideline") or "")
    return get_group(gid)


@router.get("/api/set-groups/{gid}")
def get_group(gid: int) -> dict[str, Any]:
    g = _group(gid)
    g["sets"] = [{"id": w["id"], "name": w["name"], "set_index": w["set_index"], "has_allocation": bool(w.get("allocation")),
                  "question_count": len((w.get("questions") or {}).get("questions") or [])} for w in group_sets(gid)]
    return g


@router.post("/api/set-groups/{gid}/sets")
def add_sets(gid: int, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    g = get_group(gid)
    existing = group_sets(gid)
    base = existing[-1] if existing else None
    start = (base["set_index"] if base else 0) + 1
    for i in range(start, start + max(1, int(body.get("count") or 1))):
        _make_set(
            {**g, "id": gid}, i,
            base.get("spec") if base else g["spec"],
            (base.get("guideline_ids") if base else None) or guidelines.default_selection(g["project_id"]),
            base.get("custom_guideline") if base else "",
        )
    return get_group(gid)


@router.delete("/api/set-groups/{gid}")
def delete_group(gid: int, keep_sets: bool = False) -> dict[str, bool]:
    if keep_sets:
        db.execute("UPDATE workbooks SET group_id = NULL WHERE group_id = ?", (gid,))
    else:
        db.execute("DELETE FROM workbooks WHERE group_id = ?", (gid,))
    db.execute("DELETE FROM set_groups WHERE id = ?", (gid,))
    return {"ok": True}


# ---------------------------------------------------------------- 본문 배정

def _pool(pid: int) -> list[dict[str, Any]]:
    return [p for p in materials.passages(pid, include_excluded=False) if p["located"]]


def _slots_for(w: dict[str, Any]) -> list[dict[str, Any]]:
    from . import form_pipeline

    form, _ = form_pipeline.form_context(w)
    if form:
        return allocation.build_form_slots(int((w.get("spec") or {}).get("passage_count") or form["block_count"]))
    return allocation.build_slots(w.get("spec") or {})


@router.post("/api/set-groups/{gid}/allocate")
def allocate_group(gid: int, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """그룹의 세트들(기본: 아직 문제를 안 만든 세트)에 본문을 한꺼번에 배정한다."""

    g = _group(gid)
    sets = group_sets(gid)
    if body.get("workbook_ids"):
        sets = [w for w in sets if w["id"] in body["workbook_ids"]]
    elif not body.get("all"):
        sets = [w for w in sets if not w.get("questions")] or sets
    targets = {w["id"] for w in sets}
    ledger = materials.usage(g["project_id"], exclude_workbooks=targets)
    res = allocation.allocate(_pool(g["project_id"]), [(w["id"], _slots_for(w)) for w in sets], ledger)
    for w in sets:
        r = res[w["id"]]
        db.execute("UPDATE workbooks SET allocation_json = ?, updated_at = ? WHERE id = ?", (db.dumps({**r, "at": db.now()}), db.now(), w["id"]))
    return {"allocated": [w["id"] for w in sets], "warnings": {w["name"]: res[w["id"]]["warnings"] for w in sets}}


@router.post("/api/workbooks/{wid}/allocate")
def allocate_one(wid: int) -> dict[str, Any]:
    w = _404(db.query_one("SELECT * FROM workbooks WHERE id = ?", (wid,)), "문제집")
    ledger = materials.usage(w["project_id"], exclude_workbooks={wid})
    r = allocation.allocate(_pool(w["project_id"]), [(wid, _slots_for(w))], ledger)[wid]
    db.execute("UPDATE workbooks SET allocation_json = ?, updated_at = ? WHERE id = ?", (db.dumps({**r, "at": db.now()}), db.now(), wid))
    return r


@router.put("/api/workbooks/{wid}/allocation")
def save_allocation(wid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """사용자가 고친 배정표를 저장하고 규칙 위반을 알려 준다."""

    w = _404(db.query_one("SELECT * FROM workbooks WHERE id = ?", (wid,)), "문제집")
    by_id = {p["id"]: p for p in materials.passages(w["project_id"])}
    items = []
    for it in body.get("items") or []:
        p = by_id.get(it.get("passage_id"))
        items.append({**it, "label": p["label"] if p else "", "file_name": p["file_name"] if p else "", "use_mode": p["use_mode"] if p else "adapt"})
    warnings = allocation.validate(items, materials.usage(w["project_id"], exclude_workbooks={wid}))
    data = {"items": items, "warnings": warnings, "at": db.now(), "edited": True}
    db.execute("UPDATE workbooks SET allocation_json = ?, updated_at = ? WHERE id = ?", (db.dumps(data), db.now(), wid))
    return data


@router.delete("/api/workbooks/{wid}/allocation")
def clear_allocation(wid: int) -> dict[str, bool]:
    db.execute("UPDATE workbooks SET allocation_json = NULL WHERE id = ?", (wid,))
    return {"ok": True}


@router.get("/api/set-groups/{gid}/coverage")
def coverage(gid: int) -> dict[str, Any]:
    """본문 × 세트 사용표 (어느 본문이 어느 세트에서 어떤 유형으로 쓰였나)."""

    g = _group(gid)
    sets = group_sets(gid)
    rows = []
    for p in materials.passages(g["project_id"]):
        cells = {}
        for w in sets:
            ts = [it["type"] for it in (w.get("allocation") or {}).get("items", []) if it.get("passage_id") == p["id"]]
            if ts:
                cells[str(w["id"])] = ts
        rows.append({"id": p["id"], "label": p["label"], "file_name": p["file_name"], "excluded": bool(p["excluded"]) or p["file_scope"] != "range", "cells": cells})
    return {"sets": [{"id": w["id"], "name": w["name"], "set_index": w["set_index"]} for w in sets], "rows": rows}
