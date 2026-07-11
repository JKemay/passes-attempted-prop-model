import json
from pathlib import Path
from passmodel import db
from passmodel.scrapers import oddsapi

FIX = Path(__file__).parent / "fixtures"


def _load():
    return json.loads((FIX / "oddsapi.json").read_text(encoding="utf-8"))


def test_parse_odds():
    rows = oddsapi.parse_odds(_load())
    assert rows == [
        {
            "home": "Switzerland",
            "away": "Colombia",
            "date": "2026-07-10",
            "home_spread": -0.5,
            "total": 2.5,
        }
    ]


def test_ingest_attaches_to_match(conn):
    h = db.get_or_create_team(conn, "Switzerland")
    a = db.get_or_create_team(conn, "Colombia")
    m = db.get_or_create_match(conn, "2026-07-10", "World Cup", h, a)
    oddsapi.ingest_odds(conn, _load(), fetched_at="2026-07-09T12:00:00")
    row = conn.execute("SELECT * FROM market_odds WHERE match_id=?", (m,)).fetchone()
    assert row["home_spread"] == -0.5 and row["total"] == 2.5
