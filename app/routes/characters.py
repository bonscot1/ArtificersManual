"""Party list, character creation and the live-saving sheet."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import select

from .. import auth
from ..compendium import format as fmt
from ..compendium import rules
from ..db import Character, Message, _now
from ..sheet import build_sheet, cast_options, default_hp
from ..themes import THEMES
from ..templating import page

router = APIRouter()

TEXT_FIELDS = {"name": 120, "player": 120, "alignment": 40, "other_profs": 4000, "appearance": 300,
               "features_custom": 20000, "personality": 20000, "allies": 20000, "notes": 40000, "backstory": 40000}
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


def _fetch(session, cid: int) -> Character:
    ch = session.get(Character, cid)
    if not ch:
        raise HTTPException(404, "No such character")
    return ch


def _load(request: Request, session, cid: int) -> Character:
    """The character, once this browser has claimed it (or the DM is asking)."""
    ch = _fetch(session, cid)
    if request.state.role != "dm" and not auth.is_unlocked(request, ch, request.app.state.secret):
        raise auth.Locked(cid)
    return ch


def _set_unlock_cookie(request: Request, resp: Response, ch: Character) -> Response:
    tokens = dict(request.state.unlocked)
    tokens[ch.id] = auth.unlock_token(ch.id, ch.password_hash or "", request.app.state.secret)
    resp.set_cookie(auth.CHAR_COOKIE, auth.unlock_cookie_value(tokens),
                    httponly=True, samesite="lax", max_age=60 * 60 * 24 * 365)
    return resp


def _require_dm(request: Request) -> None:
    if request.state.role != "dm":
        raise HTTPException(403, "DM only")


def _toast(resp: Response, text: str = "Saved") -> Response:
    resp.headers["HX-Trigger"] = json.dumps({"toast": text})
    return resp


def notify(request: Request, session, ch: Character, text: str) -> None:
    """When the DM changes a character's sheet, the player gets a popup saying what changed.
    Several changes within a few minutes fold into the one waiting popup."""
    if request.state.role != "dm" or not text:
        return
    last = session.scalars(select(Message).where(Message.character_id == ch.id, Message.status == "pending",
                                                 Message.batch == "dm-edit").order_by(Message.id.desc())).first()
    if last and _age_seconds(last.created_at) < 180 and len(last.text) < 1500:
        last.text = last.text + "\n" + text
    else:
        session.add(Message(batch="dm-edit", character_id=ch.id, kind="note", text=text))


def _age_seconds(dt) -> float:
    if dt is None:
        return 1e9
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.utcnow()
    return (now - dt).total_seconds()


FIELD_LABELS = {
    "name": "name", "player": "player", "alignment": "alignment", "appearance": "appearance", "level": "level",
    "xp": "XP", "hp_max": "max HP", "hp_temp": "temporary HP", "ac": "AC", "speed": "speed",
    "initiative_bonus": "initiative bonus", "score_str": "Strength", "score_dex": "Dexterity",
    "score_con": "Constitution", "score_int": "Intelligence", "score_wis": "Wisdom", "score_cha": "Charisma",
    "other_profs": "proficiencies", "features_custom": "other features", "personality": "personality",
    "allies": "allies", "notes": "session notes", "backstory": "backstory", "race_key": "race",
    "subrace_key": "subrace", "class_key": "class", "subclass_key": "subclass", "background_key": "background",
    "save_profs": "saving throws", "skill_profs": "skills", "skill_expertise": "expertise",
    "inspiration": "inspiration", "currency": "coins", "theme": "theme",
}


def _clamp(value, lo: int, hi: int, default: int = 0) -> int:
    try:
        return max(lo, min(hi, int(str(value).strip() or default)))
    except (TypeError, ValueError):
        return default


def _partial(request: Request, name: str, ch: Character, **extra):
    sheet = build_sheet(ch, _comp(request))
    return page(request, name, sheet=sheet, **extra)


def _view(form) -> dict:
    """Blocks the play view swaps back in must stay read-only."""
    play = str(form.get("view", "")) == "play"
    return {"readonly": play, "view": "play" if play else "sheet"}


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
    if request.state.role == "dm":
        return RedirectResponse(f"/c/{cid}/sheet", status_code=303)
    return RedirectResponse(f"/c/{cid}/unlock?next=/c/{cid}/sheet", status_code=303)


def fmt_key(entity: dict) -> str:
    return f"{entity['name']}|{entity['source']}"


# ----------------------------------------------------------------- claiming a character
def _safe_next(value: str, cid: int) -> str:
    return value if value.startswith(f"/c/{cid}") else f"/c/{cid}"


@router.get("/c/{cid}/unlock")
async def unlock_form(request: Request, cid: int, next: str = ""):
    with _db(request) as session:
        ch = _fetch(session, cid)
        if request.state.role == "dm" or auth.is_unlocked(request, ch, request.app.state.secret):
            return RedirectResponse(_safe_next(next, cid), status_code=303)
        return page(request, "unlock.html", ch=ch, mode="enter" if ch.password_hash else "set", error=None, next=next)


@router.post("/c/{cid}/unlock")
async def unlock(request: Request, cid: int):
    form = await request.form()
    password = str(form.get("password", ""))
    target = _safe_next(str(form.get("next", "")), cid)
    with _db(request) as session:
        ch = _fetch(session, cid)
        if not ch.password_hash:
            if not password:
                return page(request, "unlock.html", ch=ch, mode="set", next=target,
                            error="Type something - anything - to use as the password.")
            ch.password_hash = auth.hash_password(password)
            session.commit()
        elif not auth.verify_password(password, ch.password_hash):
            return page(request, "unlock.html", ch=ch, mode="enter", next=target,
                        error="That's not it. Ask the DM to reset it if it's forgotten.")
        session.refresh(ch)
    return _set_unlock_cookie(request, RedirectResponse(target, status_code=303), ch)


@router.post("/c/{cid}/password/reset")
async def password_reset(request: Request, cid: int):
    _require_dm(request)
    with _db(request) as session:
        ch = _fetch(session, cid)
        ch.password_hash = ""
        notify(request, session, ch, "The DM cleared your password - set a new one next time you open the sheet.")
        session.commit()
    return _toast(Response(status_code=204), "Password cleared - the next person to open the sheet sets a new one")


# ----------------------------------------------------------------- play view + sheet editor
@router.get("/c/{cid}")
async def play(request: Request, cid: int):
    """The table view: read-only, except what changes mid-session."""
    with _db(request) as session:
        ch = _load(request, session, cid)
        comp = _comp(request)
        others = [build_sheet(o, comp) for o in session.scalars(select(Character).order_by(Character.name)).all()
                  if o.id != cid]
        return page(request, "play.html", sheet=build_sheet(ch, comp), sheets=others, me=cid,
                    readonly=True, view="play")


@router.get("/c/{cid}/sheet")
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
        before = {f: getattr(ch, f) for f in FIELD_LABELS}
        for field, limit in TEXT_FIELDS.items():
            if field in form:
                setattr(ch, field, str(form[field])[:limit].strip() if field in ("name", "player", "alignment", "appearance") else str(form[field])[:limit])
        if not ch.name:
            ch.name = "Unnamed"
        for field, (lo, hi) in INT_FIELDS.items():
            if field in form and (field != "xp" or request.state.role == "dm"):
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
        if "inspiration" in lists and request.state.role == "dm":
            ch.inspiration = "inspiration" in form
        if "currency" in lists:
            ch.currency = {k: _clamp(form.get(f"cur_{k}"), 0, 999_999, 0) for k in ("cp", "sp", "ep", "gp", "pp")}
        if "theme" in form:
            theme = str(form["theme"])
            if theme == "" or theme in THEMES:
                ch.theme = theme
                structural = True          # the whole page recolours
        if "notes_dm" in form:
            _require_dm(request)
            ch.notes_dm = str(form["notes_dm"])[:40000]
        ch.hp_current = min(ch.hp_current, ch.hp_max)
        changes = []
        for f, label in FIELD_LABELS.items():
            if getattr(ch, f) != before[f]:
                old_v, new_v = before[f], getattr(ch, f)
                if isinstance(new_v, (int, bool)) and not isinstance(new_v, bool):
                    changes.append(f"{label} {old_v} → {new_v}")
                elif f.endswith("_key"):
                    changes.append(f"{label}: {str(new_v).split('|')[0] or 'none'}")
                else:
                    changes.append(label)
        if changes:
            notify(request, session, ch, "The DM changed your sheet: " + "; ".join(changes) + ".")
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
        notify(request, session, ch, {
            "damage": f"The DM dealt you {amount} damage.", "heal": f"The DM healed you for {amount}.",
            "set": f"The DM set your HP to {amount}.", "temp": f"The DM set your temporary HP to {amount}.",
            "death_success": "The DM marked a death save success.", "death_fail": "The DM marked a death save failure.",
            "death_reset": "The DM reset your death saves.", "hit_die": "The DM changed your hit dice.",
        }.get(action, ""))
        session.commit()
        if str(form.get("view")) == "play":
            return _partial(request, "partials/hud.html", ch)
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
        notify(request, session, ch, "The DM changed your spell slots.")
        session.commit()
        return _partial(request, "partials/slots.html", ch)


@router.post("/c/{cid}/rest")
async def rest(request: Request, cid: int):
    form = await request.form()
    kind = str(form.get("kind", "short"))
    with _db(request) as session:
        ch = _load(request, session, cid)
        ch.pact_used = 0
        counters = [dict(x) for x in (ch.counters or [])]
        for x in counters:
            if kind == "long" or x.get("reset") == "short":
                x["used"] = 0
        ch.counters = counters
        if kind == "long":
            ch.hp_current, ch.hp_temp = ch.hp_max, 0
            ch.slots_used = {}
            ch.concentration = ""
            ch.death_success = ch.death_fail = 0
            ch.hit_dice_used = max(0, ch.hit_dice_used - max(1, ch.level // 2))
        notify(request, session, ch, f"The DM gave you a {'long' if kind == 'long' else 'short'} rest.")
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
        if key in comp.spells:
            spell_name = comp.spells[key]["name"]
            notify(request, session, ch, {"add": f"The DM added [[{spell_name}|spell]] to your spells.",
                                          "remove": f"The DM removed [[{spell_name}|spell]] from your spells.",
                                          "prepare": f"The DM changed whether [[{spell_name}|spell]] is prepared."}.get(op, ""))
        session.commit()
        if str(form.get("view")) == "play":
            return _partial(request, "partials/spells_play.html", ch)
        return _partial(request, "partials/spells_oob.html", ch, **_view(form))


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
        notify(request, session, ch, "The DM changed your attacks.")
        session.commit()
        if str(form.get("op")) == "update":
            return _toast(Response(status_code=204))
        return _partial(request, "partials/attacks.html", ch)


@router.post("/c/{cid}/inventory")
async def inventory(request: Request, cid: int):
    form = await request.form()
    op = str(form.get("op", ""))
    idx = _clamp(form.get("idx"), -1, 999, -1)
    with _db(request) as session:
        ch = _load(request, session, cid)
        rows = [dict(r) for r in (ch.inventory or [])]
        removed = [dict(r) for r in (ch.inventory_removed or [])]
        if op == "remove" and 0 <= idx < len(rows):
            gone = rows.pop(idx)
            gone["when"] = datetime.now().strftime("%d %b %H:%M")
            removed.insert(0, gone)
            del removed[40:]
        elif op == "restore" and 0 <= idx < len(removed):
            back = removed.pop(idx)
            back.pop("when", None)
            rows.append(back)
        elif op == "forget" and 0 <= idx < len(removed):
            removed.pop(idx)
        else:
            rows = _rows_update(rows, form, ("name", "qty", "notes"))
        ch.inventory, ch.inventory_removed = rows, removed
        item = str(form.get("name", "")).strip()
        qty = str(form.get("qty", "")).strip()
        told = {
            "add": f"The DM gave you [[{item}]]{' (x' + qty + ')' if qty not in ('', '1') else ''}." if item else "",
            "remove": f"The DM took your [[{removed[0]['name']}]]." if op == "remove" and removed else "",
            "restore": f"The DM gave back your [[{rows[-1]['name']}]]." if op == "restore" and rows else "",
            "update": f"The DM changed an item: [[{item}]]." if item else "",
        }
        notify(request, session, ch, told.get(op, ""))
        session.commit()
        if op == "update":
            return _toast(Response(status_code=204))
        return _partial(request, "partials/inventory.html", ch)


@router.post("/c/{cid}/conditions")
async def conditions(request: Request, cid: int):
    _require_dm(request)
    form = await request.form()
    name = str(form.get("name", ""))
    comp = _comp(request)
    with _db(request) as session:
        ch = _load(request, session, cid)
        current = list(ch.conditions or [])
        if name in current:
            current.remove(name)
            notify(request, session, ch, f"The DM cleared [[{name}|condition]].")
        elif comp.find("condition", name):
            current.append(name)
            notify(request, session, ch, f"The DM marked you [[{name}|condition]].")
        ch.conditions = current
        session.commit()
        if str(form.get("view")) == "play":
            return _partial(request, "partials/hud.html", ch)
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


# ----------------------------------------------------------------- feats / class options
@router.get("/c/{cid}/picks/search")
async def pick_search(request: Request, cid: int, kind: str = "feat", q: str = "", scope: str = "class"):
    comp = _comp(request)
    q = q.strip().lower()
    with _db(request) as session:
        ch = _load(request, session, cid)
        sheet = build_sheet(ch, comp)
    if kind == "option":
        pool = comp.optionalfeatures.values()
        codes = set(sheet["option_type_codes"])
        if codes and scope != "all":
            pool = [o for o in pool if codes & set(o.get("featureType", []))]
    else:
        kind = "feat"
        pool = comp.feats.values()
    results = sorted((e for e in pool if not q or q in e["name"].lower()), key=lambda e: e["name"])[:60]
    have = {p.get("key") for p in (ch.feats if kind == "feat" else ch.options) or []}
    return page(request, "partials/pick_search.html", char=ch, kind=kind, results=results, have=have, q=q,
                store_kind="feat" if kind == "feat" else "optionalfeature")


@router.post("/c/{cid}/picks")
async def picks(request: Request, cid: int):
    form = await request.form()
    kind = "feat" if str(form.get("kind", "feat")) == "feat" else "option"
    op, key = str(form.get("op", "")), str(form.get("key", ""))
    idx = _clamp(form.get("idx"), -1, 999, -1)
    comp = _comp(request)
    store = comp.feats if kind == "feat" else comp.optionalfeatures
    with _db(request) as session:
        ch = _load(request, session, cid)
        current = [dict(x) for x in ((ch.feats if kind == "feat" else ch.options) or [])]
        if op == "add" and key in store:
            if kind == "option" or all(x.get("key") != key for x in current):   # an infusion can be taken twice
                current.append({"key": key, "note": ""})
        elif op == "remove" and 0 <= idx < len(current):
            current.pop(idx)
        elif op == "note" and 0 <= idx < len(current):
            current[idx]["note"] = str(form.get("note", ""))[:200].strip()
        if kind == "feat":
            ch.feats = current
        else:
            ch.options = current
        what = "feat" if kind == "feat" else "class option"
        picked = store[key]["name"] if key in store else ""
        notify(request, session, ch, {"add": f"The DM added the {what} [[{picked}|{'feat' if kind == 'feat' else 'optionalfeature'}]].",
                                      "remove": f"The DM removed a {what}.", "note": f"The DM changed a note on a {what}."}.get(op, ""))
        session.commit()
        if op == "note":
            return _toast(Response(status_code=204))
        return _partial(request, "partials/features.html", ch)


# ----------------------------------------------------------------- counters (rages, ki, uses per rest)
@router.post("/c/{cid}/counters")
async def counters(request: Request, cid: int):
    form = await request.form()
    op = str(form.get("op", ""))
    idx = _clamp(form.get("idx"), -1, 999, -1)
    with _db(request) as session:
        ch = _load(request, session, cid)
        rows = [dict(x) for x in (ch.counters or [])]
        if op == "add":
            name = str(form.get("name", "")).strip()[:60]
            if name:
                rows.append({"name": name, "max": _clamp(form.get("max"), 1, 99, 1), "used": 0,
                             "reset": "short" if str(form.get("reset")) == "short" else "long"})
        elif 0 <= idx < len(rows):
            row = rows[idx]
            if op == "remove":
                rows.pop(idx)
            elif op == "set":
                row["used"] = _clamp(form.get("used"), 0, int(row.get("max", 0) or 0), 0)
            elif op == "use":
                row["used"] = min(int(row.get("max", 0) or 0), int(row.get("used", 0) or 0) + 1)
            elif op == "undo":
                row["used"] = max(0, int(row.get("used", 0) or 0) - 1)
        ch.counters = rows
        notify(request, session, ch, "The DM changed your resources." if op != "add" else
               f"The DM added a resource: {str(form.get('name', '')).strip()}.")
        session.commit()
        return _partial(request, "partials/counters.html", ch, **_view(form))


# ----------------------------------------------------------------- casting
def _spell_row(sheet: dict, key: str) -> dict | None:
    for rows in sheet["ready_levels"].values():
        for r in rows:
            if r["key"] == key:
                return r
    return None


@router.get("/c/{cid}/cast-options")
async def cast_options_fragment(request: Request, cid: int, key: str = "", cancel: str = ""):
    with _db(request) as session:
        ch = _load(request, session, cid)
        sheet = build_sheet(ch, _comp(request))
    row = _spell_row(sheet, key)
    if not row:
        raise HTTPException(404, "Not a spell you can cast")
    return page(request, "partials/cast_options.html", char=ch, row=row,
                options=[] if cancel else cast_options(sheet, row["spell"]), open=not cancel)


@router.post("/c/{cid}/cast")
async def cast(request: Request, cid: int):
    form = await request.form()
    key, slot = str(form.get("key", "")), str(form.get("slot", ""))
    comp = _comp(request)
    with _db(request) as session:
        ch = _load(request, session, cid)
        sheet = build_sheet(ch, comp)
        row = _spell_row(sheet, key)
        if not row:
            raise HTTPException(400, "Not a spell you can cast")
        spell = row["spell"]
        allowed = {o["slot"]: o for o in cast_options(sheet, spell)}
        if slot not in allowed:
            resp = _partial(request, "partials/spells_play.html", ch)
            return _toast(resp, "No slot left for that")
        how = allowed[slot]["label"]
        if slot.isdigit():
            used = dict(ch.slots_used or {})
            used[slot] = int(used.get(slot, 0) or 0) + 1
            ch.slots_used = used
            how = f"{rules.ordinal(int(slot))}-level slot"
        elif slot == "pact":
            ch.pact_used = (ch.pact_used or 0) + 1
            how = "pact slot"
        elif slot == "ritual":
            how = "ritual"
        else:
            how = "cantrip"
        ended = ""
        if any(d.get("concentration") for d in spell.get("duration", [])):
            if ch.concentration and ch.concentration != spell["name"]:
                ended = f"; concentration on {ch.concentration} ended"
            ch.concentration = spell["name"]
        notify(request, session, ch, f"The DM cast [[{spell['name']}|spell]] for you ({how}){ended}.")
        session.commit()
        resp = _partial(request, "partials/spells_play.html", ch, oob_hud=True)
    return _toast(resp, f"Cast {spell['name']} ({how}){ended}")


@router.post("/c/{cid}/concentration")
async def concentration(request: Request, cid: int):
    with _db(request) as session:
        ch = _load(request, session, cid)
        name, ch.concentration = ch.concentration, ""
        if name:
            notify(request, session, ch, f"The DM ended your concentration on {name}.")
        session.commit()
        resp = _partial(request, "partials/hud.html", ch)
    return _toast(resp, f"Concentration on {name} ended" if name else "Not concentrating")


# ----------------------------------------------------------------- inspiration: players spend it, the DM grants it
@router.post("/c/{cid}/inspiration")
async def inspiration(request: Request, cid: int):
    form = await request.form()
    op = str(form.get("op", "use"))
    with _db(request) as session:
        ch = _load(request, session, cid)
        if op == "grant":
            _require_dm(request)
            ch.inspiration = True
            text = "Inspiration granted"
            notify(request, session, ch, "The DM gave you inspiration.")
        elif op == "revoke":
            _require_dm(request)
            ch.inspiration = False
            text = "Inspiration removed"
            notify(request, session, ch, "The DM took your inspiration.")
        else:
            if not ch.inspiration:
                return _toast(_partial(request, "partials/hud.html", ch), "No inspiration to spend")
            ch.inspiration = False
            text = "Inspiration spent"
        session.commit()
        resp = _partial(request, "partials/hud.html", ch)
    return _toast(resp, text)


# ----------------------------------------------------------------- art: a portrait for the page, a token for cards
ART_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def _art_dir(request: Request) -> Path:
    """Next to the database, so a test database gets its own folder."""
    return Path(request.app.state.settings.db_path).parent / "portraits"


@router.get("/c/{cid}/art/{kind}")
async def art(request: Request, cid: int, kind: str):
    with _db(request) as session:
        ch = _fetch(session, cid)           # tokens show on the party page, so no unlock needed
        name = ch.portrait if kind == "portrait" else ch.token or ch.portrait
    path = _art_dir(request) / Path(name).name if name else None
    if not path or not path.exists():
        raise HTTPException(404, "No art")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.post("/c/{cid}/art")
async def upload_art(request: Request, cid: int):
    form = await request.form()
    kind = "token" if str(form.get("kind")) == "token" else "portrait"
    file = form.get("file")
    if not isinstance(file, UploadFile) or file.content_type not in ART_TYPES:
        return _toast(Response(status_code=204), "Use a PNG, JPG or WebP")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        return _toast(Response(status_code=204), "Keep it under 8 MB")
    with _db(request) as session:
        ch = _load(request, session, cid)
        art_dir = _art_dir(request)
        art_dir.mkdir(parents=True, exist_ok=True)
        name = f"{cid}-{kind}{ART_TYPES[file.content_type]}"
        (art_dir / name).write_bytes(data)
        setattr(ch, kind, name)
        notify(request, session, ch, f"The DM changed your {kind}.")
        session.commit()
    resp = Response(status_code=204)
    resp.headers["HX-Refresh"] = "true"
    return resp


# ----------------------------------------------------------------- what the others can see
@router.get("/party/glance")
async def party_glance(request: Request, me: int = 0):
    """The rest of the party as this character sees them: phrases, not numbers (the DM gets both)."""
    with _db(request) as session:
        chars = session.scalars(select(Character).order_by(Character.name)).all()
        sheets = [build_sheet(ch, _comp(request)) for ch in chars if ch.id != me]
    return page(request, "partials/party_glance.html", sheets=sheets, me=me)


# ----------------------------------------------------------------- companions: familiars, defenders, homunculi
def _companion_fields(form, existing: dict | None = None) -> dict:
    row = dict(existing or {"name": "", "kind": "", "hp_max": 1, "hp_current": 1, "ac": "", "summoned": True,
                            "conditions": [], "notes": ""})
    for f in ("name", "kind", "notes"):
        if f in form:
            row[f] = str(form[f]).strip()[:200]
    if "ac" in form:
        row["ac"] = str(form["ac"]).strip()[:6]
    if "hp_max" in form:
        row["hp_max"] = _clamp(form["hp_max"], 0, 9999, 1)
        row["hp_current"] = min(int(row.get("hp_current", row["hp_max"])), row["hp_max"]) if existing else row["hp_max"]
    return row


@router.post("/c/{cid}/companions")
async def companions(request: Request, cid: int):
    form = await request.form()
    op = str(form.get("op", ""))
    idx = _clamp(form.get("idx"), -1, 999, -1)
    comp = _comp(request)
    with _db(request) as session:
        ch = _load(request, session, cid)
        rows = [dict(r) for r in (ch.companions or [])]
        if op == "add":
            row = _companion_fields(form)
            if row["name"]:
                rows.append(row)
        elif 0 <= idx < len(rows):
            row = rows[idx]
            hp_max = int(row.get("hp_max", 0) or 0)
            amount = _clamp(form.get("amount"), 0, 9999, 0)
            if op == "remove":
                rows.pop(idx)
            elif op == "update":
                rows[idx] = _companion_fields(form, row)
            elif op == "damage":
                row["hp_current"] = max(0, int(row.get("hp_current", 0) or 0) - amount)
            elif op == "heal":
                row["hp_current"] = min(hp_max, int(row.get("hp_current", 0) or 0) + amount)
            elif op == "summon":
                row["summoned"] = not row.get("summoned")
                if row["summoned"] and int(row.get("hp_current", 0) or 0) <= 0:
                    row["hp_current"] = hp_max
            elif op == "condition":
                _require_dm(request)
                name = str(form.get("name", ""))
                conds = list(row.get("conditions") or [])
                if name in conds:
                    conds.remove(name)
                elif comp.find("condition", name):
                    conds.append(name)
                row["conditions"] = conds
        ch.companions = rows
        who = rows[idx]["name"] if 0 <= idx < len(rows) else str(form.get("name", "")).strip()
        notify(request, session, ch, {
            "add": f"The DM added a companion: {who}.", "remove": "The DM removed a companion.",
            "damage": f"The DM dealt {who} {_clamp(form.get('amount'), 0, 9999, 0)} damage.",
            "heal": f"The DM healed {who} for {_clamp(form.get('amount'), 0, 9999, 0)}.",
            "summon": f"The DM {'summoned' if rows[idx].get('summoned') else 'dismissed'} {who}." if 0 <= idx < len(rows) else "",
            "condition": f"The DM changed {who}'s conditions: [[{str(form.get('name', ''))}|condition]].",
            "update": f"The DM changed {who}.",
        }.get(op, ""))
        session.commit()
        if op == "update":
            return _toast(Response(status_code=204))
        return _partial(request, "partials/companions.html", ch)


# ----------------------------------------------------------------- messages from the DM
def _next_message(session, cid: int):
    return session.scalars(select(Message).where(Message.character_id == cid, Message.status == "pending")
                           .order_by(Message.id)).first()


@router.get("/c/{cid}/inbox")
async def inbox(request: Request, cid: int, shown: str = ""):
    """The oldest unread message as a popup, or nothing (204) so the page stays quiet.
    `shown` is the message already on screen: leave it alone so a half-typed reply survives."""
    with _db(request) as session:
        ch = _load(request, session, cid)
        m = _next_message(session, cid)
        if not m or f"{m.id}-{len(m.text)}" == shown:      # same message, same text: leave the popup alone
            return Response(status_code=204)
        waiting = session.scalars(select(Message).where(Message.character_id == cid, Message.status == "pending")).all()
        return page(request, "partials/inbox_modal.html", char=ch, m=m, more=len(waiting) - 1)


@router.post("/c/{cid}/inbox/{mid}")
async def inbox_reply(request: Request, cid: int, mid: int):
    form = await request.form()
    with _db(request) as session:
        ch = _load(request, session, cid)
        m = session.get(Message, mid)
        if not m or m.character_id != cid:
            raise HTTPException(404, "No such message")
        if m.status == "pending":
            if m.kind == "choice":
                pick = str(form.get("answer", ""))
                if pick not in (m.options or []):
                    return page(request, "partials/inbox_modal.html", char=ch, m=m, more=0, error="Pick one of the options.")
                m.answer = pick
            elif m.kind == "prompt":
                reply = str(form.get("answer", "")).strip()[:4000]
                if not reply:
                    return page(request, "partials/inbox_modal.html", char=ch, m=m, more=0, error="Type a reply first.")
                m.answer = reply
            m.status, m.answered_at = "done", _now()
            session.commit()
        nxt = _next_message(session, cid)
        if not nxt:
            return Response(status_code=200, content="")
        waiting = session.scalars(select(Message).where(Message.character_id == cid, Message.status == "pending")).all()
        return page(request, "partials/inbox_modal.html", char=ch, m=nxt, more=len(waiting) - 1)
