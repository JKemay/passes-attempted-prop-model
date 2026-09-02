import json
from pathlib import Path
from passmodel import db
from passmodel.scrapers import fotmob

FIX = Path(__file__).parent / "fixtures"


def _load():
    return json.loads((FIX / "fotmob_match.json").read_text(encoding="utf-8"))


def _load_by_date():
    return json.loads((FIX / "fotmob_matches_by_date.json").read_text(encoding="utf-8"))


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


def test_ingest_match_then_cross_check_writes_a_flag(conn):
    """Go through the real ingest path (not manual upserts) to prove
    ingest_match's name-matching feeds cross_check correctly."""
    sui = db.get_or_create_team(conn, "Switzerland")
    col = db.get_or_create_team(conn, "Colombia")
    m = db.get_or_create_match(conn, "2026-06-20", "World Cup", sui, col)
    akanji = db.get_or_create_player(conn, "Manuel Akanji", sui)
    db.upsert_player_stat(conn, m, akanji, sui, "fbref", minutes=90, passes_attempted=64)

    fotmob.ingest_match(conn, m, _load())  # fixture has Akanji at 74 passes
    flags = fotmob.cross_check(conn, m)

    assert flags == [{"player_id": akanji, "diff": 10}]
    assert db.flagged_player_ids(conn, "source_disagreement") == {akanji}


def test_resolve_match_id_matches_date_and_teams(conn):
    sui = db.get_or_create_team(conn, "Switzerland")
    opp = db.get_or_create_team(conn, "Opponent 0")
    m = db.get_or_create_match(conn, "2026-01-01", "Qualifiers", sui, opp)

    fotmob_id = fotmob.resolve_match_id(conn, m, fetch=lambda date: _load_by_date())

    assert fotmob_id == "999001"
    row = conn.execute("SELECT fotmob_match_id FROM matches WHERE match_id=?", (m,)).fetchone()
    assert row["fotmob_match_id"] == "999001"


def test_resolve_match_id_mismatch_resolves_to_none(conn):
    """A team not present in that date's fixture must not fall back to the
    wrong match -- it should resolve to nothing."""
    sui = db.get_or_create_team(conn, "Switzerland")
    unlisted = db.get_or_create_team(conn, "Unlisted Opponent")
    m = db.get_or_create_match(conn, "2026-01-01", "Qualifiers", sui, unlisted)

    fotmob_id = fotmob.resolve_match_id(conn, m, fetch=lambda date: _load_by_date())

    assert fotmob_id is None
    row = conn.execute("SELECT fotmob_match_id FROM matches WHERE match_id=?", (m,)).fetchone()
    assert row["fotmob_match_id"] is None


def test_resolve_match_id_is_cached_after_first_lookup(conn):
    sui = db.get_or_create_team(conn, "Switzerland")
    opp = db.get_or_create_team(conn, "Opponent 0")
    m = db.get_or_create_match(conn, "2026-01-01", "Qualifiers", sui, opp)

    calls = []

    def fetch(date):
        calls.append(date)
        return _load_by_date()

    first = fotmob.resolve_match_id(conn, m, fetch=fetch)
    second = fotmob.resolve_match_id(conn, m, fetch=fetch)

    assert first == second == "999001"
    assert len(calls) == 1
