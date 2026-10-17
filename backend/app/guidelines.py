"""출제 지침: 기본(전역) 지침 + 프로젝트별 지침.

- project_id IS NULL      → 기본 지침. 모든 프로젝트가 물려받는다.
- project_id = P          → 프로젝트 P 전용 지침.
- project_id = P, base_id → 기본 지침 base_id를 프로젝트 P에서 고쳐 쓴 '수정본'.
                            프로젝트 P에서는 원본 대신 이 수정본이 보인다.
"""

from __future__ import annotations

from typing import Any

from . import db


def get(gid: int) -> dict[str, Any] | None:
    return db.query_one("SELECT * FROM guidelines WHERE id = ?", (gid,))


def create(title: str, category: str, content: str, note: str, project_id: int | None = None, base_id: int | None = None) -> dict[str, Any]:
    gid = db.execute(
        "INSERT INTO guidelines(title, category, content, version, updated_at, project_id, base_id) VALUES(?,?,?,1,?,?,?)",
        (title, category, content, db.now(), project_id, base_id),
    )
    db.execute(
        "INSERT INTO guideline_versions(guideline_id, version, content, note, created_at) VALUES(?,?,?,?,?)",
        (gid, 1, content, note, db.now()),
    )
    return get(gid)  # type: ignore[return-value]


def update(gid: int, body: dict[str, Any]) -> dict[str, Any]:
    g = get(gid)
    if not g:
        raise KeyError(gid)
    content = body.get("content", g["content"])
    version = g["version"]
    if content != g["content"]:
        version += 1
        db.execute(
            "INSERT INTO guideline_versions(guideline_id, version, content, note, created_at) VALUES(?,?,?,?,?)",
            (gid, version, content, body.get("note") or "직접 수정", db.now()),
        )
    db.execute(
        "UPDATE guidelines SET title=?, category=?, content=?, version=?, updated_at=? WHERE id=?",
        (body.get("title", g["title"]), body.get("category", g["category"]), content, version, db.now(), gid),
    )
    return get(gid)  # type: ignore[return-value]


def defaults() -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM guidelines WHERE project_id IS NULL ORDER BY category, id")
    for g in rows:
        g["scope"] = "default"
        g["overridden_by"] = None
        g["override_count"] = db.query_one("SELECT COUNT(*) AS n FROM guidelines WHERE base_id = ?", (g["id"],))["n"]
    return rows


def effective(project_id: int) -> list[dict[str, Any]]:
    """프로젝트에서 실제로 쓰이는 지침 목록 (수정본이 원본을 대신한다)."""

    own = db.query("SELECT * FROM guidelines WHERE project_id = ? ORDER BY category, id", (project_id,))
    overridden = {g["base_id"] for g in own if g.get("base_id")}
    out = []
    for g in db.query("SELECT * FROM guidelines WHERE project_id IS NULL ORDER BY category, id"):
        if g["id"] in overridden:
            continue
        out.append({**g, "scope": "default"})
    for g in own:
        out.append({**g, "scope": "override" if g.get("base_id") else "project"})
    out.sort(key=lambda g: (g["category"] or "", g.get("base_id") or g["id"]))
    return out


def resolve_ids(project_id: int, ids: list[int]) -> list[int]:
    """기본 지침 id를 이 프로젝트의 수정본 id로 바꾼다."""

    mapping = {g["base_id"]: g["id"] for g in db.query("SELECT id, base_id FROM guidelines WHERE project_id = ? AND base_id IS NOT NULL", (project_id,))}
    out: list[int] = []
    for i in ids:
        j = mapping.get(i, i)
        if j not in out:
            out.append(j)
    return out


def _remap_workbooks(project_id: int, old: int, new: int) -> None:
    for w in db.query("SELECT id, guideline_ids_json FROM workbooks WHERE project_id = ?", (project_id,)):
        ids = w.get("guideline_ids") or []
        if old in ids:
            ids = [new if i == old else i for i in ids]
            db.execute("UPDATE workbooks SET guideline_ids_json = ? WHERE id = ?", (db.dumps(list(dict.fromkeys(ids))), w["id"]))


def customize(project_id: int, gid: int) -> dict[str, Any]:
    """기본 지침을 이 프로젝트용 수정본으로 복사한다 (이미 있으면 그것을 반환)."""

    base = get(gid)
    if not base or base.get("project_id") is not None:
        raise ValueError("기본 지침만 프로젝트용으로 복사할 수 있습니다.")
    existing = db.query_one("SELECT * FROM guidelines WHERE project_id = ? AND base_id = ?", (project_id, gid))
    if existing:
        return existing
    g = create(base["title"], base["category"], base["content"], f"기본 지침 v{base['version']}에서 복사", project_id, gid)
    _remap_workbooks(project_id, gid, g["id"])
    return g


def remove(gid: int) -> None:
    """프로젝트 지침 삭제. 수정본이면 기본 지침으로 되돌린다."""

    g = get(gid)
    if not g:
        return
    if g.get("project_id") and g.get("base_id"):
        _remap_workbooks(g["project_id"], gid, g["base_id"])
    elif g.get("project_id") is None:
        # 기본 지침 삭제 → 이를 바탕으로 한 수정본은 프로젝트 전용 지침으로 남긴다
        db.execute("UPDATE guidelines SET base_id = NULL WHERE base_id = ?", (gid,))
    db.execute("DELETE FROM guidelines WHERE id = ?", (gid,))


def default_selection(project_id: int) -> list[int]:
    return [g["id"] for g in effective(project_id) if g["category"] == "공통"]
