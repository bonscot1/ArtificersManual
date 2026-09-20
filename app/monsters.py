"""Monsters as the tracker needs them: a few numbers, dice rolls, and what they carry."""
from __future__ import annotations

import random
import re

from .compendium.rules import ability_mod, strip_tags

SIZES = {"T": "Tiny", "S": "Small", "M": "Medium", "L": "Large", "H": "Huge", "G": "Gargantuan"}
_DICE = re.compile(r"^\s*(\d*)d(\d+)\s*(?:([+-])\s*(\d+))?\s*(?:\*\s*(\d+))?\s*$")


def roll(formula: str, rng: random.Random | None = None) -> int:
    """'2d6', '17d8 + 68', '6d6*100', or a plain number."""
    rng = rng or random
    text = str(formula).replace("×", "*").strip()
    if text.lstrip("-").isdigit():
        return int(text)
    m = _DICE.match(text)
    if not m:
        return 0
    count = int(m.group(1) or 1)
    faces = int(m.group(2))
    total = sum(rng.randint(1, faces) for _ in range(count))
    if m.group(3):
        total += int(m.group(4)) * (1 if m.group(3) == "+" else -1)
    if m.group(5):
        total *= int(m.group(5))
    return max(0, total)


def cr_value(cr) -> float:
    if isinstance(cr, dict):
        cr = cr.get("cr", "0")
    text = str(cr)
    if "/" in text:
        a, b = text.split("/")
        return int(a) / int(b)
    try:
        return float(text)
    except ValueError:
        return 0.0


def cr_text(cr) -> str:
    return str(cr.get("cr", "?") if isinstance(cr, dict) else cr)


def ac_value(monster: dict) -> int:
    for entry in monster.get("ac") or []:
        if isinstance(entry, int):
            return entry
        if isinstance(entry, dict) and "ac" in entry:
            return int(entry["ac"])
    return 10


def ac_text(monster: dict) -> str:
    bits = []
    for entry in monster.get("ac") or []:
        if isinstance(entry, int):
            bits.append(str(entry))
        elif isinstance(entry, dict):
            frm = ", ".join(strip_tags(x) for x in entry.get("from", []))
            bits.append(f"{entry.get('ac')}" + (f" ({frm})" if frm else "") + (f" {strip_tags(entry['condition'])}" if entry.get("condition") else ""))
    return " / ".join(bits) or "10"


def hp_average(monster: dict) -> int:
    hp = monster.get("hp") or {}
    if isinstance(hp, dict):
        if hp.get("average") is not None:
            return int(hp["average"])
        if hp.get("formula"):
            return roll(hp["formula"], random.Random(0))
        if hp.get("special"):
            digits = re.findall(r"\d+", str(hp["special"]))
            return int(digits[0]) if digits else 1
    return int(hp) if isinstance(hp, int) else 1


def hp_rolled(monster: dict, rng: random.Random | None = None) -> int:
    hp = monster.get("hp") or {}
    if isinstance(hp, dict) and hp.get("formula"):
        return max(1, roll(hp["formula"], rng))
    return hp_average(monster)


def speed_text(monster: dict) -> str:
    sp = monster.get("speed")
    if isinstance(sp, int):
        return f"{sp} ft."
    bits = []
    for k in ("walk", "fly", "swim", "climb", "burrow"):
        v = (sp or {}).get(k)
        if v:
            n = v.get("number") if isinstance(v, dict) else v
            bits.append(f"{k} {n} ft." if k != "walk" else f"{n} ft.")
    return ", ".join(bits) or "-"


def type_text(monster: dict) -> str:
    t = monster.get("type")
    if isinstance(t, dict):
        tags = t.get("tags") or []
        tag_text = ", ".join(x if isinstance(x, str) else x.get("tag", "") for x in tags)
        base = str(t.get("type", ""))
        return f"{base} ({tag_text})" if tag_text else base
    return str(t or "")


def summary(monster: dict) -> dict:
    return {
        "name": monster["name"], "source": monster["source"],
        "size": " or ".join(SIZES.get(s, s) for s in monster.get("size", ["M"])),
        "type": type_text(monster), "ac": ac_value(monster), "ac_text": ac_text(monster),
        "hp": hp_average(monster), "hp_formula": (monster.get("hp") or {}).get("formula", "") if isinstance(monster.get("hp"), dict) else "",
        "speed": speed_text(monster), "cr": cr_text(monster.get("cr", "0")), "cr_value": cr_value(monster.get("cr", "0")),
        "dex_mod": ability_mod(int(monster.get("dex", 10) or 10)),
        "senses": ", ".join(strip_tags(x) for x in monster.get("senses") or []),
        "passive": monster.get("passive", ""),
    }


def carried(monster: dict) -> list[str]:
    """What the stat block says it holds - the obvious loot ('scimitar|phb' -> 'Scimitar')."""
    out = []
    for ref in monster.get("attachedItems") or []:
        name = str(ref).split("|")[0].strip()
        if name and name.lower() not in [x.lower() for x in out]:
            out.append(name.title() if name.islower() else name)
    return out
