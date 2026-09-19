"""The arithmetic of a 5e character sheet: modifiers, proficiency, spell slots."""
from __future__ import annotations

import re

ABILITIES = ["str", "dex", "con", "int", "wis", "cha"]
ABILITY_NAMES = {
    "str": "Strength", "dex": "Dexterity", "con": "Constitution",
    "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma",
}

# (display name, governing ability)
SKILLS = [
    ("Acrobatics", "dex"), ("Animal Handling", "wis"), ("Arcana", "int"),
    ("Athletics", "str"), ("Deception", "cha"), ("History", "int"),
    ("Insight", "wis"), ("Intimidation", "cha"), ("Investigation", "int"),
    ("Medicine", "wis"), ("Nature", "int"), ("Perception", "wis"),
    ("Performance", "cha"), ("Persuasion", "cha"), ("Religion", "int"),
    ("Sleight of Hand", "dex"), ("Stealth", "dex"), ("Survival", "wis"),
]
SKILL_ABILITY = {name: ab for name, ab in SKILLS}

SCHOOLS = {
    "A": "Abjuration", "C": "Conjuration", "D": "Divination", "E": "Enchantment",
    "V": "Evocation", "I": "Illusion", "N": "Necromancy", "T": "Transmutation",
    "P": "Psionic",
}

ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th", 7: "7th", 8: "8th", 9: "9th"}

SIZES = {"T": "Tiny", "S": "Small", "M": "Medium", "L": "Large", "H": "Huge", "G": "Gargantuan"}


def ability_mod(score: int) -> int:
    return (int(score) - 10) // 2


def fmt_mod(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


def proficiency_bonus(level: int) -> int:
    return 2 + (max(1, min(20, int(level))) - 1) // 4


def ordinal(n: int) -> str:
    return ORDINALS.get(n, f"{n}th")


def average_hit_die(faces: int) -> int:
    return faces // 2 + 1


def default_max_hp(faces: int, level: int, con_mod: int) -> int:
    """Max die at level 1, the book's fixed average after that."""
    level = max(1, level)
    return faces + con_mod + (level - 1) * (average_hit_die(faces) + con_mod)


_FORMULA_TOKEN = re.compile(r"<\$(\w+)\$>")


def eval_prepared_formula(formula: str, level: int, mods: dict[str, int]) -> int:
    """5etools writes prepared-spell counts as e.g. '<$level$> / 2 + <$int_mod$>'.

    Division rounds down (the books always say 'minimum of one spell').
    """
    def sub(m: re.Match) -> str:
        tok = m.group(1)
        if tok == "level":
            return str(level)
        if tok.endswith("_mod"):
            return str(mods.get(tok[:-4], 0))
        raise ValueError(f"unknown token {tok}")

    expr = _FORMULA_TOKEN.sub(sub, formula)
    tokens = re.findall(r"-?\d+|[+\-*/()]", expr)
    if "".join(tokens).replace(" ", "") != expr.replace(" ", ""):
        raise ValueError(f"unsupported formula: {formula}")
    return max(1, _eval_tokens(tokens))


def _eval_tokens(tokens: list[str]) -> int:
    """Tiny left-to-right evaluator with * and / binding tighter than + and -."""
    pos = 0

    def parse_expr() -> int:
        nonlocal pos
        value = parse_term()
        while pos < len(tokens) and tokens[pos] in "+-":
            op = tokens[pos]; pos += 1
            rhs = parse_term()
            value = value + rhs if op == "+" else value - rhs
        return value

    def parse_term() -> int:
        nonlocal pos
        value = parse_atom()
        while pos < len(tokens) and tokens[pos] in "*/":
            op = tokens[pos]; pos += 1
            rhs = parse_atom()
            value = value * rhs if op == "*" else value // rhs
        return value

    def parse_atom() -> int:
        nonlocal pos
        tok = tokens[pos]; pos += 1
        if tok == "(":
            value = parse_expr()
            pos += 1  # ')'
            return value
        return int(tok)

    return parse_expr()


def strip_tags(text: str) -> str:
    """'{@filter 1st|spells|level=1}' -> '1st'. Good enough for table cells."""
    out = str(text)
    while "{@" in out:
        start = out.index("{@")
        depth = 0
        for i in range(start, len(out)):
            if out[i] == "{":
                depth += 1
            elif out[i] == "}":
                depth -= 1
                if depth == 0:
                    body = out[start + 2:i]
                    _, _, rest = body.partition(" ")
                    out = out[:start] + rest.split("|")[0] + out[i + 1:]
                    break
        else:
            break
    return out


def slot_rows(class_entry: dict, subclass_entry: dict | None) -> list[list[int]] | None:
    groups = list(class_entry.get("classTableGroups") or [])
    if subclass_entry:
        groups += list(subclass_entry.get("subclassTableGroups") or [])
    for g in groups:
        if "rowsSpellProgression" in g:
            return g["rowsSpellProgression"]
    return None


def spell_slots(class_entry: dict, subclass_entry: dict | None, level: int) -> list[int]:
    """Slots per spell level 1..9 at this class level (empty list = not a slot caster)."""
    rows = slot_rows(class_entry, subclass_entry)
    if not rows:
        return []
    row = list(rows[max(1, min(20, level)) - 1])
    return (row + [0] * 9)[:9]


def pact_slots(class_entry: dict, level: int) -> tuple[int, int] | None:
    """Warlock-style (count, slot level), or None."""
    if class_entry.get("casterProgression") != "pact":
        return None
    for g in class_entry.get("classTableGroups") or []:
        labels = [strip_tags(x) for x in g.get("colLabels", [])]
        if "Spell Slots" in labels and "Slot Level" in labels:
            row = g["rows"][max(1, min(20, level)) - 1]
            count = int(row[labels.index("Spell Slots")])
            slot = strip_tags(row[labels.index("Slot Level")])
            return count, int(re.sub(r"\D", "", slot) or 0)
    return None


def progression_at(entry: dict | None, key: str, level: int) -> int | None:
    if not entry:
        return None
    prog = entry.get(key)
    if not prog:
        return None
    return int(prog[max(1, min(20, level)) - 1])
