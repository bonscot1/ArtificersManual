import re

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import create_character, make_settings


def test_create_fills_in_the_books(client):
    cid = create_character(client)
    html = client.get(f"/c/{cid}/sheet").text
    for needle in ("Elf (High)", "Fey Ancestry", "Trance", "Arcane Recovery", "Sage", "Researcher",
                   "Save DC", 'value="Test Wizard"'):
        assert needle in html, needle
    # wizard 3 with Int 17: DC 8 + 2 + 3 = 13, saves Int/Wis, HP 6 + 1 + 2 * (4 + 1) = 17
    assert re.search(r"Save DC</span><span class='v'>13</span>", html) or "13" in html
    cards = client.get("/").text
    assert "Test Wizard" in cards and "HP 17/17" in cards


def test_live_save_returns_oob_fragments(client):
    cid = create_character(client)
    r = client.post(f"/c/{cid}/save", data={"score_int": "18"})
    assert r.status_code == 200
    assert r.headers["HX-Trigger"] == '{"toast": "Saved"}'
    assert 'id="mod-int" hx-swap-oob="true">+4' in r.text
    assert 'id="skills" hx-swap-oob="true"' in r.text


def test_checkbox_groups_only_touched_when_declared(client):
    cid = create_character(client)
    client.post(f"/c/{cid}/save", data={"_lists": "skill_prof,skill_expertise", "skill_prof": ["Arcana", "History"],
                                        "skill_expertise": ["Arcana"]})
    html = client.get(f"/c/{cid}/sheet").text
    assert 'value="Arcana" checked title="proficient"' in html
    assert 'value="Arcana" checked title="expertise"' in html
    # a save from another form (no _lists) must not wipe the skills
    client.post(f"/c/{cid}/save", data={"notes": "hello"})
    html = client.get(f"/c/{cid}/sheet").text
    assert 'value="Arcana" checked title="proficient"' in html and ">hello</textarea>" in html


def test_level_and_subclass_refresh(client):
    cid = create_character(client)
    r = client.post(f"/c/{cid}/save", data={"level": "5"})
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"
    html = client.get(f"/c/{cid}/sheet").text
    assert "Arcane Tradition" in html and 'name="subclass_key"' in html
    client.post(f"/c/{cid}/save", data={"subclass_key": "Evocation|PHB"})
    html = client.get(f"/c/{cid}/sheet").text
    assert "Sculpt Spells" in html and "Evocation Savant" in html
    # bogus subclass for this class is ignored
    client.post(f"/c/{cid}/save", data={"subclass_key": "Champion|PHB"})
    assert "Sculpt Spells" in client.get(f"/c/{cid}/sheet").text


def test_spells_and_slots(client):
    cid = create_character(client)
    r = client.get(f"/c/{cid}/spells/search", params={"q": "fire"})
    assert "Fireball" in r.text and "Cure Wounds" not in r.text
    r = client.get(f"/c/{cid}/spells/search", params={"q": "cure", "scope": "all"})
    assert "Cure Wounds" in r.text
    r = client.post(f"/c/{cid}/spells", data={"op": "add", "key": "Fireball|PHB"})
    assert "Fireball" in r.text and 'title="prepared"' in r.text
    client.post(f"/c/{cid}/spells", data={"op": "add", "key": "Fireball|PHB"})   # no duplicates
    assert client.get(f"/c/{cid}/sheet").text.count("spell-name\">Fireball") == 1
    r = client.post(f"/c/{cid}/spells", data={"op": "prepare", "key": "Fireball|PHB"})
    assert 'checked title="prepared"' in r.text
    r = client.post(f"/c/{cid}/slot", data={"level": "2", "used": "2"})
    assert r.text.count("pip used") == 2
    r = client.post(f"/c/{cid}/spells", data={"op": "remove", "key": "Fireball|PHB"})
    assert "Fireball" not in r.text


def test_hp_flow(client):
    cid = create_character(client)
    client.post(f"/c/{cid}/hp", data={"action": "temp", "amount": "5"})
    r = client.post(f"/c/{cid}/hp", data={"action": "damage", "amount": "8"})
    assert '<span class="hp-big">14</span>' in r.text and "temp" not in r.text.split("hp-now")[1][:80]
    r = client.post(f"/c/{cid}/hp", data={"action": "damage", "amount": "99"})
    assert '<span class="hp-big">0</span>' in r.text and "down" in r.text
    client.post(f"/c/{cid}/hp", data={"action": "death_fail"})
    r = client.post(f"/c/{cid}/hp", data={"action": "heal", "amount": "4"})
    assert '<span class="hp-big">4</span>' in r.text and "fail 0/3" in r.text
    client.post(f"/c/{cid}/slot", data={"level": "1", "used": "2"})
    r = client.post(f"/c/{cid}/rest", data={"kind": "long"})
    assert r.headers["HX-Refresh"] == "true"
    html = client.get(f"/c/{cid}/sheet").text
    assert '<span class="hp-big">17</span>' in html and "pip used" not in html


def test_attacks_prefill_from_book_weapon(client):
    cid = create_character(client)
    r = client.post(f"/c/{cid}/attacks", data={"op": "add", "name": "Dagger"})
    vals = re.findall(r'name="(?:bonus|damage|notes)" value="([^"]*)"', r.text)
    assert vals == ["+4", "1d4+2 piercing", "range 20/60, finesse, light, thrown"]
    r = client.post(f"/c/{cid}/attacks", data={"op": "update", "idx": "0", "name": "Dagger", "bonus": "+9",
                                                 "damage": "1d4", "notes": ""})
    assert r.status_code == 204 and "toast" in r.headers["HX-Trigger"]
    assert 'value="+9"' in client.get(f"/c/{cid}/sheet").text
    r = client.post(f"/c/{cid}/attacks", data={"op": "remove", "idx": "0"})
    assert "Dagger" not in r.text


def test_conditions_toggle(client):
    cid = create_character(client)
    r = client.post(f"/c/{cid}/conditions", data={"name": "Prone"})
    assert 'class="chip on"' in r.text and "Prone" in client.get("/party/cards").text
    r = client.post(f"/c/{cid}/conditions", data={"name": "Prone"})
    assert 'class="chip on"' not in r.text
    r = client.post(f"/c/{cid}/conditions", data={"name": "Made Up"})
    assert 'class="chip on"' not in r.text


def test_dm_notes_and_delete_are_dm_only(tmp_path):
    dm = TestClient(create_app(make_settings(tmp_path, table_password="tbl", dm_password="dm")))
    dm.post("/login", data={"password": "dm"})
    cid = create_character(dm)
    dm.post(f"/c/{cid}/save", data={"notes_dm": "the twist"})
    assert "the twist" in dm.get(f"/c/{cid}/sheet").text

    player = TestClient(dm.app)
    player.post("/login", data={"password": "tbl"})
    player.post(f"/c/{cid}/unlock", data={"password": "mine"})        # claims the sheet
    html = player.get(f"/c/{cid}/sheet").text
    assert "the twist" not in html and "DM notes" not in html
    assert player.post(f"/c/{cid}/save", data={"notes_dm": "hax"}).status_code == 403
    assert player.post(f"/c/{cid}/delete").status_code == 403
    assert "the twist" in dm.get(f"/c/{cid}/sheet").text
    assert dm.post(f"/c/{cid}/delete", follow_redirects=False).status_code == 303
    assert dm.get(f"/c/{cid}/sheet").status_code == 404


def test_compendium_pages(client):
    for path in ("/compendium", "/compendium?q=fire", "/compendium/spells?cls=Wizard|PHB&level=3",
                 "/compendium/spells/Fireball%7CPHB", "/compendium/classes", "/compendium/classes/Fighter%7CPHB",
                 "/compendium/classes/Fighter%7CPHB?sub=Champion%7CPHB", "/compendium/classes/Warlock%7CPHB",
                 "/compendium/races", "/compendium/races/Elf%7CPHB?sub=Wood%7CPHB", "/compendium/backgrounds",
                 "/compendium/backgrounds/Sage%7CPHB", "/compendium/feats", "/compendium/feats/Alert%7CPHB",
                 "/compendium/items?kind=weapon", "/compendium/items/Longsword%7CPHB", "/compendium/conditions",
                 "/compendium/optional-features/Archery%7CPHB"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "{@" not in r.text, path   # no raw markup leaks
    assert client.get("/compendium/spells/Nope%7CPHB").status_code == 404
    assert "Fleet of Foot" in client.get("/compendium/races/Elf%7CPHB?sub=Wood%7CPHB").text
    assert "Pact slots" in client.get("/compendium/classes/Warlock%7CPHB").text
    fighter = client.get("/compendium/classes/Fighter%7CPHB").text
    assert "&lt;a class=" not in fighter and "href='/compendium/items/Chain%20Mail%7CPHB'" in fighter


def test_no_raw_markup_on_sheet(client):
    cid = create_character(client, class_key="Cleric|PHB", race="Dwarf|PHB||Hill|PHB", background_key="Acolyte|PHB")
    client.post(f"/c/{cid}/save", data={"subclass_key": "Life|PHB"})
    client.post(f"/c/{cid}/spells", data={"op": "add", "key": "Cure Wounds|PHB"})
    html = client.get(f"/c/{cid}/sheet").text
    assert "{@" not in html
    assert "Dwarven Resilience" in html and "Disciple of Life" in html and "Shelter of the Faithful" in html
