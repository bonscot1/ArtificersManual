"""Loot tables: what a fallen creature has on it, by what it was.

A table is weighted rows plus a coin rule. The built-in ones are seeded per creature type
(a wolf leaves a pelt, a goblin leaves its pockets, a skeleton leaves dust and grave goods);
the DM edits them or writes new ones on /dm/loot. Rolling is real dice via monsters.roll.
"""
from __future__ import annotations

import random

from sqlalchemy import select

from . import loot as L
from .db import LootTable
from .monsters import roll

TYPES = ["aberration", "beast", "celestial", "construct", "dragon", "elemental", "fey", "fiend",
         "giant", "humanoid", "monstrosity", "ooze", "plant", "undead"]
COINS = ("cp", "sp", "ep", "gp", "pp")
NOTHING = {"", "-", "nothing", "none", "nothing of note"}


def _e(name: str, weight: int = 1, qty: str = "1", notes: str = "") -> dict:
    return {"name": name, "qty": qty, "weight": weight, "notes": notes}


DEFAULTS: list[dict] = [
    {"name": "Humanoid - pockets and pack", "types": ["humanoid"], "draws": "1d3-1", "coins_mode": "dmg",
     "notes": "Coins by challenge rating (DMG individual treasure) plus whatever it kept on it.",
     "entries": [
         _e("Nothing of note", 8), _e("Rations (1 day)", 6, "1d2"), _e("Waterskin", 4), _e("Torch", 4, "1d2"),
         _e("Dagger", 3, "1", "tucked in a boot"), _e("Tinderbox", 3), _e("Pouch", 3, "1", "empty but for lint"),
         _e("Whetstone", 3), _e("Hempen Rope (50 feet)", 2), _e("Bedroll", 2), _e("Candle", 2, "1d3"),
         _e("Dice Set", 2, "1", "loaded, if you look closely"), _e("Playing Card Set", 1),
         _e("Lucky charm", 2, "1", "a knot of hair, a tooth on a string - worthless to anyone else"),
         _e("Crude map", 1, "1", "of somewhere nearby, marked with an X"), _e("Letter", 1, "1", "read it: who were they writing to?"),
         _e("Amulet", 1, "1", "a symbol you don't recognise"), _e("Manacles", 1), _e("Crowbar", 1),
         _e("Potion of Healing", 1),
     ]},
    {"name": "Beast - hide and parts", "types": ["beast"], "draws": "1d2", "coins_mode": "none",
     "notes": "Nothing a beast would carry; what a hunter takes from it.",
     "entries": [
         _e("Nothing usable", 4), _e("Hide or pelt", 6, "1", "a tanner pays a few silver if it's whole"),
         _e("Meat", 5, "1d4", "a day's rations each, once cooked"), _e("Teeth or fangs", 3, "1d4"),
         _e("Claws or talons", 3, "1d2"), _e("Sinew", 2, "1", "bowstring, thread, snares"),
         _e("Horns or antlers", 1, "1", "if it had them"), _e("Feathers", 1, "2d6", "if it had them"),
         _e("Venom sac", 1, "1", "if it was venomous - a poisoner's ingredient"),
         _e("A collar", 1, "1", "someone's pet, or someone's mount"),
     ]},
    {"name": "Undead - grave goods", "types": ["undead"], "draws": "1d2-1", "coins_mode": "custom",
     "coins": {"cp": "2d6", "sp": "1d4-1"}, "notes": "Old coins and what it was buried with. Mostly dust.",
     "entries": [
         _e("Nothing but dust and bone", 6), _e("Rusted blade", 4, "1", "a sword nobody would buy"),
         _e("Rotted clothes", 3, "1", "once fine, going by the buttons"), _e("Grave ring", 2, "1", "tarnished silver, worth 5 gp"),
         _e("Bone charm", 2), _e("Tattered holy symbol", 1, "1", "of a faith that still exists"),
         _e("Amulet", 1, "1", "cold to the touch"), _e("Burial shroud", 1, "1", "linen, embroidered with a name"),
     ]},
    {"name": "Construct - scrap", "types": ["construct"], "draws": "1d2", "coins_mode": "none",
     "notes": "Parts. An artificer will want the core.",
     "entries": [
         _e("Nothing but twisted scrap", 3), _e("Scrap metal", 6, "1d4", "a smith gives a few copper a pound"),
         _e("Gears and cogs", 4, "1d6"), _e("Copper wire", 3, "1", "a coil of it"), _e("Glass lens", 2),
         _e("Still-warm core", 2, "1", "an artificer could do something with this"),
         _e("Crystal shard", 1, "1", "faintly glowing"), _e("Maker's mark", 1, "1", "a stamped plate: who built it?"),
     ]},
    {"name": "Dragon - scales and teeth", "types": ["dragon"], "draws": "1d3", "coins_mode": "none",
     "notes": "The body. The hoard is wherever it slept - roll Treasure hoard for that.",
     "entries": [
         _e("Dragon scales", 6, "2d6", "could be worked into armour"), _e("Dragon tooth", 4, "1d4"),
         _e("Dragon claw", 3, "1d2"), _e("Vial of dragon blood", 2, "1", "a spell component, and a poison"),
         _e("A swallowed gem", 2, "1", "roll a gem, or pick one"), _e("Nothing but the corpse", 1),
     ]},
    {"name": "Fiend or celestial - essence", "types": ["fiend", "celestial"], "draws": "1d2-1", "coins_mode": "none",
     "notes": "Most of them vanish. What stays behind is strange.",
     "entries": [
         _e("Nothing - it fades away", 6), _e("Vial of ichor", 3, "1", "hisses on metal"), _e("A horn", 2),
         _e("Brimstone", 2, "1", "a lump of it"), _e("A feather", 1, "1", "warm, faintly glowing"),
     ]},
    {"name": "Fey - trinkets", "types": ["fey"], "draws": "1d2", "coins_mode": "custom", "coins": {"sp": "2d6"},
     "notes": "Oddments. None of it is quite what it seems.",
     "entries": [
         _e("Nothing of note", 4), _e("Pressed flower", 3, "1", "never wilts"), _e("Silver bell", 2, "1", "no clapper; rings anyway"),
         _e("Bottle of dew", 2, "1", "cures nothing, tastes wonderful"), _e("Lock of hair", 2, "1", "whose?"),
         _e("Moonstone", 1), _e("An acorn that hums", 1),
     ]},
    {"name": "Giant - the big sack", "types": ["giant"], "draws": "1d3", "coins_mode": "dmg",
     "notes": "Coins by challenge rating, and what a giant drags around.",
     "entries": [
         _e("Nothing else", 3), _e("Giant-sized weapon", 3, "1", "too big to wield; the iron is worth something"),
         _e("A sheep", 2, "1", "alive, just"), _e("Barrel of ale", 2), _e("Hempen Rope (50 feet)", 2, "1", "as thick as your arm"),
         _e("Iron Pot", 2, "1", "you could bathe in it"), _e("A captive's belongings", 2, "1", "roll Humanoid pockets"),
         _e("Cauldron", 1), _e("Huge belt", 1, "1", "the buckle is a shield"),
     ]},
    {"name": "Monstrosity - trophies", "types": ["monstrosity"], "draws": "1d2", "coins_mode": "none",
     "notes": "Parts a collector or an alchemist would pay for.",
     "entries": [
         _e("Nothing usable", 3), _e("Hide", 4, "1", "tough; armour-grade if worked"), _e("Claws", 3, "1d4"),
         _e("Venom sac", 2, "1", "if it was venomous"), _e("Horn", 2), _e("A beak", 1),
         _e("An eye", 1, "1", "useful to alchemists"), _e("Half-digested belongings", 3, "1", "someone else's - roll Humanoid pockets"),
     ]},
    {"name": "Ooze - undigested", "types": ["ooze"], "draws": "1d2-1", "coins_mode": "custom",
     "coins": {"cp": "3d6", "sp": "1d6", "gp": "1d3-1"}, "notes": "What its last meals were carrying.",
     "entries": [
         _e("Nothing", 4), _e("Corroded weapon", 3, "1", "pitted; still sharp"), _e("Quartz", 1, "1", "a gem it couldn't dissolve"),
         _e("Half-dissolved boots", 2), _e("Acid-scarred buckle", 2),
     ]},
    {"name": "Plant - sap and seeds", "types": ["plant"], "draws": "1d2", "coins_mode": "none",
     "entries": [
         _e("Nothing usable", 3), _e("Strange seeds", 3, "1d6", "plant them?"), _e("Sap", 3, "1", "sticky; an adhesive"),
         _e("Bark", 2, "1", "a poultice ingredient"), _e("A flower", 2, "1", "sweet; then sickly"),
         _e("Bones of an earlier meal", 2, "1", "roll Humanoid pockets"),
     ]},
    {"name": "Aberration - strange organs", "types": ["aberration"], "draws": "1d2-1", "coins_mode": "none",
     "entries": [
         _e("Nothing you want", 5), _e("Ichor", 3, "1", "a vial; it moves"), _e("An eye", 2, "1", "it watches"),
         _e("A beak", 1), _e("A strange organ", 2, "1", "pulsing, slowly"),
     ]},
    {"name": "Elemental - motes", "types": ["elemental"], "draws": "1d2-1", "coins_mode": "none",
     "entries": [
         _e("Nothing - it disperses", 6), _e("A mote of its element", 3, "1", "fades in a day"),
         _e("A lump of pure element", 2, "1", "a spell component"),
     ]},
    {"name": "Coins only (DMG, by challenge rating)", "types": [], "draws": "0", "coins_mode": "dmg",
     "notes": "Just the DMG individual treasure for its challenge rating. Suits anything that keeps coins."},
    {"name": "Treasure hoard (DMG, by challenge rating)", "types": [], "mode": "hoard", "draws": "0", "coins_mode": "none",
     "notes": "A lair or a chest, not a corpse: coins, gems, art and magic items for its challenge rating."},
]


def seed(session, only_missing: bool = True) -> int:
    """Insert the built-in tables. With only_missing, ones the DM already has (by name) stay as they are."""
    have = {t.name for t in session.scalars(select(LootTable)).all()} if only_missing else set()
    n = 0
    for d in DEFAULTS:
        if d["name"] in have:
            continue
        session.add(LootTable(name=d["name"], notes=d.get("notes", ""), types=list(d.get("types", [])),
                              mode=d.get("mode", "table"), draws=d.get("draws", "1"), coins_mode=d.get("coins_mode", "none"),
                              coins=dict(d.get("coins", {})), entries=[dict(e) for e in d.get("entries", [])], builtin=True))
        n += 1
    return n


def seed_if_empty(session) -> int:
    """First run only: a deleted built-in stays deleted until the DM restores it."""
    return seed(session) if session.scalars(select(LootTable)).first() is None else 0


def all_tables(session) -> list[LootTable]:
    return session.scalars(select(LootTable).order_by(LootTable.name)).all()


def creature_type(monster: dict | None) -> str:
    """The base type as a lowercase word: 'humanoid', 'beast'..."""
    if not monster:
        return ""
    t = monster.get("type")
    while isinstance(t, dict):
        t = t.get("type")
    return str(t or "").lower()


def rank(table: LootTable, ctype: str, cr: float | None) -> int:
    """2 = made for this type, 1 = fits anything, 0 = wrong type or wrong challenge rating."""
    if cr is not None:
        if table.cr_min is not None and cr < table.cr_min:
            return 0
        if table.cr_max is not None and cr > table.cr_max:
            return 0
    if not table.types:
        return 1
    return 2 if ctype in [str(x).lower() for x in table.types] else 0


def suggestions(tables: list[LootTable], ctype: str, cr: float | None) -> list[dict]:
    """Every table with how well it fits; best fits first, so the select lands on the right one."""
    out = [{"table": t, "rank": rank(t, ctype, cr)} for t in tables]
    out.sort(key=lambda x: (-x["rank"], x["table"].name.lower()))
    return out


def _qty(spec, rng: random.Random) -> int:
    text = str(spec or "1").strip()
    return max(1, roll(text, rng)) if text else 1


def roll_table(table: LootTable, loot: dict, cr: float | None, rng: random.Random | None = None) -> dict:
    """One roll on the table: {"items": [{name, qty, notes}], "coins": {...}} - dice each time."""
    rng = rng or random.Random()
    cr = cr or 0.0
    if table.mode == "hoard":
        return L.hoard(loot, cr, rng)
    items: list[dict] = []
    rows = [e for e in (table.entries or []) if int(e.get("weight") or 0) > 0]
    draws = max(0, roll(table.draws or "1", rng))
    for _ in range(draws if rows else 0):
        e = rng.choices(rows, weights=[int(r.get("weight") or 0) for r in rows])[0]
        name = str(e.get("name", "")).strip()
        if name.lower() in NOTHING or name.lower().startswith("nothing"):
            continue
        n = _qty(e.get("qty"), rng)
        for it in items:
            if it["name"] == name:
                it["qty"] = int(it["qty"]) + n
                break
        else:
            items.append({"name": name, "qty": n, "notes": str(e.get("notes", ""))})
    coins: dict[str, int] = {}
    if table.coins_mode == "dmg":
        coins = L.individual(loot, cr, rng)["coins"]
    elif table.coins_mode == "custom":
        coins = {k: roll(v, rng) for k, v in (table.coins or {}).items() if str(v).strip()}
        coins = {k: v for k, v in coins.items() if v > 0}
    return {"items": items, "coins": coins}


def result_text(result: dict) -> str:
    bits = [f"{it['qty']} x {it['name']}" if int(it["qty"]) != 1 else it["name"] for it in result.get("items", [])]
    if result.get("coins"):
        bits.append(L.coins_text(result["coins"]))
    return ", ".join(bits) or "nothing"
