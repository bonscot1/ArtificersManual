"""Party list, character creation and the live-saving sheet."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from ..compendium import format as fmt
from ..compendium import rules
from ..db import Character
from ..sheet import build_sheet, default_hp
from ..templating import page

router = APIRouter()

TEXT_FIELDS = {"name": 120, "player": 120, "alignment": 40, "other_profs": 4000,
               "features_custom": 20000, "notes": 40000, "backstory": 40000}
INT_FIELDS = {  # name: (min, max)
    "xp": (0, 10_000_000), "hp_max": (1, 9999), "hp_temp": (0, 9999), "ac": (0, 60),
    "speed": (0, 999), "initiative_bonus": (-20, 20),
    "score_str": (1, 30), "score_dex": (1, 30), "score_con": (1, 30),
    "score_int": (1, 30), "score_wis": (1, 30), "score_cha": (1, 30),
}
STRUCTURAL = {"level", "class_key", "subclass_key", "background_key", "race"}


# ----------------------------------------------------------------- helpers
def _db(request: Request):
    return request.app.state.db()


def _comp(request: Request):
    return request.app.state.compendium


def _load(request: Request, session, cid: int) -> Character:
    ch = session.get(Character, cid)
    if not ch:
        raise HTTPException(404, "No such character")
    return ch


def _require_dm(request: Request) -> None:
    if request.state.role != "dm":
        raise HTTPException(403, "DM only")


def _toast(resp: Response, text: str = "Saved") -> Response:
    resp.headers["HX-Trigger"] = json.dumps({"toast": text})
    return resp


def _clamp(value, lo: int, hi: int, default: int = 0) -> int:
    try:
        return max(lo, min(hi, int(str(value).strip() or default)))
    except (TypeError, ValueError):
        return default


def _partial(request: Request, name: str, ch: Character, **extra):
    sheet = build_sheet(ch, _comp(request))
    return page(request, name, sheet=sheet, **extra)


def _grouped_race_options(comp):
    groups: dict[str, list] = {}
    for opt in comp.race_options():
        groups.setdefault(opt.group, []).append(opt)
    return groups


# ----------------------------------------------------------------- party
@router.get("/")
async def index(request: Request):
    with _db(request) as session:
        chars = session.scalars(select(Character).order_by(Character.name)).all()
        sheets = [build_sheet(ch, _comp(request)) for ch in chars]
    return page(request, "index.html", sheets=sheets)


@router.get("/party/cards")
async def party_cards(request: Request):
    with _db(request) as session:
        chars = session.scalars(select(Character).order_by(Character.name)).all()
        sheets = [build_sheet(ch, _comp(request)) for ch in chars]
    return page(request, "partials/party_cards.html", sheets=sheets)


# ----------------------------------------------------------------- creation
@router.get("/new")
async def new_form(request: Request):
    comp = _comp(request)
    return page(request, "new.html", race_groups=_grouped_race_options(comp),
                class_options=comp.class_options(),
                backgrounds=sorted(comp.backgrounds.values(), key=lambda b: b["name"]))


@router.post("/new")
async def create(request: Request):
    form = await request.form()
    comp = _comp(request)
    name = str(form.get("name", "")).strip()[:120]
    if not name:
        return RedirectResponse("/new", status_code=303)
    race_key, _, subrace_key = str(form.get("race", "")).partition("||")
    class_key = str(form.get("class_key", ""))
    level = _clamp(form.get("level"), 1, 20, 1)
    cls = comp.classes.get(class_key)
    race = comp.merged_race(race_key, subrace_key) if race_key in comp.races else None
    bg = comp.backgrounds.get(str(form.get("background_key", "")))

    ch = Character(name=name, player=str(form.get("player", "")).strip()[:120],
                   race_key=race_key if race else "", subrace_key=subrace_key if race else "",
                   class_key=class_key if cls else "", background_key=bg and fmt_key(bg) or "",
                   level=level, alignment=str(form.get("alignment", ""))[:40])
    for ab in rules.ABILITIES:
        setattr(ch, f"score_{ab}", _clamp(form.get(f"score_{ab}"), 1, 30, 10))
    mods = {ab: rules.ability_mod(getattr(ch, f"score_{ab}")) for ab in rules.ABILITIES}
    ch.hp_max = ch.hp_current = default_hp(cls, level, mods["con"])
    ch.ac = 10 + mods["dex"]
    ch.speed = fmt.race_speed(race) if race else 30
    ch.save_profs = list((cls or {}).get("proficiency", []))
    ch.skill_profs = fmt.background_skills(bg) if bg else []
    ch.currency = {"cp": 0, "sp": 0, "ep": 0, "gp": 0, "pp": 0}
    with _db(request) as session:
        session.add(ch)
        session.commit()
        cid = ch.id
    return RedirectResponse(f"/c/{cid}", status_code=303)


def fmt_key(entity: dict) -> str:
    return f"{entity['name']}|{entity['source']}"


# ----------------------------------------------------------------- sheet
@router.get("/c/{cid}")
async def sheet(request: Request, cid: int):
    with _db(request) as session:
        ch = _load(request, session, cid)
        comp = _comp(request)
        return page(request, "sheet.html", sheet=build_sheet(ch, comp),
                    race_groups=_grouped_race_options(comp), class_options=comp.class_options(),
                    backgrounds=sorted(comp.backgrounds.values(), key=lambda b: b["name"]))


@router.post("/c/{cid}/save")
async def save(request: Request, cid: int):
    """Live save. Any subset of fields; `_lists` names the checkbox groups this form owns."""
    form = await request.form()
    comp = _comp(request)
    structural = False
    with _db(request) as session:
        ch = _load(request, session, cid)
        for field, limit in TEXT_FIELDS.items():
            if field in form:
                setattr(ch, field, str(form[field])[:limit].strip() if field in ("name", "player", "alignment") else str(form[field])[:limit])
        if not ch.name:
            ch.name = "Unnamed"
        for field, (lo, hi) in INT_FIELDS.items():
            if field in form:
                setattr(ch, field, _clamp(form[field], lo, hi, getattr(ch, field)))
        if "level" in form:
            new_level = _clamp(form["level"], 1, 20, ch.level)
            structural |= new_level != ch.level
            ch.level = new_level
        if "class_key" in form:
            ck = str(form["class_key"])
            if ck in comp.classes and ck != ch.class_key:
                ch.class_key, ch.subclass_key, structural = ck, "", True
                ch.save_profs = list(comp.classes[ck].get("proficiency", []))
                ch.slots_used, ch.pact_used = {}, 0
        if "subclass_key" in form:
            sk = str(form["subclass_key"])
            if sk == "" or sk in comp.subclasses.get(ch.class_key, {}):
                structural |= sk != ch.subclass_key
                ch.subclass_key = sk
        if "background_key" in form:
            bk = str(form["background_key"])
            if bk == "" or bk in comp.backgrounds:
                structural |= bk != ch.background_key
                ch.background_key = bk
        if "race" in form:
            rk, _, srk = str(form["race"]).partition("||")
            if rk in comp.races and comp.merged_race(rk, srk):
                structural |= (rk, srk) != (ch.race_key, ch.subrace_key)
                ch.race_key, ch.subrace_key = rk, srk
        lists = [x for x in str(form.get("_lists", "")).split(",") if x]
        if "save_prof" in lists:
            ch.save_profs = [a for a in form.getlist("save_prof") if a in rules.ABILITIES]
        if "skill_prof" in lists:
            ch.skill_profs = [s for s in form.getlist("skill_prof") if s in rules.SKILL_ABILITY]
        if "skill_expertise" in lists:
            ch.skill_expertise = [s for s in form.getlist("skill_expertise") if s in rules.SKILL_ABILITY]
        if "inspiration" in lists:
            ch.inspiration = "inspiration" in form
        if "currency" in lists:
            ch.currency = {k: _clamp(form.get(f"cur_{k}"), 0, 999_999, 0) for k in ("cp", "sp", "ep", "gp", "pp")}
        if "notes_dm" in form:
            _require_dm(request)
            ch.notes_dm = str(form["notes_dm"])[:40000]
        ch.hp_current = min(ch.hp_current, ch.hp_max)
        session.commit()
        if structural:
            resp = Response(status_code=204)
            resp.headers["HX-Refresh"] = "true"
            return resp
        resp = _partial(request, "partials/oob.html", ch)
    return _toast(resp)


@router.post("/c/{cid}/hp")
async def hp(request: Request, cid: int):
    form = await request.form()
    action = str(form.get("action", ""))
    amount = _clamp(form.get("amount"), 0, 9999, 0)
    with _db(request) as session:
        ch = _load(request, session, cid)
        if action == "damage":
            absorbed = min(ch.hp_temp, amount)
            ch.hp_temp -= absorbed
            ch.hp_current = max(0, ch.hp_current - (amount - absorbed))
        elif action == "heal":
            ch.hp_current = min(ch.hp_max, ch.hp_current + amount)
            if ch.hp_current > 0:
                ch.death_success = ch.death_fail = 0
        elif action == "set":
            ch.hp_current = min(ch.hp_max, amount)
        elif action == "temp":
            ch.hp_temp = amount
        elif action == "death_success":
            ch.death_success = min(3, ch.death_success + 1)
        elif action == "death_fail":
            ch.death_fail = min(3, ch.death_fail + 1)
        elif action == "death_reset":
            ch.death_success = ch.death_fail = 0
        elif action == "hit_die":
            ch.hit_dice_used = _clamp(ch.hit_dice_used + _clamp(form.get("delta"), -20, 20, 0), 0, ch.level, 0)
        session.commit()
        return _partial(request, "partials/hp.html", ch)


@router.post("/c/{cid}/slot")
async def slot(request: Request, cid: int):
    form = await request.form()
    level = str(form.get("level", ""))
    used = _clamp(form.get("used"), 0, 20, 0)
    with _db(request) as session:
        ch = _load(request, session, cid)
        if level == "pact":
            ch.pact_used = used
        elif level.isdigit():
            slots = dict(ch.slots_used or {})
            slots[level] = used
            ch.slots_used = slots
        session.commit()
        return _partial(request, "partials/slots.html", ch)


@router.post("/c/{cid}/rest")
async def rest(request: Request, cid: int):
    form = await request.form()
    kind = str(form.get("kind", "short"))
    with _db(request) as session:
        ch = _load(request, session, cid)
        ch.pact_used = 0
        if kind == "long":
            ch.hp_current, ch.hp_temp = ch.hp_max, 0
            ch.slots_used = {}
            ch.death_success = ch.death_fail = 0
            ch.hit_dice_used = max(0, ch.hit_dice_used - max(1, ch.level // 2))
        session.commit()
    resp = Response(status_code=204)
    resp.headers["HX-Refresh"] = "true"
    return resp


# ----------------------------------------------------------------- spells
@router.get("/c/{cid}/spells/search")
async def spell_search(request: Request, cid: int, q: str = "", level: str = "", scope: str = "class"):
    comp = _comp(request)
    with _db(request) as session:
        ch = _load(request, session, cid)
        have = {s.get("key") for s in (ch.spells or [])}
        lvl = int(level) if level.isdigit() else None
        if scope == "all" or not ch.class_key:
            results = comp.search_spells(q, lvl)
        else:
            results = comp.search_spells(q, lvl, ch.class_key, ch.subclass_key)
        return page(request, "partials/spell_search.html", char=ch, results=results, have=have, q=q)


@router.post("/c/{cid}/spells")
async def spells(request: Request, cid: int):
    form = await request.form()
    op, key = str(form.get("op", "")), str(form.get("key", ""))
    comp = _comp(request)
    with _db(request) as session:
        ch = _load(request, session, cid)
        current = [dict(s) for s in (ch.spells or [])]
        if op == "add" and key in comp.spells and all(s.get("key") != key for s in current):
            current.append({"key": key, "prepared": comp.spells[key]["level"] == 0})
        elif op == "remove":
            current = [s for s in current if s.get("key") != key]
        elif op == "prepare":
            for s in current:
                if s.get("key") == key:
                    s["prepared"] = not s.get("prepared")
        ch.spells = current
        session.commit()
        return _partial(request, "partials/spells_oob.html", ch)


# ----------------------------------------------------------------- attacks / inventory / conditions
def _rows_update(rows: list[dict], form, fields: tuple[str, ...]) -> list[dict]:
    op = str(form.get("op", ""))
    idx = _clamp(form.get("idx"), -1, 999, -1)
    if op == "add":
        row = {f: str(form.get(f, "")).strip()[:300] for f in fields}
        if any(row.values()):
            rows.append(row)
    elif op == "remove" and 0 <= idx < len(rows):
        rows.pop(idx)
    elif op == "update" and 0 <= idx < len(rows):
        rows[idx] = {f: str(form.get(f, rows[idx].get(f, ""))).strip()[:300] for f in fields}
    return rows


@router.post("/c/{cid}/attacks")
async def attacks(request: Request, cid: int):
    form = await request.form()
    comp = _comp(request)
    with _db(request) as session:
        ch = _load(request, session, cid)
        rows = [dict(r) for r in (ch.attacks or [])]
        if str(form.get("op")) == "add" and not str(form.get("damage", "")).strip():
            # try to fill the numbers in from the weapon in the books
            weapon = comp.find("item", str(form.get("name", "")))
            if weapon and weapon.get("weapon"):
                sheet = build_sheet(ch, comp)
                filled = fmt.weapon_attack(weapon, sheet["mods"], sheet["prof"])
                form = dict(form)
                form.setdefault("bonus", filled["bonus"])
                form["bonus"] = form.get("bonus") or filled["bonus"]
                form["damage"] = filled["damage"]
                form["notes"] = form.get("notes") or filled["notes"]
        ch.attacks = _rows_update(rows, form, ("name", "bonus", "damage", "notes"))
        session.commit()
        if str(form.get("op")) == "update":
            return _toast(Response(status_code=204))
        return _partial(request, "partials/attacks.html", ch)


@router.post("/c/{cid}/inventory")
async def inventory(request: Request, cid: int):
    form = await request.form()
    with _db(request) as session:
        ch = _load(request, session, cid)
        ch.inventory = _rows_update([dict(r) for r in (ch.inventory or [])], form, ("name", "qty", "notes"))
        session.commit()
        if str(form.get("op")) == "update":
            return _toast(Response(status_code=204))
        return _partial(request, "partials/inventory.html", ch)


@router.post("/c/{cid}/conditions")
async def conditions(request: Request, cid: int):
    form = await request.form()
    name = str(form.get("name", ""))
    comp = _comp(request)
    with _db(request) as session:
        ch = _load(request, session, cid)
        current = list(ch.conditions or [])
        if name in current:
            current.remove(name)
        elif comp.find("condition", name):
            current.append(name)
        ch.conditions = current
        session.commit()
        return _partial(request, "partials/conditions.html", ch)


@router.post("/c/{cid}/delete")
async def delete(request: Request, cid: int):
    _require_dm(request)
    with _db(request) as session:
        ch = _load(request, session, cid)
        session.delete(ch)
        session.commit()
    resp = RedirectResponse("/", status_code=303)
    resp.headers["HX-Redirect"] = "/"
    return resp
