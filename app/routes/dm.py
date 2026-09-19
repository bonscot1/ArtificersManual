"""The DM screen: the party with numbers, and messages to the players."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select

from ..db import Character, Message, _now
from ..sheet import build_sheet
from ..templating import page

router = APIRouter(prefix="/dm")


def _guard(request: Request) -> None:
    if request.state.role != "dm":
        raise HTTPException(403, "DM only")


def _board(request: Request, session) -> list[dict]:
    comp = request.app.state.compendium
    return [build_sheet(ch, comp) for ch in session.scalars(select(Character).order_by(Character.name)).all()]


def _outbox(session, limit: int = 40) -> list[dict]:
    """Recent messages grouped by batch, newest first."""
    rows = session.scalars(select(Message).order_by(Message.id.desc()).limit(limit * 4)).all()
    names = {c.id: c.name for c in session.scalars(select(Character)).all()}
    batches: dict[str, dict] = {}
    for m in rows:
        b = batches.setdefault(m.batch or str(m.id), {"batch": m.batch, "kind": m.kind, "text": m.text,
                                                        "options": m.options, "created_at": m.created_at, "to": []})
        b["to"].append({"id": m.id, "name": names.get(m.character_id, "?"), "status": m.status, "answer": m.answer,
                        "answered_at": m.answered_at})
    return list(batches.values())[:limit]


@router.get("")
async def dm_screen(request: Request):
    _guard(request)
    with request.app.state.db() as session:
        return page(request, "dm.html", sheets=_board(request, session), outbox=_outbox(session))


@router.get("/board")
async def board(request: Request):
    _guard(request)
    with request.app.state.db() as session:
        return page(request, "partials/dm_board.html", sheets=_board(request, session))


@router.get("/outbox")
async def outbox(request: Request):
    _guard(request)
    with request.app.state.db() as session:
        return page(request, "partials/dm_outbox.html", outbox=_outbox(session))


@router.post("/messages")
async def send(request: Request):
    _guard(request)
    form = await request.form()
    kind = str(form.get("kind", "note"))
    if kind not in ("note", "choice", "prompt"):
        kind = "note"
    text = str(form.get("text", "")).strip()[:4000]
    options = [o.strip()[:200] for o in str(form.get("options", "")).splitlines() if o.strip()][:12]
    to = [int(x) for x in form.getlist("to") if str(x).isdigit()]
    with request.app.state.db() as session:
        if not text:
            return page(request, "partials/dm_outbox.html", outbox=_outbox(session), error="Write the message first.")
        if kind == "choice" and len(options) < 2:
            return page(request, "partials/dm_outbox.html", outbox=_outbox(session), error="A choice needs at least two options, one per line.")
        known = {c.id for c in session.scalars(select(Character)).all()}
        to = [cid for cid in to if cid in known]
        if not to:
            return page(request, "partials/dm_outbox.html", outbox=_outbox(session), error="Pick who it goes to.")
        batch = secrets.token_hex(6)
        for cid in to:
            session.add(Message(batch=batch, character_id=cid, kind=kind, text=text, options=options))
        session.commit()
        resp = page(request, "partials/dm_outbox.html", outbox=_outbox(session), sent=len(to))
    return resp


@router.post("/messages/{mid}/cancel")
async def cancel(request: Request, mid: int):
    _guard(request)
    with request.app.state.db() as session:
        m = session.get(Message, mid)
        if m and m.status == "pending":
            m.status, m.answered_at = "cancelled", _now()
            session.commit()
        return page(request, "partials/dm_outbox.html", outbox=_outbox(session))
