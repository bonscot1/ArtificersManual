"""Feats, class options, resource counters and the expansion-aware sheet."""
from tests.conftest import create_character


def test_options_follow_the_class(client):
    cid = create_character(client, class_key="Fighter|PHB")
    html = client.get(f"/c/{cid}/sheet").text
    assert "Fighting Style 1" in html                       # from the class's optionalfeatureProgression
    r = client.get(f"/c/{cid}/picks/search", params={"kind": "option", "q": "arch"})
    assert "Archery" in r.text and "Arcane Propulsion" not in r.text   # infusions are not fighter options
    r = client.get(f"/c/{cid}/picks/search", params={"kind": "option", "q": "arcane prop", "scope": "all"})
    assert "Arcane Propulsion Armor" in r.text
    r = client.post(f"/c/{cid}/picks", data={"kind": "option", "op": "add", "key": "Archery|PHB"})
    assert "+2 bonus to attack rolls you make with ranged weapons" in r.text
    r = client.post(f"/c/{cid}/picks", data={"kind": "option", "op": "note", "idx": "0", "note": "longbow"})
    assert r.status_code == 204
    assert "(longbow)" in client.get(f"/c/{cid}/sheet").text
    r = client.post(f"/c/{cid}/picks", data={"kind": "option", "op": "remove", "idx": "0"})
    assert "Archery" not in r.text.split("Class options")[1].split("Feats")[0]


def test_infusion_can_be_taken_more_than_once(client):
    cid = create_character(client, class_key="Artificer|TCE", level="2", race="Tortle|MPMM||")
    for note in ("Bag of Holding", "Goggles of Night"):
        client.post(f"/c/{cid}/picks", data={"kind": "option", "op": "add", "key": "Replicate Magic Item|TCE"})
    html = client.get(f"/c/{cid}/sheet").text
    assert html.count("Replicate Magic Item") >= 2 and "Infusions 4" in html and "Infused Items <b>2</b>" in html
    assert "Shell Defense" in html and "Magical Tinkering" in html and "Infuse Item" in html


def test_feats_dedupe_and_render(client):
    cid = create_character(client, class_key="Barbarian|PHB", race="Goliath|MPMM||", background_key="Giant Foundling|BGG")
    for _ in range(2):
        client.post(f"/c/{cid}/picks", data={"kind": "feat", "op": "add", "key": "Strike of the Giants; Hill|BGG"})
    html = client.get(f"/c/{cid}/sheet").text
    assert html.count("Strike of the Giants; Hill") == 1
    assert "Hill Strike" in html and "Cloud Strike" not in html      # the Hill version only
    assert "Stone&#39;s Endurance" in html or "Stone's Endurance" in html
    assert "Rages <b>3</b>" in html and "Rage Damage <b>+2</b>" in html
    assert "Strength or Constitution" in html or "Prerequisite" in html


def test_counters_and_rests(client):
    cid = create_character(client, class_key="Barbarian|PHB")
    r = client.post(f"/c/{cid}/counters", data={"op": "add", "name": "Rage", "max": "2", "reset": "long"})
    assert "Rage" in r.text and r.text.count('class="pip ') == 2
    client.post(f"/c/{cid}/counters", data={"op": "add", "name": "Second Wind", "max": "1", "reset": "short"})
    r = client.post(f"/c/{cid}/counters", data={"op": "set", "idx": "0", "used": "2"})
    assert r.text.count("pip used") == 2 and "0 left" in r.text
    client.post(f"/c/{cid}/counters", data={"op": "use", "idx": "1"})
    client.post(f"/c/{cid}/rest", data={"kind": "short"})
    html = client.get(f"/c/{cid}/sheet").text
    assert "2 left" not in html.split('id="counters"')[1].split("Second Wind")[0]      # rage still spent
    assert "1 left" in html                                                             # second wind back
    client.post(f"/c/{cid}/rest", data={"kind": "long"})
    assert "pip used" not in client.get(f"/c/{cid}/sheet").text.split('id="counters"')[1].split("</section>")[0]
    r = client.post(f"/c/{cid}/counters", data={"op": "remove", "idx": "0"})
    assert r.text.count("counter-row") == 1 and "Second Wind" in r.text and ">Rage<" not in r.text


def test_new_text_fields_save(client):
    cid = create_character(client)
    client.post(f"/c/{cid}/save", data={"appearance": "age 33 · 5ft 10", "personality": "Blunt.", "allies": "The clan"})
    html = client.get(f"/c/{cid}/sheet").text
    assert 'value="age 33 · 5ft 10"' in html and ">Blunt.</textarea>" in html and ">The clan</textarea>" in html


def test_inventory_links_known_items(client):
    cid = create_character(client)
    client.post(f"/c/{cid}/inventory", data={"op": "add", "name": "Belt of Dwarven Kind", "qty": "1"})
    r = client.post(f"/c/{cid}/inventory", data={"op": "add", "name": "Hand Axe (x2)", "qty": "2"})
    assert "/compendium/peek/item/Belt%20of%20Dwarvenkind%7CDMG" in r.text     # "read" opens the entry in place
    assert "/compendium/peek/item/Handaxe%7CPHB" in r.text
    r = client.post(f"/c/{cid}/inventory", data={"op": "add", "name": "1 x Tinkers Tools", "qty": "1"})
    assert "Tinker%27s%20Tools%7CPHB" in r.text
    peek = client.get("/compendium/peek/item/Belt%20of%20Dwarvenkind%7CDMG")
    assert peek.status_code == 200 and "peek-card" in peek.text and "Dwarvish" in peek.text and "requires attunement" in peek.text
    assert client.get("/compendium/items/Belt%20of%20Dwarvenkind%7CDMG").status_code == 200
