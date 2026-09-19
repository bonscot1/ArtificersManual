# Artificer's Manual

A character tracker for one D&D 5e (2014) table. Runs on the DM's machine; players open their
sheet in a browser, the DM sees the whole party and keeps private notes on each character.

Pick a race, class, subclass and background and the sheet fills itself in from the books:
traits, class features by level, spell slots, save DC, the class's spell list, weapon stats.

## First run

```powershell
cd E:\DnD\Site
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python scripts\fetch_data.py      # downloads the rules data (~8 MB) into data\5etools
.venv\Scripts\python -m app                     # or: .\run.ps1, or double-click serve.py
```

Then open http://localhost:8000. The console prints the address for other devices on your
network (e.g. `http://192.168.0.120:8000`). Windows will ask once whether Python may accept
connections - allow it on private networks.

## Passwords and remote players

With no `settings.json` the site is open to anyone who can reach it, and the machine running the
server is the DM. That is fine on a home network. Before exposing it further, copy
`settings.example.json` to `settings.json` and set both passwords:

```json
{
  "sources": ["PHB"],
  "table_password": "something-you-tell-the-players",
  "dm_password": "something-only-you-know"
}
```

Players type the table password once; the DM password unlocks DM notes and deleting characters
(from any device - once it is set, "localhost is the DM" switches off, so a tunnel can't grant DM).

To let friends who aren't on your network in, run a tunnel next to the server instead of opening
router ports. Cloudflare's quick tunnel needs no account:

```powershell
winget install Cloudflare.cloudflared       # once
.\tunnel.ps1                                # prints a https://....trycloudflare.com URL for this session
```

The URL changes every time you start the tunnel; paste it in your group chat at the start of the
session. Set the passwords first.

## Books

`sources` in `settings.json` lists the books whose content is switched on, by 5etools code.
Start with the Player's Handbook; add expansions as your table allows them:

| code | book |
| --- | --- |
| PHB | Player's Handbook (2014) - always on |
| XGE | Xanathar's Guide to Everything |
| TCE | Tasha's Cauldron of Everything (Artificer lives here) |
| MPMM | Monsters of the Multiverse (Tortle, Goliath, ... 2022 versions) |
| VGM | Volo's Guide to Monsters (Goliath 2016 version) |
| TTP | The Tortle Package |
| ERLW | Eberron: Rising from the Last War |
| SCAG | Sword Coast Adventurer's Guide |
| MTF | Mordenkainen's Tome of Foes |
| EGW | Explorer's Guide to Wildemount |

Spells from a book need that book's spell file: `python scripts\fetch_data.py --all` grabs every
spell file. Races, classes, subclasses, backgrounds, feats and items for every book are already in
the base download. The 2024 rules (`XPHB`) are deliberately left out.

Data comes from the 5etools JSON on GitHub and is stored locally; the site never calls out to the
internet while running.

## Layout

```
app/                FastAPI app
  compendium/       loader (reads the JSON), render (book markup -> HTML), rules (5e arithmetic)
  routes/           characters.py (party, creation, live-saving sheet), compendium.py (browse)
  templates/        Jinja; partials/ are the pieces the sheet swaps live via htmx
  sheet.py          everything derived from scores + level + class + race
  db.py             SQLite model (one table: characters)
data/5etools/       downloaded rules data (gitignored)
data/manual.db      your characters (gitignored - back this file up)
scripts/            fetch_data.py
tests/              pytest; `.venv\Scripts\python -m pytest`
```

Every control on the sheet saves as soon as it changes; the small "Saved" toast is the
confirmation. The party page refreshes itself every few seconds.
