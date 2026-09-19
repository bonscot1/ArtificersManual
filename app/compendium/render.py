"""Turn 5etools 'entries' (nested strings/dicts with {@tag ...} markup) into HTML.

The data uses two layers of markup:
  * inline tags inside strings: "deals {@damage 2d6} fire damage to a {@creature goblin}"
  * block objects: {"type": "list", "items": [...]}, {"type": "table", ...}, named sub-entries...

Everything is escaped; only markup this module emits reaches the page.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from markupsafe import Markup, escape

if TYPE_CHECKING:
    from .loader import Compendium

# tag -> (compendium kind, default source). Rendered as a link when the target exists.
LINKED_TAGS = {
    "spell": ("spell", "PHB"),
    "item": ("item", "PHB"),
    "condition": ("condition", "PHB"),
    "race": ("race", "PHB"),
    "class": ("class", "PHB"),
    "background": ("background", "PHB"),
    "feat": ("feat", "PHB"),
    "optfeature": ("optionalfeature", "PHB"),
}

FORMAT_TAGS = {
    "b": "b", "bold": "b", "i": "i", "italic": "i", "u": "u", "underline": "u",
    "s": "s", "strike": "s", "code": "code", "sup": "sup", "sub": "sub", "kbd": "kbd",
}

ATTACK_WORDS = {
    "m": "Melee", "r": "Ranged", "w": "Weapon", "s": "Spell", "a": "Area", "p": "Power",
}

ABILITY_LONG = {
    "str": "Strength", "dex": "Dexterity", "con": "Constitution",
    "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma",
}

# tags rendered as their display text with a third pipe segment as the override
THIRD_SEGMENT_DISPLAY = {"creature", "deity", "monster"}


def split_pipe(text: str) -> list[str]:
    """Split on '|' but not inside nested {...}."""
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


class Renderer:
    def __init__(self, compendium: "Compendium | None" = None,
                 link_for: Callable[[str, dict], str] | None = None):
        self.c = compendium
        self.link_for = link_for

    # ------------------------------------------------------------------ blocks
    def render(self, entries, depth: int = 0) -> Markup:
        if entries is None:
            return Markup("")
        if isinstance(entries, (str, int, float)):
            return Markup(f"<p>{self.inline(str(entries))}</p>")
        if isinstance(entries, dict):
            return self.block(entries, depth)
        return Markup("".join(self.render(e, depth) for e in entries))

    def block(self, e: dict, depth: int = 0) -> Markup:
        t = e.get("type", "entries")
        handler = getattr(self, f"_b_{t}", None)
        if handler:
            return Markup(handler(e, depth))
        if t in ("section", "inset", "insetReadaloud", "variant", "variantSub", "inline",
                 "inlineBlock", "options", "wrapper", "homebrew", "flowchart", "flowBlock",
                 "quote", "item", "itemSub", "itemSpell"):
            return Markup(self._b_entries(e, depth))
        if t == "hr":
            return Markup("<hr>")
        if t in ("image", "gallery", "statblock", "statblockInline", "ingredient", "recipe",
                 "spellcasting"):
            return Markup("")
        if "entries" in e or "entry" in e or "items" in e:
            return Markup(self._b_entries(e, depth))
        return Markup("")

    def _b_entries(self, e: dict, depth: int) -> str:
        t = e.get("type", "entries")
        cls = {"inset": "inset", "insetReadaloud": "inset readaloud", "quote": "quote",
               "variant": "inset variant", "variantSub": "inset variant"}.get(t, "ent")
        name = e.get("name")
        inner = ""
        if "entries" in e:
            inner = self.render(e["entries"], depth + 1)
        elif "entry" in e:
            inner = self.render(e["entry"], depth + 1)
        elif "items" in e:
            inner = self.render(e["items"], depth + 1)
        head = ""
        if name:
            if t == "section" or (depth == 0 and t == "inset"):
                head = f"<h4 class='ent-name'>{self.inline(str(name))}</h4>"
            else:
                head = f"<b class='ent-name'>{self.inline(str(name))}</b>"
        if t == "quote":
            by = e.get("by")
            tail = f"<footer>&mdash; {self.inline(str(by))}</footer>" if by else ""
            return f"<blockquote class='quote'>{inner}{tail}</blockquote>"
        return f"<div class='{cls}'>{head}{inner}</div>"

    def _b_list(self, e: dict, depth: int) -> str:
        style = e.get("style", "")
        tag = "ol" if "decimal" in style or "roman" in style else "ul"
        classes = " ".join(["ent-list"] + style.split())
        items = []
        for it in e.get("items", []):
            if isinstance(it, dict):
                it_type = it.get("type", "item")
                if it_type in ("item", "itemSub", "itemSpell"):
                    name = it.get("name", "")
                    body = self.render(it.get("entries", it.get("entry", "")), depth + 1)
                    head = f"<b class='ent-name'>{self.inline(str(name))}</b> " if name else ""
                    items.append(f"<li>{head}{body}</li>")
                else:
                    items.append(f"<li>{self.block(it, depth + 1)}</li>")
            else:
                items.append(f"<li>{self.inline(str(it))}</li>")
        return f"<{tag} class='{classes}'>{''.join(items)}</{tag}>"

    def _b_table(self, e: dict, depth: int) -> str:
        out = ["<table class='ent-table'>"]
        if e.get("caption"):
            out.append(f"<caption>{self.inline(str(e['caption']))}</caption>")
        if e.get("colLabels"):
            heads = "".join(f"<th>{self.inline(str(l))}</th>" for l in e["colLabels"])
            out.append(f"<thead><tr>{heads}</tr></thead>")
        out.append("<tbody>")
        for row in e.get("rows", []):
            if isinstance(row, dict):
                row = row.get("row", [])
            cells = []
            for cell in row:
                if isinstance(cell, dict):
                    if cell.get("type") == "cell":
                        roll = cell.get("roll")
                        if roll:
                            if "exact" in roll:
                                cells.append(str(roll["exact"]))
                            else:
                                cells.append(f"{roll.get('min', '')}&ndash;{roll.get('max', '')}")
                        else:
                            cells.append(self.render(cell.get("entry", ""), depth + 1))
                    else:
                        cells.append(self.block(cell, depth + 1))
                else:
                    cells.append(self.inline(str(cell)))
            out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        out.append("</tbody></table>")
        return "".join(out)

    def _b_abilityDc(self, e: dict, depth: int) -> str:
        abil = " or ".join(ABILITY_LONG.get(a, a) for a in e.get("attributes", []))
        return (f"<p class='ent-formula'><b>{escape(e.get('name', ''))} save DC</b> = 8 + your proficiency bonus + "
                f"your {escape(abil)} modifier</p>")

    def _b_abilityAttackMod(self, e: dict, depth: int) -> str:
        abil = " or ".join(ABILITY_LONG.get(a, a) for a in e.get("attributes", []))
        return (f"<p class='ent-formula'><b>{escape(e.get('name', ''))} attack modifier</b> = your proficiency bonus + "
                f"your {escape(abil)} modifier</p>")

    def _b_abilityGeneric(self, e: dict, depth: int) -> str:
        abil = " or ".join(ABILITY_LONG.get(a, a) for a in e.get("attributes", []))
        name = f"<b>{escape(e['name'])}</b> = " if e.get("name") else ""
        tail = f" {escape(abil)} modifier" if abil else ""
        return f"<p class='ent-formula'>{name}{self.inline(str(e.get('text', '')))}{tail}</p>"

    def _b_bonus(self, e: dict, depth: int) -> str:
        return f"<span>+{escape(str(e.get('value', '')))}</span>"

    def _b_bonusSpeed(self, e: dict, depth: int) -> str:
        return f"<span>+{escape(str(e.get('value', '')))} ft.</span>"

    def _b_dice(self, e: dict, depth: int) -> str:
        parts = []
        for r in e.get("toRoll", []):
            s = f"{r.get('number', 1)}d{r.get('faces', 6)}"
            if r.get("modifier"):
                s += f"{r['modifier']:+d}"
            parts.append(s)
        return f"<span class='dice'>{escape(' + '.join(parts))}</span>"

    def _b_link(self, e: dict, depth: int) -> str:
        href = e.get("href", {})
        url = href.get("url", "") if isinstance(href, dict) else ""
        text = e.get("text", url)
        if url.startswith(("http://", "https://")):
            return f"<a href='{escape(url)}' target='_blank' rel='noopener'>{self.inline(str(text))}</a>"
        return self.inline(str(text))

    def _b_refClassFeature(self, e: dict, depth: int) -> str:
        ref = e.get("classFeature", "")
        feat = self.c.resolve_class_feature(ref) if self.c else None
        return self._ref_block(ref, feat, depth)

    def _b_refSubclassFeature(self, e: dict, depth: int) -> str:
        ref = e.get("subclassFeature", "")
        feat = self.c.resolve_subclass_feature(ref) if self.c else None
        return self._ref_block(ref, feat, depth)

    def _ref_block(self, ref: str, feat: dict | None, depth: int) -> str:
        if not feat:
            name = split_pipe(ref)[0]
            return (f"<div class='ent'><b class='ent-name'>{escape(name)}</b>"
                    f"<p class='muted'>(not in your enabled books)</p></div>")
        body = self.render(feat.get("entries", []), depth + 1)
        return f"<div class='ent ref'><b class='ent-name'>{escape(feat['name'])}</b>{body}</div>"

    def _b_refOptionalfeature(self, e: dict, depth: int) -> str:
        ref = e.get("optionalfeature", "")
        feat = self.c.resolve_optional_feature(ref) if self.c else None
        name = split_pipe(ref)[0]
        if not feat:   # an option from a book that isn't enabled: leave it out entirely
            return ""
        body = self.render(feat.get("entries", []), depth + 1)
        src = ""
        if feat.get("source") not in (None, "PHB"):
            src = f" <small class='src'>{escape(feat.get('source', ''))}</small>"
        return f"<details class='optf'><summary>{escape(feat['name'])}{src}</summary>{body}</details>"

    # ------------------------------------------------------------------ inline
    def inline(self, s: str) -> str:
        out, i, n = [], 0, len(s)
        while i < n:
            j = s.find("{@", i)
            if j < 0:
                out.append(str(escape(s[i:])))
                break
            out.append(str(escape(s[i:j])))
            depth, k = 0, j
            while k < n:
                if s[k] == "{":
                    depth += 1
                elif s[k] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            if k >= n:  # unbalanced: show literally
                out.append(str(escape(s[j:])))
                break
            body = s[j + 2:k]
            tag, _, rest = body.partition(" ")
            out.append(self.tag(tag, rest))
            i = k + 1
        return "".join(out)

    def tag(self, tag: str, rest: str) -> str:
        parts = split_pipe(rest)
        text = parts[0]
        if tag in FORMAT_TAGS:
            html_tag = FORMAT_TAGS[tag]
            return f"<{html_tag}>{self.inline(text)}</{html_tag}>"
        if tag == "note":
            return f"<i class='note'>{self.inline(text)}</i>"
        if tag in ("dice", "damage", "d20", "autodice"):
            shown = parts[1] if len(parts) > 1 and parts[1] else text
            return f"<span class='dice'>{self.inline(shown)}</span>"
        if tag in ("scaledice", "scaledamage"):
            shown = parts[2] if len(parts) > 2 else text
            return f"<span class='dice'>{self.inline(shown)}</span>"
        if tag == "hit":
            n = text.strip()
            sign = "" if n.startswith(("-", "+")) else "+"
            return f"<span class='dice'>{sign}{escape(n)}</span>"
        if tag == "dc":
            return f"DC {escape(text.strip())}"
        if tag == "chance":
            return f"{escape(text.strip())}%"
        if tag == "recharge":
            n = text.strip() or "6"
            span = "" if n == "6" else "&ndash;6"
            return f"(Recharge {escape(n)}{span})"
        if tag == "h":
            return "<i>Hit:</i> "
        if tag == "m":
            return "<i>Miss:</i> "
        if tag in ("atk", "atkr"):
            words = []
            for code in text.split(","):
                code = code.strip()
                words.append(" ".join(ATTACK_WORDS.get(ch, ch) for ch in code) + " Attack")
            return f"<i>{escape(' or '.join(words))}:</i>"
        if tag in ("hitYourSpellAttack", "spellAttack"):
            return "your spell attack modifier"
        if tag == "actSave":
            return f"<i>{escape(ABILITY_LONG.get(text.strip(), text))} Saving Throw:</i>"
        if tag == "actSaveFail":
            return "<i>Failure:</i>"
        if tag == "actSaveSuccess":
            return "<i>Success:</i>"
        if tag == "actSaveFailBy":
            return f"<i>Failure by {escape(text)} or More:</i>"
        if tag == "actTrigger":
            return "<i>Trigger:</i>"
        if tag == "actResponse":
            return "<i>Response:</i>"
        if tag == "ability":
            bits = text.split()
            if len(bits) >= 2 and bits[1].lstrip("-").isdigit():
                score = int(bits[1])
                mod = (score - 10) // 2
                return f"{score} ({'+' if mod >= 0 else ''}{mod})"
            return str(escape(text))
        if tag in ("savingThrow", "skillCheck"):
            bits = text.split()
            return str(escape(bits[-1])) if bits else ""
        if tag == "link":
            url = parts[1] if len(parts) > 1 else ""
            if url.startswith(("http://", "https://")):
                return f"<a href='{escape(url)}' target='_blank' rel='noopener'>{self.inline(text)}</a>"
            return self.inline(text)
        if tag in ("footnote", "tip", "homebrew", "unit", "style", "font", "color", "highlight"):
            return self.inline(text)
        if tag in LINKED_TAGS:
            kind, default_src = LINKED_TAGS[tag]
            source = parts[1] if len(parts) > 1 and parts[1] else default_src
            shown = parts[2] if len(parts) > 2 and parts[2] else text
            target = self.c.find(kind, text, source) if self.c else None
            if target and self.link_for:
                href = self.link_for(kind, target)
                return f"<a class='tag tag-{kind}' href='{escape(href)}'>{self.inline(shown)}</a>"
            return f"<span class='tag tag-{kind}'>{self.inline(shown)}</span>"
        if tag in THIRD_SEGMENT_DISPLAY:
            shown = parts[2] if len(parts) > 2 and parts[2] else text
            return f"<span class='tag tag-{escape(tag)}'>{self.inline(shown)}</span>"
        if tag in ("classFeature", "subclassFeature"):
            # "Name|Class|ClassSource|Level|Source|Display" - the display text is the
            # optional last segment and never numeric
            shown = text
            if len(parts) >= 2 and not parts[-1].strip().isdigit() and parts[-1] and len(parts) > 4:
                shown = parts[-1]
            return f"<span class='tag'>{self.inline(shown)}</span>"
        # every other tag: the first segment is the text to show
        return f"<span class='tag tag-{escape(tag)}'>{self.inline(text)}</span>"


def plain_text(entries) -> str:
    """Flatten entries to text for search snippets."""
    from .rules import strip_tags
    if entries is None:
        return ""
    if isinstance(entries, (str, int, float)):
        return strip_tags(str(entries))
    if isinstance(entries, dict):
        bits = []
        if entries.get("name"):
            bits.append(str(entries["name"]))
        for k in ("entries", "entry", "items"):
            if k in entries:
                bits.append(plain_text(entries[k]))
        return " ".join(bits)
    return " ".join(plain_text(e) for e in entries)
