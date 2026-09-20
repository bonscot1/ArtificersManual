"""Initiative order, turns, and what each side of the table sees of a fight."""
from __future__ import annotations

import random

from sqlalchemy import select

from . import monsters as mon
from .db import Character, Combatant, Encounter, _now
from .narrative import describe


def active_encounter(session) -> Encounter | None:
    return session.scalars(select(Encounter).where(Encounter.active == True).order_by(Encounter.id.desc())).first()  # noqa: E712


def combatants(session, enc: Encounter) -> list[Combatant]:
    return session.scalars(select(Combatant).where(Combatant.encounter_id == enc.id)).all()


def ordered(rows: list[Combatant]) -> list[Combatant]:
    """Initiative high to low; ties by Dex; unrolled ones sink to the bottom."""
    return sorted(rows, key=lambda c: (c.initiative is None, -(c.initiative or 0), -(c.dex_mod or 0), c.name.lower(), c.id))


def start(session, name: str = "Combat") -> Encounter:
    for old in session.scalars(select(Encounter).where(Encounter.active == True)).all():  # noqa: E712
        old.active, old.ended_at = False, _now()
    enc = Encounter(name=name or "Combat")
    session.add(enc)
    session.flush()
    for ch in session.scalars(select(Character).order_by(Character.name)).all():
        session.add(Combatant(encounter_id=enc.id, kind="pc", character_id=ch.id, name=ch.name,
                              dex_mod=(ch.score_dex - 10) // 2, hp_max=ch.hp_max, hp_current=ch.hp_current, ac=ch.ac))
    return enc


def add_monster(session, enc: Encounter, monster: dict, count: int = 1, rolled_hp: bool = False,
                rng: random.Random | None = None) -> list[Combatant]:
    rng = rng or random.Random()
    s = mon.summary(monster)
    existing = sum(1 for c in combatants(session, enc) if c.monster_key == f"{monster['name']}|{monster['source']}")
    out = []
    for i in range(count):
        n = existing + i + 1
        hp = mon.hp_rolled(monster, rng) if rolled_hp else s["hp"]
        row = Combatant(encounter_id=enc.id, kind="npc", monster_key=f"{monster['name']}|{monster['source']}",
                        name=monster["name"] if count == 1 and existing == 0 else f"{monster['name']} {n}",
                        initiative=rng.randint(1, 20) + s["dex_mod"], dex_mod=s["dex_mod"], hp_max=hp, hp_current=hp,
                        ac=s["ac"], cr=s["cr_value"],
                        loot=[{"name": item, "qty": 1, "notes": "carried"} for item in mon.carried(monster)])
        session.add(row)
        out.append(row)
    session.flush()
    return out


def add_custom(session, enc: Encounter, name: str, hp: int, ac: int, initiative: int | None,
               cr: float | None = None) -> Combatant:
    row = Combatant(encounter_id=enc.id, kind="npc", name=name, hp_max=hp, hp_current=hp, ac=ac, initiative=initiative, cr=cr)
    session.add(row)
    session.flush()
    return row


def current(session, enc: Encounter) -> Combatant | None:
    rows = ordered(combatants(session, enc))
    if not rows:
        return None
    return rows[enc.turn % len(rows)]


def advance(session, enc: Encounter, step: int = 1) -> Combatant | None:
    """Next (or previous) turn, skipping downed NPCs; a wrap past the end starts a new round."""
    rows = ordered(combatants(session, enc))
    if not rows:
        return None
    n = len(rows)
    for _ in range(n):
        enc.turn += step
        if enc.turn >= n:
            enc.turn, enc.round = 0, enc.round + 1
        elif enc.turn < 0:
            enc.turn, enc.round = n - 1, max(1, enc.round - 1)
        row = rows[enc.turn]
        if row.kind == "pc" or row.hp_current > 0:
            return row
    return rows[enc.turn]


def sync_pcs(session, enc: Encounter) -> None:
    """PCs' numbers live on the character; mirror them so the order is current."""
    chars = {c.id: c for c in session.scalars(select(Character)).all()}
    for row in combatants(session, enc):
        if row.kind == "pc" and row.character_id in chars:
            ch = chars[row.character_id]
            row.hp_max, row.hp_current, row.ac, row.name = ch.hp_max, ch.hp_current, ch.ac, ch.name
            row.conditions = list(ch.conditions or [])


def view(session, enc: Encounter, me: int | None = None, dm: bool = False) -> dict:
    """The order as one seat sees it: everything for the DM, phrases for players."""
    sync_pcs(session, enc)
    rows = ordered(combatants(session, enc))
    cur = rows[enc.turn % len(rows)] if rows else None
    out = []
    for row in rows:
        if not dm and not row.visible:
            continue
        seen = describe(row.name, row.hp_current, row.hp_max, row.conditions or [])
        out.append({
            "id": row.id, "kind": row.kind, "character_id": row.character_id, "name": row.name,
            "initiative": row.initiative, "current": row is cur, "mine": row.character_id == me and me is not None,
            "seen": seen, "hp_current": row.hp_current, "hp_max": row.hp_max, "ac": row.ac, "conditions": row.conditions or [],
            "monster_key": row.monster_key, "visible": row.visible, "notes": row.notes, "loot": row.loot or [],
            "coins": row.coins or {}, "down": row.hp_current <= 0, "dex_mod": row.dex_mod, "cr": row.cr,
        })
    return {"encounter": enc, "rows": out, "current": cur, "my_turn": bool(cur and me is not None and cur.character_id == me),
            "waiting": [r.name for r in rows if r.kind == "pc" and r.initiative is None]}
