"""The DM's loot tables: what falls off what, editable, rollable."""
from __future__ import annotations

import random

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from .. import loot_tables as LT
from ..db import LootTable
from ..templating import page
from .characters import _clamp, _toast
from .combat import _cr

router = APIRouter(prefix="/dm/loot")


def _dm(request: Request) -> None:
    if request.state.role != "dm":
        raise HTTPException(403, "DM only")


def _get(session, tid: int) -> LootTable:
    t = session.get(LootTable, tid)
    if not t:
        raise HTTPException(404, "No such loot table")
    return t


def _entry(form, old: dict | None = None) -> dict:
    old = old or {}
    return {"name": str(form.get("name", old.get("name", ""))).strip()[:200],
            "qty": str(form.get("qty", old.get("qty", "1"))).strip()[:20] or "1",
            "weight": _clamp(form.get("weight", old.get("weight", 1)), 0, 1000, 1),
            "notes": str(form.get("notes", old.get("notes", ""))).strip()[:300]}


@router.get("")
async def index(request: Request):
    _dm(request)
    with request.app.state.db() as session:
        return page(request, "dm_loot.html", tables=LT.all_tables(session), types=LT.TYPES)


@router.post("")
async def create(request: Request):
    _dm(request)
    form = await request.form()
    with request.app.state.db() as session:
        src = session.get(LootTable, _clamp(form.get("copy"), 0, 10**9, 0))
        name = str(form.get("name", "")).strip()[:120] or (f"{src.name} (copy)" if src else "New table")
        t = LootTable(name=name, notes=src.notes if src else "", types=list(src.types or []) if src else [],
                      cr_min=src.cr_min if src else None, cr_max=src.cr_max if src else None,
                      mode=src.mode if src else "table", draws=src.draws if src else "1",
                      coins_mode=src.coins_mode if src else "none", coins=dict(src.coins or {}) if src else {},
                      entries=[dict(e) for e in (src.entries or [])] if src else [])
        session.add(t)
        session.commit()
        return RedirectResponse(f"/dm/loot/{t.id}", status_code=303)


@router.post("/restore")
async def restore(request: Request):
    _dm(request)
    with request.app.state.db() as session:
        n = LT.seed(session)
        session.commit()
    resp = RedirectResponse("/dm/loot", status_code=303)
    resp.headers["HX-Redirect"] = "/dm/loot"
    return resp if n else _toast(resp, "Every built-in table is still here")


@router.get("/{tid}")
async def edit(request: Request, tid: int):
    _dm(request)
    with request.app.state.db() as session:
        t = _get(session, tid)
        return page(request, "dm_loot_table.html", t=t, types=LT.TYPES, coin_names=LT.COINS, sample=None)


@router.post("/{tid}")
async def save(request: Request, tid: int):
    _dm(request)
    form = await request.form()
    with request.app.state.db() as session:
        t = _get(session, tid)
        t.name = str(form.get("name", t.name)).strip()[:120] or t.name
        t.notes = str(form.get("notes", t.notes)).strip()[:300]
        t.types = [x for x in form.getlist("types") if x in LT.TYPES]
        t.cr_min, t.cr_max = _cr(form.get("cr_min")), _cr(form.get("cr_max"))
        t.mode = "hoard" if str(form.get("mode")) == "hoard" else "table"
        t.draws = str(form.get("draws", t.draws)).strip()[:20] or "1"
        t.coins_mode = str(form.get("coins_mode")) if str(form.get("coins_mode")) in ("none", "dmg", "custom") else t.coins_mode
        t.coins = {k: str(form.get(k, "")).strip()[:20] for k in LT.COINS if str(form.get(k, "")).strip()}
        session.commit()
    return _toast(Response(status_code=204))


@router.post("/{tid}/entries")
async def entries(request: Request, tid: int):
    _dm(request)
    form = await request.form()
    op = str(form.get("op", ""))
    idx = _clamp(form.get("idx"), -1, 9999, -1)
    with request.app.state.db() as session:
        t = _get(session, tid)
        rows = [dict(e) for e in (t.entries or [])]
        if op == "add" and str(form.get("name", "")).strip():
            rows.append(_entry(form))
        elif op == "update" and 0 <= idx < len(rows):
            rows[idx] = _entry(form, rows[idx])
        elif op == "remove" and 0 <= idx < len(rows):
            rows.pop(idx)
        t.entries = rows
        session.commit()
        resp = page(request, "partials/loot_entries.html", t=t)
    return _toast(resp) if op == "update" else resp


@router.post("/{tid}/roll")
async def sample(request: Request, tid: int):
    _dm(request)
    form = await request.form()
    comp = request.app.state.compendium
    with request.app.state.db() as session:
        t = _get(session, tid)
        result = LT.roll_table(t, comp.loot, _cr(form.get("cr")) or 0.0, random.Random())
        return page(request, "partials/loot_roll.html", t=t, result=result, text=LT.result_text(result))


@router.post("/{tid}/delete")
async def delete(request: Request, tid: int):
    _dm(request)
    with request.app.state.db() as session:
        session.delete(_get(session, tid))
        session.commit()
    resp = RedirectResponse("/dm/loot", status_code=303)
    resp.headers["HX-Redirect"] = "/dm/loot"
    return resp
