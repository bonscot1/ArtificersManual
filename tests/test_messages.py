"""DM messages: notes, choices and questions that pop up for the right character."""
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import create_character, make_settings


def _table(tmp_path):
    app = create_app(make_settings(tmp_path, dm_password="dm"))
    dm = TestClient(app)
    dm.post("/login", data={"password": "dm"})
    a, b = create_character(dm, name="Aldo"), create_character(dm, name="Bea")
    pa, pb = TestClient(app), TestClient(app)
    for p, cid in ((pa, a), (pb, b)):
        p.headers["x-forwarded-for"] = "203.0.113.5"
        p.post(f"/c/{cid}/unlock", data={"password": "x"})
    return dm, pa, pb, a, b


def test_dm_screen_is_dm_only(tmp_path):
    dm, pa, pb, a, b = _table(tmp_path)
    assert pa.get("/dm").status_code == 403
    assert pa.post("/dm/messages", data={"kind": "note", "text": "hi", "to": [a]}).status_code == 403
    html = dm.get("/dm").text
    assert "Aldo" in html and "Bea" in html and 'name="to"' in html and "17</b>" in html    # numbers, not phrases


def test_note_pops_up_for_the_recipient_until_dismissed(tmp_path):
    dm, pa, pb, a, b = _table(tmp_path)
    assert pa.get(f"/c/{a}/inbox").status_code == 204
    r = dm.post("/dm/messages", data={"kind": "note", "text": "You hear a whisper.", "to": [a]})
    assert "sent-ok" in r.text and "Sent to 1." in r.text and "waiting" in r.text
    r = pa.get(f"/c/{a}/inbox")
    assert r.status_code == 200 and "You hear a whisper." in r.text and ">OK<" in r.text
    assert pb.get(f"/c/{b}/inbox").status_code == 204                      # Bea gets nothing
    assert f'hx-get="/c/{a}/inbox"' in pa.get(f"/c/{a}").text             # the page polls for it
    mid = int(r.text.split(f"/c/{a}/inbox/")[1].split('"')[0])
    assert pa.get(f"/c/{a}/inbox", params={"shown": mid}).status_code == 204       # already on screen: no re-render
    assert pa.get(f"/c/{a}/inbox", params={"shown": "999"}).status_code == 200
    r = pa.post(f"/c/{a}/inbox/{mid}")
    assert r.status_code == 200 and r.text == ""
    assert pa.get(f"/c/{a}/inbox").status_code == 204
    assert "read" in dm.get("/dm/outbox").text and "waiting" not in dm.get("/dm/outbox").text


def test_choice_and_question_record_answers(tmp_path):
    dm, pa, pb, a, b = _table(tmp_path)
    r = dm.post("/dm/messages", data={"kind": "choice", "text": "Two items on the altar. Which do you take?",
                                      "options": "The sword\nThe bow\n", "to": [a, b]})
    assert "Sent to 2." in r.text
    r = pa.get(f"/c/{a}/inbox")
    assert "The sword" in r.text and "The bow" in r.text and "1 more waiting" not in r.text
    mid = int(r.text.split(f"/c/{a}/inbox/")[1].split('"')[0])
    assert "Pick one of the options" in pa.post(f"/c/{a}/inbox/{mid}", data={"answer": "The cat"}).text
    assert pa.post(f"/c/{a}/inbox/{mid}", data={"answer": "The bow"}).text == ""
    dm.post("/dm/messages", data={"kind": "prompt", "text": "What do you shout?", "to": [b]})
    r = pb.get(f"/c/{b}/inbox")
    assert "Which do you take" in r.text and "1 more waiting" in r.text
    mid_b = int(r.text.split(f"/c/{b}/inbox/")[1].split('"')[0])
    r = pb.post(f"/c/{b}/inbox/{mid_b}", data={"answer": "The sword"})
    assert "What do you shout?" in r.text and 'name="answer"' in r.text    # the next one follows straight on
    mid_q = int(r.text.split(f"/c/{b}/inbox/")[1].split('"')[0])
    assert "Type a reply first" in pb.post(f"/c/{b}/inbox/{mid_q}", data={"answer": "  "}).text
    assert pb.post(f"/c/{b}/inbox/{mid_q}", data={"answer": "For Silverdeep!"}).text == ""
    out = dm.get("/dm/outbox").text
    assert "The bow" in out and "For Silverdeep!" in out and out.count("The sword") >= 2


def test_validation_and_cancel(tmp_path):
    dm, pa, pb, a, b = _table(tmp_path)
    assert "Write the message first" in dm.post("/dm/messages", data={"kind": "note", "text": " ", "to": [a]}).text
    assert "Pick who" in dm.post("/dm/messages", data={"kind": "note", "text": "x"}).text
    assert "at least two options" in dm.post("/dm/messages", data={"kind": "choice", "text": "x", "options": "one", "to": [a]}).text
    dm.post("/dm/messages", data={"kind": "note", "text": "Never mind.", "to": [a]})
    mid = int(pa.get(f"/c/{a}/inbox").text.split(f"/c/{a}/inbox/")[1].split('"')[0])
    assert "cancelled" in dm.post(f"/dm/messages/{mid}/cancel").text
    assert pa.get(f"/c/{a}/inbox").status_code == 204
    assert pb.post(f"/c/{b}/inbox/{mid}").status_code == 404               # not Bea's message
