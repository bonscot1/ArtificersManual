"""SQLite via SQLAlchemy. One table: the characters. Reference data lives in memory."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Character(Base):
    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    player: Mapped[str] = mapped_column(String(120), default="")

    race_key: Mapped[str] = mapped_column(String(160), default="")
    subrace_key: Mapped[str] = mapped_column(String(160), default="")
    class_key: Mapped[str] = mapped_column(String(160), default="")
    subclass_key: Mapped[str] = mapped_column(String(160), default="")
    background_key: Mapped[str] = mapped_column(String(160), default="")
    level: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    alignment: Mapped[str] = mapped_column(String(40), default="")

    score_str: Mapped[int] = mapped_column(Integer, default=10)
    score_dex: Mapped[int] = mapped_column(Integer, default=10)
    score_con: Mapped[int] = mapped_column(Integer, default=10)
    score_int: Mapped[int] = mapped_column(Integer, default=10)
    score_wis: Mapped[int] = mapped_column(Integer, default=10)
    score_cha: Mapped[int] = mapped_column(Integer, default=10)

    hp_max: Mapped[int] = mapped_column(Integer, default=10)
    hp_current: Mapped[int] = mapped_column(Integer, default=10)
    hp_temp: Mapped[int] = mapped_column(Integer, default=0)
    ac: Mapped[int] = mapped_column(Integer, default=10)
    speed: Mapped[int] = mapped_column(Integer, default=30)
    initiative_bonus: Mapped[int] = mapped_column(Integer, default=0)
    hit_dice_used: Mapped[int] = mapped_column(Integer, default=0)
    death_success: Mapped[int] = mapped_column(Integer, default=0)
    death_fail: Mapped[int] = mapped_column(Integer, default=0)
    inspiration: Mapped[bool] = mapped_column(Boolean, default=False)

    save_profs: Mapped[list] = mapped_column(JSON, default=list)       # ["str", "con"]
    skill_profs: Mapped[list] = mapped_column(JSON, default=list)      # ["Athletics", ...]
    skill_expertise: Mapped[list] = mapped_column(JSON, default=list)
    other_profs: Mapped[str] = mapped_column(Text, default="")         # armour, weapons, tools, languages
    conditions: Mapped[list] = mapped_column(JSON, default=list)       # ["Prone", ...]

    slots_used: Mapped[dict] = mapped_column(JSON, default=dict)       # {"1": 2, "2": 0}
    pact_used: Mapped[int] = mapped_column(Integer, default=0)
    spells: Mapped[list] = mapped_column(JSON, default=list)           # [{"key": "Fireball|PHB", "prepared": true}]
    attacks: Mapped[list] = mapped_column(JSON, default=list)          # [{"name","bonus","damage","notes"}]
    inventory: Mapped[list] = mapped_column(JSON, default=list)        # [{"name","qty","notes"}]
    currency: Mapped[dict] = mapped_column(JSON, default=dict)         # {"cp":0,"sp":0,"ep":0,"gp":0,"pp":0}

    features_custom: Mapped[str] = mapped_column(Text, default="")     # feats, boons, anything not auto-found
    notes: Mapped[str] = mapped_column(Text, default="")
    backstory: Mapped[str] = mapped_column(Text, default="")
    notes_dm: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def scores(self) -> dict[str, int]:
        return {
            "str": self.score_str, "dex": self.score_dex, "con": self.score_con,
            "int": self.score_int, "wis": self.score_wis, "cha": self.score_cha,
        }


def make_engine(db_url: str):
    engine = create_engine(db_url, connect_args={"check_same_thread": False} if db_url.startswith("sqlite") else {})
    if db_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


def make_session_factory(engine) -> sessionmaker[Session]:
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
