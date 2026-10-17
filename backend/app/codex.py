"""Codex CLI 실행기.

각 단계(분석/제작/검수/수정/지침반영)는 `codex exec`를 비대화형으로 호출하고,
`--output-schema`로 JSON 응답 형태를 고정한다. 진행 상황은 `--json` 이벤트를
작업 로그에 쌓아 프론트엔드가 실시간으로 보여준다.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import db

STAGES: dict[str, str] = {
    "segment": "본문 나누기",
    "analyze": "샘플 분석",
    "generate": "문제 제작",
    "review": "검수",
    "revise": "수정 (피드백/검수 반영)",
    "layout": "양식 배치 (지문 세트형 출력)",
    "guideline": "지침 업데이트 제안",
}

EFFORT_LABELS = {
    "minimal": "최소",
    "low": "낮음",
    "medium": "보통",
    "high": "높음",
    "xhigh": "매우 높음",
    "max": "최대",
    "ultra": "울트라",
}

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
JOBS_DIR = db.DATA_DIR / "jobs"


def codex_bin() -> str | None:
    return shutil.which("codex") or (
        "/opt/homebrew/bin/codex" if Path("/opt/homebrew/bin/codex").exists() else None
    )


def available_models() -> list[dict[str, Any]]:
    """`~/.codex/models_cache.json`에서 사용 가능한 모델과 effort 단계를 읽는다."""

    path = CODEX_HOME / "models_cache.json"
    models: list[dict[str, Any]] = []
    try:
        data = json.loads(path.read_text())
        items = data.get("models", data) if isinstance(data, dict) else data
        for item in items:
            slug = item.get("slug") or item.get("id")
            if not slug:
                continue
            efforts = [
                lvl.get("effort")
                for lvl in item.get("supported_reasoning_levels") or []
                if lvl.get("effort")
            ]
            models.append(
                {
                    "id": slug,
                    "name": item.get("display_name") or slug,
                    "description": item.get("description") or "",
                    "efforts": efforts or ["low", "medium", "high"],
                    "default_effort": item.get("default_reasoning_level") or "medium",
                }
            )
    except Exception:
        pass
    if not models:
        models = [
            {"id": "gpt-5-codex", "name": "gpt-5-codex", "description": "",
             "efforts": ["low", "medium", "high"], "default_effort": "medium"}
        ]
    return models


def default_model() -> str:
    try:
        for line in (CODEX_HOME / "config.toml").read_text().splitlines():
            line = line.strip()
            if line.startswith("model ") or line.startswith("model="):
                return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return available_models()[0]["id"]


DEFAULT_EFFORTS = {
    "segment": "medium",
    "analyze": "medium",
    "generate": "high",
    "review": "high",
    "revise": "medium",
    "layout": "medium",
    "guideline": "medium",
}


def stage_settings() -> dict[str, dict[str, str]]:
    saved = db.get_setting("stage_models", {}) or {}
    model = default_model()
    out = {}
    for stage in STAGES:
        cfg = saved.get(stage) or {}
        out[stage] = {
            "model": cfg.get("model") or model,
            "effort": cfg.get("effort") or DEFAULT_EFFORTS[stage],
        }
    return out


RUNNER_DEFAULTS = {
    "ignore_user_config": True,
    "timeout_minutes": 30,
    "batch_size": 5,  # 묶음 하나에 넣을 문항 수
    "concurrency": 3,  # 동시에 실행할 Codex 세션 수
}


def runner_options() -> dict[str, Any]:
    return {**RUNNER_DEFAULTS, **(db.get_setting("runner_options", {}) or {})}


@dataclass
class CodexResult:
    ok: bool
    output: Any
    raw: str
    error: str | None = None


def _summarize_event(event: dict[str, Any]) -> str | None:
    """JSONL 이벤트를 사람이 읽을 수 있는 한 줄로 바꾼다."""

    etype = event.get("type", "")
    item = event.get("item") or {}
    itype = item.get("type") or item.get("item_type") or ""
    if etype == "thread.started":
        return "Codex 세션 시작"
    if etype == "turn.started":
        return "작업 시작"
    if etype in ("item.started", "item.completed"):
        if itype == "reasoning":
            text = (item.get("text") or item.get("summary") or "").strip()
            return f"생각 중: {text[:300]}" if text and etype == "item.completed" else None
        if itype == "command_execution":
            cmd = item.get("command", "")
            return f"명령 실행: {cmd[:200]}" if etype == "item.started" else None
        if itype == "agent_message" and etype == "item.completed":
            return "응답 작성 완료"
        if itype == "error":
            return f"오류: {item.get('message', '')}"
    if etype == "turn.completed":
        usage = event.get("usage") or {}
        tok = usage.get("output_tokens")
        return f"작업 완료 (출력 토큰 {tok})" if tok else "작업 완료"
    if etype in ("turn.failed", "error"):
        err = event.get("error") or event
        return f"실패: {err.get('message', err) if isinstance(err, dict) else err}"
    return None


async def run_codex(
    *,
    job_id: int,
    prompt: str,
    schema: dict[str, Any],
    model: str,
    effort: str,
    on_log: Callable[[str], Awaitable[None] | None],
    attachments: dict[str, str] | None = None,
    sub: str = "",
) -> CodexResult:
    """Codex를 실행하고 스키마에 맞춘 JSON 결과를 반환한다."""

    binary = codex_bin()
    if not binary:
        return CodexResult(False, None, "", "codex CLI를 찾을 수 없습니다. `npm i -g @openai/codex` 등으로 설치하세요.")

    if job_id in _cancelled:
        return CodexResult(False, None, "", "사용자가 작업을 중단했습니다.")
    workdir = JOBS_DIR / str(job_id) / sub if sub else JOBS_DIR / str(job_id)
    workdir.mkdir(parents=True, exist_ok=True)
    schema_path = workdir / "schema.json"
    out_path = workdir / "result.json"
    (workdir / "prompt.md").write_text(prompt)
    schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2))
    for name, content in (attachments or {}).items():
        (workdir / name).write_text(content)

    opts = runner_options()
    cmd = [
        binary, "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--json",
        "--color", "never",
        "-s", "read-only",
        "-C", str(workdir),
        "-m", model,
        "-c", f'model_reasoning_effort="{effort}"',
        "--output-schema", str(schema_path),
        "-o", str(out_path),
    ]
    if opts.get("ignore_user_config", True):
        # 개인 설정·플러그인(스킬)·앱 연동을 건너뛰어 문제 작업에만 집중시킨다
        cmd += ["--ignore-user-config", "--disable", "plugins", "--disable", "apps"]
    # 작업 폴더(data/jobs/…)가 이 프로젝트 안에 있어서, 개발용 AGENTS.md가 문제 생성에 섞이지 않도록 끈다
    cmd += ["-c", "project_doc_max_bytes=0"]
    cmd.append("-")

    async def log(msg: str) -> None:
        res = on_log(f"[{sub}] {msg}" if sub else msg)
        if asyncio.iscoroutine(res):
            await res

    async with _slot():
        if job_id in _cancelled:
            return CodexResult(False, None, "", "사용자가 작업을 중단했습니다.")
        return await _run(cmd, prompt, workdir, out_path, job_id, opts, log, model, effort)


_sem: asyncio.Semaphore | None = None
_sem_size = 0


def _slot() -> asyncio.Semaphore:
    """앱 전체에서 동시에 도는 Codex 세션 수를 '동시 실행 수' 설정으로 제한한다."""

    global _sem, _sem_size
    size = max(1, int(runner_options().get("concurrency") or 3))
    if _sem is None or size != _sem_size:
        _sem, _sem_size = asyncio.Semaphore(size), size
    return _sem


async def _run(cmd: list[str], prompt: str, workdir: Path, out_path: Path, job_id: int, opts: dict[str, Any], log: Callable[[str], Awaitable[None]], model: str, effort: str) -> CodexResult:
    await log(f"모델 {model} · effort {effort} 로 실행합니다.")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(workdir),
        limit=16 * 1024 * 1024,
    )
    _running.setdefault(job_id, set()).add(proc)
    assert proc.stdin and proc.stdout and proc.stderr
    proc.stdin.write(prompt.encode())
    await proc.stdin.drain()
    proc.stdin.close()

    stderr_chunks: list[bytes] = []

    async def read_stderr() -> None:
        assert proc.stderr
        while chunk := await proc.stderr.read(4096):
            stderr_chunks.append(chunk)

    async def read_stdout() -> None:
        assert proc.stdout
        while line := await proc.stdout.readline():
            text = line.decode(errors="replace").strip()
            if not text:
                continue
            try:
                summary = _summarize_event(json.loads(text))
            except json.JSONDecodeError:
                summary = text[:300]
            if summary:
                await log(summary)

    timeout = float(opts.get("timeout_minutes", 30)) * 60
    try:
        await asyncio.wait_for(
            asyncio.gather(read_stdout(), read_stderr(), proc.wait()), timeout=timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        return CodexResult(False, None, "", f"시간 초과 ({opts.get('timeout_minutes')}분)")
    finally:
        _running.get(job_id, set()).discard(proc)

    raw = out_path.read_text() if out_path.exists() else ""
    if proc.returncode != 0 or not raw.strip():
        err = b"".join(stderr_chunks).decode(errors="replace")[-2000:]
        if proc.returncode in (-9, -15) or job_id in _cancelled:
            err = "사용자가 작업을 중단했습니다."
        return CodexResult(False, None, raw, err or f"codex 종료 코드 {proc.returncode}")
    try:
        return CodexResult(True, json.loads(raw), raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return CodexResult(True, json.loads(raw[start : end + 1]), raw)
            except json.JSONDecodeError:
                pass
        return CodexResult(False, None, raw, "Codex 응답을 JSON으로 해석하지 못했습니다.")


_running: dict[int, set[asyncio.subprocess.Process]] = {}
_cancelled: set[int] = set()


def cancel(job_id: int) -> bool:
    """작업에 딸린 모든 Codex 프로세스를 멈추고, 아직 시작 안 한 묶음도 막는다."""

    _cancelled.add(job_id)
    procs = [p for p in _running.get(job_id, set()) if p.returncode is None]
    for proc in procs:
        proc.terminate()
    return bool(procs)


def is_cancelled(job_id: int) -> bool:
    return job_id in _cancelled
