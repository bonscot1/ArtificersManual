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
    assert "Tortle|TTP" in big.races and "Tortle|MPMM" in big.races
    labels = [o.label for o in big.race_options()]
    assert "Tortle (TTP)" in labels and "Tortle (MPMM)" in labels
    tortle = big.merged_race("Tortle|TTP", "")
    assert "Shell Defense" in [e.get("name") for e in tortle["entries"] if isinstance(e, dict)]
    art = big.classes["Artificer|TCE"]
    assert art["hd"]["faces"] == 8
    names = [(f.name, f.level) for f in big.features_for("Artificer|TCE", "Battle Smith|TCE", 3)]
    assert ("Infuse Item", 2) in names and ("Battle Smith", 3) in names
    assert rules.spell_slots(art, None, 2) == [2, 0, 0, 0, 0, 0, 0, 0, 0]
    assert rules.eval_prepared_formula(art["preparedSpells"], 2, {"int": 3}) == 4
    assert "Cure Wounds" in {s["name"] for s in big.spells_for_class("Artificer|TCE")}


def test_goliath_and_tasha_subclasses(big):
    assert "Goliath|VGM" in big.races and "Goliath|MPMM" in big.races
    assert "Stone's Endurance" in [e["name"] for e in big.merged_race("Goliath|MPMM", "")["entries"]]
    subs = dict(big.subclass_options("Fighter|PHB"))
    assert "Rune Knight (TCE)" in subs and "Samurai (XGE)" in subs
    assert "Fighter|XPHB" not in big.classes   # 2024 rules stay out unless asked for
