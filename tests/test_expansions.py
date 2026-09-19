"""The expansion path: the same loader with more books switched on."""
import pytest

from app.compendium import rules
from app.compendium.loader import Compendium
from tests.conftest import DATA_DIR


@pytest.fixture(scope="module")
def big():
    if not (DATA_DIR / "races.json").exists():
        pytest.skip("run scripts/fetch_data.py first")
    return Compendium(DATA_DIR, ["PHB", "TCE", "MPMM", "TTP", "VGM", "XGE"])


def test_tortle_artificer(big):
    assert "Tortle|MPMM" in big.races and "Tortle|TTP" not in big.races   # the Tortle Package printing is superseded
    labels = [o.label for o in big.race_options()]
    assert labels.count("Tortle") == 1 and "Tortle (TTP)" not in labels
    tortle = big.merged_race("Tortle|MPMM", "")
    assert "Shell Defense" in [e.get("name") for e in tortle["entries"] if isinstance(e, dict)]
    assert big.find("race", "Tortle", "TTP")["source"] == "MPMM"           # old tags land on the current version
    art = big.classes["Artificer|TCE"]
    assert art["hd"]["faces"] == 8
    names = [(f.name, f.level) for f in big.features_for("Artificer|TCE", "Battle Smith|TCE", 3)]
    assert ("Infuse Item", 2) in names and ("Battle Smith", 3) in names
    assert rules.spell_slots(art, None, 2) == [2, 0, 0, 0, 0, 0, 0, 0, 0]
    assert rules.eval_prepared_formula(art["preparedSpells"], 2, {"int": 3}) == 4
    assert "Cure Wounds" in {s["name"] for s in big.spells_for_class("Artificer|TCE")}


def test_goliath_and_tasha_subclasses(big):
    assert "Goliath|MPMM" in big.races and "Goliath|VGM" not in big.races
    assert [o.label for o in big.race_options()].count("Goliath") == 1
    assert "Stone's Endurance" in [e["name"] for e in big.merged_race("Goliath|MPMM", "")["entries"]]
    assert "Aasimar; Radiant Soul|MPMM" not in big.races                   # in-race choices stay inside the race
    subs = dict(big.subclass_options("Fighter|PHB"))
    assert "Rune Knight (TCE)" in subs and "Samurai (XGE)" in subs
    assert "Fighter|XPHB" not in big.classes   # 2024 rules stay out unless asked for


def test_older_printing_kept_when_the_reprint_is_not_enabled():
    small = Compendium(DATA_DIR, ["PHB", "VGM"])
    assert "Goliath|VGM" in small.races and "Goliath|MPMM" not in small.races
