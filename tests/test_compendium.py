from app.compendium import rules
from app.compendium.loader import entity_url, parse_class_ref, parse_subclass_ref, resolve_copies
from app.compendium.render import Renderer


def test_parse_refs():
    assert parse_class_ref("Second Wind|Fighter||1") == ("Second Wind", "Fighter", "PHB", 1, "PHB")
    assert parse_class_ref("Martial Versatility|Fighter||4|TCE") == ("Martial Versatility", "Fighter", "PHB", 4, "TCE")
    assert parse_subclass_ref("Improved Critical|Fighter||Champion||3") == (
        "Improved Critical", "Fighter", "PHB", "Champion", "PHB", 3, "PHB")


def test_resolve_copies_applies_mods():
    base = {"name": "Orc", "source": "A", "speed": 30,
            "entries": [{"name": "Age", "entries": ["old"]}, {"name": "Menacing", "entries": ["x"]}]}
    copy = {"name": "Orc", "source": "B", "speed": 35, "_copy": {"name": "Orc", "source": "A", "_mod": {
        "entries": [{"mode": "replaceArr", "replace": "Age", "items": {"name": "Age", "entries": ["young"]}},
                    {"mode": "appendArr", "items": {"name": "New", "entries": ["n"]}},
                    {"mode": "removeArr", "names": "Menacing"}]}}}
    out = {(e["name"], e["source"]): e for e in resolve_copies([base, copy], ("name", "source"))}
    b = out[("Orc", "B")]
    assert [e["name"] for e in b["entries"]] == ["Age", "New"]
    assert b["entries"][0]["entries"] == ["young"]
    assert b["speed"] == 35
    assert "_copy" not in b
    assert out[("Orc", "A")]["speed"] == 30   # base untouched


def test_phb_only_sees_phb(comp):
    assert set(c["source"] for c in comp.classes.values()) == {"PHB"}
    assert "Artificer|TCE" not in comp.classes
    assert all(r["source"] == "PHB" for r in comp.races.values())
    assert comp.subclass_options("Fighter|PHB") == [
        ("Battle Master", "Battle Master|PHB"), ("Champion", "Champion|PHB"), ("Eldritch Knight", "Eldritch Knight|PHB")]


def test_race_options_merge_subraces(comp):
    labels = [o.label for o in comp.race_options()]
    assert "Elf (High)" in labels and "Elf (Wood)" in labels and "Elf" not in labels
    assert "Human" in labels and "Human (Variant)" in labels
    high = comp.merged_race("Elf|PHB", "High|PHB")
    assert high["ability"] == [{"dex": 2, "int": 1}]
    assert "Elf Weapon Training" in [e["name"] for e in high["entries"]]
    assert comp.merged_race("Elf|PHB", "Wood|PHB")["speed"] == 35
    assert comp.merged_race("Human|PHB", "")["ability"] == [
        {"str": 1, "dex": 1, "con": 1, "int": 1, "wis": 1, "cha": 1}]


def test_features_by_level(comp):
    names = [(f.name, f.level, f.kind) for f in comp.features_for("Fighter|PHB", "Champion|PHB", 3)]
    assert names == [("Fighting Style", 1, "class"), ("Second Wind", 1, "class"), ("Action Surge", 2, "class"),
                     ("Martial Archetype", 3, "class"), ("Champion", 3, "subclass")]
    assert comp.subclass_level("Fighter|PHB") == 3
    assert comp.subclass_level("Cleric|PHB") == 1
    assert all(f.source == "PHB" for f in comp.features_for("Fighter|PHB", "", 20))


def test_spell_slots(comp):
    wiz = comp.classes["Wizard|PHB"]
    assert rules.spell_slots(wiz, None, 5) == [4, 3, 2, 0, 0, 0, 0, 0, 0]
    assert rules.spell_slots(comp.classes["Paladin|PHB"], None, 1) == [0] * 9
    assert rules.spell_slots(comp.classes["Fighter|PHB"], None, 5) == []
    ek = comp.subclasses["Fighter|PHB"]["Eldritch Knight|PHB"]
    assert rules.spell_slots(comp.classes["Fighter|PHB"], ek, 3) == [2, 0, 0, 0, 0, 0, 0, 0, 0]
    assert rules.pact_slots(comp.classes["Warlock|PHB"], 5) == (2, 3)
    assert rules.pact_slots(wiz, 5) is None


def test_spell_lists(comp):
    wizard = {s["name"] for s in comp.spells_for_class("Wizard|PHB")}
    assert "Fireball" in wizard and "Cure Wounds" not in wizard
    light = {s["name"] for s in comp.spells_for_class("Cleric|PHB", "Light|PHB")}
    assert "Fireball" in light
    assert "Fireball" not in {s["name"] for s in comp.spells_for_class("Cleric|PHB")}
    assert [s["name"] for s in comp.search_spells("fire", 3, "Wizard|PHB")] == ["Fireball"]


def test_find_and_links(comp):
    assert comp.find("spell", "fireball")["name"] == "Fireball"
    assert comp.find("item", "Longsword", "phb")["weapon"] is True
    assert comp.find("race", "Tortle") is None
    assert entity_url("spell", comp.spells["Fireball|PHB"]) == "/compendium/spells/Fireball%7CPHB"
    html = Renderer(comp, link_for=entity_url).inline("{@spell fireball} {@condition prone}")
    assert "href='/compendium/spells/Fireball%7CPHB'" in html
    assert "href='/compendium/conditions/Prone%7CPHB'" in html


def test_render_real_features_resolve_refs(comp):
    champ = comp.subclass_features[("champion", "Fighter", "PHB", "Champion", "PHB", 3, "PHB")]
    html = Renderer(comp).render(champ["entries"])
    assert "Improved Critical" in html and "critical hit on a roll of 19 or 20" in html
    fs = Renderer(comp).render(comp.class_features[("fighting style", "Fighter", "PHB", 1, "PHB")]["entries"])
    assert "Archery" in fs and "Blind Fighting" not in fs   # TCE option hidden on a PHB-only table
