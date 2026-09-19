from app.compendium.render import Renderer, split_pipe


def r():
    return Renderer(None)


def test_split_pipe_respects_braces():
    assert split_pipe("a|b|c") == ["a", "b", "c"]
    assert split_pipe("{@dice 1d6|x}|b") == ["{@dice 1d6|x}", "b"]


def test_inline_tags():
    out = r().inline("Make a {@b Dexterity} save {@dc 15}, {@hit 5} to hit, {@damage 2d6} fire")
    assert "<b>Dexterity</b>" in out
    assert "DC 15" in out
    assert "<span class='dice'>+5</span>" in out
    assert "<span class='dice'>2d6</span>" in out


def test_inline_escapes_html():
    assert "&lt;script&gt;" in r().inline("<script>alert(1)</script>")


def test_nested_and_unknown_tags_show_text_only():
    out = r().inline("{@i {@spell mage hand}} and {@madeup thing|extra}")
    assert "<i>" in out and "mage hand" in out and "thing" in out and "@madeup" not in out


def test_scaledamage_shows_increment():
    assert "1d6" in r().inline("{@scaledamage 8d6|3-9|1d6}")
    assert "8d6" not in r().inline("{@scaledamage 8d6|3-9|1d6}")


def test_unbalanced_brace_is_literal():
    assert "{@b oops" in r().inline("{@b oops")


def test_blocks():
    html = r().render([
        "para one",
        {"type": "list", "items": ["a", {"type": "item", "name": "N", "entry": "e"}]},
        {"type": "table", "caption": "T", "colLabels": ["x"], "rows": [["1"], [{"type": "cell", "roll": {"min": 1, "max": 5}}]]},
        {"type": "entries", "name": "Sub", "entries": ["inner"]},
        {"type": "abilityDc", "name": "Ki", "attributes": ["wis"]},
    ])
    assert "<p>para one</p>" in html
    assert "<li>a</li>" in html and "<b class='ent-name'>N</b>" in html
    assert "<caption>T</caption>" in html and "1&ndash;5" in html
    assert "<b class='ent-name'>Sub</b><p>inner</p>" in html
    assert "Ki save DC</b> = 8 + your proficiency bonus + your Wisdom modifier" in html


def test_refs_without_compendium_degrade():
    html = r().render([{"type": "refClassFeature", "classFeature": "Rage|Barbarian||1"},
                       {"type": "refOptionalfeature", "optionalfeature": "Archery"}])
    assert "Rage" in html and "not in your enabled books" in html
    assert "Archery" not in html   # options from disabled books are left out
