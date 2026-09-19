"""Themes follow the class unless a character picks one; art is served and uploadable."""
import io

from app.themes import THEMES, theme_key, theme_style
from tests.conftest import create_character


class _Ch:
    def __init__(self, theme=""):
        self.theme = theme


def test_theme_key_prefers_the_character_then_the_class():
    assert theme_key(_Ch(), {"name": "Wizard"}) == "wizard"
    assert theme_key(_Ch("iron"), {"name": "Artificer"}) == "iron"
    assert theme_key(_Ch("nonsense"), {"name": "Artificer"}) == "artificer"
    assert theme_key(_Ch(), None) == "default"
    assert "--red: #4a6fd6" in theme_style("wizard") and "--glow:" in theme_style("wizard")
    assert {"artificer", "barbarian", "cleric", "rogue", "warlock", "iron", "lorbah"} <= set(THEMES)


def test_pages_carry_the_theme(client):
    cid = create_character(client)                                  # a wizard
    assert 'style="--red: #4a6fd6' in client.get(f"/c/{cid}").text
    assert 'style="--red: #4a6fd6' in client.get(f"/c/{cid}/sheet").text
    assert 'class="card themed' in client.get("/").text and "--red: #4a6fd6" in client.get("/").text
    r = client.post(f"/c/{cid}/save", data={"theme": "lorbah"})
    assert r.headers.get("HX-Refresh") == "true"
    assert 'style="--red: #9c3e30' in client.get(f"/c/{cid}").text
    client.post(f"/c/{cid}/save", data={"theme": "not-a-theme"})
    assert 'style="--red: #9c3e30' in client.get(f"/c/{cid}").text            # ignored
    assert "--red: #c0392b" not in client.get("/compendium").text              # only character pages are themed


def test_art_upload_and_serve(client):
    cid = create_character(client)
    assert client.get(f"/c/{cid}/art/portrait").status_code == 404
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = client.post(f"/c/{cid}/art", data={"kind": "portrait"}, files={"file": ("me.png", io.BytesIO(png), "image/png")})
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true"
    r = client.get(f"/c/{cid}/art/portrait")
    assert r.status_code == 200 and r.content == png
    assert client.get(f"/c/{cid}/art/token").status_code == 200              # token falls back to the portrait
    assert f'src="/c/{cid}/art/portrait"' in client.get(f"/c/{cid}").text
    assert f'src="/c/{cid}/art/token"' in client.get("/").text
    r = client.post(f"/c/{cid}/art", data={"kind": "token"}, files={"file": ("x.txt", io.BytesIO(b"nope"), "text/plain")})
    assert "PNG, JPG or WebP" in r.headers["HX-Trigger"]
