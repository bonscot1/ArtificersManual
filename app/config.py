"""Settings. Everything has a default so the site runs with no config at all.

Optional overrides live in settings.json at the project root (gitignored);
see settings.example.json. Environment variables win over the file.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_FILE = BASE_DIR / "settings.json"

# The books this table allows, by 5etools code, in the order a bare name should
# resolve ("Tortle" -> MPMM before TTP). Override with `sources` in settings.json.
# PHB is always on; magic items load from every book regardless.
DEFAULT_SOURCES = ["PHB", "XGE", "TCE", "SCAG", "MPMM", "VGM", "TTP", "BGG"]


@dataclass
class Settings:
    sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    table_password: str = ""         # players type this once; empty = no login at all (LAN-only use)
    dm_password: str = ""            # unlocks DM notes / delete; empty = the machine running the server is the DM
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: Path = BASE_DIR / "data" / "5etools"
    db_path: Path = BASE_DIR / "data" / "manual.db"
    books_dir: Path = BASE_DIR.parent   # where the PDFs live (E:\DnD); served read-only at /books

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"


def load_settings(path: Path | None = None) -> Settings:
    s = Settings()
    path = path or DEFAULT_SETTINGS_FILE
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if "sources" in raw:
            s.sources = [str(x).strip() for x in raw["sources"] if str(x).strip()]
        s.table_password = str(raw.get("table_password", s.table_password))
        s.dm_password = str(raw.get("dm_password", s.dm_password))
        s.host = str(raw.get("host", s.host))
        s.port = int(raw.get("port", s.port))
        if raw.get("books_dir"):
            s.books_dir = Path(raw["books_dir"])
    if os.environ.get("AM_SOURCES"):
        s.sources = [x.strip() for x in os.environ["AM_SOURCES"].split(",") if x.strip()]
    if os.environ.get("AM_TABLE_PASSWORD") is not None:
        s.table_password = os.environ["AM_TABLE_PASSWORD"]
    if os.environ.get("AM_DM_PASSWORD") is not None:
        s.dm_password = os.environ["AM_DM_PASSWORD"]
    if os.environ.get("AM_DB"):
        s.db_path = Path(os.environ["AM_DB"])
    if os.environ.get("AM_PORT"):
        s.port = int(os.environ["AM_PORT"])
    if "PHB" not in s.sources:   # the core book is never optional
        s.sources.insert(0, "PHB")
    return s
