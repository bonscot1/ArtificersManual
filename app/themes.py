"""Colour themes: one per class, plus hand-made ones for particular characters.

A theme only swaps the accent colours and the background tint; layout and type stay
the same. Values are CSS custom properties the stylesheet already uses: `red` is the
primary accent (titles, buttons), `red2` its bright form, `gold` the secondary accent
(links, dice, modifiers), then the three background steps, the line colour and a glow
for the top of the page.
"""
from __future__ import annotations

from markupsafe import Markup

THEMES: dict[str, dict[str, str]] = {
    "default":   dict(name="Default (ember)", red="#c0392b", red2="#e0523f", gold="#d3a955",
                      bg="#16130f", bg2="#201b15", bg3="#2a241c", line="#3d342a", glow="#241a12"),
    "artificer": dict(name="Artificer - copper and brass", red="#b87333", red2="#d18a45", gold="#7fd1d1",
                      bg="#151311", bg2="#1f1b17", bg3="#2a241e", line="#3e352a", glow="#2a1c12"),
    "barbarian": dict(name="Barbarian - blood and rust", red="#b3312a", red2="#d64a3f", gold="#d98b3a",
                      bg="#171210", bg2="#211915", bg3="#2c211c", line="#43302a", glow="#33150f"),
    "bard":      dict(name="Bard - plum and gilt", red="#b5387a", red2="#d4569a", gold="#e0b25a",
                      bg="#17121a", bg2="#211a26", bg3="#2c2333", line="#43334a", glow="#2f1530"),
    "cleric":    dict(name="Cleric - radiant gold", red="#b8922e", red2="#dbb045", gold="#f2e2b0",
                      bg="#16140f", bg2="#201d15", bg3="#2b271c", line="#433c2a", glow="#332812"),
    "druid":     dict(name="Druid - moss and bark", red="#4f8a3d", red2="#66a54c", gold="#c49a5a",
                      bg="#101510", bg2="#171e17", bg3="#1f281f", line="#2f3f2f", glow="#142915"),
    "fighter":   dict(name="Fighter - steel", red="#7b8794", red2="#97a3b0", gold="#d3a955",
                      bg="#131416", bg2="#1b1d20", bg3="#25282c", line="#3a3f45", glow="#222831"),
    "monk":      dict(name="Monk - saffron and jade", red="#d9822b", red2="#f0993f", gold="#7fb069",
                      bg="#171310", bg2="#211b15", bg3="#2c241c", line="#43362a", glow="#331d0e"),
    "paladin":   dict(name="Paladin - silver and gold", red="#b9b4a6", red2="#d9d3c3", gold="#e0c060",
                      bg="#141518", bg2="#1c1d21", bg3="#26272c", line="#3c3e45", glow="#292a33"),
    "ranger":    dict(name="Ranger - forest and leather", red="#3f7d4a", red2="#55a061", gold="#a67c52",
                      bg="#0f140f", bg2="#161d16", bg3="#1e271e", line="#2e3d2e", glow="#132a1a"),
    "rogue":     dict(name="Rogue - shadow and venom", red="#5a6570", red2="#7a8794", gold="#9ccf5a",
                      bg="#111214", bg2="#181a1d", bg3="#212429", line="#353a41", glow="#1a2126"),
    "sorcerer":  dict(name="Sorcerer - wildfire", red="#d4432a", red2="#ee5a3e", gold="#f0b429",
                      bg="#171110", bg2="#211816", bg3="#2c201d", line="#45302a", glow="#36130f"),
    "warlock":   dict(name="Warlock - eldritch", red="#6f3fb0", red2="#8a5ad0", gold="#58c88a",
                      bg="#120f17", bg2="#1a1622", bg3="#241e2e", line="#382f47", glow="#221338"),
    "wizard":    dict(name="Wizard - arcane blue", red="#4a6fd6", red2="#6688e8", gold="#b48ef0",
                      bg="#0f1118", bg2="#161923", bg3="#1f232f", line="#303748", glow="#151e3d"),
    # hand-made for the table
    "iron":      dict(name="Iron - brass, leather and the sapphire core", red="#b8862e", red2="#d9a441",
                      gold="#3d8de8", bg="#131311", bg2="#1c1b16", bg3="#26241c", line="#3f3a2b", glow="#1a2440"),
    "lorbah":    dict(name="Lor' B'ah - Silverdeep stone", red="#9c3e30", red2="#c4503f", gold="#b9c4cf",
                      bg="#14161a", bg2="#1b1e23", bg3="#262a30", line="#3a3f47", glow="#2a2f36"),
}


def theme_key(character, class_entry: dict | None) -> str:
    """The character's chosen theme, else the class's, else the default."""
    chosen = getattr(character, "theme", "") or ""
    if chosen in THEMES:
        return chosen
    if class_entry:
        slug = class_entry["name"].lower()
        if slug in THEMES:
            return slug
    return "default"


def theme_style(key: str) -> Markup:
    """Inline CSS custom properties for a `style=` attribute."""
    t = THEMES.get(key, THEMES["default"])
    return Markup("; ".join([
        f"--red: {t['red']}", f"--red-2: {t['red2']}", f"--gold: {t['gold']}", f"--bg: {t['bg']}",
        f"--bg-2: {t['bg2']}", f"--bg-3: {t['bg3']}", f"--line: {t['line']}", f"--glow: {t['glow']}",
    ]))


def theme_choices() -> list[tuple[str, str]]:
    return [("", "Auto (by class)")] + [(k, t["name"]) for k, t in THEMES.items()]
