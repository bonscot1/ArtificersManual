from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def test_open_mode_localhost_is_dm(client):
    r = client.get("/")
    assert r.status_code == 200 and 'class="pill pill-dm"' in r.text


def test_table_password_gates_everything(tmp_path):
    c = TestClient(create_app(make_settings(tmp_path, table_password="tbl", dm_password="dm")))
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert c.post("/new", data={"name": "x"}, follow_redirects=False).status_code == 401
    assert c.post("/login", data={"password": "nope"}).status_code == 200   # re-shows the form
    r = c.post("/login", data={"password": "tbl"}, follow_redirects=False)
    assert r.status_code == 303 and "am_auth" in r.cookies
    r = c.get("/")
    assert r.status_code == 200 and "pill-dm" not in r.text


def test_dm_password_switches_off_loopback_shortcut(tmp_path):
    c = TestClient(create_app(make_settings(tmp_path, dm_password="dm")))
    assert "pill-dm" not in c.get("/").text                      # table is open, but nobody is DM yet
    c.post("/login", data={"password": "dm"}, follow_redirects=False)
    assert "pill-dm" in c.get("/").text


def test_forged_cookie_is_ignored(tmp_path):
    c = TestClient(create_app(make_settings(tmp_path, table_password="tbl", dm_password="dm")))
    c.cookies.set("am_auth", "dm.0000")
    assert c.get("/", follow_redirects=False).status_code == 303


def test_proxied_request_is_not_local(tmp_path):
    c = TestClient(create_app(make_settings(tmp_path)))
    r = c.get("/", headers={"cf-connecting-ip": "203.0.113.9"})
    assert r.status_code == 200 and "pill-dm" not in r.text
