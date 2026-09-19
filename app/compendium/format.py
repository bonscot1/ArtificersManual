"""Short human strings for spell/race/class facts ("1 action", "60 ft.", "+2 Dex, +1 Int")."""
from __future__ import annotations

from .rules import ABILITY_NAMES, SCHOOLS, SIZES, ordinal


def spell_time(sp: dict) -> str:
    bits = []
    for t in sp.get("time", []):
        n, unit = t.get("number", 1), t.get("unit", "action")
        if unit == "bonus":
            unit = "bonus action"
        s = f"{n} {unit}" + ("s" if n != 1 and unit not in ("bonus action",) else "")
        if t.get("condition"):
            s += f", {t['condition']}"
        bits.append(s)
    return " or ".join(bits) or "-"


def spell_range(sp: dict) -> str:
    r = sp.get("range", {})
    kind = r.get("type", "point")
    d = r.get("distance", {})
    dt, amt = d.get("type", ""), d.get("amount")
    if kind == "special":
        return "Special"
    if dt in ("self", "touch", "sight", "unlimited"):
        base = dt.capitalize()
    elif amt is not None:
        base = f"{amt} {'ft.' if dt == 'feet' else dt}"
    else:
        base = dt.capitalize() if dt else "-"
    if kind not in ("point",):
        shape = {"radius": "radius", "sphere": "sphere", "cone": "cone", "line": "line",
                 "cube": "cube", "hemisphere": "hemisphere", "cylinder": "cylinder"}.get(kind, kind)
        return f"Self ({base} {shape})" if dt != "self" else f"Self ({shape})"
    return base


def spell_components(sp: dict) -> str:
    c = sp.get("components", {})
    bits = []
    if c.get("v"):
        bits.append("V")
    if c.get("s"):
        bits.append("S")
    if c.get("m"):
        m = c["m"]
        text = m.get("text", "") if isinstance(m, dict) else ("" if m is True else str(m))
        bits.append(f"M ({text})" if text else "M")
    return ", ".join(bits) or "-"


def spell_duration(sp: dict) -> str:
    bits = []
    for d in sp.get("duration", []):
        t = d.get("type")
        if t == "instant":
            s = "Instantaneous"
        elif t == "timed":
            inner = d.get("duration", {})
            n, unit = inner.get("amount", 1), inner.get("type", "round")
            s = f"{n} {unit}{'s' if n != 1 else ''}"
            if inner.get("upTo"):
                s = "up to " + s
        elif t == "permanent":
            ends = d.get("ends")
            s = "Until dispelled" + (" or triggered" if ends and "trigger" in ends else "")
        else:
            s = "Special"
        if d.get("concentration"):
            s = f"Concentration, up to {s}" if not s.startswith("up to") else f"Concentration, {s}"
        bits.append(s)
    return " or ".join(bits) or "-"


def spell_level_label(sp: dict) -> str:
    lvl = sp.get("level", 0)
    school = SCHOOLS.get(sp.get("school", ""), "")
    if lvl == 0:
        return f"{school} cantrip"
    return f"{ordinal(lvl)}-level {school.lower()}"


def spell_flags(sp: dict) -> list[str]:
    out = []
    if (sp.get("meta") or {}).get("ritual"):
        out.append("ritual")
    if any(d.get("concentration") for d in sp.get("duration", [])):
        out.append("concentration")
    return out


def race_ability_text(race: dict) -> str:
    ab = race.get("ability")
    if not ab:
        if race.get("lineage"):
            return "+2 to one score and +1 to another, or +1 to three"
        return "-"
    bits = []
    for choice in ab:
        for k, v in choice.items():
            if k == "choose":
                cnt = v.get("count", 1)
                amt = v.get("amount", 1)
                frm = ", ".join(ABILITY_NAMES.get(x, x)[:3] for x in v.get("from", []))
                bits.append(f"+{amt} to {cnt} of {frm}")
            else:
                bits.append(f"{v:+d} {ABILITY_NAMES.get(k, k)[:3]}")
    return ", ".join(bits) or "-"


def race_speed(race: dict) -> int:
    sp = race.get("speed", 30)
    if isinstance(sp, dict):
        walk = sp.get("walk", 30)
        return int(walk) if isinstance(walk, (int, float)) else 30
    return int(sp) if isinstance(sp, (int, float)) else 30


def race_speed_text(race: dict) -> str:
    sp = race.get("speed", 30)
    if isinstance(sp, dict):
        bits = []
        for k in ("walk", "fly", "swim", "climb", "burrow"):
            v = sp.get(k)
            if v:
                bits.append(f"{k} {v if v is not True else sp.get('walk', 30)} ft.")
        return ", ".join(bits)
    return f"{sp} ft."


def race_size(race: dict) -> str:
    return " or ".join(SIZES.get(s, s) for s in race.get("size", ["M"]))


def prof_list(entries: list | None) -> str:
    """5etools proficiency lists: [{"perception": true, "anyStandard": 1, "choose": {...}}] -> text."""
    if not entries:
        return ""
    bits = []
    for e in entries:
        for k, v in e.items():
            if k == "choose":
                cnt = v.get("count", 1)
                bits.append(f"choose {cnt} of {', '.join(x.title() for x in v.get('from', []))}")
            elif k in ("any", "anyStandard"):
                bits.append(f"{v} of your choice")
            elif v is True:
                bits.append(k.title())
            elif isinstance(v, (int, float)):
                bits.append(f"{k.title()} ({v})")
    return ", ".join(bits)


def background_feature(bg: dict) -> dict | None:
    for e in bg.get("entries", []):
        if isinstance(e, dict) and (e.get("data") or {}).get("isFeature"):
            return e
    for e in bg.get("entries", []):
        if isinstance(e, dict) and str(e.get("name", "")).startswith("Feature"):
            return e
    return None


def background_skills(bg: dict) -> list[str]:
    out = []
    for e in bg.get("skillProficiencies", []) or []:
        for k, v in e.items():
            if v is True:
                out.append(k.title())
    return out


def weapon_summary(item: dict) -> str:
    bits = []
    if item.get("dmg1"):
        dmg_type = {"S": "slashing", "P": "piercing", "B": "bludgeoning"}.get(item.get("dmgType", ""), "")
        bits.append(f"{item['dmg1']} {dmg_type}".strip())
    props = item.get("property") or []
    names = {"V": "versatile", "F": "finesse", "L": "light", "H": "heavy", "T": "thrown", "2H": "two-handed",
             "R": "reach", "A": "ammunition", "LD": "loading", "S": "special"}
    if props:
        bits.append(", ".join(names.get(p if isinstance(p, str) else p.get("uid", ""), str(p)) for p in props))
    if item.get("range"):
        bits.append(f"range {item['range']}")
    if item.get("dmg2"):
        bits.append(f"({item['dmg2']} two-handed)")
    return " - ".join(bits)


def armor_summary(item: dict) -> str:
    if not item.get("ac"):
        return ""
    t = item.get("type", "")
    if t == "LA":
        return f"AC {item['ac']} + Dex"
    if t == "MA":
        return f"AC {item['ac']} + Dex (max 2)"
    if t == "HA":
        return f"AC {item['ac']}" + (f", Str {item['strength']}" if item.get("strength") else "")
    if t == "S":
        return f"+{item['ac']} AC"
    return f"AC {item['ac']}"


def weapon_attack(item: dict, mods: dict, prof: int) -> dict:
    """Prefill an attack row from a book weapon: to-hit, damage with modifier, properties."""
    props = [(p if isinstance(p, str) else p.get("uid", "")).split("|")[0] for p in item.get("property") or []]
    if "F" in props:
        ab = max(("str", "dex"), key=lambda a: mods[a])
    elif item.get("type") == "R":
        ab = "dex"
    else:
        ab = "str"
    mod = mods[ab]
    dmg_type = {"S": "slashing", "P": "piercing", "B": "bludgeoning"}.get(item.get("dmgType", ""), "")
    damage = f"{item['dmg1']}{mod:+d} {dmg_type}".strip() if item.get("dmg1") else ""
    names = {"V": "versatile", "F": "finesse", "L": "light", "H": "heavy", "T": "thrown", "2H": "two-handed",
             "R": "reach", "A": "ammunition", "LD": "loading", "S": "special"}
    notes = ", ".join(names.get(p, p) for p in props)
    if item.get("range"):
        notes = f"range {item['range']}" + (f", {notes}" if notes else "")
    if item.get("dmg2"):
        notes += f" ({item['dmg2']} two-handed)"
    return {"bonus": f"{prof + mod:+d}", "damage": damage, "notes": notes.strip()}


def prerequisite_text(prereq) -> str:
    """Feat / option prerequisites: [{"level": {...}, "ability": [{"str": 13}], "other": "..."}] -> text."""
    if not prereq:
        return ""
    bits = []
    for p in prereq if isinstance(prereq, list) else [prereq]:
        if not isinstance(p, dict):
            bits.append(str(p))
            continue
        if "level" in p:
            lv = p["level"]
            if isinstance(lv, dict):
                cls = (lv.get("class") or {}).get("name")
                sub = (lv.get("subclass") or {}).get("name")
                bits.append(f"level {lv.get('level')}" + (f" {cls}" if cls else "") + (f" ({sub})" if sub else ""))
            else:
                bits.append(f"level {lv}")
        for ab in p.get("ability", []) or []:
            bits += [f"{ABILITY_NAMES.get(k, k)} {v}" for k, v in ab.items()]
        for r in p.get("race", []) or []:
            bits.append(r.get("displayEntry") or r.get("name", ""))
        for pr in p.get("proficiency", []) or []:
            bits += [f"{v} {k} proficiency" for k, v in pr.items()]
        if p.get("spellcasting") or p.get("spellcasting2020"):
            bits.append("the ability to cast at least one spell")
        for f in p.get("feat", []) or []:
            bits.append(str(f).split("|")[0])
        if p.get("other"):
            bits.append(str(p["other"]))
        if p.get("otherSummary"):
            bits.append(str(p["otherSummary"].get("entrySummary", "")))
        if p.get("item"):
            bits += [str(x) for x in p["item"]]
        if p.get("pact"):
            bits.append(f"Pact of the {p['pact']}")
        if p.get("patron"):
            bits.append(f"{p['patron']} patron")
        if p.get("spell"):
            bits += [str(x).split("#")[0] for x in p["spell"]]
    return "; ".join(b for b in bits if b)
