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
    password_hash: Mapped[str] = mapped_column(String(200), default="")   # empty = nobody has claimed this sheet yet
    theme: Mapped[str] = mapped_column(String(40), default="")             # "" = the class's theme
    portrait: Mapped[str] = mapped_column(String(120), default="")         # file in data/portraits/
    token: Mapped[str] = mapped_column(String(120), default="")            # round token for cards

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
    concentration: Mapped[str] = mapped_column(String(120), default="")   # spell being concentrated on
    pact_used: Mapped[int] = mapped_column(Integer, default=0)
    spells: Mapped[list] = mapped_column(JSON, default=list)           # [{"key": "Fireball|PHB", "prepared": true}]
    attacks: Mapped[list] = mapped_column(JSON, default=list)          # [{"name","bonus","damage","notes"}]
    inventory: Mapped[list] = mapped_column(JSON, default=list)        # [{"name","qty","notes"}]
    inventory_removed: Mapped[list] = mapped_column(JSON, default=list)  # same rows + "when": easy to put back
    currency: Mapped[dict] = mapped_column(JSON, default=dict)         # {"cp":0,"sp":0,"ep":0,"gp":0,"pp":0}

    feats: Mapped[list] = mapped_column(JSON, default=list)            # [{"key": "Alert|PHB", "note": ""}]
    options: Mapped[list] = mapped_column(JSON, default=list)          # class options: infusions, invocations, styles...
    counters: Mapped[list] = mapped_column(JSON, default=list)         # [{"name": "Rage", "max": 2, "used": 0, "reset": "long"}]
    companions: Mapped[list] = mapped_column(JSON, default=list)       # familiars, defenders: [{"name","kind","hp_max","hp_current","ac","summoned","conditions","notes"}]

    features_custom: Mapped[str] = mapped_column(Text, default="")     # anything the books don't fill in
    appearance: Mapped[str] = mapped_column(String(300), default="")   # age, height, eyes...
    personality: Mapped[str] = mapped_column(Text, default="")         # traits, ideals, bonds, flaws
    allies: Mapped[str] = mapped_column(Text, default="")              # allies and organisations
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
    migrate(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _sql_default(column) -> str:
    """create_all never adds columns to an existing table; new ones get a literal default."""
    default = column.default.arg if column.default is not None else None
    if callable(default):
        default = default(None) if column.type.python_type in (list, dict) else None
    if isinstance(default, bool):
        return "1" if default else "0"
    if isinstance(default, (int, float)):
        return str(default)
    if isinstance(default, (list, dict)):
        import json
        return "'" + json.dumps(default) + "'"
    if isinstance(default, str):
        return "'" + default.replace("'", "''") + "'"
    return "NULL"


def migrate(engine) -> list[str]:
    """Add any model column missing from the live table (SQLite can only ADD COLUMN)."""
    added = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table.name})")}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {column.type.compile(engine.dialect)}"
                if not column.nullable or column.default is not None:
                    ddl += f" DEFAULT {_sql_default(column)}"
                conn.exec_driver_sql(ddl)
                added.append(f"{table.name}.{column.name}")
    return added


class Message(Base):
    """Something the DM sent a character: a note to dismiss, a choice to make, a question to answer."""
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch: Mapped[str] = mapped_column(String(32), default="")        # one send to several characters
    character_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(10), default="note")      # note | choice | prompt
    text: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[list] = mapped_column(JSON, default=list)          # for a choice
    status: Mapped[str] = mapped_column(String(10), default="pending") # pending | done | cancelled
    answer: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
