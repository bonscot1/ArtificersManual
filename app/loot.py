"""Treasure from the DMG tables (loot.json): what an individual carries, what a hoard holds.

Rolls are real dice; the DM can reroll. Gems, art objects and magic items come from the
book's tables so the names link to the compendium.
"""
from __future__ import annotations

import random

from .compendium.rules import strip_tags
from .monsters import roll

COIN_ORDER = ("pp", "gp", "ep", "sp", "cp")


def _band(tables: list[dict], cr: float) -> dict | None:
    for t in tables:
        if t.get("crMin", 0) <= cr <= t.get("crMax", 999):
            return t
    return tables[-1] if tables else None


def _row(table: list[dict], rng: random.Random) -> dict:
    n = rng.randint(1, 100)
    for row in table:
        if row.get("min", 1) <= n <= row.get("max", 100):
            return row
    return table[-1]


def _coins(spec: dict | None, rng: random.Random) -> dict[str, int]:
    return {k: roll(v, rng) for k, v in (spec or {}).items() if roll(v, rng) > 0} if spec else {}


def _pick_from(loot: dict, kind: str, type_value, rng: random.Random) -> str:
    """One entry off a gem / art / magic item table of the given value or letter."""
    for table in loot.get(kind, []):
        if str(table.get("type")) == str(type_value):
            rows = table.get("table", [])
            if not rows:
                return ""
            if isinstance(rows[0], dict):
                return strip_tags(str(_row(rows, rng).get("item", "")))
            return strip_tags(str(rng.choice(rows)))
    return ""


def individual(loot: dict, cr: float, rng: random.Random | None = None) -> dict:
    """Coins carried by one creature of this challenge rating (DMG p.136)."""
    rng = rng or random.Random()
    band = _band(loot.get("individual", []), cr)
    if not band:
        return {"coins": {}, "items": []}
    row = _row(band.get("table", []), rng)
    return {"coins": _coins(row.get("coins"), rng), "items": []}


def hoard(loot: dict, cr: float, rng: random.Random | None = None) -> dict:
    """A treasure hoard for this challenge rating (DMG p.137): coins, gems or art, magic items."""
    rng = rng or random.Random()
    band = _band(loot.get("hoard", []), cr)
    if not band:
        return {"coins": {}, "items": []}
    coins = _coins(band.get("coins"), rng)
    items: list[dict] = []
    row = _row(band.get("table", []), rng)
    for kind in ("gems", "artObjects"):
        spec = row.get(kind)
        if spec:
            count = roll(spec.get("amount", "1"), rng)
            kind_type = spec.get("type")
            for _ in range(max(0, count)):
                name = _pick_from(loot, kind, kind_type, rng)
                if name:
                    _add(items, name, f"worth {kind_type} gp")
    for spec in row.get("magicItems") or []:
        count = roll(spec.get("amount", "1"), rng)
        for _ in range(max(0, count)):
            name = _pick_from(loot, "magicItems", spec.get("type"), rng)
            if name:
                _add(items, name, f"magic item table {spec.get('type')}")
    return {"coins": coins, "items": items}


def _add(items: list[dict], name: str, notes: str = "") -> None:
    for it in items:
        if it["name"] == name:
            it["qty"] = int(it.get("qty", 1)) + 1
            return
    items.append({"name": name, "qty": 1, "notes": notes})


def coins_text(coins: dict) -> str:
    return ", ".join(f"{coins[k]} {k}" for k in COIN_ORDER if coins.get(k)) or ""
