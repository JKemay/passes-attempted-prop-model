import json
from pathlib import Path
from passmodel import db
from passmodel.scrapers import fotmob

FIX = Path(__file__).parent / "fixtures"


def _load():
    return json.loads((FIX / "fotmob_match.json").read_text(encoding="utf-8"))


def test_parse_match_json():
    players = fotmob.parse_match_json(_load())
    assert players[0] == {"name": "Manuel Akanji", "passes_attempted": 74, "minutes": 90}


def test_cross_check_flags_disagreement(conn):
    t = db.get_or_create_team(conn, "Switzerland")
    p = db.get_or_create_player(conn, "Manuel Akanji", t)
    m = db.get_or_create_match(conn, "2026-06-20", "World Cup", t, t)
    db.upsert_player_stat(conn, m, p, t, "fbref", minutes=90, passes_attempted=78)
    db.upsert_player_stat(conn, m, p, t, "fotmob", minutes=90, passes_attempted=70)
    flags = fotmob.cross_check(conn, m)
    assert len(flags) == 1 and flags[0]["diff"] == 8


def test_cross_check_persists_flags_for_the_engine(conn):
    """Returning flags is not enough -- project_slate reads them from the DB."""
    t = db.get_or_create_team(conn, "Switzerland")
    p = db.get_or_create_player(conn, "Manuel Akanji", t)
    m = db.get_or_create_match(conn, "2026-06-20", "World Cup", t, t)
    db.upsert_player_stat(conn, m, p, t, "fbref", minutes=90, passes_attempted=78)
    db.upsert_player_stat(conn, m, p, t, "fotmob", minutes=90, passes_attempted=70)

    fotmob.cross_check(conn, m)
    assert db.flagged_player_ids(conn, "source_disagreement") == {p}

    # Re-scraping the same match must not duplicate the flag.
    fotmob.cross_check(conn, m)
    n = conn.execute("SELECT COUNT(*) c FROM data_quality_flags").fetchone()["c"]
    assert n == 1


def test_cross_check_within_tolerance_records_nothing(conn):
    t = db.get_or_create_team(conn, "Switzerland")
    p = db.get_or_create_player(conn, "Manuel Akanji", t)
    m = db.get_or_create_match(conn, "2026-06-21", "World Cup", t, t)
    db.upsert_player_stat(conn, m, p, t, "fbref", minutes=90, passes_attempted=78)
    db.upsert_player_stat(conn, m, p, t, "fotmob", minutes=90, passes_attempted=76)

    assert fotmob.cross_check(conn, m) == []
    assert db.flagged_player_ids(conn, "source_disagreement") == set()
