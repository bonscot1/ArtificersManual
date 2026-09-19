"""Everything a character sheet shows that is derived rather than stored.

Stored: scores, level, class/race keys, HP, proficiency choices, spell list...
Derived here: modifiers, saves, skills, spell DC and slots, the features and traits
pulled from the enabled books for that race/class/subclass/background.
"""
from __future__ import annotations

import re

from .compendium import format as fmt
from .compendium import rules
from .compendium.loader import Compendium, entity_url
from .db import Character
from .narrative import describe
from .themes import theme_key, theme_style

# race entries that describe rather than grant something
_RACE_FLUFF = {"Age", "Alignment", "Size", "Languages", "Speed", "Creature Type", "Life Span"}

# 5etools optional-feature type codes -> what the sheet calls them
OPTION_TYPES = {
    "AI": "Infusion", "EI": "Eldritch Invocation", "MM": "Metamagic", "MV:B": "Maneuver",
    "MV:C2-UA": "Maneuver", "FS:F": "Fighting Style", "FS:R": "Fighting Style", "FS:P": "Fighting Style",
    "FS:B": "Fighting Style", "ED": "Elemental Discipline", "AS": "Arcane Shot", "AS:V1-UA": "Arcane Shot",
    "AS:V2-UA": "Arcane Shot", "RN": "Rune", "PB": "Pact Boon", "OTH": "Other", "AF": "Alchemical Formula",
    "OR": "Onomancy Resonant", "RP": "Rune", "TT": "Tactic", "PS": "Psionic Power", "SHP:H": "Ship Upgrade",
    "VEH": "Vehicle Upgrade",
}


def build_sheet(ch: Character, c: Compendium) -> dict:
    scores = ch.scores()
    mods = {k: rules.ability_mod(v) for k, v in scores.items()}
    prof = rules.proficiency_bonus(ch.level)

    race = c.merged_race(ch.race_key, ch.subrace_key) if ch.race_key else None
    cls = c.classes.get(ch.class_key)
    sub = c.subclasses.get(ch.class_key, {}).get(ch.subclass_key) if ch.subclass_key else None
    bg = c.backgrounds.get(ch.background_key) if ch.background_key else None

    save_profs = set(ch.save_profs or [])
    saves = [{
        "ability": a, "name": rules.ABILITY_NAMES[a], "prof": a in save_profs,
        "total": mods[a] + (prof if a in save_profs else 0),
    } for a in rules.ABILITIES]

    skill_profs = set(ch.skill_profs or [])
    expertise = set(ch.skill_expertise or [])
    skills = []
    for name, ab in rules.SKILLS:
        bonus = 0
        if name in expertise:
            bonus = prof * 2
        elif name in skill_profs:
            bonus = prof
        skills.append({"name": name, "ability": ab, "prof": name in skill_profs,
                       "expertise": name in expertise, "total": mods[ab] + bonus})
    perception = next(s for s in skills if s["name"] == "Perception")

    subclass_level = c.subclass_level(ch.class_key) if cls else None
    features = c.features_for(ch.class_key, ch.subclass_key, ch.level) if cls else []

    race_traits, race_fluff = [], []
    if race:
        for e in race.get("entries", []):
            if not isinstance(e, dict) or not e.get("name"):
                continue
            (race_fluff if e["name"] in _RACE_FLUFF else race_traits).append(e)

    spellcasting = _spellcasting(ch, cls, sub, mods, prof)
    always = always_prepared(sub, ch.level, c)
    spell_rows = [{"key": k, "spell": c.spells[k], "prepared": True, "always": True, "level": c.spells[k]["level"]}
                  for k in always]
    for entry in ch.spells or []:
        sp = c.spells.get(entry.get("key", ""))
        if sp and entry.get("key") not in always:
            spell_rows.append({"key": entry["key"], "spell": sp, "prepared": bool(entry.get("prepared")),
                               "always": False, "level": sp["level"]})
    spell_rows.sort(key=lambda r: (r["level"], r["spell"]["name"]))
    spell_levels: dict[int, list] = {}
    for r in spell_rows:
        spell_levels.setdefault(r["level"], []).append(r)

    hit_die = (cls or {}).get("hd", {}).get("faces")
    feat_rows = _pick_rows(ch.feats, c.feats)
    option_rows = _pick_rows(ch.options, c.optionalfeatures)
    option_types = _option_types(cls, sub, ch.level)
    for row in option_rows:
        codes = row["entity"].get("featureType", []) if row["entity"] else []
        row["type"] = next((OPTION_TYPES.get(code, code) for code in codes), "Option")
    counters = [{"name": x.get("name", ""), "max": max(0, int(x.get("max", 0) or 0)),
                 "used": max(0, min(int(x.get("max", 0) or 0), int(x.get("used", 0) or 0))),
                 "reset": x.get("reset", "long")} for x in (ch.counters or [])]
    inventory_links = {}
    for i, row in enumerate(ch.inventory or []):
        wanted = _item_name(row.get("name", ""))
        item = c.find("item", wanted) or c.find("item", wanted.rstrip("s"))
        if item:
            inventory_links[i] = entity_url("item", item)
    castable = [r for r in spell_rows
                if r["level"] == 0 or r["prepared"] or not (spellcasting or {}).get("prepares")]
    ready_levels: dict[int, list] = {}
    for r in castable:
        ready_levels.setdefault(r["level"], []).append(r)
    theme = theme_key(ch, cls)
    companions = []
    for i, comp in enumerate(ch.companions or []):
        hp_max = max(0, int(comp.get("hp_max", 0) or 0))
        row = {"idx": i, "name": comp.get("name", "") or "Companion", "kind": comp.get("kind", ""),
               "hp_max": hp_max, "hp_current": max(0, min(hp_max, int(comp.get("hp_current", 0) or 0))),
               "ac": comp.get("ac", ""), "summoned": bool(comp.get("summoned")),
               "conditions": list(comp.get("conditions") or []), "notes": comp.get("notes", "")}
        row["seen"] = describe(row["name"], row["hp_current"], row["hp_max"], row["conditions"])
        companions.append(row)
    return {
        "seen": describe(ch.name, ch.hp_current, ch.hp_max, ch.conditions or []),
        "companions": companions,
        "theme": theme,
        "theme_style": theme_style(theme),
        "ready_levels": ready_levels,
        "inventory_links": inventory_links,
        "feats": feat_rows,
        "options": option_rows,
        "option_types": option_types,
        "option_type_codes": sorted({code for t in option_types for code in t["codes"]}),
        "class_table": class_table_values(cls, sub, ch.level),
        "counters": counters,
        "char": ch,
        "scores": scores,
        "mods": mods,
        "prof": prof,
        "race": race,
        "race_traits": race_traits,
        "race_fluff": race_fluff,
        "race_ability": fmt.race_ability_text(race) if race else "",
        "race_speed": fmt.race_speed_text(race) if race else "",
        "race_size": fmt.race_size(race) if race else "",
        "cls": cls,
        "sub": sub,
        "subclass_title": (cls or {}).get("subclassTitle") or "Subclass",
        "subclass_level": subclass_level,
        "subclass_options": c.subclass_options(ch.class_key) if cls else [],
        "needs_subclass": bool(cls and subclass_level and ch.level >= subclass_level and not sub),
        "bg": bg,
        "bg_feature": fmt.background_feature(bg) if bg else None,
        "features": features,
        "saves": saves,
        "skills": skills,
        "passive_perception": 10 + perception["total"],
        "initiative": mods["dex"] + (ch.initiative_bonus or 0),
        "hit_die": hit_die,
        "hit_dice_left": max(0, ch.level - (ch.hit_dice_used or 0)),
        "spellcasting": spellcasting,
        "spell_levels": spell_levels,
        "spell_count": len(spell_rows),
        "spell_total": len(spell_rows),
        "prepared_count": sum(1 for r in spell_rows if r["prepared"] and r["level"] > 0 and not r["always"]),
        "racial_spells": racial_spells(race, ch.level, c) if race else [],
        "conditions": list(ch.conditions or []),
        "condition_names": [x["name"] for x in sorted(c.conditions.values(), key=lambda x: x["name"])],
        "currency": {k: int((ch.currency or {}).get(k, 0) or 0) for k in ("cp", "sp", "ep", "gp", "pp")},
    }


def _spellcasting(ch: Character, cls: dict | None, sub: dict | None, mods: dict, prof: int) -> dict | None:
    if not cls:
        return None
    ability = (sub or {}).get("spellcastingAbility") or cls.get("spellcastingAbility")
    slots_raw = rules.spell_slots(cls, sub, ch.level)
    pact = rules.pact_slots(cls, ch.level)
    if not ability and not any(slots_raw) and not pact:
        return None
    used = ch.slots_used or {}
    slots = []
    for i, total in enumerate(slots_raw):
        lvl = i + 1
        if total:
            slots.append({"level": lvl, "label": rules.ordinal(lvl), "total": total,
                          "used": max(0, min(total, int(used.get(str(lvl), 0) or 0)))})
    pact_info = None
    if pact and pact[0]:
        pact_info = {"count": pact[0], "level": pact[1], "label": rules.ordinal(pact[1]),
                     "used": max(0, min(pact[0], ch.pact_used or 0))}
    prepared_max = None
    formula = cls.get("preparedSpells")
    if formula:
        try:
            prepared_max = rules.eval_prepared_formula(formula, ch.level, mods)
        except ValueError:
            prepared_max = None
    known_source = sub if sub and sub.get("spellsKnownProgression") else cls
    cantrip_source = sub if sub and sub.get("cantripProgression") else cls
    return {
        "ability": ability,
        "ability_name": rules.ABILITY_NAMES.get(ability, "") if ability else "",
        "dc": 8 + prof + mods[ability] if ability else None,
        "attack": prof + mods[ability] if ability else None,
        "slots": slots,
        "pact": pact_info,
        "cantrips_known": rules.progression_at(cantrip_source, "cantripProgression", ch.level),
        "spells_known": rules.progression_at(known_source, "spellsKnownProgression", ch.level),
        "prepared_max": prepared_max,
        "prepares": bool(formula),
    }


def default_hp(cls: dict | None, level: int, con_mod: int) -> int:
    faces = (cls or {}).get("hd", {}).get("faces", 8)
    return rules.default_max_hp(faces, level, con_mod)


def _pick_rows(picks: list | None, store: dict) -> list[dict]:
    rows = []
    for i, pick in enumerate(picks or []):
        entity = store.get(pick.get("key", ""))
        rows.append({"idx": i, "key": pick.get("key", ""), "note": pick.get("note", ""), "entity": entity,
                     "name": entity["name"] if entity else pick.get("key", "").split("|")[0]})
    return rows


def _option_types(cls: dict | None, sub: dict | None, level: int) -> list[dict]:
    """Which class options this character picks from, and how many they know at this level."""
    out = []
    for entry in (cls, sub):
        for prog in (entry or {}).get("optionalfeatureProgression", []) or []:
            codes = prog.get("featureType", [])
            progression = prog.get("progression")
            known = None
            if isinstance(progression, list):
                known = int(progression[max(1, min(20, level)) - 1])
            elif isinstance(progression, dict):
                reached = [int(v) for k, v in progression.items() if str(k).isdigit() and int(k) <= level]
                known = reached[-1] if reached else 0
            if known:
                out.append({"name": prog.get("name") or OPTION_TYPES.get(codes[0] if codes else "", "Options"),
                            "codes": codes, "known": known})
    return out


def class_table_values(cls: dict | None, sub: dict | None, level: int) -> list[tuple[str, str]]:
    """The class table's non-slot columns at this level: Rages 2, Rage Damage +2, Infused Items 2..."""
    out = []
    groups = list((cls or {}).get("classTableGroups") or [])
    if sub:
        groups += list(sub.get("subclassTableGroups") or [])
    for g in groups:
        if "rowsSpellProgression" in g or not g.get("rows"):
            continue
        labels = [rules.strip_tags(x) for x in g.get("colLabels", [])]
        row = g["rows"][max(1, min(20, level)) - 1]
        for label, value in zip(labels, row):
            if label in ("Slot Level", "Spell Slots"):
                continue
            if isinstance(value, dict):
                text = str(value.get("value", ""))
                if value.get("type") == "bonus" and text.lstrip("-").isdigit():
                    text = f"+{text}" if not text.startswith("-") else text
                elif value.get("type") == "bonusSpeed":
                    text = f"+{text} ft."
            else:
                text = rules.strip_tags(str(value))
            if text not in ("", "0", "-"):
                out.append((label, text))
    return out


def _item_name(text: str) -> str:
    """'Hand Axe (x2)' / '2 x Javelin' / 'Belt of Dwarven Kind' -> something the books might know."""
    name = re.sub(r"\(.*?\)", "", text)
    name = re.sub(r"^\d+\s*[x×]\s*", "", name, flags=re.I).strip()
    return name.replace("Dwarven Kind", "Dwarvenkind").replace("Hand Axe", "Handaxe")


def _spell_key(text: str, c: Compendium) -> str | None:
    """'bless', 'thaumaturgy#c', 'hellish rebuke#2', 'shield|phb' -> the compendium key."""
    name = text.split("#")[0]
    source = None
    if "|" in name:
        name, source = name.split("|", 1)
    sp = c.find("spell", name, source)
    return f"{sp['name']}|{sp['source']}" if sp else None


def always_prepared(sub: dict | None, level: int, c: Compendium) -> list[str]:
    """Domain / oath / circle spells: always prepared, never counted. Named variants need a pick."""
    out: list[str] = []
    for block in (sub or {}).get("additionalSpells", []) or []:
        if block.get("name"):
            continue
        for lvl, names in (block.get("prepared") or {}).items():
            if not str(lvl).isdigit() or int(lvl) > level:
                continue
            for n in names:
                key = _spell_key(n, c) if isinstance(n, str) else None
                if key and key not in out:
                    out.append(key)
    return out


def racial_spells(race: dict, level: int, c: Compendium) -> list[str]:
    """One line per racial spell: 'Thaumaturgy (cantrip)', 'Hellish Rebuke at 2nd level, 1/day (from level 3)'."""
    out = []
    for block in race.get("additionalSpells", []) or []:
        ability = block.get("ability")
        ability = ability.upper() if isinstance(ability, str) else ""
        for lvl, names in (block.get("known") or {}).items():
            names = names.get("_", []) if isinstance(names, dict) else names
            for n in names:
                key = _spell_key(n, c) if isinstance(n, str) else None
                if key:
                    out.append(f"{key.split('|')[0]} (cantrip)" if c.spells[key]["level"] == 0 else key.split("|")[0])
        for lvl, block2 in (block.get("innate") or {}).items():
            if not isinstance(block2, dict):
                continue
            for cadence, spells in block2.items():
                if cadence not in ("daily", "rest"):
                    continue
                for uses, names in spells.items():
                    for n in names:
                        key = _spell_key(n, c) if isinstance(n, str) else None
                        if not key:
                            continue
                        cast_at = n.split("#")[1] if "#" in n and n.split("#")[1].isdigit() else ""
                        line = key.split("|")[0]
                        if cast_at:
                            line += f" at {rules.ordinal(int(cast_at))} level"
                        line += f", {uses.rstrip('e')}/{'day' if cadence == 'daily' else 'rest'}"
                        if str(lvl).isdigit() and int(lvl) > 1:
                            line += f" (from level {lvl})"
                        if ability:
                            line += f" - {ability}"
                        out.append(line)
    return out


def cast_options(sheet: dict, spell: dict) -> list[dict]:
    """How this spell can be cast right now: which slot levels have a slot left, pact, ritual."""
    sc = sheet["spellcasting"] or {}
    level = spell.get("level", 0)
    out = []
    if level == 0:
        return [{"slot": "cantrip", "label": "Cast"}]
    for s in sc.get("slots", []):
        if s["level"] >= level and s["used"] < s["total"]:
            out.append({"slot": str(s["level"]), "label": f"{s['label']} ({s['total'] - s['used']} left)"})
    pact = sc.get("pact")
    if pact and pact["level"] >= level and pact["used"] < pact["count"]:
        out.append({"slot": "pact", "label": f"Pact {pact['label']} ({pact['count'] - pact['used']} left)"})
    if (spell.get("meta") or {}).get("ritual"):
        out.append({"slot": "ritual", "label": "Ritual (no slot, +10 min)"})
    return out
