"""Initiative, turns, monsters, loot, and what each seat sees of the fight."""
import random
import re

from fastapi.testclient import TestClient

from app import loot as L
from app import loot_tables as LT
from app import monsters as mon
from app.economy import classify
from app.main import create_app
from tests.conftest import create_character, make_settings


def _table(tmp_path):
    app = create_app(make_settings(tmp_path, dm_password="dm"))
    dm = TestClient(app)
    dm.post("/login", data={"password": "dm"})
    a = create_character(dm, name="Aldo")
    b = create_character(dm, name="Bea", class_key="Barbarian|PHB", race="Goliath|MPMM||", score_dex="14")
    pa, pb = TestClient(app), TestClient(app)
    for p, cid in ((pa, a), (pb, b)):
        p.headers["x-forwarded-for"] = "203.0.113.5"
        p.post(f"/c/{cid}/unlock", data={"password": "x"})
    return dm, pa, pb, a, b


def test_dice_and_monster_numbers():
    assert mon.roll("12") == 12 and mon.roll("2d6+2", random.Random(1)) >= 4 and mon.roll("6d6*100", random.Random(1)) % 100 == 0
    assert mon.cr_value("1/4") == 0.25 and mon.cr_value("15") == 15 and mon.cr_value({"cr": "1/2"}) == 0.5
    assert mon.ac_value({"ac": [{"ac": 15, "from": ["x"]}]}) == 15 and mon.ac_value({"ac": [13]}) == 13
    assert mon.hp_average({"hp": {"average": 7, "formula": "2d6"}}) == 7
    assert mon.carried({"attachedItems": ["scimitar|phb", "shortbow|phb"]}) == ["Scimitar", "Shortbow"]


def test_treasure_tables(comp):
    if not comp.loot:
        return
    coins = L.individual(comp.loot, 0.25, random.Random(2))["coins"]
    assert coins and all(v > 0 for v in coins.values())
    h = L.hoard(comp.loot, 5, random.Random(3))
    assert h["coins"] and isinstance(h["items"], list)
    assert L.coins_text({"gp": 3, "cp": 10}) == "3 gp, 10 cp"


def test_classify_reads_the_rules_text():
    assert classify(["you can enter a rage as a bonus action"]) == {"bonus"}
    assert classify(["you can use your reaction to roll a d12"]) == {"reaction"}
    assert classify(["As an action, you can touch a creature"]) == {"action"}
    assert classify(["Once per turn, when you hit a creature"]) == {"free"}
    assert classify(["You have proficiency in the Stealth skill."]) == set()


def test_fight_from_both_sides(tmp_path):
    dm, pa, pb, a, b = _table(tmp_path)
    assert pa.get("/dm/combat").status_code == 403
    assert pa.post("/dm/combat/start").status_code == 403
    assert pa.get(f"/combat/tracker?me={a}").text == ""                           # nothing on

    r = dm.post("/dm/combat/start", data={"name": "Ambush"})
    assert "Ambush" in r.text and "round <b>1</b>" in r.text and "waiting on initiative: Aldo, Bea" in r.text
    popup = pa.get(f"/c/{a}/inbox")
    assert "Roll initiative" in popup.text and 'name="answer"' in popup.text
    mid = int(popup.text.split(f"/c/{a}/inbox/")[1].split('"')[0])
    assert "Type the number" in pa.post(f"/c/{a}/inbox/{mid}", data={"answer": "high"}).text
    assert pa.post(f"/c/{a}/inbox/{mid}", data={"answer": "17"}).text == ""
    assert "Aldo" not in dm.get("/dm/combat").text.split("waiting on initiative")[1].split("<")[0]

    r = dm.get("/dm/combat/monsters", params={"q": "gobl"})
    assert "Goblin" in r.text and 'data-key="Goblin|MM"' in r.text
    r = dm.post("/dm/combat/add", data={"monster": "Goblin|MM", "count": "2", "hp": "average"})
    assert "Goblin 1" in r.text and "Goblin 2" in r.text and "Scimitar" in r.text     # carried loot
    r = dm.post("/dm/combat/add", data={"name": "Bandit Captain", "hp_max": "30", "ac": "15", "initiative": "3", "cr": "2"})
    assert "Bandit Captain" in r.text
    assert "Humanoid - pockets and pack - suits it" in dm.get("/dm").text         # the full page offers the tables too

    # Bea sets initiative from her tracker; a hidden goblin stays hidden from players
    r = pb.post(f"/c/{b}/initiative", data={"initiative": "9"})
    assert "Bea" in r.text and "(you)" in r.text
    html = dm.get("/dm/combat").text
    rows = html.split("<tr ")[1:]
    gob1_id = next(int(x.split('hx-post="/dm/combat/')[1].split('"')[0]) for x in rows if "Goblin 1" in x)
    gob2_id = next(int(x.split('hx-post="/dm/combat/')[1].split('"')[0]) for x in rows if "Goblin 2" in x)
    dm.post(f"/dm/combat/{gob1_id}", data={"op": "initiative", "initiative": "12"})     # the goblins rolled d20+2: pin them
    dm.post(f"/dm/combat/{gob2_id}", data={"op": "initiative", "initiative": "5"})
    dm.post(f"/dm/combat/{gob2_id}", data={"op": "visible"})
    seen = pa.get(f"/combat/tracker?me={a}").text
    assert "Goblin 1" in seen and "Goblin 2" not in seen and "looks unhurt" in seen and "7/7" not in seen
    assert "Goblin 2" in dm.get(f"/combat/tracker?me=0").text                      # the DM sees it

    # turns: Aldo (17) first, dead goblins are skipped, rounds tick over
    html = dm.get("/dm/combat").text
    assert "<span class=\"turn-now\">Aldo</span>" in html
    strip = pa.get(f"/combat/strip?me={a}").text
    assert "YOUR TURN" in strip
    dm.post(f"/dm/combat/{gob1_id}", data={"op": "damage", "amount": "7"})
    assert "is down and not moving" in dm.get("/dm/combat").text
    order = []
    for _ in range(6):
        html = dm.post("/dm/combat/turn").text
        order.append(html.split('<span class="turn-now">')[1].split("<")[0])
    assert order == ["Bea", "Goblin 2", "Bandit Captain", "Aldo", "Bea", "Goblin 2"] and "round <b>2</b>" in html

    # loot: the DM rolls the table that suits a goblin, hands a piece out, then the rest
    html = dm.get("/dm/combat").text
    suits = [x for x in re.findall(r'<option value="(\d+)">([^<]+)</option>', html) if "suits it" in x[1]]
    assert suits and suits[0][1].startswith("Humanoid")
    r = dm.post(f"/dm/combat/{gob1_id}/loot", data={"op": "roll", "table": suits[0][0]})
    assert r.headers["HX-Trigger"].startswith('{"toast": "Goblin 1: ')
    assert " cp" in r.text or " sp" in r.text or " ep" in r.text or " gp" in r.text or " pp" in r.text
    r = dm.post(f"/dm/combat/{gob1_id}/loot", data={"op": "give", "idx": "0", "to": str(a)})
    assert "Scimitar" in pa.get(f"/c/{a}/sheet").text
    note = pa.get(f"/c/{a}/inbox").text
    assert "From Goblin 1" in note and "Scimitar" in note
    tracker = pa.get(f"/combat/tracker?me={a}").text
    assert "search the body" not in tracker and "Shortbow" not in tracker            # players don't help themselves
    assert pa.post(f"/c/{a}/loot/{gob1_id}", data={"idx": "0"}).status_code in (404, 405)
    before = pa.get(f"/c/{a}/sheet").text
    dm.post(f"/dm/combat/{gob1_id}/loot", data={"op": "give", "idx": "-1", "to": str(a)})
    after = pa.get(f"/c/{a}/sheet").text
    assert "Shortbow" in after and before != after
    assert "0 items" in dm.get("/dm/combat").text.split(f"loot-{gob1_id}")[1].split("</summary>")[0]

    # end: the order disappears, pending initiative prompts are cancelled
    dm.post("/dm/combat/end")
    assert pa.get(f"/combat/tracker?me={a}").text == "" and "Start combat" in dm.get("/dm/combat").text
    assert pb.get(f"/c/{b}/inbox").status_code == 204


def test_actions_panel_reads_the_sheet(tmp_path):
    dm, pa, pb, a, b = _table(tmp_path)
    dm.post(f"/c/{b}/attacks", data={"op": "add", "name": "Handaxe"})
    dm.post(f"/c/{b}/attacks", data={"op": "add", "name": "Dagger"})
    dm.post(f"/c/{b}/inventory", data={"op": "add", "name": "Potion of Healing", "qty": "1"})
    html = pb.get(f"/c/{b}").text
    panel = html.split('id="actions-panel"')[1].split("</section>")[0]
    assert "Attack: Handaxe" in panel and "Off-hand attack: Dagger" in panel
    assert "Rage" in panel and "Stone" in panel and "Drink a potion" in panel and "house rule" in panel
    assert "Opportunity attack" in panel and "Dash" in panel and "Use an Object" in panel
    dm.post(f"/c/{b}/attacks", data={"op": "remove", "idx": "1"})                       # just "Handaxe (x2)" left
    dm.post(f"/c/{b}/attacks", data={"op": "update", "idx": "0", "name": "Handaxe (x2)"})
    panel = pb.get(f"/c/{b}").text.split('id="actions-panel"')[1].split("</section>")[0]
    assert "Off-hand attack: Handaxe (x2)" in panel                                        # a pair counts as two
    wiz = pa.get(f"/c/{a}").text.split('id="actions-panel"')[1].split("</section>")[0]
    assert "Off-hand" not in wiz and "Dodge" in wiz and "Attack: " not in wiz


def test_monster_stat_block_is_dm_only(tmp_path):
    dm, pa, pb, a, b = _table(tmp_path)
    assert pa.get("/compendium/peek/monster/Goblin%7CMM").status_code == 403
    r = dm.get("/compendium/peek/monster/Goblin%7CMM")
    assert r.status_code == 200 and "Nimble Escape" in r.text and "Scimitar" in r.text and "CR 1/4" in r.text


def test_loot_tables_roll_by_what_it_was(tmp_path, comp):
    dm, pa, pb, a, b = _table(tmp_path)
    with dm.app.state.db() as session:
        tables = LT.all_tables(session)
        assert len(tables) == len(LT.DEFAULTS) and all(t.builtin for t in tables)
        by = {t.name.split(" - ")[0].split(" (")[0]: t for t in tables}
        goblin = LT.suggestions(tables, "humanoid", 0.25)
        assert goblin[0]["table"].name.startswith("Humanoid") and goblin[0]["rank"] == 2
        assert {s["table"].name: s["rank"] for s in goblin}["Beast - hide and parts"] == 0
        assert {s["table"].name: s["rank"] for s in goblin}["Coins only (DMG, by challenge rating)"] == 1
        wolf = LT.roll_table(by["Beast"], comp.loot, 0.25, random.Random(4))
        assert not wolf["coins"] and all(it["name"] not in ("Nothing usable",) for it in wolf["items"])
        pockets = [LT.roll_table(by["Humanoid"], comp.loot, 0.25, random.Random(i)) for i in range(20)]
        assert all(p["coins"] for p in pockets) and any(p["items"] for p in pockets)
        assert all(not it["name"].lower().startswith("nothing") for p in pockets for it in p["items"])
        assert LT.roll_table(by["Treasure hoard"], comp.loot, 5, random.Random(1))["coins"]
        assert LT.result_text({"items": [{"name": "Torch", "qty": 2}], "coins": {"gp": 3}}) == "2 x Torch, 3 gp"
        assert LT.result_text({"items": [], "coins": {}}) == "nothing"


def test_loot_table_editor(tmp_path):
    dm, pa, pb, a, b = _table(tmp_path)
    assert pa.get("/dm/loot").status_code == 403
    html = dm.get("/dm/loot").text
    assert "Humanoid - pockets and pack" in html and "Beast - hide and parts" in html
    beast_id = int(html.split("Beast - hide and parts")[0].rsplit('href="/dm/loot/', 1)[1].split('"')[0])

    r = dm.post("/dm/loot", data={"name": "Vampire spawn", "copy": str(beast_id)}, follow_redirects=False)
    tid = int(r.headers["location"].rsplit("/", 1)[1])
    page_html = dm.get(f"/dm/loot/{tid}").text
    assert "Vampire spawn" in page_html and "Hide or pelt" in page_html
    r = dm.post(f"/dm/loot/{tid}", data={"name": "Vampire spawn", "types": ["undead"], "cr_min": "1", "cr_max": "10",
                                         "mode": "table", "draws": "1d2", "coins_mode": "custom", "gp": "2d6"})
    assert r.status_code == 204 and "toast" in r.headers["HX-Trigger"]
    r = dm.post(f"/dm/loot/{tid}/entries", data={"op": "add", "name": "Signet ring", "qty": "1", "weight": "3", "notes": "a noble house"})
    assert "Signet ring" in r.text
    n = r.text.count('name="op" value="update"')
    r = dm.post(f"/dm/loot/{tid}/entries", data={"op": "update", "idx": str(n - 1), "name": "Signet ring", "qty": "2", "weight": "9", "notes": ""})
    assert 'value="9"' in r.text and "toast" in r.headers["HX-Trigger"]
    r = dm.post(f"/dm/loot/{tid}/entries", data={"op": "remove", "idx": "0"})
    assert "Nothing usable" not in r.text and "Hide or pelt" in r.text and "Signet ring" in r.text
    with dm.app.state.db() as session:
        t = session.get(LT.LootTable, tid)
        assert t.types == ["undead"] and t.cr_min == 1 and t.cr_max == 10 and t.coins == {"gp": "2d6"} and t.draws == "1d2"
        assert LT.rank(t, "undead", 3) == 2 and LT.rank(t, "undead", 12) == 0 and LT.rank(t, "beast", 3) == 0
    r = dm.post(f"/dm/loot/{tid}/roll", data={"cr": "3"})
    assert r.status_code == 200 and (" gp" in r.text or "nothing this time" in r.text)

    # delete a built-in, restore brings only it back
    dm.post(f"/dm/loot/{beast_id}/delete")
    assert "Beast - hide and parts" not in dm.get("/dm/loot").text
    dm.post("/dm/loot/restore")
    html = dm.get("/dm/loot").text
    assert "Beast - hide and parts" in html and "Vampire spawn" in html               # restored, and the edited one kept
    dm.post(f"/dm/loot/{tid}/delete")
    assert "Vampire spawn" not in dm.get("/dm/loot").text
