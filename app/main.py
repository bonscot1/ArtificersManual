"""Artificer's Manual - a character tracker for one table.

    python -m app             # or run.ps1 (uvicorn with --factory create_app)
"""
from __future__ import annotations

import socket
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth
from .compendium.loader import Compendium
from .config import BASE_DIR, Settings, load_settings
from .db import make_engine, make_session_factory
from .templating import build_templates, page

STATIC_DIR = Path(__file__).resolve().parent / "static"
_OPEN_PATHS = ("/login", "/static/", "/healthz")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    compendium = Compendium(settings.data_dir, settings.sources)
    engine = make_engine(settings.db_url)
    secret = auth.load_secret(settings)

    app = FastAPI(title="Artificer's Manual", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.secret = secret
    app.state.compendium = compendium
    app.state.engine = engine
    app.state.db = make_session_factory(engine)
    app.state.templates = build_templates(compendium)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        settings.refresh()          # a saved settings.json applies straight away
        request.state.role = auth.role_for(request, settings, secret)
        request.state.unlocked = auth.unlocked_from_cookie(request, secret)
        if request.state.role is None and not path.startswith(_OPEN_PATHS):
            if request.method == "GET" and "hx-request" not in request.headers:
                return RedirectResponse(f"/login?next={path}", status_code=303)
            resp = Response("Login required", status_code=401)
            resp.headers["HX-Redirect"] = "/login"
            return resp
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.exception_handler(auth.Locked)
    async def locked(request: Request, exc: auth.Locked):
        target = f"/c/{exc.cid}/unlock"
        if request.method == "GET" and "hx-request" not in request.headers:
            return RedirectResponse(target, status_code=303)
        resp = Response("This sheet needs its password", status_code=401)
        resp.headers["HX-Redirect"] = target
        return resp

    @app.get("/rules")
    async def rules(request: Request):
        import markdown
        path = BASE_DIR / "house_rules.md"
        text = path.read_text(encoding="utf-8") if path.exists() else "# House rules\n\nNone written yet."
        html = markdown.markdown(text, extensions=["tables"])
        return page(request, "rules.html", body=html)

    @app.get("/healthz")
    async def healthz():
        return JSONResponse({"ok": True, "sources": sorted(compendium.sources),
                             "spells": len(compendium.spells), "races": len(compendium.races)})

    @app.get("/login")
    async def login_form(request: Request, next: str = "/"):
        if request.state.role == "dm":
            return RedirectResponse(next if next.startswith("/") else "/", status_code=303)
        if not settings.dm_password and not settings.table_password:
            return RedirectResponse("/", status_code=303)
        return page(request, "login.html", error=None, next=next)

    @app.post("/login")
    async def login(request: Request, password: str = Form(""), next: str = Form("/")):
        role = auth.login_role(password, settings)
        if not role:
            return page(request, "login.html", error="That's not it.", next=next)
        target = next if next.startswith("/") and not next.startswith("//") else "/"
        resp = RedirectResponse(target, status_code=303)
        resp.set_cookie(auth.COOKIE, auth.token_for(role, secret, settings), httponly=True, samesite="lax",
                        max_age=60 * 60 * 24 * 90)
        return resp

    @app.post("/logout")
    async def logout():
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie(auth.COOKIE)
        return resp

    from .routes import characters, compendium as compendium_routes
    app.include_router(characters.router)
    app.include_router(compendium_routes.router)
    return app


def lan_ip() -> str:
    """Best-effort address other devices on the network can use."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()

