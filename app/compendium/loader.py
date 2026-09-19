"""Load the 5etools JSON into memory and answer the questions a character sheet asks.

Only entries from the enabled `sources` (settings.json) are exposed, so a PHB-only
table never sees Tasha's subclasses. Everything is keyed "Name|SOURCE".
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .render import split_pipe

KIND_PATHS = {
    "spell": "spells", "item": "items", "condition": "conditions", "race": "races",
    "class": "classes", "background": "backgrounds", "feat": "feats",
    "optionalfeature": "optional-features",
}

# the 2024 rules: never loaded, even for items
SOURCES_2024 = {"XPHB", "XDMG", "XMM", "XSCREEN"}

# subrace keys that never merge into the race
_SUBRACE_SKIP = {
    "raceName", "raceSource", "name", "source", "page", "srd", "basicRules", "reprintedAs",
    "hasFluff", "hasFluffImages", "overwrite", "_versions", "otherSources", "alias", "srd52",
    "basicRules2024",
}


def key(name: str, source: str) -> str:
    return f"{name}|{source}"


def entity_url(kind: str, entity: dict) -> str:
    return f"/compendium/{KIND_PATHS[kind]}/{quote(key(entity['name'], entity['source']), safe='')}"


def wikidot_slug(name: str) -> str:
    name = str(name).split(";")[0]                      # "Strike of the Giants; Hill" -> the feat page
    name = re.sub(r"\(.*?\)", "", name)                # "Variant Criminal (Spy)" -> the base page
    name = re.sub(r"^variant\s+", "", name.strip(), flags=re.I)
    name = name.lower().replace("'", "").replace("’", "")
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name)).strip("-")


def wikidot_url(kind: str, entity: dict, class_entity: dict | None = None) -> str | None:
    """The matching dnd5e.wikidot.com page, for the details the sheet doesn't show."""
    base = "https://dnd5e.wikidot.com/"
    if kind == "spell":
        return base + "spell:" + wikidot_slug(entity["name"])
    if kind == "race":
        return base + "lineage:" + wikidot_slug(entity["name"])
    if kind == "class":
        return base + wikidot_slug(entity["name"])
    if kind == "subclass" and class_entity:
        return base + wikidot_slug(class_entity["name"]) + ":" + wikidot_slug(entity.get("shortName") or entity["name"])
    if kind == "feat":
        return base + "feat:" + wikidot_slug(entity["name"])
    if kind == "background":
        return base + "background:" + wikidot_slug(entity["name"])
    return None


def reprint_targets(entity: dict) -> list[tuple[str, str]]:
    """(name, source) of every later printing this entry was replaced by."""
    out = []
    for r in entity.get("reprintedAs") or []:
        uid = r.get("uid", "") if isinstance(r, dict) else str(r)
        parts = split_pipe(uid)
        if parts and parts[0]:
            out.append((parts[0], parts[-1] if len(parts) > 1 and parts[-1] else "PHB"))
    return out


def norm_name(name: str) -> str:
    """Lookup key: case and apostrophes don't matter ("Tinkers Tools" finds "Tinker's Tools")."""
    return str(name).strip().lower().replace("’", "").replace("'", "")


def _as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


# --------------------------------------------------------------------- _copy / _mod
def _name_of(item) -> str:
    return item.get("name", "") if isinstance(item, dict) else str(item)


def _find_index(arr: list, target) -> int | None:
    if isinstance(target, dict):
        if "index" in target:
            return int(target["index"]) if 0 <= int(target["index"]) < len(arr) else None
        if "regex" in target:
            pat = re.compile(target["regex"], re.I if "i" in target.get("flags", "") else 0)
            for i, it in enumerate(arr):
                if pat.search(_name_of(it)):
                    return i
        return None
    for i, it in enumerate(arr):
        if _name_of(it) == target or it == target:
            return i
    return None


def _replace_txt(node, pattern: re.Pattern, repl: str):
    if isinstance(node, str):
        return pattern.sub(repl, node)
    if isinstance(node, list):
        return [_replace_txt(x, pattern, repl) for x in node]
    if isinstance(node, dict):
        return {k: (_replace_txt(v, pattern, repl) if k != "type" else v) for k, v in node.items()}
    return node


def _apply_op(target: dict, prop: str, op) -> None:
    if op == "remove":
        target.pop(prop, None)
        return
    if not isinstance(op, dict):
        return
    mode = op.get("mode")
    items = copy.deepcopy(_as_list(op.get("items")))
    arr = _as_list(target.get(prop))
    if mode == "appendArr":
        target[prop] = arr + items
    elif mode == "prependArr":
        target[prop] = items + arr
    elif mode == "insertArr":
        idx = int(op.get("index", len(arr)))
        arr[idx:idx] = items
        target[prop] = arr
    elif mode == "replaceArr":
        idx = _find_index(arr, op.get("replace"))
        if idx is not None:
            arr[idx:idx + 1] = items
        target[prop] = arr
    elif mode == "removeArr":
        names = _as_list(op.get("names")) + _as_list(op.get("items"))
        target[prop] = [x for x in arr if not any(_find_index([x], n) == 0 for n in names)]
    elif mode == "appendIfNotExistsArr":
        for it in items:
            if _find_index(arr, _name_of(it) if isinstance(it, dict) else it) is None:
                arr.append(it)
        target[prop] = arr
    elif mode == "renameArr":
        for r in op.get("renames", []):
            for it in arr:
                if isinstance(it, dict) and it.get("name") == r.get("rename"):
                    it["name"] = r.get("with", it["name"])
        target[prop] = arr
    elif mode == "replaceTxt":
        flags = re.I if "i" in op.get("flags", "") else 0
        pattern = re.compile(op["replace"], flags)
        target[prop] = _replace_txt(target.get(prop), pattern, op.get("with", ""))
    # other modes (setProp, scalarAddProp, addSkills...) are rare in character options; ignored


def resolve_copies(entries: list[dict], match_keys: tuple[str, ...]) -> list[dict]:
    """Expand `_copy` entries (an entry that inherits another and patches it)."""
    index = {tuple(e.get(k) for k in match_keys): e for e in entries}

    def resolve(e: dict, depth: int = 0) -> dict:
        if "_copy" not in e or depth > 6:
            return e
        spec = e["_copy"]
        base = index.get(tuple(spec.get(k, e.get(k)) for k in match_keys))
        if base is None:
            return {k: v for k, v in e.items() if k != "_copy"}
        merged = copy.deepcopy(resolve(base, depth + 1))
        for drop in ("srd", "basicRules", "reprintedAs", "otherSources", "hasFluff", "hasFluffImages"):
            merged.pop(drop, None)
        for k, v in e.items():
            if k != "_copy":
                merged[k] = copy.deepcopy(v)
        for prop, ops in (spec.get("_mod") or {}).items():
            if prop == "*":
                continue
            for op in _as_list(ops):
                _apply_op(merged, prop, op)
        return merged

    return [resolve(e) for e in entries]


def expand_versions(entries: list[dict]) -> list[dict]:
    """Add each `_versions` variant as its own entry ("Strike of the Giants; Hill")."""
    out = []
    for e in entries:
        versions = e.pop("_versions", None) if isinstance(e, dict) else None
        out.append(e)
        for v in versions or []:
            if "_template" in v or "_implementations" in v or "_abstract" in v:
                template = v.get("_template") or v.get("_abstract") or {}
                impls = v.get("_implementations") or []
            else:
                template, impls = {}, [v]
            for impl in impls:
                spec = {**template, **impl}
                variables = spec.pop("_variables", {}) or {}
                merged = copy.deepcopy(e)
                for k, val in spec.items():
                    if k not in ("_mod", "_preserve"):
                        merged[k] = copy.deepcopy(val)
                for prop, ops in (spec.get("_mod") or {}).items():
                    if prop == "*":
                        continue
                    for op in _as_list(ops):
                        _apply_op(merged, prop, _fill_variables(op, variables))
                merged["_version_of"] = e.get("name")
                out.append(merged)
    return out


def _fill_variables(node, variables: dict):
    if not variables:
        return node
    if isinstance(node, str):
        for k, v in variables.items():
            node = node.replace("{{" + k + "}}", str(v))
        return node
    if isinstance(node, list):
        return [_fill_variables(x, variables) for x in node]
    if isinstance(node, dict):
        return {k: _fill_variables(v, variables) for k, v in node.items()}
    return node


# --------------------------------------------------------------------- refs
def parse_class_ref(ref: str) -> tuple[str, str, str, int, str]:
    """'Second Wind|Fighter||1' -> (name, class, class source, level, feature source)."""
    p = split_pipe(ref) + [""] * 6
    class_source = p[2] or "PHB"
    return p[0], p[1], class_source, int(p[3] or 1), (p[4] or class_source)


def parse_subclass_ref(ref: str) -> tuple[str, str, str, str, str, int, str]:
    """'Improved Critical|Fighter||Champion||3' -> (name, class, class src, sub short, sub src, level, src)."""
    p = split_pipe(ref) + [""] * 8
    class_source = p[2] or "PHB"
    sub_source = p[4] or "PHB"
    return p[0], p[1], class_source, p[3], sub_source, int(p[5] or 1), (p[6] or sub_source)


@dataclass
class Feature:
    name: str
    level: int
    source: str
    entries: list
    kind: str            # "class" | "subclass"
    gain_subclass: bool = False


@dataclass
class RaceOption:
    label: str
    race_key: str
    subrace_key: str
    group: str

    @property
    def value(self) -> str:
        return f"{self.race_key}||{self.subrace_key}"


class Compendium:
    def __init__(self, data_dir: Path, sources: list[str]):
        self.data_dir = Path(data_dir)
        self.sources = set(sources)
        self.source_order = list(sources)
        self.races: dict[str, dict] = {}
        self.subraces: dict[str, list[dict]] = {}
        self.classes: dict[str, dict] = {}
        self.subclasses: dict[str, dict[str, dict]] = {}
        self.class_features: dict[tuple, dict] = {}
        self.subclass_features: dict[tuple, dict] = {}
        self.spells: dict[str, dict] = {}
        self.backgrounds: dict[str, dict] = {}
        self.feats: dict[str, dict] = {}
        self.optionalfeatures: dict[str, dict] = {}
        self.items: dict[str, dict] = {}
        self.conditions: dict[str, dict] = {}
        self._by_name: dict[str, dict[str, dict[str, str]]] = {}
        self._merged_race_cache: dict[tuple[str, str], dict] = {}
        self.load()

    # ---------------------------------------------------------------- loading
    def _read(self, rel: str) -> dict | None:
        path = self.data_dir / rel
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _register(self, kind: str, entity: dict, store: dict[str, dict]) -> None:
        k = key(entity["name"], entity["source"])
        store[k] = entity
        self._by_name.setdefault(kind, {}).setdefault(norm_name(entity["name"]), {})[entity["source"]] = k

    def _enabled(self, e: dict) -> bool:
        return e.get("source") in self.sources

    def load(self) -> None:
        self._load_races()
        self._load_classes()
        self._load_spells()
        for rel, kind, store, prop in (
            ("backgrounds.json", "background", self.backgrounds, "background"),
            ("feats.json", "feat", self.feats, "feat"),
            ("optionalfeatures.json", "optionalfeature", self.optionalfeatures, "optionalfeature"),
            ("conditionsdiseases.json", "condition", self.conditions, "condition"),
        ):
            data = self._read(rel)
            if not data:
                continue
            entries = resolve_copies(data.get(prop, []), ("name", "source"))
            if kind == "feat":   # "Strike of the Giants; Hill" is a pick of its own
                entries = expand_versions(entries)
            for e in entries:
                if self._enabled(e):
                    self._register(kind, e, store)
        self._load_items()
        self._drop_superseded()

    # ---------------------------------------------------------------- one printing per name
    def _superseded(self, entity: dict, *stores: dict) -> bool:
        """Replaced by a later printing that is also enabled (Volo's Goliath -> Multiverse Goliath)."""
        for name, src in reprint_targets(entity):
            if src in SOURCES_2024 or src not in self.sources or src == entity.get("source"):
                continue
            if any(key(name, src) in st for st in stores):
                return True
        return False

    def _unregister(self, kind: str, k: str, store: dict) -> None:
        e = store.pop(k, None)
        if e:
            by_src = self._by_name.get(kind, {}).get(norm_name(e["name"]), {})
            by_src.pop(e["source"], None)

    def _drop_superseded(self) -> None:
        """Keep the version the books themselves call current - what wikidot shows first."""
        for kind, store in (("race", self.races), ("class", self.classes), ("background", self.backgrounds),
                            ("feat", self.feats), ("optionalfeature", self.optionalfeatures),
                            ("spell", self.spells), ("item", self.items)):
            for k in [k for k, e in store.items() if self._superseded(e, store)]:
                self._unregister(kind, k, store)
        for rk in [rk for rk in self.subraces if rk not in self.races]:
            del self.subraces[rk]
        for rk, subs in self.subraces.items():
            self.subraces[rk] = [s for s in subs if not self._superseded(s, self.races)]
        for ck in [ck for ck in self.subclasses if ck not in self.classes]:
            del self.subclasses[ck]
        for ck, subs in self.subclasses.items():
            named = {key(sc["name"], sc["source"]): sc for sc in subs.values()}
            for sk in [sk for sk, sc in subs.items() if self._superseded(sc, named)]:
                del subs[sk]

    def _load_races(self) -> None:
        data = self._read("races.json")
        if not data:
            return
        races = resolve_copies(data.get("race", []), ("name", "source"))   # versions are in-race choices, not races
        subraces = resolve_copies(data.get("subrace", []), ("name", "source", "raceName", "raceSource"))
        for r in races:
            if self._enabled(r):
                self._register("race", r, self.races)
        for s in subraces:
            rk = key(s.get("raceName", ""), s.get("raceSource", ""))
            if self._enabled(s) and rk in self.races:
                self.subraces.setdefault(rk, []).append(s)

    def _load_classes(self) -> None:
        class_dir = self.data_dir / "class"
        if not class_dir.exists():
            return
        for path in sorted(class_dir.glob("class-*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for c in data.get("class", []):
                if self._enabled(c):
                    self._register("class", c, self.classes)
            for f in data.get("classFeature", []):
                k = (f["name"].lower(), f["className"], f["classSource"], int(f["level"]), f["source"])
                self.class_features[k] = f
            for f in data.get("subclassFeature", []):
                k = (f["name"].lower(), f["className"], f["classSource"], f["subclassShortName"],
                     f["subclassSource"], int(f["level"]), f["source"])
                self.subclass_features[k] = f
            subs = resolve_copies(data.get("subclass", []),
                                  ("name", "shortName", "source", "className", "classSource"))
            for s in subs:
                ck = key(s.get("className", ""), s.get("classSource", ""))
                if self._enabled(s) and ck in self.classes:
                    self.subclasses.setdefault(ck, {})[key(s["shortName"], s["source"])] = s

    def _load_spells(self) -> None:
        spell_dir = self.data_dir / "spells"
        if not spell_dir.exists():
            return
        for path in sorted(spell_dir.glob("spells-*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            for sp in data.get("spell", []):
                if self._enabled(sp):
                    self._register("spell", sp, self.spells)
        self.spell_norms = {re.sub(r"[^a-z0-9]", "", sp["name"].lower()) for sp in self.spells.values()}
        lookup = self._read("generated/gendata-spell-source-lookup.json") or {}
        for sp in self.spells.values():
            info = lookup.get(sp["source"].lower(), {}).get(sp["name"].lower(), {})
            classes, subclasses = set(), set()
            for csrc, names in (info.get("class") or {}).items():
                for cname in names:
                    ck = key(cname, csrc)
                    if ck in self.classes:
                        classes.add(ck)
            for csrc, by_class in (info.get("subclass") or {}).items():
                for cname, by_sub_src in by_class.items():
                    ck = key(cname, csrc)
                    if ck not in self.classes:
                        continue
                    for ssrc, subs in by_sub_src.items():
                        for short in subs:
                            sk = key(short, ssrc)
                            if sk in self.subclasses.get(ck, {}):
                                subclasses.add((ck, sk))
            sp["_classes"] = classes
            sp["_subclasses"] = subclasses

    def _item_ok(self, it: dict) -> bool:
        """Loot comes from any book the DM likes, so items ignore `sources` (bar the 2024 rules)."""
        return it.get("source") not in SOURCES_2024 and it.get("edition") != "one"

    def _load_items(self) -> None:
        base = self._read("items-base.json") or {}
        for it in base.get("baseitem", []):
            if self._item_ok(it):
                self._register("item", it, self.items)
        self.item_properties = {p["abbreviation"]: p for p in base.get("itemProperty", []) if p.get("source") == "PHB"}
        self.item_types = {t["abbreviation"]: t for t in base.get("itemType", [])}
        items = self._read("items.json") or {}
        for it in resolve_copies(items.get("item", []), ("name", "source")):
            if self._item_ok(it):
                self._register("item", it, self.items)

    # ---------------------------------------------------------------- lookups
    def store(self, kind: str) -> dict[str, dict]:
        return {
            "spell": self.spells, "item": self.items, "condition": self.conditions,
            "race": self.races, "class": self.classes, "background": self.backgrounds,
            "feat": self.feats, "optionalfeature": self.optionalfeatures,
        }[kind]

    def find(self, kind: str, name: str, source: str | None = None) -> dict | None:
        """By name (case-insensitive); exact source first, then any enabled source."""
        by_src = self._by_name.get(kind, {}).get(norm_name(name))
        if not by_src:
            return None
        store = self.store(kind)
        if source:
            for src, k in by_src.items():
                if src.lower() == source.lower():
                    return store[k]
        for src in ["PHB", "DMG", *self.source_order]:
            if src in by_src:
                return store[by_src[src]]
        return store[next(iter(by_src.values()))]

    def get(self, kind: str, k: str) -> dict | None:
        return self.store(kind).get(k)

    # ---------------------------------------------------------------- races
    def race_options(self) -> list[RaceOption]:
        counts: dict[str, int] = {}
        for r in self.races.values():
            counts[r["name"]] = counts.get(r["name"], 0) + 1
        opts: list[RaceOption] = []
        for rk, race in sorted(self.races.items(), key=lambda kv: (kv[1]["name"], kv[1]["source"])):
            group = race["name"] + (f" ({race['source']})" if counts[race["name"]] > 1 else "")
            subs = self.subraces.get(rk, [])
            named = sorted((s for s in subs if s.get("name")), key=lambda s: s["name"])
            nameless = [s for s in subs if not s.get("name")]
            if nameless or not named:
                opts.append(RaceOption(group, rk, "", group))
            for s in named:
                opts.append(RaceOption(f"{group} ({s['name']})", rk, key(s["name"], s["source"]), group))
        return opts

    def merged_race(self, race_key: str, subrace_key: str = "") -> dict | None:
        cache_key = (race_key, subrace_key or "")
        if cache_key in self._merged_race_cache:
            return self._merged_race_cache[cache_key]
        race = self.races.get(race_key)
        if not race:
            return None
        out = copy.deepcopy(race)
        subs = self.subraces.get(race_key, [])
        nameless = next((s for s in subs if not s.get("name")), None)
        if nameless:
            out = _merge_subrace(out, nameless)
        if subrace_key:
            sub = next((s for s in subs if key(s.get("name", ""), s["source"]) == subrace_key), None)
            if sub:
                out = _merge_subrace(out, sub)
                out["name"] = f"{race['name']} ({sub['name']})"
                out["subrace_source"] = sub["source"]
        self._merged_race_cache[cache_key] = out
        return out

    # ---------------------------------------------------------------- classes
    def class_options(self) -> list[tuple[str, str]]:
        counts: dict[str, int] = {}
        for c in self.classes.values():
            counts[c["name"]] = counts.get(c["name"], 0) + 1
        return [
            (c["name"] + (f" ({c['source']})" if counts[c["name"]] > 1 else ""), k)
            for k, c in sorted(self.classes.items(), key=lambda kv: (kv[1]["name"], kv[1]["source"]))
        ]

    def subclass_options(self, class_key: str) -> list[tuple[str, str]]:
        subs = self.subclasses.get(class_key, {})
        return [
            (s["name"] + (f" ({s['source']})" if s["source"] != "PHB" else ""), k)
            for k, s in sorted(subs.items(), key=lambda kv: kv[1]["name"])
        ]

    def subclass_level(self, class_key: str) -> int | None:
        c = self.classes.get(class_key)
        if not c:
            return None
        for ref in c.get("classFeatures", []):
            if isinstance(ref, dict) and ref.get("gainSubclassFeature"):
                return parse_class_ref(ref["classFeature"])[3]
        return None

    def resolve_class_feature(self, ref: str) -> dict | None:
        name, cn, cs, lvl, src = parse_class_ref(ref)
        return self.class_features.get((name.lower(), cn, cs, lvl, src))

    def resolve_subclass_feature(self, ref: str) -> dict | None:
        name, cn, cs, ss, ssrc, lvl, src = parse_subclass_ref(ref)
        return self.subclass_features.get((name.lower(), cn, cs, ss, ssrc, lvl, src))

    def resolve_optional_feature(self, ref: str) -> dict | None:
        p = split_pipe(ref)
        return self.find("optionalfeature", p[0], p[1] if len(p) > 1 and p[1] else "PHB")

    def features_for(self, class_key: str, subclass_key: str, level: int) -> list[Feature]:
        c = self.classes.get(class_key)
        if not c:
            return []
        out: list[Feature] = []
        for ref in c.get("classFeatures", []):
            gain = False
            if isinstance(ref, dict):
                gain = bool(ref.get("gainSubclassFeature"))
                ref = ref["classFeature"]
            name, cn, cs, lvl, src = parse_class_ref(ref)
            if lvl > level or src not in self.sources:
                continue
            f = self.resolve_class_feature(ref)
            if f:
                out.append(Feature(f["name"], lvl, src, f.get("entries", []), "class", gain))
        sub = self.subclasses.get(class_key, {}).get(subclass_key) if subclass_key else None
        if sub:
            for ref in sub.get("subclassFeatures", []):
                name, cn, cs, ss, ssrc, lvl, src = parse_subclass_ref(ref)
                if lvl > level:
                    continue
                f = self.resolve_subclass_feature(ref)
                if f:
                    out.append(Feature(f["name"], lvl, src, f.get("entries", []), "subclass"))
        out.sort(key=lambda f: (f.level, 0 if f.kind == "class" else 1))
        return out

    # ---------------------------------------------------------------- spells
    def spells_for_class(self, class_key: str, subclass_key: str = "") -> list[dict]:
        found = [
            sp for sp in self.spells.values()
            if class_key in sp["_classes"] or (subclass_key and (class_key, subclass_key) in sp["_subclasses"])
        ]
        found.sort(key=lambda s: (s["level"], s["name"]))
        return found

    def search_spells(self, q: str = "", level: int | None = None, class_key: str = "",
                      subclass_key: str = "", limit: int = 60) -> list[dict]:
        q = (q or "").strip().lower()
        pool = self.spells_for_class(class_key, subclass_key) if class_key else sorted(
            self.spells.values(), key=lambda s: (s["level"], s["name"]))
        out = []
        for sp in pool:
            if level is not None and sp["level"] != level:
                continue
            if q and q not in sp["name"].lower():
                continue
            out.append(sp)
            if len(out) >= limit:
                break
        return out


def _merge_subrace(base: dict, sub: dict) -> dict:
    out = copy.deepcopy(base)
    overwrite = sub.get("overwrite") or {}
    for k, v in sub.items():
        if k in _SUBRACE_SKIP:
            continue
        if k == "entries":
            entries = list(out.get("entries", []))
            for e in v:
                target = e.get("data", {}).get("overwrite") if isinstance(e, dict) else None
                if target:
                    idx = next((i for i, b in enumerate(entries)
                                if isinstance(b, dict) and b.get("name") == target), None)
                    if idx is not None:
                        entries[idx] = copy.deepcopy(e)
                        continue
                entries.append(copy.deepcopy(e))
            out["entries"] = entries
        elif k == "ability":
            if overwrite.get("ability") or not out.get("ability"):
                out["ability"] = copy.deepcopy(v)
            else:
                merged = list(out["ability"])
                for i, choice in enumerate(v):
                    if i < len(merged):
                        merged[i] = {**merged[i], **choice}
                    else:
                        merged.append(copy.deepcopy(choice))
                out["ability"] = merged
        elif isinstance(v, list) and isinstance(out.get(k), list) and not overwrite.get(k):
            out[k] = out[k] + copy.deepcopy(v)
        else:
            out[k] = copy.deepcopy(v)
    return out
