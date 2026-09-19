# Artificer's Manual

A character tracker for one D&D 5e (2014) table. Runs on the DM's machine; players open their
sheet in a browser, the DM sees the whole party and keeps private notes on each character.

Pick a race, class, subclass and background and the sheet fills itself in from the books:
traits, class features by level, spell slots, save DC, the class's spell list, weapon stats,
feats, class options (infusions, invocations, fighting styles...) and the class table's numbers
(rages, ki, infused items). Resource counters track uses per rest.

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

## Play view and sheet

Opening a character lands on the **play view**: a HUD (hit points with damage/heal, AC,
initiative, speed, passive perception, spell DC, inspiration, concentration, conditions) over
three screens - **Combat** (attacks, spells, resources, saves, rests), **Roleplay** (skills,
notes, equipment, features, backstory) and **Everything** (every section, one tab at a time).
The screen is remembered per character. Players change what changes at the table: damage and
healing, hit dice and rests, resource pips, casting, preparing spells, equipment and coins,
session notes. Everything else is edited on the full sheet via **Edit sheet**.

Every character page is coloured by class (arcane blue for wizards, copper for artificers,
eldritch purple for warlocks...); the sheet's Theme picker overrides that, and `app/themes.py`
holds the palettes, including hand-made ones for Iron and Lor' B'ah drawn from their art. A
portrait and a round token can be uploaded on the sheet (stored in `data/portraits/`,
gitignored); the portrait heads the play view, the token sits on the party card.

**Cast** on a spell offers the slot levels that still have a slot (or the pact slot, or ritual
for ritual spells), spends it, and puts concentration spells in the HUD with an "end" button.
The full spell list sits under "All spells".

Some things are the DM's to give, not the player's: inspiration (players can only spend it),
conditions, XP and max hit points. The DM gets the extra controls on the same play view, plus
the DM notes on each character.

**What the others see.** Players never see each other's numbers. On the party page and in the
"The party" pane of the play view (refreshes every few seconds), everyone else is described the
way you'd see them across the room: health in ten steps from "looks unhurt" to "is struggling
to stay conscious" and "is down and not moving", coloured green to red, and conditions as what
they look like - "is on the ground", "looks dazed", "looks sickly". The DM sees the phrases and
the numbers. Your own card keeps its numbers.

**Companions** - familiars, steel defenders, homunculi - live on the sheet (name, kind, HP,
AC, notes) and on the Combat screen: summon or dismiss, damage and heal. While summoned they
appear in the party's view with the same phrases ("Iron's Homunculus is lightly wounded").

## DM screen

**DM screen** (top right when signed in as DM) shows the whole party with the numbers - HP,
AC, passive perception, conditions to toggle, inspiration to grant - refreshing every few
seconds, and a line to each player:

- **Note** - a private message they read and click OK.
- **Choice** - options one per line ("The sword / The bow"); they click one.
- **Question** - they type a reply.

Tick who it goes to (or everyone). It pops up over whatever page that character has open within
a couple of seconds and stays until they act on it; further messages queue behind it. Answers
appear in the Sent list as they come in; a pending message can be cancelled.

Write `[[Potion of Healing]]` (or `[[Bless|spell]]`) in a message and it becomes a link that opens
the compendium entry inside the popup; the box under the message searches names to insert.

**Anything the DM does to a sheet tells the player** - a condition, inspiration, damage, an item
handed over or taken, a spell added, XP - as a "Your sheet changed" popup listing the changes
(several within a few minutes fold into one). Items and conditions in it are links to their
entries. Players' own edits don't notify anyone. On the play view, "read" next to an item and
tapping a condition in the HUD open the entry in place too.

Removing an item from the equipment list moves it to a **Removed** list underneath, with
"put back" - so a potion drunk in error, or a sword the DM hands back, is one click.

`scripts/seed_test_party.py` adds three made-up level-2 characters (rogue, life cleric, fiend
warlock) for trying things out; `--replace` resets them.

## Who can open what

Every character has its own password. The first person to open a new sheet is asked to set one
(anything goes - it only stops people picking the wrong character); that browser then stays
unlocked and everyone else needs the password. The DM opens every sheet and can clear a
forgotten password from the DM tools at the bottom of the sheet.

The DM signs in at **DM sign in** (top right) with `dm_password` from `settings.json`. With no
`settings.json` at all the site is open and the machine running the server counts as the DM;
that is fine on a home network. Before exposing it further, copy `settings.example.json` to
`settings.json` and set both passwords:

```json
{
  "sources": ["PHB"],
  "table_password": "something-you-tell-the-players",
  "dm_password": "something-only-you-know"
}
```

Players type the table password once; the DM password unlocks DM notes, password resets and
deleting characters (from any device - once it is set, "localhost is the DM" switches off, so a
tunnel can't grant DM). Cookies are signed with `data/secret.key`, generated on first run.

To let friends who aren't on your network in, run a tunnel next to the server instead of opening
router ports. Cloudflare's quick tunnel needs no account:

```powershell
winget install Cloudflare.cloudflared       # once
.\tunnel.ps1                                # prints a https://....trycloudflare.com URL for this session
```

The URL changes every time you start the tunnel; paste it in your group chat at the start of the
session. Set the passwords first.

## Importing a character sheet

Players who fill in the official (WotC) fillable PDF can be imported in one go - scores, ticks,
spells (with prepared marks), attacks, equipment, coins, personality, backstory:

```powershell
.venv\Scripts\python scripts\import_sheet.py "E:\DnD\Characters\Iron Wavebreaker\Iron Wavebreaker.pdf" `
    --race "Tortle|MPMM" --option "Replicate Magic Item|TCE:Bag of Holding" --option "Homunculus Servant|TCE" `
    --dm-notes "E:\DnD\Characters\Iron Wavebreaker\IronWavebreaker_Hidden_Backstory_DM_ONLY.md"
```

Names on the sheet are matched against the enabled books; `--dry-run` shows what it found and
warns about anything it couldn't place. Pin the rest with `--race`, `--class`, `--subclass`,
`--background`, `--level`, `--feat`, `--option` (`"Key|SRC:note"`), `--counter "Rage:2:long"`.
`--replace` updates a character that already exists. DM notes never leave this machine's database.

## Books

`sources` in `settings.json` lists the books whose content is switched on, by 5etools code.
The default is this table's set - PHB, XGE, TCE, SCAG, MPMM, VGM, TTP, BGG.

When a race, subclass, feat or spell was reprinted in a later enabled book, only the newest
printing is offered - the version dnd5e.wikidot.com shows first (the Multiverse Goliath and
Tortle, Tasha's Artificer). The older text stays in the data but out of the pickers. Compendium
pages link to the matching wikidot page for anything the sheet doesn't show.
Magic items load from every book regardless, so loot from the DMG is always there.

## House rules

`house_rules.md` in the site folder is the **Rules** page: the 2014 base plus whichever 2024
rules the table has adopted (potions as a bonus action, and so on). Edit the file; the page
updates on the next load.

| code | book |
| --- | --- |
| PHB | Player's Handbook (2014) - always on |
| XGE | Xanathar's Guide to Everything |
| TCE | Tasha's Cauldron of Everything (Artificer, infusions) |
| SCAG | Sword Coast Adventurer's Guide (Clan Crafter) |
| MPMM | Monsters of the Multiverse (Tortle, Goliath - 2022 versions) |
| VGM | Volo's Guide to Monsters (Goliath - 2016 version) |
| TTP | The Tortle Package |
| BGG | Bigby Presents: Glory of the Giants (Giant Foundling, Strike of the Giants) |
| ERLW | Eberron: Rising from the Last War |
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
scripts/            fetch_data.py, import_sheet.py
tests/              pytest; `.venv\Scripts\python -m pytest`
```

Every control on the sheet saves as soon as it changes; the small "Saved" toast is the
confirmation. The party page refreshes itself every few seconds.
