"""[[Name]] in DM text -> a link that opens the compendium entry in place.

`[[Potion of Healing]]` finds the entry by name across items, spells, conditions, feats and
the rest; `[[Bless|spell]]` pins the kind. Unknown names stay as plain text.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from markupsafe import Markup, escape

from .loader import KIND_PATHS, entity_url, key

LINK = re.compile(r"\[\[([^\]|]+?)(?:\|([a-z]+))?\]\]")
KIND_ORDER = ("item", "spell", "condition", "feat", "optionalfeature", "race", "class", "background")


def find_any(comp, name: str, kind: str | None = None):
    kinds = [kind] if kind in KIND_ORDER else KIND_ORDER
    for k in kinds:
        e = comp.find(k, name)
        if e:
            return k, e
    return None, None


def peek_url(kind: str, entity: dict) -> str:
    return f"/compendium/peek/{kind}/{quote(key(entity['name'], entity['source']), safe='')}"


def linkify(text: str, comp, target: str = "") -> Markup:
    """Escape `text`; turn [[links]] into peek links (when `target` is given) or page links."""
    out, pos = [], 0
    for m in LINK.finditer(text or ""):
        out.append(str(escape(text[pos:m.start()])))
        kind, entity = find_any(comp, m.group(1).strip(), m.group(2))
        if not entity:
            out.append(str(escape(m.group(1))))
        elif target:
            out.append(f"<a class='peek-link' href='{entity_url(kind, entity)}' hx-get='{peek_url(kind, entity)}' "
                       f"hx-target='{target}' hx-swap='innerHTML'>{escape(entity['name'])}</a>")
        else:
            out.append(f"<a class='peek-link' href='{entity_url(kind, entity)}'>{escape(entity['name'])}</a>")
        pos = m.end()
    out.append(str(escape((text or "")[pos:])))
    return Markup("".join(out))


def strip_links(text: str) -> str:
    return LINK.sub(lambda m: m.group(1), text or "")
