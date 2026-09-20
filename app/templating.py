"""Jinja environment shared by every router."""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from .compendium import format as fmt
from .compendium import rules
from .compendium.linkify import linkify, peek_url
from .compendium.loader import Compendium, entity_url, key, wikidot_url
from .compendium.render import Renderer
from .themes import theme_choices

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def build_templates(compendium: Compendium) -> Jinja2Templates:
    t = Jinja2Templates(directory=str(TEMPLATES_DIR))
    renderer = Renderer(compendium, link_for=entity_url)
    env = t.env
    env.filters["entries"] = renderer.render
    env.filters["inline"] = lambda s: Markup(renderer.inline(str(s)))
    env.filters["mod"] = rules.fmt_mod
    env.filters["ordinal"] = rules.ordinal
    env.filters["spell_time"] = fmt.spell_time
    env.filters["spell_range"] = fmt.spell_range
    env.filters["spell_components"] = fmt.spell_components
    env.filters["spell_duration"] = fmt.spell_duration
    env.filters["spell_level_label"] = fmt.spell_level_label
    env.filters["spell_flags"] = fmt.spell_flags
    env.filters["prof_list"] = fmt.prof_list
    env.filters["weapon_summary"] = fmt.weapon_summary
    env.filters["armor_summary"] = fmt.armor_summary
    env.filters["race_ability"] = fmt.race_ability_text
    env.filters["race_size"] = fmt.race_size
    env.filters["race_speed_text"] = fmt.race_speed_text
    env.filters["prereq"] = fmt.prerequisite_text
    env.filters["ekey"] = lambda e: key(e["name"], e["source"])
    env.globals["entity_url"] = entity_url
    env.globals["wikidot_url"] = wikidot_url
    env.globals["peek_url"] = peek_url
    from .loot import coins_text
    env.globals["coins_text"] = coins_text
    env.filters["linkify"] = lambda text, target="": linkify(text, compendium, target)
    env.globals["theme_choices"] = theme_choices
    env.globals["ABILITIES"] = rules.ABILITIES
    env.globals["ABILITY_NAMES"] = rules.ABILITY_NAMES
    env.globals["SKILLS"] = rules.SKILLS
    env.globals["SCHOOLS"] = rules.SCHOOLS
    return t


def page(request: Request, name: str, **ctx):
    """Render a full page or partial with the app-wide context merged in."""
    app = request.app
    from . import auth
    ctx.setdefault("role", getattr(request.state, "role", None))
    ctx["is_dm"] = ctx["role"] == "dm"
    ctx["signed_in"] = auth.role_from_cookie(request, app.state.secret, app.state.settings) is not None
    ctx["is_unlocked"] = lambda ch: auth.is_unlocked(request, ch, app.state.secret)
    ctx["settings"] = app.state.settings
    sheet = ctx.get("sheet")
    ctx["theme_style"] = sheet["theme_style"] if isinstance(sheet, dict) and "theme_style" in sheet else ""
    ctx["sources"] = sorted(app.state.compendium.sources)
    return app.state.templates.TemplateResponse(request, name, ctx)
