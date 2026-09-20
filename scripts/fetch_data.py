"""Download the 5e reference data the site reads from.

Source: the 5etools JSON on GitHub (github.com/5etools-mirror-3/5etools-src).
Everything lands in data/5etools/ as plain JSON; the app never talks to the
internet itself, so once this has run the site works fully offline.

    python scripts/fetch_data.py            # base game files (PHB spells) + every class/race/background file
    python scripts/fetch_data.py --all      # also every expansion's spell file
    python scripts/fetch_data.py --force    # re-download files that already exist
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

RAW = "https://raw.githubusercontent.com/5etools-mirror-3/5etools-src/main/data/"
API = "https://api.github.com/repos/5etools-mirror-3/5etools-src/contents/data/"
DEST = Path(__file__).resolve().parent.parent / "data" / "5etools"

# One file per class; the file holds the class plus every subclass from every book.
CLASSES = [
    "artificer", "barbarian", "bard", "cleric", "druid", "fighter", "monk",
    "paladin", "ranger", "rogue", "sorcerer", "warlock", "wizard",
]

# Monsters: the Monster Manual, the table's expansion books, and the campaign (Curse of Strahd).
BESTIARIES = ["mm", "mpmm", "vgm", "bgg", "tce", "ttp", "xge", "phb", "dmg", "cos"]

# Races/backgrounds/feats/items are single files covering every book, so the
# base set already contains the expansion entries; the app filters by source.
BASE_FILES = [
    "races.json",
    "backgrounds.json",
    "feats.json",
    "optionalfeatures.json",   # fighting styles, invocations, metamagic, infusions, maneuvers
    "items-base.json",
    "items.json",
    "conditionsdiseases.json",
    "skills.json",
    "senses.json",
    "actions.json",
    "languages.json",
    "spells/index.json",
    "spells/spells-phb.json",
    "generated/gendata-spell-source-lookup.json",   # spell -> which classes can cast it
    "loot.json",                                   # the DMG treasure tables
    "bestiary/index.json",
    *[f"bestiary/bestiary-{b}.json" for b in BESTIARIES],
    *[f"class/class-{c}.json" for c in CLASSES],
]


def fetch(rel: str, force: bool) -> bool:
    target = DEST / rel
    if target.exists() and not force:
        print(f"  keep   {rel}")
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    url = RAW + rel
    req = urllib.request.Request(url, headers={"User-Agent": "artificers-manual/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read()
    json.loads(body)  # refuse to keep a half-downloaded or non-JSON file
    target.write_bytes(body)
    print(f"  fetch  {rel}  ({len(body) // 1024} KB)")
    return True


def list_spell_files() -> list[str]:
    """Every spells-<source>.json the mirror currently ships."""
    req = urllib.request.Request(API + "spells", headers={"User-Agent": "artificers-manual/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        listing = json.load(resp)
    return sorted(
        "spells/" + e["name"] for e in listing
        if e["name"].startswith("spells-") and e["name"].endswith(".json")
    )


def list_bestiary_files() -> list[str]:
    req = urllib.request.Request(API + "bestiary", headers={"User-Agent": "artificers-manual/0.1"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        listing = json.load(resp)
    return sorted(
        "bestiary/" + e["name"] for e in listing
        if e["name"].startswith("bestiary-") and e["name"].endswith(".json")
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="also fetch every expansion's spell file")
    ap.add_argument("--force", action="store_true", help="re-download files that already exist")
    args = ap.parse_args()

    files = list(BASE_FILES)
    if args.all:
        files += [f for f in list_spell_files() if f not in files]
        files += [f for f in list_bestiary_files() if f not in files]

    DEST.mkdir(parents=True, exist_ok=True)
    print(f"-> {DEST}")
    fetched = 0
    for rel in files:
        try:
            fetched += fetch(rel, args.force)
        except Exception as exc:  # keep going; report at the end
            print(f"  FAIL   {rel}: {exc}", file=sys.stderr)
    (DEST / "manifest.json").write_text(json.dumps({
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": files,
    }, indent=2))
    print(f"done: {fetched} downloaded, {len(files) - fetched} already present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
