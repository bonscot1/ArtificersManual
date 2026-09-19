"""Browse the enabled books: spells, classes, races, backgrounds, feats, items, conditions."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..compendium import rules
from ..templating import page

router = APIRouter(prefix="/compendium")


def _comp(request: Request):
    return request.app.state.compendium


def _get(request: Request, kind: str, key: str) -> dict:
    e = _comp(request).get(kind, key)
    if not e:
        raise HTTPException(404, "Not in your enabled books")
    return e


@router.get("")
async def hub(request: Request, q: str = ""):
    comp = _comp(request)
    q = q.strip()
    hits = []
    if q:
        ql = q.lower()
        for kind in ("spell", "race", "class", "background", "feat", "item", "condition", "optionalfeature"):
            for e in comp.store(kind).values():
                if ql in e["name"].lower():
                    hits.append((kind, e))
        hits.sort(key=lambda h: (not h[1]["name"].lower().startswith(ql), h[1]["name"]))
    counts = {kind: len(comp.store(kind)) for kind in
              ("spell", "race", "class", "background", "feat", "item", "condition")}
    return page(request, "compendium/hub.html", q=q, hits=hits[:80], counts=counts)


@router.get("/spells")
async def spells(request: Request, q: str = "", level: str = "", cls: str = "", school: str = ""):
    comp = _comp(request)
    lvl = int(level) if level.isdigit() else None
    results = comp.search_spells(q, lvl, cls if cls in comp.classes else "", limit=1000)
    if school:
        results = [s for s in results if s.get("school") == school]
    return page(request, "compendium/spells.html", results=results, q=q, level=level, cls=cls,
                school=school, class_options=comp.class_options())


@router.get("/spells/{key}")
async def spell(request: Request, key: str):
    sp = _get(request, "spell", key)
    comp = _comp(request)
    casters = sorted(comp.classes[k]["name"] for k in sp["_classes"])
    sub_casters = sorted(f"{comp.classes[ck]['name']} ({comp.subclasses[ck][sk]['name']})"
                         for ck, sk in sp["_subclasses"])
    return page(request, "compendium/spell.html", sp=sp, casters=casters, sub_casters=sub_casters)


@router.get("/classes")
async def classes(request: Request):
    comp = _comp(request)
    return page(request, "compendium/classes.html", classes=sorted(comp.classes.values(), key=lambda c: c["name"]))


@router.get("/classes/{key}")
async def class_detail(request: Request, key: str, sub: str = ""):
    comp = _comp(request)
    cls = _get(request, "class", key)
    subs = comp.subclass_options(key)
    sub_entry = comp.subclasses.get(key, {}).get(sub)
    features = comp.features_for(key, sub if sub_entry else "", 20)
    by_level: dict[int, list] = {}
    for f in features:
        by_level.setdefault(f.level, []).append(f)
    return page(request, "compendium/class.html", cls=cls, key=key, subs=subs, sub=sub, sub_entry=sub_entry,
                by_level=by_level, slots=[rules.spell_slots(cls, sub_entry, lvl) for lvl in range(1, 21)],
                pact=[rules.pact_slots(cls, lvl) for lvl in range(1, 21)])


@router.get("/races")
async def races(request: Request):
    comp = _comp(request)
    return page(request, "compendium/races.html", options=comp.race_options())


@router.get("/races/{key}")
async def race_detail(request: Request, key: str, sub: str = ""):
    comp = _comp(request)
    _get(request, "race", key)
    race = comp.merged_race(key, sub)
    variants = [o for o in comp.race_options() if o.race_key == key]
    return page(request, "compendium/race.html", race=race, key=key, sub=sub, variants=variants)


@router.get("/backgrounds")
async def backgrounds(request: Request):
    comp = _comp(request)
    return page(request, "compendium/list.html", title="Backgrounds", kind="background",
                items=sorted(comp.backgrounds.values(), key=lambda b: b["name"]))


@router.get("/backgrounds/{key}")
async def background(request: Request, key: str):
    return page(request, "compendium/entry.html", title="Background", kind="background", e=_get(request, "background", key))


@router.get("/feats")
async def feats(request: Request):
    comp = _comp(request)
    return page(request, "compendium/list.html", title="Feats", kind="feat",
                items=sorted(comp.feats.values(), key=lambda f: f["name"]))


@router.get("/feats/{key}")
async def feat(request: Request, key: str):
    return page(request, "compendium/entry.html", title="Feat", kind="feat", e=_get(request, "feat", key))


@router.get("/optional-features/{key}")
async def optional_feature(request: Request, key: str):
    return page(request, "compendium/entry.html", title="Option", kind=None, e=_get(request, "optionalfeature", key))


@router.get("/items")
async def items(request: Request, q: str = "", kind: str = ""):
    comp = _comp(request)
    ql = q.strip().lower()
    results = []
    for it in comp.items.values():
        if ql and ql not in it["name"].lower():
            continue
        if kind == "weapon" and not it.get("weapon"):
            continue
        if kind == "armor" and not it.get("armor"):
            continue
        results.append(it)
    results.sort(key=lambda i: i["name"])
    return page(request, "compendium/items.html", results=results[:300], q=q, kind=kind)


@router.get("/items/{key}")
async def item(request: Request, key: str):
    return page(request, "compendium/item.html", it=_get(request, "item", key))


@router.get("/conditions")
async def conditions(request: Request):
    comp = _comp(request)
    return page(request, "compendium/conditions.html",
                conditions=sorted(comp.conditions.values(), key=lambda c: c["name"]))


@router.get("/conditions/{key}")
async def condition(request: Request, key: str):
    return page(request, "compendium/entry.html", title="Condition", kind=None, e=_get(request, "condition", key))
