"""Each character has its own password; the DM sees everything."""
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import WIZARD, create_character, make_settings


def _player(app) -> TestClient:
    c = TestClient(app)
    c.headers["x-forwarded-for"] = "203.0.113.5"    # not the host machine, so not the DM
    return c


def test_first_opener_sets_the_password_then_stays_in(tmp_path):
    app = create_app(make_settings(tmp_path))
    p = _player(app)
    r = p.post("/new", data=WIZARD, follow_redirects=False)
    cid = int(r.headers["location"].split("/")[2])
    assert r.headers["location"] == f"/c/{cid}/unlock?next=/c/{cid}/sheet"
    r = p.get(f"/c/{cid}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/c/{cid}/unlock"
    assert "Nobody has claimed this sheet yet" in p.get(f"/c/{cid}/unlock").text
    assert "Type something" in p.post(f"/c/{cid}/unlock", data={"password": ""}).text
    r = p.post(f"/c/{cid}/unlock", data={"password": "owlbear", "next": f"/c/{cid}/sheet"}, follow_redirects=False)
    assert r.status_code == 303 and "am_chars" in r.cookies and r.headers["location"] == f"/c/{cid}/sheet"
    r = p.get(f"/c/{cid}/unlock?next=https://evil.example/", follow_redirects=False)
    assert r.headers["location"] == f"/c/{cid}"          # off-site `next` is ignored
    assert p.get(f"/c/{cid}").status_code == 200
    assert p.post(f"/c/{cid}/save", data={"notes": "hi"}).status_code == 200
    assert p.get(f"/c/{cid}/unlock", follow_redirects=False).headers["location"] == f"/c/{cid}"   # nothing to do


def test_others_need_the_password(tmp_path):
    app = create_app(make_settings(tmp_path))
    owner = _player(app)
    cid = int(owner.post("/new", data=WIZARD, follow_redirects=False).headers["location"].split("/")[2])
    owner.post(f"/c/{cid}/unlock", data={"password": "owlbear"})

    other = _player(app)
    assert other.get(f"/c/{cid}", follow_redirects=False).status_code == 303
    r = other.post(f"/c/{cid}/save", data={"notes": "hax"})
    assert r.status_code == 401 and r.headers["HX-Redirect"] == f"/c/{cid}/unlock"
    assert "This sheet has a password" in other.get(f"/c/{cid}/unlock").text
    assert "not it" in other.post(f"/c/{cid}/unlock", data={"password": "nope"}).text
    assert other.get(f"/c/{cid}", follow_redirects=False).status_code == 303
    other.post(f"/c/{cid}/unlock", data={"password": "owlbear"})
    assert other.get(f"/c/{cid}").status_code == 200
    # a second character stays locked for the same browser
    cid2 = int(owner.post("/new", data={**WIZARD, "name": "Second"}, follow_redirects=False).headers["location"].split("/")[2])
    owner.post(f"/c/{cid2}/unlock", data={"password": "x"})
    assert other.get(f"/c/{cid2}", follow_redirects=False).status_code == 303
    assert other.get(f"/c/{cid}").status_code == 200


def test_forged_unlock_cookie_is_ignored(tmp_path):
    app = create_app(make_settings(tmp_path))
    owner = _player(app)
    cid = int(owner.post("/new", data=WIZARD, follow_redirects=False).headers["location"].split("/")[2])
    owner.post(f"/c/{cid}/unlock", data={"password": "owlbear"})
    thief = _player(app)
    thief.cookies.set("am_chars", f"{cid}.0000deadbeef")
    assert thief.get(f"/c/{cid}", follow_redirects=False).status_code == 303


def test_dm_opens_everything_and_can_reset(tmp_path):
    app = create_app(make_settings(tmp_path, dm_password="dm"))
    owner = _player(app)
    cid = int(owner.post("/new", data=WIZARD, follow_redirects=False).headers["location"].split("/")[2])
    owner.post(f"/c/{cid}/unlock", data={"password": "owlbear"})

    dm = TestClient(app)
    assert dm.get(f"/c/{cid}", follow_redirects=False).status_code == 303   # localhost is no longer the DM
    assert "The DM password" in dm.get("/login").text
    dm.post("/login", data={"password": "dm"})
    assert dm.get(f"/c/{cid}").status_code == 200
    assert "Reset password" in dm.get(f"/c/{cid}/sheet").text
    assert _player(app).post(f"/c/{cid}/password/reset").status_code in (401, 403)
    assert dm.post(f"/c/{cid}/password/reset").status_code == 204
    newcomer = _player(app)
    assert "Nobody has claimed this sheet yet" in newcomer.get(f"/c/{cid}/unlock").text
    owner_again = owner.get(f"/c/{cid}")
    assert owner_again.status_code == 200          # the original browser's unlock cookie still works


def test_party_page_shows_who_is_claimed(tmp_path):
    app = create_app(make_settings(tmp_path))
    p = _player(app)
    cid = int(p.post("/new", data=WIZARD, follow_redirects=False).headers["location"].split("/")[2])
    assert "unclaimed - open it to set a password" in p.get("/").text
    p.post(f"/c/{cid}/unlock", data={"password": "x"})
    assert "card-lock" not in p.get("/").text
    other = _player(app)
    html = other.get("/").text
    assert 'class="card-lock">password<' in html
    assert "card-lock" not in TestClient(app).get("/").text   # the DM sees no locks
