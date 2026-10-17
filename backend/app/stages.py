"""문항이 많을 때의 단계 실행: 출제 계획 → 묶음별 병렬 제작, 묶음별 병렬 검수, 바뀐 문항만 수정.

문항 수가 묶음 크기(batch_size) 이하이면 예전처럼 Codex 한 번으로 처리한다.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from . import checks, codex, db, pipeline


class StageError(RuntimeError):
    pass


LANG_RULE = """[응답 언어 — 반드시 지킬 것]
JSON의 모든 자연어 값(요약, 설명, 해설, 유형명, 지침, 발문, 로그 등)은 한국어로 쓴다.
영어 지문·영어 선택지·영어 예문처럼 영어가 필요한 내용만 영어로 쓴다. 중국어·일본어는 절대 쓰지 않는다.

"""

LANG_RETRY = """[주의] 직전 응답이 중국어로 작성되었습니다. 이번에는 모든 설명을 반드시 한국어로 작성하세요.

"""


def chinese_chars(value: Any) -> int:
    """응답 JSON 안의 한자(중국어) 글자 수. 원문 지문에 섞인 몇 글자는 무시하도록 호출 쪽에서 기준을 둔다."""

    text = value if isinstance(value, str) else __import__("json").dumps(value, ensure_ascii=False)
    return len(re.findall(r"[\u4e00-\u9fff]", text))


@dataclass
class Ctx:
    job_id: int
    wb: dict[str, Any]
    model: str
    effort: str
    log: Callable[[str], None]

    @property
    def opts(self) -> dict[str, Any]:
        return codex.runner_options()

    def progress(self, done: int, total: int, label: str) -> None:
        db.execute(
            "UPDATE jobs SET progress_json = ? WHERE id = ?",
            (db.dumps({"done": done, "total": total, "label": label}), self.job_id),
        )

    async def call(self, prompt: str, schema: dict[str, Any], sub: str = "") -> dict[str, Any]:
        prompt = LANG_RULE + prompt
        self.log(f"{'[' + sub + '] ' if sub else ''}프롬프트 준비 완료 ({len(prompt):,}자)")
        for attempt in range(2):
            res = await codex.run_codex(
                job_id=self.job_id, prompt=prompt, schema=schema, model=self.model, effort=self.effort,
                on_log=self.log, sub=sub if attempt == 0 else f"{sub or '응답'} 언어 재시도",
            )
            if not res.ok:
                raise StageError(res.error or "Codex 실행 실패")
            n = chinese_chars(res.output)
            if n < 20:
                return res.output
            self.log(f"{'[' + sub + '] ' if sub else ''}응답에 중국어 문자가 {n}자 섞여 있어 한국어로 다시 요청합니다.")
            prompt = LANG_RETRY + prompt
        return res.output


def chunks(items: list[Any], size: int) -> list[list[Any]]:
    size = max(1, int(size))
    return [items[i : i + size] for i in range(0, len(items), size)]


async def gather_limited(ctx: Ctx, jobs: list[tuple[str, Callable[[], Awaitable[Any]]]], label: str, offset: int = 0, total: int | None = None) -> list[Any]:
    """동시 실행 수를 제한해 병렬로 돌리고, 끝날 때마다 진행률을 갱신한다. 실패는 예외 객체로 돌려준다."""

    sem = asyncio.Semaphore(max(1, int(ctx.opts.get("concurrency") or 3)))
    total = total if total is not None else len(jobs)
    done = 0

    async def one(name: str, fn: Callable[[], Awaitable[Any]]) -> Any:
        nonlocal done
        async with sem:
            if codex.is_cancelled(ctx.job_id):
                return StageError("사용자가 작업을 중단했습니다.")
            try:
                return await fn()
            except Exception as exc:  # noqa: BLE001
                ctx.log(f"[{name}] 실패: {exc}")
                return exc
            finally:
                done += 1
                ctx.progress(offset + done, total, label)

    ctx.progress(offset, total, label)
    return await asyncio.gather(*(one(n, f) for n, f in jobs))


def _normalize(q: dict[str, Any], plan_item: dict[str, Any] | None = None) -> dict[str, Any]:
    if plan_item:
        q["number"] = plan_item["number"]
        q["kind"] = plan_item["kind"]
        if plan_item.get("passage_id"):
            q["passage_id"] = plan_item["passage_id"]
            q["source"] = f"{plan_item.get('file_name', '')} · {plan_item['source']}".strip(" ·")
    if q.get("kind") == "서술형":
        q["choices"] = []
    q.setdefault("points", 0)
    q.setdefault("rubric", "")
    return q


# ---------------------------------------------------------------- 제작

async def generate(ctx: Ctx) -> dict[str, Any]:
    spec = ctx.wb.get("spec") or {}
    mc, essay = pipeline.counts(spec)
    total = mc + essay
    size = int(ctx.opts.get("batch_size") or 5)

    alloc = (ctx.wb.get("allocation") or {}).get("items") or []
    if alloc and len(alloc) == total:
        return await _generate_allocated(ctx, alloc, spec, mc, size)

    if total <= size:
        answers = checks.answer_plan(mc) if spec.get("balance_answers", True) else []
        answer_map = {i + 1: a for i, a in enumerate(answers)}
        ctx.progress(0, 1, "문항 제작")
        prompt, schema = pipeline.prompt_generate(ctx.wb, answer_map)
        out = await ctx.call(prompt, schema)
        ctx.progress(1, 1, "문항 제작")
        out["questions"] = [_normalize(q) for q in out.get("questions", [])]
        return out

    # 1) 출제 계획표
    batches_n = len(chunks(list(range(total)), size))
    steps = 1 + batches_n
    ctx.progress(0, steps, "출제 계획")
    ctx.log(f"문항 {total}개 → 출제 계획 1회 + {batches_n}개 묶음(묶음당 {size}문항, 동시 {ctx.opts.get('concurrency')}개)으로 나눠 제작합니다.")
    prompt, schema = pipeline.prompt_plan(ctx.wb)
    plan = await ctx.call(prompt, schema, sub="계획")
    items = plan.get("items") or []
    if len(items) != total:
        ctx.log(f"계획표 문항 수가 {len(items)}개라 {total}개로 맞춥니다.")
        items = (items + [dict(items[-1]) for _ in range(total - len(items))])[:total] if items else []
        if not items:
            raise StageError("출제 계획표가 비어 있습니다.")
    answers = checks.answer_plan(mc) if spec.get("balance_answers", True) else []
    for i, it in enumerate(items):
        it["number"] = i + 1
        it["kind"] = "객관식" if i < mc else "서술형"
        it["answer"] = str(answers[i]) if i < len(answers) else ""
    plan["items"] = items
    ctx.progress(1, steps, "문항 제작")

    # 2) 묶음별 병렬 제작 (실패한 묶음은 한 번 더 시도)
    return await _run_batches(ctx, plan, items, size, offset=1, steps=steps)


async def _generate_allocated(ctx: Ctx, alloc: list[dict[str, Any]], spec: dict[str, Any], mc: int, size: int) -> dict[str, Any]:
    """본문 배정표가 있으면 계획 단계 없이 배정대로 묶음 제작한다."""

    ids = [it["passage_id"] for it in alloc if it.get("passage_id")]
    rows = db.query(
        f"SELECT p.id, p.text, f.use_mode, f.paraphrase_json FROM passages p JOIN project_files f ON f.id = p.file_id WHERE p.id IN ({','.join('?' * len(ids))})", ids
    ) if ids else []
    texts = {r["id"]: r["text"] for r in rows}
    modes = {r["id"]: r["use_mode"] for r in rows}  # 배정 뒤에 바꾼 '지문 사용 방식'도 반영
    para = {r["id"]: r.get("paraphrase") for r in rows}
    answers = checks.answer_plan(mc) if spec.get("balance_answers", True) else []
    items = []
    for i, it in enumerate(alloc):
        items.append({
            "number": i + 1,
            "kind": it.get("kind") or ("객관식" if i < mc else "서술형"),
            "type": it.get("type") or "자유",
            "difficulty": spec.get("difficulty") or "",
            "source": it.get("label", ""),
            "point": "(출제자가 정함 — 같은 본문을 쓰는 다른 세트·문항과 겹치지 않게)",
            "file_name": it.get("file_name", ""),
            "use_mode": modes.get(it.get("passage_id")) or it.get("use_mode") or "adapt",
            "passage_id": it.get("passage_id"),
            "passage_text": texts.get(it.get("passage_id"), ""),
            "paraphrase": para.get(it.get("passage_id")),
            "answer": str(answers[i]) if i < len(answers) else "",
        })
    missing = [it["number"] for it in items if not it["passage_text"]]
    if missing:
        raise StageError(f"배정된 본문을 찾을 수 없습니다 ({missing}번). 본문 배정을 다시 하세요.")
    plan = {"title": spec.get("title") or "", "items": items}
    steps = len(chunks(items, size))
    ctx.log(f"본문 배정표대로 {len(items)}문항을 {steps}개 묶음으로 제작합니다.")
    return await _run_batches(ctx, plan, items, size, offset=0, steps=steps)


async def _run_batches(ctx: Ctx, plan: dict[str, Any], items: list[dict[str, Any]], size: int, offset: int, steps: int) -> dict[str, Any]:
    spec = ctx.wb.get("spec") or {}

    def make_job(batch: list[dict[str, Any]]) -> tuple[str, Callable[[], Awaitable[Any]]]:
        name = f"{batch[0]['number']}~{batch[-1]['number']}번"

        async def run() -> list[dict[str, Any]]:
            want = {it["number"]: it for it in batch}
            last: Exception | None = None
            for attempt in range(2):
                try:
                    p, sch = pipeline.prompt_generate_batch(ctx.wb, plan, batch)
                    out = await ctx.call(p, sch, sub=name if attempt == 0 else f"{name} 재시도")
                    got = {q.get("number"): q for q in out.get("questions", [])}
                    if not set(want) <= set(got):
                        qs = out.get("questions", [])
                        if len(qs) == len(batch):
                            got = {it["number"]: q for it, q in zip(batch, qs)}
                        else:
                            raise StageError(f"{sorted(set(want) - set(got))}번이 빠졌습니다.")
                    return [_normalize(got[n], want[n]) for n in want]
                except StageError as exc:
                    last = exc
                    if codex.is_cancelled(ctx.job_id):
                        break
            raise last or StageError("실패")

        return name, run

    results = await gather_limited(ctx, [make_job(b) for b in chunks(items, size)], "문항 제작", offset=offset, total=steps)
    questions: list[dict[str, Any]] = []
    failed: list[str] = []
    for batch, r in zip(chunks(items, size), results):
        if isinstance(r, Exception):
            failed.append(f"{batch[0]['number']}~{batch[-1]['number']}번")
        else:
            questions.extend(r)
    questions.sort(key=lambda q: q["number"])
    saved_plan = {**plan, "items": [{k: v for k, v in it.items() if k != "passage_text"} for it in plan["items"]]}
    out = {"title": plan.get("title") or spec.get("title") or "", "questions": questions, "change_log": [], "plan": saved_plan}
    if failed:
        out["failed_batches"] = failed
    return out


# ---------------------------------------------------------------- 검수

async def review(ctx: Ctx, rule_result: dict[str, Any]) -> dict[str, Any]:
    qs = (ctx.wb.get("questions") or {}).get("questions", [])
    size = int(ctx.opts.get("batch_size") or 5)
    if len(qs) <= size:
        ctx.progress(0, 1, "검수")
        prompt, schema = pipeline.prompt_review(ctx.wb, rule_result)
        out = await ctx.call(prompt, schema)
        ctx.progress(1, 1, "검수")
        return out

    parts = chunks(qs, size)
    ctx.log(f"문항 {len(qs)}개 → {len(parts)}개 묶음 검수 + 전체 점검을 함께 실행합니다.")
    jobs: list[tuple[str, Callable[[], Awaitable[Any]]]] = [
        ("전체 점검", lambda: ctx.call(*pipeline.prompt_review_global(ctx.wb, rule_result), sub="전체 점검"))
    ]
    for part in parts:
        name = f"{part[0]['number']}~{part[-1]['number']}번"
        jobs.append((name, (lambda p=part, n=name: ctx.call(*pipeline.prompt_review(ctx.wb, rule_result, p), sub=n))))
    results = await gather_limited(ctx, jobs, "검수")
    ok = [r for r in results if not isinstance(r, Exception)]
    if not ok:
        raise StageError("모든 검수 묶음이 실패했습니다.")
    glob = results[0] if not isinstance(results[0], Exception) else None
    batch_ok = [r for r in results[1:] if not isinstance(r, Exception)]
    issues = [i for r in ok for i in r.get("issues", [])]
    scores = [r.get("score", 0) for r in batch_ok]
    score = round((sum(scores) / len(scores) + glob["score"]) / 2) if glob and scores else (glob or ok[0])["score"]
    failed = [jobs[i][0] for i, r in enumerate(results) if isinstance(r, Exception)]
    summary = (glob or {}).get("summary") or " / ".join(r.get("summary", "") for r in batch_ok)
    if failed:
        summary += f" (검수 실패: {', '.join(failed)})"
    return {"summary": summary, "score": score, "issues": issues}


# ---------------------------------------------------------------- 수정

REQ_NUM = re.compile(r"^\[(\d+)번(?! 지문)")
REQ_SET = re.compile(r"^\[(\d+)번 지문\]")  # 양식 모드: 검수가 지문 세트 전체에 낸 지적


async def revise(ctx: Ctx, requests: list[str]) -> dict[str, Any]:
    """요청이 걸린 문항만 묶음으로 나눠 고치고, 고친 문항만 원래 자리에 끼워 넣는다."""

    current = ctx.wb.get("questions") or {"title": "", "questions": []}
    qs = current.get("questions", [])
    by_num = {q["number"]: q for q in qs}
    targeted: dict[int, list[str]] = {}
    general: list[str] = []
    for r in requests:
        m = REQ_NUM.match(r)
        if m and int(m.group(1)) in by_num:
            targeted.setdefault(int(m.group(1)), []).append(r)
        else:
            general.append(r)

    targets = qs if general else [by_num[n] for n in sorted(targeted)]
    size = int(ctx.opts.get("batch_size") or 5)
    parts = chunks(targets, size)
    ctx.log(f"수정 대상 {len(targets)}문항 → {len(parts)}개 묶음" + (" (전체 요청 포함)" if general else ""))

    jobs = []
    for part in parts:
        nums = [q["number"] for q in part]
        reqs = general + [r for n in nums for r in targeted.get(n, [])]
        name = f"{nums[0]}~{nums[-1]}번" if len(parts) > 1 else ""
        jobs.append((name or "수정", (lambda p=part, rq=reqs, n=name: ctx.call(*pipeline.prompt_revise(ctx.wb, rq, p), sub=n))))
    results = await gather_limited(ctx, jobs, "문항 수정")

    changed: dict[int, dict[str, Any]] = {}
    log: list[str] = []
    failed = []
    for part, r in zip(parts, results):
        if isinstance(r, Exception):
            failed.append(f"{part[0]['number']}~{part[-1]['number']}번")
            continue
        allowed = {q["number"] for q in part}
        for q in r.get("questions", []):
            if q.get("number") in allowed:
                orig = by_num[q["number"]]
                changed[q["number"]] = _normalize(q, {"number": q["number"], "kind": orig.get("kind") or ("서술형" if not orig.get("choices") else "객관식")})
                if orig.get("passage_id"):
                    changed[q["number"]]["passage_id"] = orig["passage_id"]
        log.extend(r.get("change_log", []))
    if failed and not changed:
        raise StageError(f"수정 실패: {', '.join(failed)}")
    merged = [changed.get(q["number"], q) for q in qs]
    out = {"title": current.get("title", ""), "questions": merged, "change_log": log, "changed_numbers": sorted(changed)}
    if failed:
        out["failed_batches"] = failed
    return out


# ================================================================ 양식(지문 세트형) 모드

async def generate_form(ctx: Ctx) -> dict[str, Any]:
    from . import form_pipeline as fp

    wb = ctx.wb
    spec = wb.get("spec") or {}
    form, segs = fp.form_context(wb)
    n = int(spec.get("passage_count") or form["block_count"])
    alloc = (wb.get("allocation") or {}).get("items") or []
    if len(alloc) != n:
        raise StageError(f"지문 {n}개를 먼저 배정하세요. (현재 배정 {len(alloc)}개) — 제작 단계의 '본문 배정'에서 자동 배정을 누르세요.")
    passages = [fp.passage_row(it.get("passage_id")) for it in alloc]
    if any(p is None for p in passages):
        raise StageError("배정된 본문을 찾을 수 없습니다. 본문 배정을 다시 하세요.")
    plans = fp.answer_plan(n, segs, fp.WEIGHT_PRESETS.get(spec.get("answer_weights") or "even"))
    labels = [p["label"] for p in passages]
    valid = {s["segment_id"] for s in fp.used_segments(segs)}
    order = [s["segment_id"] for s in segs]
    group_of = {s["segment_id"]: s["usage"] for s in segs if s["usage"].startswith("pick")}
    ctx.log(f"지문 {n}개 × 하위 문항 {len(valid)}종을 지문별로 나눠 제작합니다.")

    def make(i: int) -> tuple[str, Callable[[], Awaitable[Any]]]:
        p = passages[i]
        name = f"{i + 1}번 지문"

        async def run() -> dict[str, Any]:
            last: Exception | None = None
            for attempt in range(2):
                try:
                    others = [l for k, l in enumerate(labels) if k != i]
                    out = await ctx.call(*fp.prompt_set(wb, form, segs, p, i + 1, plans[i], others), sub=name if attempt == 0 else f"{name} 재시도")
                    items, seen_groups = [], set()
                    for it in sorted(out.get("items", []), key=lambda x: order.index(x["segment_id"]) if x.get("segment_id") in order else 99):
                        sid = it.get("segment_id")
                        if sid not in valid:
                            continue
                        g = group_of.get(sid)
                        if g and g in seen_groups:
                            continue
                        if g:
                            seen_groups.add(g)
                        items.append(it)
                    if not items:
                        raise StageError("하위 문항이 비어 있습니다.")
                    return {"index": i + 1, "passage_id": p["id"], "label": out.get("label") or p["label"],
                            "passage": fp.clean_passage(out.get("passage", "")), "logic_flow": out.get("logic_flow") or [],
                            "items": [fp.clean_item(it) for it in items]}
                except StageError as exc:
                    last = exc
                    if codex.is_cancelled(ctx.job_id):
                        break
            raise last or StageError("실패")

        return name, run

    results = await gather_limited(ctx, [make(i) for i in range(n)], "지문 세트 제작")
    sets, failed = [], []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            failed.append(f"{i + 1}번 지문")
        else:
            sets.append(r)
    out = {"mode": "form", "title": spec.get("title") or "", "sets": sets, "questions": fp.flatten(sets), "change_log": []}
    if failed:
        out["failed_batches"] = failed
    return out


async def layout_form(ctx: Ctx) -> dict[str, Any]:
    """세트마다 양식 칸 채우기 내용을 만든다 (내용이 바뀐 세트만 다시)."""

    from . import form_pipeline as fp

    wb = ctx.wb
    data = wb.get("questions") or {}
    form, segs = fp.form_context(wb)
    all_ids = [s["id"] for s in form["segments"]]
    style = fp.style_of(wb)
    todo = [st for st in data.get("sets", []) if (st.get("layout") or {}).get("hash") != fp.content_hash(st, style)]
    ctx.log(f"양식 배치: 지문 세트 {len(data.get('sets', []))}개 중 {len(todo)}개를 새로 배치합니다.")

    def make(st: dict[str, Any]) -> tuple[str, Callable[[], Awaitable[Any]]]:
        async def run() -> dict[str, Any]:
            out = await ctx.call(*fp.prompt_layout(wb, form, segs, st), sub=f"{st['index']}번 지문")
            fills = {f["slot"]: f["text"] for f in out.get("fills", []) if f.get("slot")}
            used = {it["segment_id"] for it in st.get("items", [])}
            return {"hash": fp.content_hash(st, style), "fills": fills, "remove_segments": [s for s in all_ids if s not in used]}

        return f"{st['index']}번 지문", run

    results = await gather_limited(ctx, [make(st) for st in todo], "양식 배치")
    failed = []
    for st, r in zip(todo, results):
        if isinstance(r, Exception):
            failed.append(f"{st['index']}번 지문")
        else:
            st["layout"] = r
    if failed:
        raise StageError(f"양식 배치 실패: {', '.join(failed)}")
    return data


async def review_form(ctx: Ctx, rule_result: dict[str, Any]) -> dict[str, Any]:
    from . import form_pipeline as fp

    wb = ctx.wb
    data = wb.get("questions") or {}
    form, segs = fp.form_context(wb)
    qs = data.get("questions", [])
    jobs = []
    for st in data.get("sets", []):
        numbers = {q["segment_id"]: q["number"] for q in qs if q.get("set") == st["index"]}
        src = (fp.passage_row(st.get("passage_id")) or {}).get("text", "")
        jobs.append((f"{st['index']}번 지문", (lambda st=st, nb=numbers, src=src: ctx.call(*fp.prompt_set_review(wb, form, segs, st, nb, rule_result, src), sub=f"{st['index']}번 지문"))))
    results = await gather_limited(ctx, jobs, "검수")
    ok = [r for r in results if not isinstance(r, Exception)]
    if not ok:
        raise StageError("모든 지문 세트 검수가 실패했습니다.")
    failed = [jobs[i][0] for i, r in enumerate(results) if isinstance(r, Exception)]
    summary = " / ".join(f"[{jobs[i][0]}] {r.get('summary', '')}" for i, r in enumerate(results) if not isinstance(r, Exception))
    if failed:
        summary += f" (검수 실패: {', '.join(failed)})"
    # 세트 전체 지적(number 0)은 어느 지문 것인지 남겨야 수정 때 그 지문에만 전달된다
    sets = data.get("sets", [])
    issues = [{**i, "set": sets[k]["index"]} if not i.get("number") else i
              for k, r in enumerate(results) if not isinstance(r, Exception) for i in r.get("issues", [])]
    return {"summary": summary, "score": round(sum(r.get("score", 0) for r in ok) / len(ok)), "issues": issues}


async def revise_form(ctx: Ctx, requests: list[str]) -> dict[str, Any]:
    from . import form_pipeline as fp

    wb = ctx.wb
    data = wb.get("questions") or {}
    form, segs = fp.form_context(wb)
    qs = data.get("questions", [])
    set_of = {q["number"]: q.get("set") for q in qs}
    targeted: dict[int, list[str]] = {}
    general: list[str] = []
    sets = data.get("sets", [])
    set_ids = {str(st["index"]) for st in sets}
    for r in requests:
        m, ms = REQ_NUM.match(r), REQ_SET.match(r)
        if ms and ms.group(1) in set_ids:
            key = next(st["index"] for st in sets if str(st["index"]) == ms.group(1))
            targeted.setdefault(key, []).append(r)
        elif m and int(m.group(1)) in set_of:
            targeted.setdefault(set_of[int(m.group(1))], []).append(r)
        else:
            general.append(r)
    targets = sets if general else [st for st in sets if st["index"] in targeted]
    ctx.log(f"수정 대상 지문 세트 {len(targets)}개" + (" (전체 요청 포함)" if general else ""))

    def make(st: dict[str, Any]) -> tuple[str, Callable[[], Awaitable[Any]]]:
        async def run() -> dict[str, Any]:
            src = (fp.passage_row(st.get("passage_id")) or {}).get("text", "")
            return await ctx.call(*fp.prompt_set_revise(wb, form, segs, st, general + targeted.get(st["index"], []), src), sub=f"{st['index']}번 지문")

        return f"{st['index']}번 지문", run

    results = await gather_limited(ctx, [make(st) for st in targets], "문항 수정")
    log, changed_sets, failed = [], [], []
    valid = {s["segment_id"] for s in fp.used_segments(segs)}
    for st, r in zip(targets, results):
        if isinstance(r, Exception):
            failed.append(f"{st['index']}번 지문")
            continue
        items = [it for it in r.get("items", []) if it.get("segment_id") in valid] or st["items"]
        st.update({"label": r.get("label") or st["label"], "passage": fp.clean_passage(r.get("passage") or st["passage"]),
                   "logic_flow": r.get("logic_flow") or st.get("logic_flow", []), "items": [fp.clean_item(it) for it in items]})
        log.extend(f"[{st['index']}번 지문] {c}" for c in r.get("change_log", []))
        changed_sets.append(st["index"])
    if failed and not changed_sets:
        raise StageError(f"수정 실패: {', '.join(failed)}")
    data["questions"] = fp.flatten(sets)
    changed = [q["number"] for q in data["questions"] if q.get("set") in changed_sets]
    out = {**data, "change_log": log, "changed_numbers": changed}
    if failed:
        out["failed_batches"] = failed
    return out
