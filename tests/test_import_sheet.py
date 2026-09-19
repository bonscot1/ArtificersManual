"""The official-sheet importer: name matching, equipment parsing, and the real PDFs when present."""
from pathlib import Path

import pytest

from scripts.import_sheet import Matcher, parse_equipment, read_pdf, strip_urls

IRON = Path(r"E:\DnD\Characters\Iron Wavebreaker\Iron Wavebreaker.pdf")


def test_parse_equipment():
    rows = parse_equipment("1 x 10gp Gem\n\n2 x Javelin\n-Backpack\nTorches (x10)\nhttps://example.com/x")
    assert [(r["qty"], r["name"]) for r in rows] == [("1", "10gp Gem"), ("2", "Javelin"), ("1", "Backpack"), ("10", "Torches")]


def test_strip_urls():
    assert strip_urls("Homunculus Servant - https://dnd5e.wikidot.com/artificer:infusions") == "Homunculus Servant"
    assert strip_urls("https://dnd5e.wikidot.com/barbarian") == ""


def test_matcher_races_and_names(comp):
    m = Matcher(comp)
    assert m.race("High Elf", None) == ("Elf|PHB", "High|PHB")
    assert m.race("Elf (Wood)", None) == ("Elf|PHB", "Wood|PHB")
    assert m.race("Human", None) == ("Human|PHB", "")           # plain human beats the variant
    assert m.race("Tortle", None) == ("", "") and any("Tortle" in w for w in m.warnings)
    assert m.race("Dwarf", "Dwarf|PHB||Mountain|PHB") == ("Dwarf|PHB", "Mountain|PHB")
    assert m.by_name("class", "Fighter", None, "class") == "Fighter|PHB"
    assert m.by_name("background", "Clan-Crafter", None, "background") == ""     # SCAG is not enabled here
    assert m.by_name("background", "Sage", None, "background") == "Sage|PHB"
    assert m.spell("Cure Wound", "Cleric|PHB", "") == "Cure Wounds|PHB"
    assert m.spell("Firebolt", "Wizard|PHB", "") == "Fire Bolt|PHB"
    assert m.spell("https://somewhere", "Wizard|PHB", "") is None
    assert m.spell("Fireball", "Cleric|PHB", "") == "Fireball|PHB"              # falls back to every list


@pytest.mark.skipif(not IRON.exists(), reason="Iron's sheet is not on this machine")
def test_real_sheet_fields_and_prepared_ticks():
    fields, prepared = read_pdf(IRON)
    assert fields["CharacterName"] == "Iron Wavebreaker" and fields["Race"] == "Tortle"
    assert fields["Check Box 19"] == "/Yes" and fields["Check Box 20"] == "/Yes"      # Con + Int saves
    assert {n for n, p in prepared.items() if p} == {"Spells 1015", "Spells 1023", "Spells 1024"}
    assert {fields[n] for n, p in prepared.items() if p} == {"Cure Wound", "Catapult", "Faerie Fire"}
    assert fields["Spells 1014"] == "Firebolt" and "Spells 1014" not in prepared     # cantrips have no tick box
