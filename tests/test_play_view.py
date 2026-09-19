"""The play view: read-only except what changes mid-session."""
from tests.conftest import create_character


def test_play_view_is_the_landing_page_and_is_read_only(client):
    cid = create_character(client)
    client.post(f"/c/{cid}/spells", data={"op": "add", "key": "Fireball|PHB"})
    client.post(f"/c/{cid}/attacks", data={"op": "add", "name": "Dagger"})
    client.post(f"/c/{cid}/counters", data={"op": "add", "name": "Arcane Recovery", "max": "1", "reset": "long"})
    html = client.get(f"/c/{cid}").text
    assert "Edit sheet" in html and 'href="/c/%d/sheet"' % cid in html
    # editable at the table
    for needle in ('name="notes"', 'name="amount"', 'class="pip', 'title="prepared"', 'name="cur_gp"', 'value="add"'):
        assert needle in html, needle
    # not editable at the table
    for needle in ('name="score_str"', 'name="skill_prof"', 'name="class_key"', "Add a spell", "pick-add",
                   'name="damage"', "counter-add", '"op": "remove", "key"', '"kind": "feat", "op": "remove"',
                   'name="notes_dm"'):
        assert needle not in html, needle
    assert "Fey Ancestry" in html and "Arcane Recovery" in html and "Dagger" in html and "Fireball" in html


def test_play_view_swaps_stay_read_only(client):
    cid = create_character(client)
    client.post(f"/c/{cid}/spells", data={"op": "add", "key": "Fireball|PHB"})
    r = client.post(f"/c/{cid}/spells", data={"op": "prepare", "key": "Fireball|PHB", "view": "play"})
    assert 'checked title="prepared"' in r.text and "Add a spell" not in r.text and 'title="remove"' not in r.text
    client.post(f"/c/{cid}/counters", data={"op": "add", "name": "Rage", "max": "2"})
    r = client.post(f"/c/{cid}/counters", data={"op": "set", "idx": "0", "used": "1", "view": "play"})
    assert "pip used" in r.text and "counter-add" not in r.text
    r = client.post(f"/c/{cid}/save", data={"notes": "met a hag"})
    assert r.status_code == 200 and "met a hag" in client.get(f"/c/{cid}").text


def test_removed_inventory_can_be_put_back(client):
    cid = create_character(client)
    client.post(f"/c/{cid}/inventory", data={"op": "add", "name": "Potion of Healing", "qty": "2"})
    client.post(f"/c/{cid}/inventory", data={"op": "add", "name": "Rope", "qty": "1"})
    r = client.post(f"/c/{cid}/inventory", data={"op": "remove", "idx": "0"})
    assert "Removed (1)" in r.text and "put back" in r.text
    assert r.text.count('name="name" value="') == 1                       # only Rope is still carried
    r = client.post(f"/c/{cid}/inventory", data={"op": "restore", "idx": "0"})
    assert "Removed (" not in r.text and 'value="Potion of Healing"' in r.text
    client.post(f"/c/{cid}/inventory", data={"op": "remove", "idx": "1"})
    r = client.post(f"/c/{cid}/inventory", data={"op": "forget", "idx": "0"})
    assert "Removed (" not in r.text and 'value="Potion of Healing"' not in r.text


def test_new_character_lands_on_the_editor_after_claiming(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from tests.conftest import WIZARD, make_settings
    p = TestClient(create_app(make_settings(tmp_path)))
    p.headers["x-forwarded-for"] = "203.0.113.5"
    r = p.post("/new", data=WIZARD, follow_redirects=False)
    cid = int(r.headers["location"].split("/")[2])
    r = p.post(f"/c/{cid}/unlock", data={"password": "x", "next": f"/c/{cid}/sheet"}, follow_redirects=False)
    assert r.headers["location"] == f"/c/{cid}/sheet"
    assert "Character sheet" in p.get(f"/c/{cid}/sheet").text
    assert "Edit sheet" in p.get(f"/c/{cid}").text
