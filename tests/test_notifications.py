"""Anything the DM does to a sheet tells the player; [[links]] open compendium entries in the popup."""
from fastapi.testclient import TestClient

from app.compendium.linkify import linkify, strip_links
from app.main import create_app
from tests.conftest import create_character, make_settings


def _pair(tmp_path):
    app = create_app(make_settings(tmp_path, dm_password="dm"))
    dm = TestClient(app)
    dm.post("/login", data={"password": "dm"})
    cid = create_character(dm, name="Aldo")
    player = TestClient(app)
    player.headers["x-forwarded-for"] = "203.0.113.5"
    player.post(f"/c/{cid}/unlock", data={"password": "x"})
    return dm, player, cid


def _popup(player, cid):
    r = player.get(f"/c/{cid}/inbox")
    return r.text if r.status_code == 200 else ""


def test_dm_changes_fold_into_one_popup(tmp_path):
    dm, player, cid = _pair(tmp_path)
    assert _popup(player, cid) == ""
    dm.post(f"/c/{cid}/conditions", data={"name": "Prone"})
    dm.post(f"/c/{cid}/inspiration", data={"op": "grant"})
    dm.post(f"/c/{cid}/hp", data={"action": "damage", "amount": "4"})
    dm.post(f"/c/{cid}/save", data={"xp": "900", "hp_max": "20"})
    dm.post(f"/c/{cid}/inventory", data={"op": "add", "name": "Potion of Healing", "qty": "2"})
    text = _popup(player, cid)
    assert "Your sheet changed" in text
    first = text.split('data-mid="')[1].split('"')[0]
    dm.post(f"/c/{cid}/inspiration", data={"op": "revoke"})
    assert player.get(f"/c/{cid}/inbox", params={"shown": first}).status_code == 200   # grown text re-renders
    text = _popup(player, cid)
    for needle in ("The DM marked you", ">Prone<", "The DM gave you inspiration", "dealt you 4 damage",
                   "XP 0 → 900", "max HP 17 → 20", "The DM gave you", ">Potion of Healing<", "(x2)"):
        assert needle in text, needle
    assert text.count("modal-head") == 1                                        # one popup, not five
    assert "/compendium/peek/item/Potion%20of%20Healing%7CDMG" in text          # the item is a link in the popup
    assert "/compendium/peek/condition/Prone%7CPHB" in text
    assert "The DM" not in dm.get("/dm/outbox").text                          # automatic notes stay out of Sent
    mid = int(text.split(f"/c/{cid}/inbox/")[1].split('"')[0])
    player.post(f"/c/{cid}/inbox/{mid}")
    assert _popup(player, cid) == ""
    dm.post(f"/c/{cid}/conditions", data={"name": "Prone"})
    assert "The DM cleared" in _popup(player, cid)                              # a new popup after the old one is gone


def test_players_own_changes_do_not_notify(tmp_path):
    dm, player, cid = _pair(tmp_path)
    player.post(f"/c/{cid}/hp", data={"action": "damage", "amount": "4"})
    player.post(f"/c/{cid}/inventory", data={"op": "add", "name": "Rope", "qty": "1"})
    player.post(f"/c/{cid}/save", data={"notes": "hi"})
    assert _popup(player, cid) == ""


def test_links_in_messages_and_the_peek(tmp_path):
    dm, player, cid = _pair(tmp_path)
    dm.post("/dm/messages", data={"kind": "note", "text": "Take the [[Bag of Holding]] and cast [[Bless|spell]]. Not a [[Thingummy]].", "to": [cid]})
    text = _popup(player, cid)
    assert "/compendium/peek/item/Bag%20of%20Holding%7CDMG" in text and "/compendium/peek/spell/Bless%7CPHB" in text
    assert "Thingummy" in text and "[[" not in text
    assert "hx-target='#peek-" in text
    r = player.get("/compendium/peek/spell/Bless%7CPHB")
    assert r.status_code == 200 and "Bless" in r.text and "1st-level enchantment" in r.text and "open in compendium" in r.text
    assert player.get("/compendium/peek/nonsense/x").status_code == 404
    assert "The party" not in dm.get("/dm/outbox").text or "Bag of Holding" in dm.get("/dm/outbox").text
    r = dm.get("/compendium/link-search", params={"q": "bag of h"})
    assert "Bag of Holding" in r.text and "[[Bag of Holding]]" in r.text


def test_linkify_and_strip():
    class C:
        def find(self, kind, name, source=None):
            return {"name": "Bless", "source": "PHB"} if (kind, name) == ("spell", "Bless") else None
    html = linkify("cast [[Bless]] <b>", C(), "#peek-1")
    assert "&lt;b&gt;" in html and "peek-link" in html and "hx-target='#peek-1'" in html
    assert linkify("[[Nothing]]", C()) == "Nothing"
    assert strip_links("a [[b|spell]] c") == "a b c"
