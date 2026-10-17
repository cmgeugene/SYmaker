"""SYmaker API 서버."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import checks, codex, db, form_pipeline, guidelines, hwpx_io, materials, pipeline, project_api, seed, stages
from .hwpx_writer import build_hwpx

app = FastAPI(title="SYmaker")
app.include_router(project_api.router)
WB_DIR = db.DATA_DIR / "workbooks"
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@app.on_event("startup")
def _startup() -> None:
    db.conn()
    seed.seed()
    # 서버 재시작 시 끊긴 작업 정리
    db.execute("UPDATE jobs SET status='failed', error='서버가 재시작되어 작업이 중단되었습니다.' WHERE status IN ('queued','running')")


def _404(obj: Any, what: str = "항목") -> Any:
    if not obj:
        raise HTTPException(404, f"{what}을(를) 찾을 수 없습니다.")
    return obj


# ---------------------------------------------------------------- 설정

@app.get("/api/health")
def health() -> dict[str, Any]:
    binary = codex.codex_bin()
    version = None
    if binary:
        try:
            version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            pass
    return {"codex": bool(binary), "codex_version": version}


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return {
        "stages": codex.stage_settings(),
        "stage_labels": codex.STAGES,
        "models": codex.available_models(),
        "effort_labels": codex.EFFORT_LABELS,
        "runner": codex.runner_options(),
    }


@app.put("/api/settings")
def put_settings(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if "stages" in body:
        db.set_setting("stage_models", body["stages"])
    if "runner" in body:
        db.set_setting("runner_options", body["runner"])
    return get_settings()


# ---------------------------------------------------------------- 프로젝트

@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    projects = db.query("SELECT * FROM projects ORDER BY year DESC, semester DESC, id DESC")
    for p in projects:
        p["workbooks"] = [_wb_summary(w) for w in db.query("SELECT * FROM workbooks WHERE project_id = ? ORDER BY id", (p["id"],))]
    return projects


def _project_extras(pid: int) -> dict[str, Any]:
    groups = db.query("SELECT * FROM set_groups WHERE project_id = ? ORDER BY id", (pid,))
    n = db.query_one(
        "SELECT (SELECT COUNT(*) FROM project_files WHERE project_id = ?) AS files, "
        "(SELECT COUNT(*) FROM passages WHERE project_id = ? AND excluded = 0) AS passages",
        (pid, pid),
    )
    return {"groups": groups, "material_count": n["files"], "passage_count": n["passages"]}


@app.post("/api/projects")
def create_project(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "프로젝트 이름을 입력하세요.")
    pid = db.execute(
        "INSERT INTO projects(name, year, semester, description, created_at) VALUES(?,?,?,?,?)",
        (body["name"].strip(), int(body.get("year") or 2026), body.get("semester") or "1학기", body.get("description", ""), db.now()),
    )
    return get_project(pid)


@app.get("/api/projects/{pid}")
def get_project(pid: int) -> dict[str, Any]:
    p = _404(db.query_one("SELECT * FROM projects WHERE id = ?", (pid,)), "프로젝트")
    p["workbooks"] = [_wb_summary(w) for w in db.query("SELECT * FROM workbooks WHERE project_id = ? ORDER BY group_id, set_index, id", (pid,))]
    p.update(_project_extras(pid))
    return p


@app.put("/api/projects/{pid}")
def update_project(pid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    p = get_project(pid)
    db.execute(
        "UPDATE projects SET name=?, year=?, semester=?, description=? WHERE id=?",
        (body.get("name", p["name"]), int(body.get("year", p["year"])), body.get("semester", p["semester"]), body.get("description", p["description"]), pid),
    )
    return get_project(pid)


@app.delete("/api/projects/{pid}")
def delete_project(pid: int) -> dict[str, bool]:
    for w in db.query("SELECT id FROM workbooks WHERE project_id = ?", (pid,)):
        shutil.rmtree(WB_DIR / str(w["id"]), ignore_errors=True)
    db.execute("DELETE FROM guidelines WHERE project_id = ?", (pid,))
    db.execute("DELETE FROM projects WHERE id = ?", (pid,))
    shutil.rmtree(project_api.PROJ_DIR / str(pid), ignore_errors=True)
    return {"ok": True}


# ---------------------------------------------------------------- 문제집

def _latest_version_id(wid: int) -> int | None:
    row = db.query_one("SELECT id FROM question_versions WHERE workbook_id = ? ORDER BY id DESC LIMIT 1", (wid,))
    return row["id"] if row else None


def _stage_status(w: dict[str, Any]) -> dict[str, str]:
    wid = w["id"]
    files = db.query("SELECT kind FROM files WHERE workbook_id = ?", (wid,))
    latest = _latest_version_id(wid)
    review = w.get("review") or {}
    exports = db.query("SELECT created_at FROM exports WHERE workbook_id = ? ORDER BY id DESC LIMIT 1", (wid,))
    open_fb = db.query_one("SELECT COUNT(*) AS n FROM feedback WHERE workbook_id = ? AND status = 'open'", (wid,))["n"]
    latest_row = db.query_one("SELECT created_at FROM question_versions WHERE id = ?", (latest,)) if latest else None
    return {
        "materials": "done" if files or db.query_one("SELECT id FROM project_files WHERE project_id = ? AND scope != 'exclude'", (w["project_id"],)) else "todo",
        "analyze": "done" if w.get("analysis") else "todo",
        "generate": "done" if w.get("questions") else "todo",
        "review": "done" if review and review.get("version_id") == latest and latest else ("stale" if review else "todo"),
        "export": "done" if exports and latest_row and exports[0]["created_at"] >= latest_row["created_at"] else ("stale" if exports else "todo"),
        "feedback": "open" if open_fb else ("done" if db.query_one("SELECT id FROM feedback WHERE workbook_id = ?", (wid,)) else "todo"),
    }


def _wb_summary(w: dict[str, Any]) -> dict[str, Any]:
    qs = (w.get("questions") or {}).get("questions") or []
    return {
        "id": w["id"],
        "project_id": w["project_id"],
        "name": w["name"],
        "description": w["description"],
        "updated_at": w["updated_at"],
        "question_count": len(qs),
        "status": _stage_status(w),
        "group_id": w.get("group_id"),
        "set_index": w.get("set_index"),
        "has_allocation": bool(w.get("allocation")),
    }


def _get_wb(wid: int) -> dict[str, Any]:
    return _404(db.query_one("SELECT * FROM workbooks WHERE id = ?", (wid,)), "문제집")


@app.post("/api/projects/{pid}/workbooks")
def create_workbook(pid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    get_project(pid)
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "문제집 이름을 입력하세요.")
    common = guidelines.default_selection(pid)
    spec = {"question_count": 10, "types": [], "difficulty": "", "extra_instructions": "", "balance_answers": True, "title": body["name"].strip()}
    wid = db.execute(
        "INSERT INTO workbooks(project_id, name, description, spec_json, guideline_ids_json, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
        (pid, body["name"].strip(), body.get("description", ""), db.dumps(spec), db.dumps(common), db.now(), db.now()),
    )
    return get_workbook(wid)


@app.get("/api/workbooks/{wid}")
def get_workbook(wid: int) -> dict[str, Any]:
    w = _get_wb(wid)
    w["project"] = db.query_one("SELECT * FROM projects WHERE id = ?", (w["project_id"],))
    w["files"] = [_file_summary(f) for f in db.query("SELECT * FROM files WHERE workbook_id = ? ORDER BY id", (wid,))]
    w["feedback"] = db.query("SELECT * FROM feedback WHERE workbook_id = ? ORDER BY id DESC", (wid,))
    w["exports"] = [
        {**e, "name": Path(e["path"]).name}
        for e in db.query("SELECT * FROM exports WHERE workbook_id = ? ORDER BY id DESC", (wid,))
    ]
    w["versions"] = db.query(
        "SELECT id, note, created_at FROM question_versions WHERE workbook_id = ? ORDER BY id DESC", (wid,)
    )
    w["jobs"] = [_job_summary(j) for j in db.query("SELECT * FROM jobs WHERE workbook_id = ? ORDER BY id DESC LIMIT 30", (wid,))]
    w["status"] = _stage_status(w)
    tpl = pipeline.template_file(wid)
    w["template_file_id"] = (tpl or {}).get("id")
    w["template_source"] = ("project" if tpl and "project_id" in tpl else "workbook") if tpl else None
    form = pipeline.form_of(tpl)
    w["form"] = {
        "block_count": form["block_count"],
        "segments": [{"id": sg["id"], "instruction": sg["instruction"], "choices": len(sg["choice_slots"])} for sg in form["segments"]],
        "front_boxes": len((form.get("front") or {}).get("boxes") or {}),
        "boxes": __import__("app.hwpx_form", fromlist=["boxes"]).boxes(form),
    } if form else None
    w["group"] = None
    if w.get("group_id"):
        g = db.query_one("SELECT * FROM set_groups WHERE id = ?", (w["group_id"],))
        if g:
            w["group"] = {"id": g["id"], "name": g["name"], "sets": [
                {"id": s["id"], "name": s["name"], "set_index": s["set_index"]}
                for s in db.query("SELECT id, name, set_index FROM workbooks WHERE group_id = ? ORDER BY set_index", (g["id"],))
            ]}
    w["project_materials"] = [project_api.file_summary(f) for f in materials.project_files(w["project_id"])]
    w["passage_count"] = len([p for p in materials.passages(w["project_id"], include_excluded=False) if p["located"]])
    return w


@app.put("/api/workbooks/{wid}")
def update_workbook(wid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    w = _get_wb(wid)
    fields = {
        "name": ("name", lambda v: v),
        "description": ("description", lambda v: v),
        "spec": ("spec_json", db.dumps),
        "analysis": ("analysis_json", db.dumps),
        "guideline_ids": ("guideline_ids_json", db.dumps),
        "custom_guideline": ("custom_guideline", lambda v: v),
    }
    sets, params = [], []
    for key, (col, conv) in fields.items():
        if key in body:
            sets.append(f"{col} = ?")
            params.append(conv(body[key]))
    if sets:
        db.execute(f"UPDATE workbooks SET {', '.join(sets)}, updated_at = ? WHERE id = ?", (*params, db.now(), wid))
    if "analysis" in body and (w.get("questions") or {}).get("mode") == "form":
        # 하위 문항 순서를 바꿨으면 이미 만든 세트의 문항 순서도 맞춘다 (새 버전은 만들지 않음)
        order = [s["segment_id"] for s in (body["analysis"] or {}).get("form_segments") or []]
        data = w["questions"]
        for st in data.get("sets", []):
            st["items"].sort(key=lambda it: order.index(it["segment_id"]) if it.get("segment_id") in order else 99)
        data["questions"] = form_pipeline.flatten(data.get("sets", []))
        db.execute("UPDATE workbooks SET questions_json = ? WHERE id = ?", (db.dumps(data), wid))
        w["questions"] = data
    if "questions" in body and body["questions"] != w.get("questions"):
        save_questions(wid, body["questions"], body.get("version_note") or "직접 편집")
    return get_workbook(wid)


@app.delete("/api/workbooks/{wid}")
def delete_workbook(wid: int) -> dict[str, bool]:
    shutil.rmtree(WB_DIR / str(wid), ignore_errors=True)
    db.execute("DELETE FROM workbooks WHERE id = ?", (wid,))
    return {"ok": True}


def save_questions(wid: int, questions: dict[str, Any], note: str) -> None:
    if questions.get("mode") == "form":
        # 양식 모드: 세트가 원본. 화면에서 고친 평탄 문항을 세트에 되돌린 뒤 다시 평탄화한다.
        questions = form_pipeline.sync_sets({"mode": "form", "title": questions.get("title", ""),
                                             "sets": questions.get("sets", []), "questions": questions.get("questions", [])})
    else:
        questions = {"title": questions.get("title", ""), "questions": questions.get("questions", [])}
    for i, q in enumerate(questions["questions"], 1):
        q["number"] = i
    db.execute("UPDATE workbooks SET questions_json = ?, updated_at = ? WHERE id = ?", (db.dumps(questions), db.now(), wid))
    db.execute(
        "INSERT INTO question_versions(workbook_id, questions_json, note, created_at) VALUES(?,?,?,?)",
        (wid, db.dumps(questions), note, db.now()),
    )


@app.post("/api/workbooks/{wid}/versions/{vid}/restore")
def restore_version(wid: int, vid: int) -> dict[str, Any]:
    v = _404(db.query_one("SELECT * FROM question_versions WHERE id = ? AND workbook_id = ?", (vid, wid)), "버전")
    import json

    save_questions(wid, json.loads(v["questions_json"]), f"버전 복원 ({v['created_at']})")
    return get_workbook(wid)


# ---------------------------------------------------------------- 파일

def _file_summary(f: dict[str, Any]) -> dict[str, Any]:
    fmt = f.get("format") or {}
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
        "format_brief": {
            "highlights": fmt.get("highlights", []),
            "headings": fmt.get("headings", [])[:5],
            "paragraph_count": fmt.get("paragraph_count"),
            "conversion": fmt.get("conversion"),
        } if fmt else None,
        "created_at": f["created_at"],
    }


@app.post("/api/workbooks/{wid}/files")
async def upload_file(wid: int, kind: str = Form("sample"), file: UploadFile = File(...)) -> dict[str, Any]:
    _get_wb(wid)
    name = file.filename or "file"
    ext = Path(name).suffix.lower()
    if ext not in (".txt", ".pdf", ".hwp", ".hwpx", ".md"):
        raise HTTPException(400, "txt, pdf, hwp, hwpx 파일만 올릴 수 있습니다.")
    folder = WB_DIR / str(wid) / "files"
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / f"{uuid.uuid4().hex[:8]}_{re.sub(r'[^\w.\-가-힣]', '_', name)}"
    stored.write_bytes(await file.read())

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
    except Exception as exc:  # noqa: BLE001
        stored.unlink(missing_ok=True)
        if hwpx_path and hwpx_path != stored:
            hwpx_path.unlink(missing_ok=True)
        raise HTTPException(400, f"파일을 읽지 못했습니다: {exc}") from exc

    fid = db.execute(
        "INSERT INTO files(workbook_id, kind, orig_name, stored_path, hwpx_path, text, format_json, created_at) VALUES(?,?,?,?,?,?,?,?)",
        (wid, kind, name, str(stored), str(hwpx_path) if hwpx_path else None, text, db.dumps(fmt) if fmt else None, db.now()),
    )
    return _file_summary(db.query_one("SELECT * FROM files WHERE id = ?", (fid,)))  # type: ignore[arg-type]


@app.get("/api/files/{fid}")
def get_file(fid: int) -> dict[str, Any]:
    f = _404(db.query_one("SELECT * FROM files WHERE id = ?", (fid,)), "파일")
    return {**_file_summary(f), "text": f["text"], "format": f.get("format")}


@app.put("/api/files/{fid}")
def update_file(fid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    f = _404(db.query_one("SELECT * FROM files WHERE id = ?", (fid,)), "파일")
    db.execute(
        "UPDATE files SET kind = ?, note = ?, text = ?, scope = ?, use_mode = ?, paraphrase_json = ? WHERE id = ?",
        (body.get("kind", f["kind"]), body.get("note", f["note"]), body.get("text", f["text"]),
         body.get("scope", f.get("scope") or "range"), body.get("use_mode", f.get("use_mode") or "adapt"),
         db.dumps(materials.paraphrase_cfg(body.get("paraphrase", f.get("paraphrase")))), fid),
    )
    return get_file(fid)


@app.delete("/api/files/{fid}")
def delete_file(fid: int) -> dict[str, bool]:
    f = _404(db.query_one("SELECT * FROM files WHERE id = ?", (fid,)), "파일")
    for p in {f["stored_path"], f.get("hwpx_path")}:
        if p:
            Path(p).unlink(missing_ok=True)
    db.execute("DELETE FROM files WHERE id = ?", (fid,))
    return {"ok": True}


@app.get("/api/files/{fid}/download")
def download_file(fid: int, hwpx: bool = False) -> FileResponse:
    f = _404(db.query_one("SELECT * FROM files WHERE id = ?", (fid,)), "파일")
    path = f["hwpx_path"] if hwpx and f.get("hwpx_path") else f["stored_path"]
    name = Path(f["orig_name"]).stem + (".hwpx" if hwpx else Path(f["orig_name"]).suffix)
    return FileResponse(path, filename=name)


# ---------------------------------------------------------------- 작업 (Codex)

def _job_summary(j: dict[str, Any]) -> dict[str, Any]:
    return {k: j.get(k) for k in ("id", "workbook_id", "stage", "status", "model", "effort", "error", "created_at", "finished_at")}


@app.get("/api/jobs/{jid}")
def get_job(jid: int) -> dict[str, Any]:
    return _404(db.query_one("SELECT * FROM jobs WHERE id = ?", (jid,)), "작업")


@app.post("/api/jobs/{jid}/cancel")
def cancel_job(jid: int) -> dict[str, Any]:
    if not codex.cancel(jid):
        db.execute("UPDATE jobs SET status='cancelled', finished_at=? WHERE id=? AND status IN ('queued','running')", (db.now(), jid))
    return get_job(jid)


_tasks: set[asyncio.Task] = set()


@app.post("/api/workbooks/{wid}/run/{stage}")
async def run_stage(wid: int, stage: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    if stage not in codex.STAGES:
        raise HTTPException(400, "알 수 없는 단계입니다.")
    w = _get_wb(wid)
    running = db.query_one("SELECT id FROM jobs WHERE workbook_id = ? AND status IN ('queued','running')", (wid,))
    if running:
        raise HTTPException(409, "이미 진행 중인 작업이 있습니다. 끝난 뒤 다시 시도하세요.")
    if stage == "analyze" and not pipeline._files(wid, "sample"):
        raise HTTPException(400, "먼저 샘플 문제지를 올려 주세요.")
    if stage in ("review", "revise", "layout") and not w.get("questions"):
        raise HTTPException(400, "먼저 문제를 제작하세요.")

    cfg = codex.stage_settings()[stage]
    model = body.get("model") or cfg["model"]
    effort = body.get("effort") or cfg["effort"]
    jid = db.execute(
        "INSERT INTO jobs(workbook_id, stage, status, model, effort, log, created_at) VALUES(?,?,?,?,?,?,?)",
        (wid, stage, "running", model, effort, "", db.now()),
    )
    task = asyncio.create_task(_execute(jid, wid, stage, model, effort, body))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return get_job(jid)


@app.post("/api/set-groups/{gid}/run/{stage}")
async def run_group_stage(gid: int, stage: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """세트 그룹의 모든 세트(또는 지정한 세트)에 같은 단계를 시작한다. 동시 실행 수는 전체 설정을 따른다."""

    ids = body.get("workbook_ids") or [w["id"] for w in project_api.group_sets(gid)]
    started, skipped = [], []
    for wid in ids:
        try:
            j = await run_stage(wid, stage, {k: v for k, v in body.items() if k != "workbook_ids"})
            started.append(j["id"])
        except HTTPException as exc:
            skipped.append({"workbook_id": wid, "reason": exc.detail})
    return {"started": started, "skipped": skipped}


def _append_log(jid: int, msg: str) -> None:
    from datetime import datetime

    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n"
    db.execute("UPDATE jobs SET log = COALESCE(log, '') || ? WHERE id = ?", (line, jid))


def _feedback_texts(wid: int, ids: list[int] | None) -> list[tuple[int, str]]:
    rows = db.query("SELECT * FROM feedback WHERE workbook_id = ? AND status = 'open' ORDER BY id", (wid,))
    if ids:
        rows = [r for r in rows if r["id"] in ids]
    return [
        (r["id"], (f"[{r['question_number']}번 문항] " if r.get("question_number") else "[전체] ") + r["text"])
        for r in rows
    ]


async def _execute(jid: int, wid: int, stage: str, model: str, effort: str, body: dict[str, Any]) -> None:
    ctx = stages.Ctx(job_id=jid, wb=_get_wb(wid), model=model, effort=effort, log=lambda m: _append_log(jid, m))
    try:
        w = ctx.wb
        rule_result = None
        fb: list[tuple[int, str]] = []
        if stage == "analyze":
            out = await ctx.call(*pipeline.prompt_analyze(w))
        elif stage == "generate":
            out = await (stages.generate_form(ctx) if form_pipeline.is_form(w) else stages.generate(ctx))
        elif stage == "layout":
            data = await stages.layout_form(ctx)
            db.execute("UPDATE workbooks SET questions_json=? WHERE id=?", (db.dumps(data), wid))
            out = {"exports": _build_form_exports(wid, body.get("modes") or ["teacher", "student"])}
            _append_log(jid, f"HWPX {len(out['exports'])}개를 만들었습니다.")
        elif stage == "review":
            rule_result = run_rule_checks(w)
            _append_log(jid, f"규칙 검사 완료: {len(rule_result['issues'])}건 발견, 정답 분포 {rule_result['answer_distribution']}")
            out = await (stages.review_form(ctx, rule_result) if form_pipeline.is_form(w) else stages.review(ctx, rule_result))
        elif stage == "revise":
            requests = list(body.get("requests") or [])
            fb = _feedback_texts(wid, body.get("feedback_ids")) if body.get("use_feedback") else []
            requests += [t for _, t in fb]
            if not requests:
                raise stages.StageError("수정 요청 내용이 없습니다.")
            out = await (stages.revise_form(ctx, requests) if form_pipeline.is_form(w) else stages.revise(ctx, requests))
        else:  # guideline
            fb = _feedback_texts(wid, body.get("feedback_ids"))
            texts = [t for _, t in fb] + list(body.get("requests") or [])
            if not texts:
                raise stages.StageError("지침에 반영할 피드백이 없습니다.")
            out = await ctx.call(*pipeline.prompt_guideline(w, texts))
            out["feedback_ids"] = [i for i, _ in fb]
            out["applied"] = False
            out["materials"] = {
                f["ref"]: {"name": f["orig_name"], "where": f["where"], "scope": f.get("scope") or "range",
                           "use_mode": f.get("use_mode") or "adapt", "paraphrase": materials.paraphrase_cfg(f.get("paraphrase")), "note": f.get("note") or ""}
                for f in pipeline.material_refs(w)
            }

        if stage == "analyze":
            prev = w.get("analysis") or {}
            if prev.get("form_style"):  # 다시 분석해도 사용자가 정한 출력 서식은 유지
                out["form_style"] = prev["form_style"]
            prev_order = [x["segment_id"] for x in prev.get("form_segments") or []]
            if prev_order and out.get("form_segments"):  # 사용자가 바꾼 문항 순서도 유지
                out["form_segments"].sort(key=lambda x: prev_order.index(x["segment_id"]) if x["segment_id"] in prev_order else 99)
            tpl = pipeline.template_file(wid)
            out["format_facts"] = {k: v for k, v in (tpl or {}).get("format", {}).items() if k != "paragraphs"} if tpl else None
            out["template_file_id"] = tpl["id"] if tpl else None
            out["highlight_color"] = (out["format_facts"] or {}).get("highlights", [{}])[0].get("color", "#FFFF00") if tpl and tpl["format"].get("highlights") else "#FFFF00"
            db.execute("UPDATE workbooks SET analysis_json=?, updated_at=? WHERE id=?", (db.dumps(out), db.now(), wid))
            if w.get("group_id"):  # 같은 세트 그룹의 다른 세트도 같은 샘플 분석을 쓴다
                n = db.execute("UPDATE workbooks SET analysis_json=? WHERE group_id=? AND id!=? AND analysis_json IS NULL", (db.dumps(out), w["group_id"], wid))
                _append_log(jid, f"같은 그룹의 세트 {n}개에도 분석 결과를 적용했습니다.")
            spec = w.get("spec") or {}
            form = pipeline.form_of(tpl)
            if form:  # 양식 모드: 지문 수 기본값 = 양식 블록 수
                spec.setdefault("passage_count", form["block_count"])
                spec.setdefault("answer_weights", "even")
                db.execute("UPDATE workbooks SET spec_json=? WHERE id=?", (db.dumps(spec), wid))
            elif not spec.get("types") and out.get("question_types"):
                spec["types"] = [{"name": t["name"], "count": 0} for t in out["question_types"]]
                db.execute("UPDATE workbooks SET spec_json=? WHERE id=?", (db.dumps(spec), wid))
        elif stage == "generate":
            note = f"Codex 제작 ({model}/{effort})"
            if out.get("failed_batches"):
                note += f" — 실패한 묶음: {', '.join(out['failed_batches'])}"
            if out.get("questions"):
                save_questions(wid, out, note)
                db.execute("UPDATE workbooks SET review_json=NULL WHERE id=?", (wid,))
        elif stage == "review":
            review = {
                "summary": out.get("summary"),
                "score": out.get("score"),
                "issues": (rule_result or {}).get("issues", []) + [{**i, "source": "model"} for i in out.get("issues", [])],
                "answer_distribution": (rule_result or {}).get("answer_distribution"),
                "version_id": _latest_version_id(wid),
                "at": db.now(),
                "model": f"{model}/{effort}",
            }
            db.execute("UPDATE workbooks SET review_json=? WHERE id=?", (db.dumps(review), wid))
        elif stage == "revise":
            changed = out.get("changed_numbers") or []
            note = f"Codex 수정 ({', '.join(map(str, changed)) or '변경 없음'}번): " + "; ".join(out.get("change_log") or [])
            if changed:
                save_questions(wid, out, note[:300])
            if fb:
                ids = [i for i, _ in fb]
                db.execute(f"UPDATE feedback SET status='applied' WHERE id IN ({','.join('?' * len(ids))})", ids)

        if out.get("failed_batches"):
            err = f"일부 묶음이 실패했습니다: {', '.join(out['failed_batches'])}. 성공한 문항은 저장했습니다."
            db.execute("UPDATE jobs SET status='failed', error=?, result_json=?, finished_at=? WHERE id=?", (err, db.dumps(out), db.now(), jid))
            return
        db.execute("UPDATE jobs SET status='done', result_json=?, finished_at=? WHERE id=?", (db.dumps(out), db.now(), jid))
        _append_log(jid, "완료되었습니다.")
    except Exception as exc:  # noqa: BLE001
        status = "cancelled" if codex.is_cancelled(jid) or "중단" in str(exc) else "failed"
        db.execute("UPDATE jobs SET status=?, error=?, finished_at=? WHERE id=?", (status, str(exc), db.now(), jid))


def _check_inputs(w: dict[str, Any]) -> dict[str, Any]:
    """규칙 검사용: 지정 본문(사용 방식 포함)과 다른 세트들의 실제 출제 기록."""

    pids = {q.get("passage_id") for q in (w.get("questions") or {}).get("questions", []) if q.get("passage_id")}
    passages = {p["id"]: p for p in materials.passages(w["project_id"]) if p["id"] in pids}
    other = []
    for o in db.query("SELECT id, name, questions_json FROM workbooks WHERE project_id = ? AND id != ?", (w["project_id"], w["id"])):
        for q in (o.get("questions") or {}).get("questions", []):
            if q.get("passage_id"):
                other.append({"passage_id": q["passage_id"], "type": q.get("type"), "workbook": o["name"]})
    return {"passages": passages, "other_usage": other}


def run_rule_checks(w: dict[str, Any]) -> dict[str, Any]:
    return checks.run_checks(w.get("questions"), w.get("spec"), w.get("analysis"), **_check_inputs(w))


@app.post("/api/workbooks/{wid}/checks")
def rule_checks(wid: int) -> dict[str, Any]:
    return run_rule_checks(_get_wb(wid))


# ---------------------------------------------------------------- 출력

@app.post("/api/workbooks/{wid}/export")
def export(wid: int, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    w = _get_wb(wid)
    if not w.get("questions"):
        raise HTTPException(400, "출력할 문제가 없습니다.")
    if (w.get("questions") or {}).get("mode") == "form":
        raise HTTPException(409, "양식 모드는 '양식 배치' 작업으로 출력합니다.")
    analysis = w.get("analysis") or {}
    tpl = pipeline.template_file(wid) if body.get("use_template", True) else None
    role_map = analysis.get("role_map") if tpl and analysis.get("template_file_id") == tpl["id"] else None
    if tpl and role_map is None:
        role_map = {"preamble_end": 0}
    modes = body.get("modes") or ["questions", "answers"]
    labels = {"questions": "문제지", "answers": "정답해설", "both": "문제+정답"}
    stamp = db.now().replace(":", "").replace("-", "")[:13]
    safe = re.sub(r"[^\w가-힣\-]+", "_", w["name"]).strip("_") or "workbook"
    made = []
    for mode in modes:
        out = WB_DIR / str(wid) / "exports" / f"{safe}_{labels.get(mode, mode)}_{stamp}.hwpx"
        try:
            build_hwpx(
                template=Path(tpl["hwpx_path"]) if tpl else None,
                role_map=role_map,
                questions=w["questions"],
                out_path=out,
                mode=mode,
                highlight_color=analysis.get("highlight_color") or "#FFFF00",
                choice_marker=analysis.get("choice_marker") or "circled",
                keep_preamble=body.get("keep_preamble", True),
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"HWPX 생성 실패: {exc}") from exc
        eid = db.execute("INSERT INTO exports(workbook_id, kind, path, created_at) VALUES(?,?,?,?)", (wid, mode, str(out), db.now()))
        made.append({"id": eid, "kind": mode, "name": out.name})
    return {"exports": made}


def _build_form_exports(wid: int, modes: list[str]) -> list[dict[str, Any]]:
    """양식 모드 출력: 교사용(정답 표시) / 학생용(정답 표시 없음)."""

    from .hwpx_form import build_form

    w = _get_wb(wid)
    tpl = pipeline.template_file(wid)
    form = pipeline.form_of(tpl)
    sets = (w.get("questions") or {}).get("sets") or []
    if not (tpl and form and sets):
        raise stages.StageError("양식 템플릿이나 지문 세트가 없습니다.")
    color = (w.get("analysis") or {}).get("highlight_color") or "#FFFF00"
    labels = {"teacher": "교사용", "student": "학생용"}
    stamp = db.now().replace(":", "").replace("-", "")[:13]
    safe = re.sub(r"[^\w가-힣\-]+", "_", w["name"]).strip("_") or "workbook"
    made = []
    for mode in modes:
        out = WB_DIR / str(wid) / "exports" / f"{safe}_{labels.get(mode, mode)}_{stamp}.hwpx"
        build_form(template=Path(tpl["hwpx_path"]), form=form, sets=sets, out_path=out, teacher=(mode == "teacher"), highlight_color=color,
                   style=form_pipeline.style_of(w), order=form_pipeline.segment_order(w))
        eid = db.execute("INSERT INTO exports(workbook_id, kind, path, created_at) VALUES(?,?,?,?)", (wid, mode, str(out), db.now()))
        made.append({"id": eid, "kind": mode, "name": out.name})
    return made


@app.get("/api/exports/{eid}/download")
def download_export(eid: int) -> FileResponse:
    e = _404(db.query_one("SELECT * FROM exports WHERE id = ?", (eid,)), "출력 파일")
    return FileResponse(e["path"], filename=Path(e["path"]).name, media_type="application/hwp+zip")


@app.delete("/api/exports/{eid}")
def delete_export(eid: int) -> dict[str, bool]:
    e = _404(db.query_one("SELECT * FROM exports WHERE id = ?", (eid,)), "출력 파일")
    Path(e["path"]).unlink(missing_ok=True)
    db.execute("DELETE FROM exports WHERE id = ?", (eid,))
    return {"ok": True}


@app.post("/api/exports/{eid}/reveal")
def reveal_export(eid: int) -> dict[str, bool]:
    e = _404(db.query_one("SELECT * FROM exports WHERE id = ?", (eid,)), "출력 파일")
    subprocess.run(["open", "-R", e["path"]], check=False)
    return {"ok": True}


# ---------------------------------------------------------------- 피드백

@app.post("/api/workbooks/{wid}/feedback")
def add_feedback(wid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _get_wb(wid)
    if not (body.get("text") or "").strip():
        raise HTTPException(400, "피드백 내용을 입력하세요.")
    qn = body.get("question_number")
    fid = db.execute(
        "INSERT INTO feedback(workbook_id, question_number, text, status, created_at) VALUES(?,?,?,?,?)",
        (wid, int(qn) if qn else None, body["text"].strip(), "open", db.now()),
    )
    return db.query_one("SELECT * FROM feedback WHERE id = ?", (fid,))  # type: ignore[return-value]


@app.put("/api/feedback/{fid}")
def update_feedback(fid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    f = _404(db.query_one("SELECT * FROM feedback WHERE id = ?", (fid,)), "피드백")
    db.execute("UPDATE feedback SET text=?, status=? WHERE id=?", (body.get("text", f["text"]), body.get("status", f["status"]), fid))
    return db.query_one("SELECT * FROM feedback WHERE id = ?", (fid,))  # type: ignore[return-value]


@app.delete("/api/feedback/{fid}")
def delete_feedback(fid: int) -> dict[str, bool]:
    db.execute("DELETE FROM feedback WHERE id = ?", (fid,))
    return {"ok": True}


# ---------------------------------------------------------------- 지침

@app.get("/api/guidelines")
def list_guidelines(project_id: int | None = None) -> list[dict[str, Any]]:
    """project_id가 없으면 기본 지침, 있으면 그 프로젝트에서 쓰이는 지침(기본+전용+수정본)."""

    return guidelines.effective(project_id) if project_id else guidelines.defaults()


@app.post("/api/guidelines")
def create_guideline(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if not (body.get("title") or "").strip():
        raise HTTPException(400, "지침 제목을 입력하세요.")
    pid = body.get("project_id")
    if pid:
        get_project(int(pid))
    return guidelines.create(
        body["title"].strip(), body.get("category") or "유형", body.get("content") or "",
        body.get("note") or "새 지침", int(pid) if pid else None,
    )


@app.put("/api/guidelines/{gid}")
def update_guideline(gid: int, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    _404(guidelines.get(gid), "지침")
    return guidelines.update(gid, body)


@app.delete("/api/guidelines/{gid}")
def delete_guideline(gid: int) -> dict[str, bool]:
    guidelines.remove(gid)
    return {"ok": True}


@app.post("/api/projects/{pid}/guidelines/{gid}/customize")
def customize_guideline(pid: int, gid: int) -> dict[str, Any]:
    """기본 지침을 이 프로젝트용 수정본으로 복사한다."""

    get_project(pid)
    try:
        return guidelines.customize(pid, gid)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/guidelines/{gid}/versions")
def guideline_versions(gid: int) -> list[dict[str, Any]]:
    return db.query("SELECT * FROM guideline_versions WHERE guideline_id = ? ORDER BY version DESC", (gid,))


@app.post("/api/guidelines/apply")
def apply_guideline_updates(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Codex가 제안한 지침 수정안 중 사용자가 승인한 것을 반영한다.

    각 수정안의 scope: "project"(기본값) → 이 프로젝트에만, "default" → 기본 지침에 반영.
    """

    applied = []
    wid = body.get("workbook_id")
    w = _get_wb(int(wid)) if wid else None
    pid = w["project_id"] if w else None
    for u in body.get("updates") or []:
        note = f"피드백 반영: {u.get('reason', '')}"[:300]
        scope = u.get("scope") or ("project" if pid else "default")
        gid = int(u.get("guideline_id") or 0)
        target = guidelines.get(gid) if gid else None
        if target:
            if target.get("project_id") is None and scope == "project" and pid:
                target = guidelines.customize(pid, gid)
            elif target.get("base_id") and scope == "default":
                target = guidelines.get(target["base_id"]) or target
            applied.append(guidelines.update(target["id"], {"content": u["new_content"], "note": note}))
        else:
            g = guidelines.create(
                u.get("title") or "새 지침", u.get("category") or "유형", u["new_content"], note,
                pid if scope == "project" else None,
            )
            applied.append(g)
            if w:
                w = _get_wb(int(wid))
                ids = list(w.get("guideline_ids") or []) + [g["id"]]
                db.execute("UPDATE workbooks SET guideline_ids_json=? WHERE id=?", (db.dumps(ids), wid))
    changed_materials = [_apply_material_update(m) for m in body.get("material_updates") or []]
    if body.get("job_id"):
        job = db.query_one("SELECT result_json FROM jobs WHERE id = ?", (body["job_id"],))
        if job and job.get("result"):
            db.execute("UPDATE jobs SET result_json = ? WHERE id = ?", (db.dumps({**job["result"], "applied": True}), body["job_id"]))
    if body.get("feedback_ids"):
        # 지침·자료 설정에 반영했다는 표시만 남긴다. 문제 수정은 따로 해야 하므로 '처리 대기'에 그대로 둔다.
        ids = body["feedback_ids"]
        db.execute(f"UPDATE feedback SET guideline_at = ? WHERE id IN ({','.join('?' * len(ids))})", (db.now(), *ids))
    return {"applied": applied, "materials": [m for m in changed_materials if m]}


def _apply_material_update(u: dict[str, Any]) -> dict[str, Any] | None:
    """승인된 '자료 설정 변경 제안'을 반영한다. 빈 값은 바꾸지 않는다."""

    ref = u.get("file_ref") or ""
    table = {"p": "project_files", "w": "files"}.get(ref[:1])
    if not table or ":" not in ref:
        return None
    f = db.query_one(f"SELECT * FROM {table} WHERE id = ?", (int(ref.split(":", 1)[1]),))
    if not f:
        return None
    para = materials.paraphrase_cfg(f.get("paraphrase"))
    for key in ("length", "level", "note"):
        if u.get(f"paraphrase_{key}"):
            para[key] = u[f"paraphrase_{key}"]
    if u.get("paraphrase_min_words"):
        para["min_words"] = int(u["paraphrase_min_words"])
    if u.get("paraphrase_max_words"):
        para["max_words"] = int(u["paraphrase_max_words"])
    if para["level"] not in materials.PARAPHRASE_LEVELS:
        para["level"] = "same"
    db.execute(
        f"UPDATE {table} SET scope = ?, use_mode = ?, note = ?, paraphrase_json = ? WHERE id = ?",
        (u.get("scope") or f.get("scope") or "range", u.get("use_mode") or f.get("use_mode") or "adapt",
         u.get("note") or f.get("note") or "", db.dumps(para), f["id"]),
    )
    return {"ref": ref, "name": f["orig_name"]}


# ---------------------------------------------------------------- 정적 파일 (빌드된 프론트엔드)

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str) -> FileResponse:
        target = DIST / path
        if path and target.is_file():
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
