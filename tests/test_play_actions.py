"""Casting, concentration, inspiration and the DM-only statuses on the play view."""
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import WIZARD, create_character, make_settings


def _add(client, cid, key, prepared=True):
    client.post(f"/c/{cid}/spells", data={"op": "add", "key": key})
    if prepared:
        client.post(f"/c/{cid}/spells", data={"op": "prepare", "key": key})


def test_cast_options_follow_the_slots(client):
    cid = create_character(client)                      # wizard 3: 4 x 1st, 2 x 2nd
    _add(client, cid, "Magic Missile|PHB")
    _add(client, cid, "Fireball|PHB")
    r = client.get(f"/c/{cid}/cast-options", params={"key": "Magic Missile|PHB"})
    assert "1st (4 left)" in r.text and "2nd (2 left)" in r.text and "Ritual" not in r.text
    r = client.get(f"/c/{cid}/cast-options", params={"key": "Fireball|PHB"})
    assert "no slot left" in r.text                     # no 3rd-level slots yet
    assert client.get(f"/c/{cid}/cast-options", params={"key": "Wish|PHB"}).status_code == 404
    r = client.get(f"/c/{cid}/cast-options", params={"key": "Magic Missile|PHB", "cancel": "1"})
    assert ">Cast<" in r.text and "left)" not in r.text


def test_cast_spends_the_slot_and_tracks_concentration(client):
    cid = create_character(client)
    _add(client, cid, "Magic Missile|PHB")
    _add(client, cid, "Web|PHB")
    _add(client, cid, "Detect Magic|PHB")
    _add(client, cid, "Fire Bolt|PHB", prepared=False)
    r = client.post(f"/c/{cid}/cast", data={"key": "Magic Missile|PHB", "slot": "2"})
    assert r.status_code == 200 and "Cast Magic Missile (2nd-level slot)" in r.headers["HX-Trigger"]
    assert "2nd (1 left)" in client.get(f"/c/{cid}/cast-options", params={"key": "Magic Missile|PHB"}).text
    r = client.post(f"/c/{cid}/cast", data={"key": "Web|PHB", "slot": "2"})
    assert "Concentrating" in r.text and "<b>Web</b>" in r.text            # the HUD comes back out of band
    r = client.post(f"/c/{cid}/cast", data={"key": "Web|PHB", "slot": "2"})
    assert "No slot left" in r.headers["HX-Trigger"]                        # both 2nd-level slots are gone
    r = client.post(f"/c/{cid}/cast", data={"key": "Detect Magic|PHB", "slot": "ritual"})
    assert "(ritual)" in r.headers["HX-Trigger"] and "concentration on Web ended" in r.headers["HX-Trigger"]
    assert "<b>Detect Magic</b>" in r.text
    r = client.post(f"/c/{cid}/cast", data={"key": "Fire Bolt|PHB", "slot": "cantrip"})
    assert "Cast Fire Bolt (cantrip)" in r.headers["HX-Trigger"]
    assert "1st (4 left)" in client.get(f"/c/{cid}/cast-options", params={"key": "Magic Missile|PHB"}).text
    r = client.post(f"/c/{cid}/concentration")
    assert "Concentration on Detect Magic ended" in r.headers["HX-Trigger"] and "Concentrating" not in r.text


def test_unprepared_spells_cannot_be_cast(client):
    cid = create_character(client)
    _add(client, cid, "Magic Missile|PHB", prepared=False)
    assert client.post(f"/c/{cid}/cast", data={"key": "Magic Missile|PHB", "slot": "1"}).status_code == 400
    html = client.get(f"/c/{cid}").text
    assert "Nothing ready to cast" in html or "Magic Missile" not in html.split("all-spells")[0]


def test_warlock_casts_from_pact_slots(client):
    cid = create_character(client, class_key="Warlock|PHB", level="3")
    _add(client, cid, "Hex|PHB", prepared=False)        # known caster: everything known is ready
    r = client.get(f"/c/{cid}/cast-options", params={"key": "Hex|PHB"})
    assert "Pact 2nd (2 left)" in r.text
    client.post(f"/c/{cid}/cast", data={"key": "Hex|PHB", "slot": "pact"})
    assert "Pact 2nd (1 left)" in client.get(f"/c/{cid}/cast-options", params={"key": "Hex|PHB"}).text
    client.post(f"/c/{cid}/rest", data={"kind": "short"})
    assert "Pact 2nd (2 left)" in client.get(f"/c/{cid}/cast-options", params={"key": "Hex|PHB"}).text


def test_inspiration_and_conditions_are_the_dms_to_give(tmp_path):
    app = create_app(make_settings(tmp_path, dm_password="dm"))
    dm = TestClient(app)
    dm.post("/login", data={"password": "dm"})
    cid = create_character(dm)
    player = TestClient(app)
    player.headers["x-forwarded-for"] = "203.0.113.5"
    player.post(f"/c/{cid}/unlock", data={"password": "x"})

    assert player.post(f"/c/{cid}/inspiration", data={"op": "grant"}).status_code == 403
    assert "No inspiration to spend" in player.post(f"/c/{cid}/inspiration", data={"op": "use"}).headers["HX-Trigger"]
    r = dm.post(f"/c/{cid}/inspiration", data={"op": "grant"})
    assert 'class="token on"' in r.text
    html = player.get(f"/c/{cid}").text
    assert 'class="token on"' in html and ">spend<" in html and ">grant<" not in html
    r = player.post(f"/c/{cid}/inspiration", data={"op": "use"})
    assert "Inspiration spent" in r.headers["HX-Trigger"] and 'class="token on"' not in r.text
    # the sheet's checkbox and XP are ignored for players
    player.post(f"/c/{cid}/save", data={"_lists": "inspiration", "inspiration": "on", "xp": "9999"})
    html = dm.get(f"/c/{cid}/sheet").text
    assert 'name="inspiration"' in html and 'name="inspiration" checked' not in html and 'value="9999"' not in html

    assert player.post(f"/c/{cid}/conditions", data={"name": "Prone"}).status_code == 403
    r = dm.post(f"/c/{cid}/conditions", data={"name": "Prone", "view": "play"})
    assert 'id="hud"' in r.text and 'class="chip on"' in r.text
    html = player.get(f"/c/{cid}").text
    assert 'class="chip warn"' in html and "Prone" in html and f'hx-post="/c/{cid}/conditions"' not in html
    assert f'hx-post="/c/{cid}/conditions"' in dm.get(f"/c/{cid}").text
