"""Everything a character sheet shows that is derived rather than stored.

Stored: scores, level, class/race keys, HP, proficiency choices, spell list...
Derived here: modifiers, saves, skills, spell DC and slots, the features and traits
pulled from the enabled books for that race/class/subclass/background.
"""
from __future__ import annotations

from .compendium import format as fmt
from .compendium import rules
from .compendium.loader import Compendium
from .db import Character

# race entries that describe rather than grant something
_RACE_FLUFF = {"Age", "Alignment", "Size", "Languages", "Speed", "Creature Type", "Life Span"}


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
    spell_rows = []
    for entry in ch.spells or []:
        sp = c.spells.get(entry.get("key", ""))
        if sp:
            spell_rows.append({"key": entry["key"], "spell": sp, "prepared": bool(entry.get("prepared")),
                               "level": sp["level"]})
    spell_rows.sort(key=lambda r: (r["level"], r["spell"]["name"]))
    spell_levels: dict[int, list] = {}
    for r in spell_rows:
        spell_levels.setdefault(r["level"], []).append(r)

    hit_die = (cls or {}).get("hd", {}).get("faces")
    return {
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
        "prepared_count": sum(1 for r in spell_rows if r["prepared"] and r["level"] > 0),
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
