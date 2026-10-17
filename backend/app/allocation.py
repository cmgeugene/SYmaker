"""여러 세트에 '본문 × 유형'을 배정한다 (모델이 아니라 규칙으로 계산 — 항상 지켜지도록).

규칙 (비용이 낮은 쪽을 고른다)
1. 한 세트 안에서 같은 본문을 두 번 쓰지 않는다.            (본문 수가 모자랄 때만 어쩔 수 없이 허용)
2. 같은 본문을 다른 세트에서 다시 쓰면 다른 유형으로 낸다.    (이전 세트 사용 기록 포함)
3. 본문에 맞지 않는 유형은 배정하지 않는다.                   (본문 나누기에서 표시한 적합 유형)
4. 덜 쓰인 본문부터 쓴다 → 모든 본문이 고르게 쓰인다.
5. 한 세트 안에서 자료(파일)별 비율이 본문 수 비율에 가깝게 섞인다.
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Any

from . import pipeline

ESSAY = "서술형"


def build_slots(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """제작 설정 → 문항 칸 목록. 객관식(유형 순서대로) 다음 서술형."""

    mc, essay = pipeline.counts(spec)
    mc_slots: list[str | None] = []
    essay_slots: list[str] = []
    for t in spec.get("types") or []:
        name, cnt = (t.get("name") or "").strip(), int(t.get("count") or 0)
        if not name or cnt <= 0:
            continue
        if "서술" in name:
            essay_slots += [name] * cnt
        else:
            mc_slots += [name] * cnt
    mc_slots = (mc_slots + [None] * mc)[:mc]
    essay_slots = (essay_slots + [ESSAY] * essay)[:essay]
    slots = [{"kind": "객관식", "type": t} for t in mc_slots] + [{"kind": "서술형", "type": t} for t in essay_slots]
    for i, s in enumerate(slots, 1):
        s["number"] = i
    return slots


FORM_SLOT = "지문 세트"


def build_form_slots(n: int) -> list[dict[str, Any]]:
    """양식 모드: 지문 n개 (각 지문이 하위 문항 전부를 가진다)."""

    return [{"number": i + 1, "kind": "객관식", "type": FORM_SLOT} for i in range(n)]


def _fits(ptypes: list[str], t: str | None) -> bool:
    if not t or not ptypes or t == FORM_SLOT:
        return True
    a = t.replace(" ", "")
    return any(a in p.replace(" ", "") or p.replace(" ", "") in a for p in ptypes)


def allocate(
    passages: list[dict[str, Any]],
    sets: list[tuple[int, list[dict[str, Any]]]],
    ledger: list[dict[str, Any]],
    seed: int | None = None,
) -> dict[int, dict[str, Any]]:
    """sets: [(workbook_id, slots)] → {workbook_id: {"items": [...], "warnings": [...]}}"""

    rng = random.Random(seed)
    if not passages:
        return {wid: {"items": [], "warnings": ["출제 범위 본문이 없습니다. 자료실에서 본문 나누기를 먼저 하세요."]} for wid, _ in sets}

    by_id = {p["id"]: p for p in passages}
    use = Counter(e["passage_id"] for e in ledger if e["passage_id"] in by_id)
    pairs = {(e["passage_id"], (e.get("type") or "").replace(" ", "")) for e in ledger}
    file_total = Counter(p["file_id"] for p in passages)
    share = {f: n / len(passages) for f, n in file_total.items()}

    result: dict[int, dict[str, Any]] = {}
    for wid, slots in sets:
        in_set: Counter = Counter()
        file_in_set: Counter = Counter()
        type_in_set: Counter = Counter()
        warnings: list[str] = []
        if len(passages) < len(slots):
            warnings.append(f"출제 범위 본문이 {len(passages)}개로 문항 {len(slots)}개보다 적어, 한 세트 안에서 일부 본문을 (다른 유형으로) 다시 씁니다.")

        # 맞는 본문이 적은 유형부터 채운다
        order = sorted(slots, key=lambda s: (sum(_fits(p.get("suitable_types") or [], s["type"]) for p in passages), rng.random()))
        chosen: dict[int, dict[str, Any]] = {}
        for s in order:
            t = s["type"]
            best, best_cost = None, None
            for p in passages:
                pid = p["id"]
                cost = 100_000 * in_set[pid]
                if t and (pid, t.replace(" ", "")) in pairs:
                    cost += 10_000
                if not _fits(p.get("suitable_types") or [], t):
                    cost += 5_000
                cost += 100 * use[pid]
                cost += 40 * file_in_set[p["file_id"]] / max(share[p["file_id"]], 0.01) / max(len(slots), 1)
                cost += rng.random()
                if best_cost is None or cost < best_cost:
                    best, best_cost = p, cost
            assert best is not None
            pid = best["id"]
            item_type = t
            if not item_type:  # 유형 미지정 칸: 이 본문에 맞고, 이 본문에 아직 안 쓴, 이 세트에 덜 나온 유형
                cands = [x for x in (best.get("suitable_types") or []) if "서술" not in x] or ["자유"]
                cands.sort(key=lambda x: ((pid, x.replace(" ", "")) in pairs, type_in_set[x], rng.random()))
                item_type = cands[0]
            if in_set[pid]:
                warnings.append(f"{s['number']}번: '{best['label']}' 본문을 이 세트에서 다시 사용")
            elif (pid, item_type.replace(" ", "")) in pairs:
                warnings.append(f"{s['number']}번: '{best['label']}' 본문을 다른 세트와 같은 유형({item_type})으로 사용")
            if not _fits(best.get("suitable_types") or [], item_type):
                warnings.append(f"{s['number']}번: '{best['label']}' 본문이 '{item_type}' 유형에 적합하지 않을 수 있음")
            in_set[pid] += 1
            use[pid] += 1
            file_in_set[best["file_id"]] += 1
            type_in_set[item_type] += 1
            pairs.add((pid, item_type.replace(" ", "")))
            chosen[s["number"]] = {
                "number": s["number"],
                "kind": s["kind"],
                "type": item_type,
                "passage_id": pid,
                "label": best["label"],
                "file_name": best.get("file_name", ""),
                "use_mode": best.get("use_mode", "adapt"),
            }
        result[wid] = {"items": [chosen[s["number"]] for s in slots], "warnings": warnings}
    return result


def validate(items: list[dict[str, Any]], ledger: list[dict[str, Any]]) -> list[str]:
    """사용자가 배정표를 직접 고친 뒤 규칙 위반을 알려 준다."""

    warnings = []
    dup = Counter(i["passage_id"] for i in items if i.get("passage_id"))
    for pid, n in dup.items():
        if n > 1:
            label = next(i["label"] for i in items if i["passage_id"] == pid)
            warnings.append(f"'{label}' 본문을 이 세트에서 {n}번 사용")
    pairs = {(e["passage_id"], (e.get("type") or "").replace(" ", "")): e.get("workbook", "") for e in ledger}
    for i in items:
        key = (i.get("passage_id"), (i.get("type") or "").replace(" ", ""))
        if key in pairs:
            warnings.append(f"{i['number']}번: '{i['label']}' 본문을 '{pairs[key]}'에서 같은 유형({i['type']})으로 이미 사용")
    return warnings
