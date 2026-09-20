"""What a character can do on their turn: action, bonus action, reaction.

Read off the character's own sheet: their weapons (an off-hand attack needs two light
weapons), their spells (the spell's casting time says which slot it uses), their class
features, racial traits, feats and options (the rules text says "as a bonus action",
"use your reaction", "as an action"), plus the standard actions from the book.

The table plays 2014 rules with a few 2024 adoptions (see house_rules.md): potions are
a bonus action here, so that goes in the bonus column.
"""
from __future__ import annotations

import re

from .compendium.render import plain_text

# the 2014 standard actions, in the book's order; Use an Object is 'Utilize' in 2024
STANDARD_ACTIONS = ["Attack", "Cast a Spell", "Dash", "Disengage", "Dodge", "Help", "Hide", "Ready", "Search",
                    "Use an Object", "Grapple", "Shove"]

_BONUS = re.compile(r"\bbonus action\b", re.I)
_REACTION = re.compile(r"\byour reaction\b|\bas a reaction\b|\buse (?:a|your) reaction\b|\breaction to\b", re.I)
_ACTION = re.compile(r"\b(?:as|use|take|using) an action\b|\bas your action\b|\btake the (?:\w+ )?action\b|\baction to\b", re.I)
_ONHIT = re.compile(r"\bonce per turn\b|\bwhen you hit\b|\bonce on each of your turns\b", re.I)
_PASSIVE_NAMES = {"ability score improvement", "spellcasting", "pact magic", "extra attack", "proficiency versatility"}


def classify(entries) -> set[str]:
    """Which parts of a turn a feature touches, from its text."""
    text = plain_text(entries)
    out = set()
    if _BONUS.search(text):
        out.add("bonus")
    if _REACTION.search(text):
        out.add("reaction")
    if _ACTION.search(text):
        out.add("action")
    if _ONHIT.search(text) and not out:
        out.add("free")
    return out


def _light(comp, name: str) -> bool:
    base = name.split(" (")[0].strip()
    item = comp.find("item", base) or comp.find("item", base.replace(" ", "")) or comp.find("item", base.replace("-", ""))
    props = [(p if isinstance(p, str) else p.get("uid", "")).split("|")[0] for p in (item or {}).get("property") or []]
    return "L" in props


def combat_options(sheet: dict, comp) -> dict:
    """Lists for the play view's actions panel: [{name, detail, peek}] per part of the turn."""
    ch = sheet["char"]
    action, bonus, reaction, free = [], [], [], []

    # attacks
    weapons = [a for a in (ch.attacks or []) if str(a.get("name", "")).strip()]
    for a in weapons:
        action.append({"name": f"Attack: {a['name']}", "detail": f"{a.get('bonus', '')} to hit, {a.get('damage', '')}".strip(", "),
                       "kind": "attack"})
    light = [a for a in weapons if _light(comp, str(a["name"]))]
    pair = [a for a in light if re.search(r"\(x\s*[2-9]\d*\)", str(a["name"]))]     # "Handaxe (x2)" is two of them
    if len(light) >= 2 or pair:
        light = light if len(light) >= 2 else [pair[0], pair[0]]
        bonus.append({"name": f"Off-hand attack: {light[1]['name']}",
                      "detail": "after attacking with a light weapon; no ability modifier to the damage unless it is negative",
                      "kind": "offhand"})

    # spells ready to cast, by casting time
    for level, rows in sheet.get("ready_levels", {}).items():
        for r in rows:
            sp = r["spell"]
            unit = (sp.get("time") or [{}])[0].get("unit", "action")
            entry = {"name": sp["name"], "detail": ("cantrip" if level == 0 else f"level {level}") + (" · concentration" if any(d.get("concentration") for d in sp.get("duration", [])) else ""),
                     "kind": "spell", "peek": ("spell", sp)}
            if unit == "bonus":
                bonus.append(entry)
            elif unit == "reaction":
                entry["detail"] += " · " + str((sp.get("time") or [{}])[0].get("condition", "")).strip()
                reaction.append(entry)
            elif unit == "action":
                action.append(entry)

    # features, traits, feats, options: what the text says
    sources = []
    for f in sheet.get("features", []):
        sources.append((f.name, f.entries, None))
    for t in sheet.get("race_traits", []):
        sources.append((t.get("name", ""), t.get("entries", []), None))
    for row in sheet.get("feats", []) + sheet.get("options", []):
        if row.get("entity"):
            sources.append((row["name"], row["entity"].get("entries", []), ("feat" if row in sheet.get("feats", []) else "optionalfeature", row["entity"])))
    seen = set()
    for name, entries, peek in sources:
        if name.lower() in _PASSIVE_NAMES or name in seen:
            continue
        seen.add(name)
        parts = classify(entries)
        entry = {"name": name, "detail": "", "kind": "feature", "peek": peek, "entries": entries}
        if "bonus" in parts:
            bonus.append(entry)
        if "reaction" in parts:
            reaction.append(entry)
        if "action" in parts:
            action.append(entry)
        if "free" in parts:
            free.append(entry)

    # the table's rules
    if any("potion" in str(i.get("name", "")).lower() for i in (ch.inventory or [])):
        bonus.append({"name": "Drink a potion", "detail": "house rule (2024): a bonus action, or give one to someone within 5 ft.", "kind": "rule"})
    reaction.insert(0, {"name": "Opportunity attack", "detail": "a creature you can see leaves your reach", "kind": "rule",
                        "peek": ("action", comp.find("action", "Opportunity Attack")) if comp.find("action", "Opportunity Attack") else None})
    standard = []
    for name in STANDARD_ACTIONS:
        a = comp.find("action", name)
        if a:
            standard.append({"name": name, "detail": "", "kind": "standard", "peek": ("action", a)})
    return {"action": action, "bonus": bonus, "reaction": reaction, "free": free, "standard": standard}
