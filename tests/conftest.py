import pytest
from pathlib import Path

from fastapi.testclient import TestClient

from app.compendium.loader import Compendium
from app.config import Settings
from app.main import create_app

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "5etools"

pytestmark = pytest.mark.skipif(not (DATA_DIR / "races.json").exists(),
                                reason="run scripts/fetch_data.py first")


@pytest.fixture(scope="session")
def comp() -> Compendium:
    if not (DATA_DIR / "races.json").exists():
        pytest.skip("run scripts/fetch_data.py first")
    return Compendium(DATA_DIR, ["PHB"])


def make_settings(tmp_path: Path, **kw) -> Settings:
    s = Settings(db_path=tmp_path / "test.db", data_dir=DATA_DIR)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


@pytest.fixture
def client(tmp_path) -> TestClient:
    if not (DATA_DIR / "races.json").exists():
        pytest.skip("run scripts/fetch_data.py first")
    return TestClient(create_app(make_settings(tmp_path)))


WIZARD = {
    "name": "Test Wizard", "player": "Charles", "race": "Elf|PHB||High|PHB", "class_key": "Wizard|PHB",
    "level": "3", "background_key": "Sage|PHB", "score_str": "8", "score_dex": "14", "score_con": "13",
    "score_int": "17", "score_wis": "12", "score_cha": "10",
}


def create_character(client: TestClient, **overrides) -> int:
    data = {**WIZARD, **overrides}
    r = client.post("/new", data=data, follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(r.headers["location"].rsplit("/", 1)[-1])
