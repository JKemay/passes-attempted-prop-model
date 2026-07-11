import json
from pathlib import Path
from passmodel import db
from passmodel.scrapers import prizepicks

FIX = Path(__file__).parent / "fixtures"


def _load():
    return json.loads((FIX / "prizepicks.json").read_text(encoding="utf-8"))


def test_parse_filters_to_passes_attempted():
    lines = prizepicks.parse_projections(_load())
    assert lines == [
        {
            "player_name": "Manuel Akanji",
            "stat_type": "Passes Attempted",
            "line": 64.5,
        }
    ]


def test_ingest_matches_known_player(conn):
    t = db.get_or_create_team(conn, "Switzerland")
    pid = db.get_or_create_player(conn, "Manuel Akanji", t)
    prizepicks.ingest_lines(conn, _load(), fetched_at="2026-07-09T12:00:00")
    row = conn.execute("SELECT player_id, line FROM prop_lines").fetchone()
    assert row["player_id"] == pid and row["line"] == 64.5
