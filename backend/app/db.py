"""SQLite 저장소. 구조가 자주 바뀌는 데이터는 JSON 컬럼으로 보관한다."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = DATA_DIR / "symaker.db"

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    year INTEGER NOT NULL,
    semester TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workbooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    spec_json TEXT DEFAULT '{}',
    analysis_json TEXT,
    questions_json TEXT,
    review_json TEXT,
    guideline_ids_json TEXT DEFAULT '[]',
    custom_guideline TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workbook_id INTEGER NOT NULL REFERENCES workbooks(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    orig_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    hwpx_path TEXT,
    text TEXT DEFAULT '',
    format_json TEXT,
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guidelines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT DEFAULT '',
    content TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS guideline_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guideline_id INTEGER NOT NULL REFERENCES guidelines(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    content TEXT NOT NULL,
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workbook_id INTEGER NOT NULL REFERENCES workbooks(id) ON DELETE CASCADE,
    questions_json TEXT NOT NULL,
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workbook_id INTEGER REFERENCES workbooks(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    model TEXT,
    effort TEXT,
    log TEXT DEFAULT '',
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workbook_id INTEGER NOT NULL REFERENCES workbooks(id) ON DELETE CASCADE,
    question_number INTEGER,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workbook_id INTEGER NOT NULL REFERENCES workbooks(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    orig_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    hwpx_path TEXT,
    text TEXT DEFAULT '',
    format_json TEXT,
    note TEXT DEFAULT '',
    scope TEXT DEFAULT 'range',
    use_mode TEXT DEFAULT 'adapt',
    segmented_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS passages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    label TEXT NOT NULL,
    text TEXT NOT NULL,
    summary TEXT DEFAULT '',
    suitable_types_json TEXT DEFAULT '[]',
    excluded INTEGER DEFAULT 0,
    located INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS set_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    spec_json TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
"""

JSON_COLUMNS = {
    "spec_json": "spec",
    "analysis_json": "analysis",
    "questions_json": "questions",
    "review_json": "review",
    "guideline_ids_json": "guideline_ids",
    "format_json": "format",
    "result_json": "result",
    "value_json": "value",
    "progress_json": "progress",
    "allocation_json": "allocation",
    "paraphrase_json": "paraphrase",
    "suitable_types_json": "suitable_types",
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _connect()
        _conn.executescript(SCHEMA)
        _migrate(_conn)
        _conn.commit()
    return _conn


def _migrate(c: sqlite3.Connection) -> None:
    """기존 DB에 새 열을 추가한다."""

    def add(table: str, col: str, decl: str) -> None:
        if col not in {r[1] for r in c.execute(f"PRAGMA table_info({table})")}:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

    add("guidelines", "project_id", "INTEGER")
    add("guidelines", "base_id", "INTEGER")
    add("jobs", "progress_json", "TEXT")
    add("jobs", "project_id", "INTEGER")
    add("files", "scope", "TEXT DEFAULT 'range'")
    add("files", "use_mode", "TEXT DEFAULT 'adapt'")
    add("workbooks", "group_id", "INTEGER")
    add("workbooks", "set_index", "INTEGER")
    add("workbooks", "allocation_json", "TEXT")
    add("project_files", "paraphrase_json", "TEXT")
    add("files", "paraphrase_json", "TEXT")
    add("feedback", "guideline_at", "TEXT")


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    with _lock:
        c = conn()
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out: dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if key in JSON_COLUMNS:
            out[JSON_COLUMNS[key]] = json.loads(value) if value else None
        else:
            out[key] = value
    return out


def query(sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    with _lock:
        rows = conn().execute(sql, params).fetchall()
    return [row_to_dict(r) for r in rows]  # type: ignore[misc]


def query_one(sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
    with _lock:
        row = conn().execute(sql, params).fetchone()
    return row_to_dict(row)


def execute(sql: str, params: tuple | list = ()) -> int:
    with tx() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid or cur.rowcount


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def get_setting(key: str, default: Any = None) -> Any:
    row = query_one("SELECT value_json FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: Any) -> None:
    execute(
        "INSERT INTO settings(key, value_json) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
        (key, dumps(value)),
    )
