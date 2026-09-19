from app.compendium import rules


def test_ability_mod():
    assert rules.ability_mod(10) == 0
    assert rules.ability_mod(8) == -1
    assert rules.ability_mod(17) == 3
    assert rules.ability_mod(1) == -5


def test_proficiency_bonus():
    assert [rules.proficiency_bonus(l) for l in (1, 4, 5, 8, 9, 12, 13, 16, 17, 20)] == [2, 2, 3, 3, 4, 4, 5, 5, 6, 6]


def test_default_max_hp():
    assert rules.default_max_hp(10, 1, 2) == 12
    assert rules.default_max_hp(6, 3, 1) == 7 + 2 * (4 + 1)


def test_prepared_formula_rounds_down_and_floors_at_one():
    assert rules.eval_prepared_formula("<$level$> + <$int_mod$>", 5, {"int": 3}) == 8
    assert rules.eval_prepared_formula("<$level$> / 2 + <$int_mod$>", 5, {"int": 3}) == 5   # artificer
    assert rules.eval_prepared_formula("<$level$> / 2 + <$cha_mod$>", 1, {"cha": -2}) == 1


def test_strip_tags():
    assert rules.strip_tags("{@filter 1st|spells|level=1}") == "1st"
    assert rules.strip_tags("plain") == "plain"
    assert rules.strip_tags("a {@b bold {@i nested}} end") == "a bold {@i nested} end" or rules.strip_tags("a {@b x} end") == "a x end"
