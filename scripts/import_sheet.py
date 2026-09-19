"""Import a character from the official (WotC) fillable character-sheet PDF.

    python scripts/import_sheet.py "path/to/sheet.pdf" [options]

Names on the sheet are matched against the enabled books (race, class, background,
spells); anything ambiguous or hand-written can be pinned with a flag:

    --race "Tortle|MPMM" --class "Artificer|TCE" --background "Clan Crafter|SCAG" --level 2
    --feat "Strike of the Giants; Hill|BGG" --option "Replicate Magic Item|TCE:Bag of Holding"
    --counter "Rage:2:long" --dm-notes secrets.md --backstory backstory.txt --replace

The character's mechanical facts, notes, spells, attacks and equipment come from the
PDF's form fields; the sheet then fills in the rest from the books.
"""
from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfReader  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.compendium import format as fmt  # noqa: E402
from app.compendium import rules  # noqa: E402
from app.compendium.loader import Compendium  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.db import Character, make_engine, make_session_factory  # noqa: E402

# the official sheet's proficiency ticks, in print order
SAVE_BOXES = {"Check Box 11": "str", "Check Box 18": "dex", "Check Box 19": "con",
              "Check Box 20": "int", "Check Box 21": "wis", "Check Box 22": "cha"}
SKILL_BOXES = {f"Check Box {23 + i}": name for i, (name, _) in enumerate(rules.SKILLS)}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def read_pdf(path: Path) -> tuple[dict[str, str], dict[str, bool]]:
    """Filled text fields (keys stripped) and, for each spell line, whether its prepared box is ticked."""
    reader = PdfReader(str(path))
    raw = reader.get_fields() or {}
    fields: dict[str, str] = {}
    for k, v in raw.items():
        val = v.get("/V")
        if val in (None, ""):
            continue
        fields[str(k).strip()] = str(val).replace("\r\n", "\n").replace("\r", "\n")
    # geometry: the prepared checkbox sits just left of each "Spells NNNN" line
    widgets = []
    for pno, page in enumerate(reader.pages):
        for a in page.get("/Annots", []) or []:
            a = a.get_object()
            if a.get("/Subtype") != "/Widget":
                continue
            name = a.get("/T") or (a.get("/Parent") or {}).get("/T")
            if name is None:
                continue
            rect = [float(x) for x in a["/Rect"]]
            widgets.append((pno, str(name).strip(), rect))
    prepared: dict[str, bool] = {}
    boxes = [w for w in widgets if w[1].startswith("Check Box")]
    for pno, name, rect in widgets:
        if not re.fullmatch(r"Spells \d+", name):
            continue
        cy = (rect[1] + rect[3]) / 2
        for bp, bname, brect in boxes:
            if bp != pno:
                continue
            bcy = (brect[1] + brect[3]) / 2
            if abs(bcy - cy) < 3 and -14 < brect[0] - rect[0] < -3:
                prepared[name] = fields.get(bname) == "/Yes"
                break
    return fields, prepared


def to_int(text, default=0) -> int:
    m = re.search(r"-?\d+", str(text or ""))
    return int(m.group()) if m else default


class Matcher:
    def __init__(self, comp: Compendium):
        self.comp = comp
        self.warnings: list[str] = []

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def race(self, text: str, override: str | None) -> tuple[str, str]:
        opts = self.comp.race_options()
        if override:
            rk, _, sk = override.partition("||")
            if rk in self.comp.races:
                return rk, sk
            for o in opts:
                if o.race_key == override or o.label == override:
                    return o.race_key, o.subrace_key
            self.warn(f"race override {override!r} not found")
        want = norm(text)
        if not want:
            return "", ""
        hits = []
        for o in opts:
            base = o.group.split(" (")[0]
            sub = o.label[len(o.group) + 2:-1] if o.subrace_key else ""
            forms = {norm(o.label), norm(o.group), norm(base), norm(f"{sub} {base}"), norm(f"{base} {sub}")}
            if want in forms:
                hits.append(o)
        if not hits:
            self.warn(f"race {text!r} not in the enabled books; set it on the sheet or pass --race")
            return "", ""
        # a bare race name with subraces: prefer the plain version, then the books' order
        order = {src: i for i, src in enumerate(self.comp.source_order)}
        hits.sort(key=lambda o: (bool(o.subrace_key), order.get(o.race_key.split("|")[1], 99)))
        if len({(h.race_key, h.subrace_key) for h in hits}) > 1:
            self.warn(f"race {text!r} matched several ({', '.join(h.label for h in hits)}); using {hits[0].label}")
        return hits[0].race_key, hits[0].subrace_key

    def by_name(self, kind: str, text: str, override: str | None, label: str) -> str:
        store = self.comp.store(kind)
        if override:
            if override in store:
                return override
            self.warn(f"{label} override {override!r} not found")
        want = norm(re.sub(r"\(.*?\)", "", text or ""))
        if not want:
            return ""
        order = {src: i for i, src in enumerate(self.comp.source_order)}
        hits = sorted((k for k, e in store.items() if norm(e["name"]) == want),
                      key=lambda k: order.get(k.split("|")[1], 99))
        if not hits:
            close = difflib.get_close_matches(want, [norm(e["name"]) for e in store.values()], n=1, cutoff=0.85)
            if close:
                hits = [k for k, e in store.items() if norm(e["name"]) == close[0]]
        if not hits:
            self.warn(f"{label} {text!r} not in the enabled books; pass --{label}")
            return ""
        if len(hits) > 1:
            self.warn(f"{label} {text!r} matched several ({', '.join(hits)}); using {hits[0]}")
        return hits[0]

    def spell(self, text: str, class_key: str, subclass_key: str) -> str | None:
        want = norm(text)
        if not want or "http" in text:
            return None
        pools = [self.comp.spells_for_class(class_key, subclass_key), list(self.comp.spells.values())]
        for pool in pools:
            by_norm = {norm(s["name"]): s for s in pool}
            if want in by_norm:
                s = by_norm[want]
                return f"{s['name']}|{s['source']}"
        for pool in pools:
            by_norm = {norm(s["name"]): s for s in pool}
            close = difflib.get_close_matches(want, list(by_norm), n=1, cutoff=0.8)
            if close:
                s = by_norm[close[0]]
                self.warn(f"spell {text!r} read as {s['name']}")
                return f"{s['name']}|{s['source']}"
        self.warn(f"spell {text!r} not found")
        return None


def parse_equipment(text: str) -> list[dict]:
    rows = []
    for line in (text or "").splitlines():
        line = line.strip(" -\t")
        if not line or "http" in line:
            continue
        qty = "1"
        m = re.match(r"^(\d+)\s*[x×]\s*(.+)$", line, re.I)
        if m:
            qty, line = m.group(1), m.group(2)
        m = re.match(r"^(.+?)\s*\(\s*[x×]\s*(\d+)\s*\)$", line, re.I)
        if m:
            line, qty = m.group(1), m.group(2)
        rows.append({"name": line.strip()[:300], "qty": qty, "notes": ""})
    return rows


def strip_urls(text: str) -> str:
    return re.sub(r"\s*-?\s*https?://\S+", "", text or "").strip()


def parse_pick(text: str) -> dict:
    key, _, note = text.partition(":")
    return {"key": key.strip(), "note": note.strip()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--name"), ap.add_argument("--player")
    ap.add_argument("--race", help='"Tortle|MPMM" or "Elf|PHB||High|PHB"')
    ap.add_argument("--class", dest="class_key"), ap.add_argument("--subclass")
    ap.add_argument("--background"), ap.add_argument("--level", type=int)
    ap.add_argument("--feat", action="append", default=[], help='"Alert|PHB" or "Key|SRC:note"')
    ap.add_argument("--option", action="append", default=[], help='class option "Replicate Magic Item|TCE:Bag of Holding"')
    ap.add_argument("--counter", action="append", default=[], help='"Name:max:long|short"')
    ap.add_argument("--dm-notes", type=Path), ap.add_argument("--backstory", type=Path)
    ap.add_argument("--replace", action="store_true", help="update a character that already has this name")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    settings = load_settings()
    comp = Compendium(settings.data_dir, settings.sources)
    m = Matcher(comp)
    fields, prepared = read_pdf(args.pdf)
    g = lambda *names, default="": next((fields[n] for n in names if fields.get(n)), default)  # noqa: E731

    class_text = g("ClassLevel", "Class")
    class_name = re.split(r"[\(\d]", class_text)[0].strip()
    level = args.level or max(1, to_int(re.sub(r"^\D*", "", class_text), 1))
    class_key = m.by_name("class", class_name, args.class_key, "class")
    subclass_key = ""
    if args.subclass:
        if args.subclass in comp.subclasses.get(class_key, {}):
            subclass_key = args.subclass
        else:
            m.warn(f"subclass {args.subclass!r} is not a {class_key} subclass")
    race_key, subrace_key = m.race(g("Race"), args.race)
    background_key = m.by_name("background", g("Background"), args.background, "background")

    scores = {ab: to_int(g(ab.upper()), 10) for ab in rules.ABILITIES}
    mods = {ab: rules.ability_mod(v) for ab, v in scores.items()}
    hp_max = to_int(g("HPMax"), 10)
    spell_keys, seen = [], set()
    for fname in sorted((k for k in fields if re.fullmatch(r"Spells \d+", k)), key=lambda k: int(k.split()[-1])):
        key = m.spell(fields[fname], class_key, subclass_key)
        if key and key not in seen:
            seen.add(key)
            spell_keys.append({"key": key, "prepared": comp.spells[key]["level"] == 0 or prepared.get(fname, False)})
    attacks = []
    for n, (nm, bonus, dmg) in enumerate([("Wpn Name", "Wpn1 AtkBonus", "Wpn1 Damage"),
                                          ("Wpn Name 2", "Wpn2 AtkBonus", "Wpn2 Damage"),
                                          ("Wpn Name 3", "Wpn3 AtkBonus", "Wpn3 Damage")]):
        if g(nm):
            attacks.append({"name": g(nm).strip(), "bonus": g(bonus).strip(), "damage": g(dmg).strip(), "notes": ""})
    personality = "\n\n".join(f"{label}: {g(f).strip()}" for label, f in
                              (("Personality", "PersonalityTraits"), ("Ideals", "Ideals"), ("Bonds", "Bonds"), ("Flaws", "Flaws"))
                              if g(f).strip())
    appearance = " · ".join(x for x in (
        f"age {g('Age')}" if g("Age") else "", g("Height"), g("Weight"),
        f"eyes {g('Eyes')}" if g("Eyes") and g("Eyes").lower() != "yes" else "",
        f"skin {g('Skin')}" if g("Skin") and g("Skin").lower() != "yes" else "",
        f"hair {g('Hair')}" if g("Hair") else "") if x)
    backstory = args.backstory.read_text(encoding="utf-8") if args.backstory else g("Backstory", "Background Story Text")
    features_text = "\n\n".join(t for t in (strip_urls(g(f)) for f in ("Features and Traits", "Feat+Traits", "Additional Notes")) if t)
    sheet_init = g("Initiative")

    values = dict(
        name=(args.name or g("CharacterName", "Character Name", "CharacterName 2")).strip()[:120],
        player=(args.player or g("PlayerName")).strip()[:120],
        race_key=race_key, subrace_key=subrace_key, class_key=class_key, subclass_key=subclass_key,
        background_key=background_key, level=level, xp=to_int(g("XP")), alignment=g("Alignment").strip()[:40],
        hp_max=hp_max, hp_current=to_int(g("HPCurrent"), hp_max) if g("HPCurrent") else hp_max, hp_temp=to_int(g("HPTemp")),
        ac=to_int(g("AC"), 10), speed=to_int(g("Speed"), 30),
        initiative_bonus=(to_int(sheet_init) - mods["dex"]) if sheet_init.strip() else 0,
        save_profs=[ab for box, ab in SAVE_BOXES.items() if fields.get(box) == "/Yes"],
        skill_profs=[sk for box, sk in SKILL_BOXES.items() if fields.get(box) == "/Yes"],
        other_profs=g("ProficienciesLang").strip(),
        spells=spell_keys, attacks=attacks, inventory=parse_equipment(g("Equipment")),
        currency={k: to_int(g(k.upper())) for k in ("cp", "sp", "ep", "gp", "pp")},
        feats=[parse_pick(x) for x in args.feat], options=[parse_pick(x) for x in args.option],
        counters=[{"name": n, "max": to_int(mx, 1), "used": 0, "reset": "short" if rs.strip() == "short" else "long"}
                  for n, _, rest in (c.partition(":") for c in args.counter) for mx, _, rs in [rest.partition(":")]],
        features_custom=features_text, appearance=appearance[:300], personality=personality,
        allies=g("Allies").strip(), backstory=backstory.strip(),
        notes_dm=args.dm_notes.read_text(encoding="utf-8") if args.dm_notes else "",
        inspiration=g("Inspiration").strip() not in ("", "0"),
    )
    for ab, v in scores.items():
        values[f"score_{ab}"] = v
    for pick in values["feats"]:
        if pick["key"] not in comp.feats:
            m.warn(f"feat {pick['key']!r} not in the enabled books")
    for pick in values["options"]:
        if pick["key"] not in comp.optionalfeatures:
            m.warn(f"option {pick['key']!r} not in the enabled books")

    print(f"{values['name']} - {race_key or '?'} {class_key or '?'} {level}, {background_key or 'no background'}")
    print(f"  scores {scores}  hp {values['hp_max']}  ac {values['ac']}  saves {values['save_profs']}")
    print(f"  skills {values['skill_profs']}")
    print(f"  spells {[s['key'].split('|')[0] + ('*' if s['prepared'] else '') for s in spell_keys]}")
    print(f"  attacks {[a['name'] for a in attacks]}  items {len(values['inventory'])}  feats {[p['key'] for p in values['feats']]}")
    print(f"  options {[p['key'] + (' (' + p['note'] + ')' if p['note'] else '') for p in values['options']]}  counters {[c['name'] for c in values['counters']]}")
    for w in m.warnings:
        print(f"  ! {w}")
    if args.dry_run:
        return 0

    engine = make_engine(settings.db_url)
    Session = make_session_factory(engine)
    with Session() as session:
        existing = session.scalars(select(Character).where(Character.name == values["name"])).first()
        if existing and not args.replace:
            print(f"  a character called {values['name']!r} already exists (id {existing.id}); pass --replace to update it")
            return 1
        ch = existing or Character()
        for k, v in values.items():
            setattr(ch, k, v)
        if not existing:
            session.add(ch)
        session.commit()
        print(f"  {'updated' if existing else 'created'} /c/{ch.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
