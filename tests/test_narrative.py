"""Health and conditions as the rest of the table sees them; companions get the same."""
from fastapi.testclient import TestClient

from app.main import create_app
from app.narrative import HEALTH_STEPS, describe, health_step
from tests.conftest import WIZARD, create_character, make_settings


def test_health_steps_are_per_tenth():
    assert health_step(17, 17) == 10 and health_step(16, 17) == 10       # 94% still "unhurt"
    assert health_step(9, 17) == 6 and health_step(8, 17) == 5
    assert health_step(1, 17) == 1 and health_step(2, 17) == 2
    assert health_step(0, 17) == 0 and health_step(5, 0) == 0
    assert len(HEALTH_STEPS) == 11
    seen = describe("Wick", 1, 17, ["Prone", "Stunned", "Charmed"])
    assert seen["health"] == "is struggling to stay conscious" and seen["pct"] == 10
    assert seen["looks"] == ["is on the ground", "looks dazed", "seems oddly taken with someone"]
    assert describe("x", 17, 17)["colour"] == "hsl(120, 62%, 52%)" and describe("x", 0, 17)["colour"] == "hsl(0, 62%, 52%)"


def _party(tmp_path):
    app = create_app(make_settings(tmp_path, dm_password="dm"))
    dm = TestClient(app)
    dm.post("/login", data={"password": "dm"})
    a = create_character(dm, name="Aldo")
    b = create_character(dm, name="Bea")
    player = TestClient(app)
    player.headers["x-forwarded-for"] = "203.0.113.5"
    player.post(f"/c/{a}/unlock", data={"password": "x"})
    return dm, player, a, b


def test_players_see_phrases_not_numbers(tmp_path):
    dm, player, a, b = _party(tmp_path)
    dm.post(f"/c/{b}/hp", data={"action": "damage", "amount": "15"})      # Bea: 2/17
    dm.post(f"/c/{b}/conditions", data={"name": "Prone"})
    html = player.get("/").text
    mine, theirs = html.split("Bea")[0], html.split("Bea")[1]
    assert "HP 17/17" in mine                                            # your own card keeps its numbers
    assert "HP 2/17" not in theirs and "AC " not in theirs
    assert "Is barely standing" in theirs and "is on the ground" in theirs
    glance = player.get(f"/party/glance?me={a}").text
    assert "Bea" in glance and "Aldo" not in glance and "2/17" not in glance and "barely standing" in glance
    assert "2/17" in dm.get(f"/party/glance?me={a}").text                # the DM sees numbers
    html = player.get(f"/c/{a}").text
    assert "hx-get=\"/party/glance?me=%d\"" % a in html
    assert "barely standing" in html and "2/17" not in html          # populated on first load, still no numbers


def test_companions_show_when_summoned(tmp_path):
    dm, player, a, b = _party(tmp_path)
    player.post(f"/c/{a}/unlock", data={"password": "x"})
    r = player.post(f"/c/{a}/companions", data={"op": "add", "name": "Pip", "kind": "Owl familiar", "hp_max": "1", "ac": "11"})
    assert "Pip" in r.text and ">dismiss<" in r.text
    assert "Aldo's Pip" in player.get(f"/party/glance?me={b}").text
    r = player.post(f"/c/{a}/companions", data={"op": "summon", "idx": "0"})
    assert ">summon<" in r.text and "Aldo's Pip" not in player.get(f"/party/glance?me={b}").text
    player.post(f"/c/{a}/companions", data={"op": "summon", "idx": "0"})
    player.post(f"/c/{a}/companions", data={"op": "damage", "idx": "0", "amount": "1"})
    glance = dm.get(f"/party/glance?me={b}").text
    assert "Aldo's Pip" in glance and "is down and not moving" in glance
    assert player.post(f"/c/{a}/companions", data={"op": "condition", "idx": "0", "name": "Prone"}).status_code == 403
    r = dm.post(f"/c/{a}/companions", data={"op": "condition", "idx": "0", "name": "Prone"})
    assert 'class="chip on"' in r.text
    r = player.post(f"/c/{a}/companions", data={"op": "update", "idx": "0", "name": "Pip", "kind": "Owl", "hp_max": "3", "ac": "11", "notes": ""})
    assert r.status_code == 204
    r = player.post(f"/c/{a}/companions", data={"op": "heal", "idx": "0", "amount": "9"})
    assert "3</span><span class=\"hp-max\">/ 3" in r.text
    r = player.post(f"/c/{a}/companions", data={"op": "remove", "idx": "0"})
    assert "Pip" not in r.text
