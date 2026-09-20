"""The fight: the DM runs the order and the NPCs; players see it from their seat."""
from __future__ import annotations

import random

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select

from .. import combat as C
from .. import loot as L
from .. import loot_tables as LT
from .. import monsters as mon
from ..db import Character, Combatant, LootTable, Message, _now
from ..templating import page
from .characters import _clamp, _load, _toast, notify

router = APIRouter()


def _dm(request: Request) -> None:
    if request.state.role != "dm":
        raise HTTPException(403, "DM only")


def _comp(request: Request):
    return request.app.state.compendium


def _cr(value) -> float | None:
    """'1/4', '0.25' or '5' - blank means unknown."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return min(30.0, max(0.0, mon.cr_value(text)))
    except (ValueError, ZeroDivisionError):
        return None


def combat_context(request: Request, session) -> dict:
    """Everything the DM's combat panel needs; the DM screen and every partial share it."""
    enc = C.active_encounter(session)
    v = C.view(session, enc, dm=True) if enc else None
    comp = _comp(request)
    if v:
        tables = LT.all_tables(session)
        for r in v["rows"]:
            if r["kind"] == "npc":
                r["tables"] = LT.suggestions(tables, LT.creature_type(comp.monsters.get(r["monster_key"])), r["cr"])
    return {"enc": enc, "v": v, "chars": session.scalars(select(Character).order_by(Character.name)).all(),
            "condition_names": [x["name"] for x in sorted(comp.conditions.values(), key=lambda x: x["name"])]}


def _dm_partial(request: Request, session, **extra):
    return page(request, "partials/dm_combat.html", **combat_context(request, session), **extra)


# ----------------------------------------------------------------- DM: the encounter
@router.get("/dm/combat")
async def dm_combat(request: Request):
    _dm(request)
    with request.app.state.db() as session:
        return _dm_partial(request, session)


@router.post("/dm/combat/start")
async def start(request: Request):
    _dm(request)
    form = await request.form()
    with request.app.state.db() as session:
        enc = C.start(session, str(form.get("name", "Combat")).strip()[:120] or "Combat")
        for ch in session.scalars(select(Character)).all():
            session.add(Message(batch="combat", character_id=ch.id, kind="initiative",
                                text=f"{enc.name}: roll initiative and type the result."))
        session.commit()
        return _dm_partial(request, session)


@router.post("/dm/combat/end")
async def end(request: Request):
    _dm(request)
    with request.app.state.db() as session:
        enc = C.active_encounter(session)
        if enc:
            enc.active, enc.ended_at = False, _now()
            for m in session.scalars(select(Message).where(Message.kind == "initiative", Message.status == "pending")).all():
                m.status = "cancelled"
            session.commit()
        return _dm_partial(request, session)


@router.post("/dm/combat/turn")
async def turn(request: Request):
    _dm(request)
    form = await request.form()
    step = -1 if str(form.get("dir")) == "prev" else 1
    with request.app.state.db() as session:
        enc = C.active_encounter(session)
        if enc:
            C.advance(session, enc, step)
            session.commit()
        return _dm_partial(request, session)


@router.get("/dm/combat/monsters")
async def monster_search(request: Request, q: str = ""):
    _dm(request)
    comp = _comp(request)
    return page(request, "partials/monster_search.html", hits=comp.search_monsters(q), q=q)


@router.post("/dm/combat/add")
async def add(request: Request):
    _dm(request)
    form = await request.form()
    comp = _comp(request)
    with request.app.state.db() as session:
        enc = C.active_encounter(session)
        if not enc:
            enc = C.start(session)
        key = str(form.get("monster", ""))
        count = _clamp(form.get("count"), 1, 20, 1)
        if key in comp.monsters:
            C.add_monster(session, enc, comp.monsters[key], count, rolled_hp=str(form.get("hp")) == "rolled")
        elif str(form.get("name", "")).strip():
            init = form.get("initiative")
            C.add_custom(session, enc, str(form["name"]).strip()[:120], _clamp(form.get("hp_max"), 1, 9999, 1),
                         _clamp(form.get("ac"), 0, 60, 10), _clamp(init, -20, 60, 0) if str(init or "").strip() else None,
                         cr=_cr(form.get("cr")))
        session.commit()
        return _dm_partial(request, session)


@router.post("/dm/combat/{cid}")
async def update(request: Request, cid: int):
    _dm(request)
    form = await request.form()
    op = str(form.get("op", ""))
    comp = _comp(request)
    with request.app.state.db() as session:
        row = session.get(Combatant, cid)
        enc = C.active_encounter(session)
        if not row or not enc or row.encounter_id != enc.id:
            raise HTTPException(404, "Not in this fight")
        amount = _clamp(form.get("amount"), 0, 9999, 0)
        if op == "remove":
            session.delete(row)
        elif op == "initiative":
            val = str(form.get("initiative", "")).strip()
            row.initiative = _clamp(val, -20, 60, 0) if val else None
        elif op == "name":
            row.name = str(form.get("name", "")).strip()[:120] or row.name
            row.notes = str(form.get("notes", row.notes))[:2000]
        elif op == "visible":
            row.visible = not row.visible
        elif row.kind == "npc" and op == "damage":
            row.hp_current = max(0, row.hp_current - amount)
        elif row.kind == "npc" and op == "heal":
            row.hp_current = min(row.hp_max, row.hp_current + amount)
        elif row.kind == "npc" and op == "condition":
            name = str(form.get("name", ""))
            conds = list(row.conditions or [])
            if name in conds:
                conds.remove(name)
            elif comp.find("condition", name):
                conds.append(name)
            row.conditions = conds
        session.commit()
        return _dm_partial(request, session)


# ----------------------------------------------------------------- DM: loot on the fallen
@router.post("/dm/combat/{cid}/loot")
async def loot(request: Request, cid: int):
    _dm(request)
    form = await request.form()
    op = str(form.get("op", ""))
    comp = _comp(request)
    toast = ""
    with request.app.state.db() as session:
        row = session.get(Combatant, cid)
        if not row:
            raise HTTPException(404, "No such combatant")
        items = [dict(i) for i in (row.loot or [])]
        coins = dict(row.coins or {})
        idx = _clamp(form.get("idx"), -1, 999, -1)
        if op == "add" and str(form.get("name", "")).strip():
            items.append({"name": str(form["name"]).strip()[:200], "qty": str(form.get("qty", "1")).strip() or "1",
                          "notes": str(form.get("notes", "")).strip()[:200]})
        elif op == "remove" and 0 <= idx < len(items):
            items.pop(idx)
        elif op == "coins":
            coins = {k: _clamp(form.get(k), 0, 999_999, 0) for k in ("cp", "sp", "ep", "gp", "pp")}
            coins = {k: v for k, v in coins.items() if v}
        elif op == "roll":
            table = session.get(LootTable, _clamp(form.get("table"), 0, 10**9, 0))
            if not table:
                raise HTTPException(404, "No such loot table")
            rolled = LT.roll_table(table, comp.loot, row.cr, random.Random())
            for k, v in rolled["coins"].items():
                coins[k] = coins.get(k, 0) + v
            for it in rolled["items"]:
                same = next((x for x in items if x["name"] == it["name"] and str(x.get("qty", "1")).isdigit()), None)
                if same:
                    same["qty"] = str(int(same["qty"]) + int(it["qty"]))
                else:
                    items.append({"name": it["name"], "qty": str(it["qty"]), "notes": it.get("notes", "")})
            toast = f"{row.name}: {LT.result_text(rolled)}"
        elif op == "give":
            target = session.get(Character, _clamp(form.get("to"), 0, 10**9, 0))
            if target:
                given = []
                inv = [dict(i) for i in (target.inventory or [])]
                if 0 <= idx < len(items):
                    it = items.pop(idx)
                    inv.append({"name": it["name"], "qty": str(it.get("qty", "1")), "notes": it.get("notes", "")})
                    given.append(f"[[{it['name']}]]" + (f" (x{it['qty']})" if str(it.get("qty", "1")) != "1" else ""))
                elif idx == -1:
                    for it in items:
                        inv.append({"name": it["name"], "qty": str(it.get("qty", "1")), "notes": it.get("notes", "")})
                        given.append(f"[[{it['name']}]]" + (f" (x{it['qty']})" if str(it.get("qty", "1")) != "1" else ""))
                    items = []
                    if coins:
                        cur = dict(target.currency or {})
                        for k, v in coins.items():
                            cur[k] = int(cur.get(k, 0) or 0) + v
                        target.currency = cur
                        given.append(L.coins_text(coins))
                        coins = {}
                target.inventory = inv
                if given:
                    notify(request, session, target, f"From {row.name}: " + ", ".join(given) + ".")
        row.loot, row.coins = items, coins
        session.commit()
        resp = _dm_partial(request, session)
    return _toast(resp, toast) if toast else resp


# ----------------------------------------------------------------- players: the fight from their seat
@router.get("/combat/tracker")
async def tracker(request: Request, me: int = 0):
    with request.app.state.db() as session:
        enc = C.active_encounter(session)
        if not enc:
            return Response(status_code=200, content="")
        v = C.view(session, enc, me=me, dm=request.state.role == "dm")
        return page(request, "partials/combat_tracker.html", v=v, me=me)


@router.get("/combat/strip")
async def strip(request: Request, me: int = 0):
    with request.app.state.db() as session:
        enc = C.active_encounter(session)
        if not enc:
            return Response(status_code=200, content="")
        v = C.view(session, enc, me=me, dm=request.state.role == "dm")
        return page(request, "partials/combat_strip.html", v=v, me=me)


@router.post("/c/{cid}/initiative")
async def set_initiative(request: Request, cid: int):
    form = await request.form()
    with request.app.state.db() as session:
        _load(request, session, cid)
        enc = C.active_encounter(session)
        if enc:
            for row in C.combatants(session, enc):
                if row.character_id == cid:
                    row.initiative = _clamp(form.get("initiative"), -20, 60, 0)
            for m in session.scalars(select(Message).where(Message.character_id == cid, Message.kind == "initiative",
                                                           Message.status == "pending")).all():
                m.status, m.answer, m.answered_at = "done", str(form.get("initiative", "")), _now()
            session.commit()
        v = C.view(session, enc, me=cid, dm=request.state.role == "dm") if enc else None
        return page(request, "partials/combat_tracker.html", v=v, me=cid) if v else Response(content="")
