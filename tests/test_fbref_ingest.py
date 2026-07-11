from pathlib import Path
from passmodel.scrapers import fbref

FIX = Path(__file__).parent / "fixtures"


def test_parse_fixtures_returns_played_and_upcoming():
    html = (FIX / "fbref_sched.html").read_text(encoding="utf-8")
    rows = fbref.parse_fixtures(html)
    assert len(rows) == 3
    assert rows[0] == {
        "date": "2026-06-20",
        "home": "Switzerland",
        "away": "Colombia",
        "match_url": "/en/matches/m123/report",
        "fbref_match_id": "m123",
    }
    assert rows[2]["match_url"] is None


def test_ingest_match_writes_all_tables(conn):
    html = (FIX / "fbref_match.html").read_text(encoding="utf-8")
    mid = fbref.ingest_match(
        conn,
        html,
        date="2026-06-20",
        competition="World Cup",
        home="Switzerland",
        away="Colombia",
        fbref_match_id="m123",
    )
    n_players = conn.execute("SELECT COUNT(*) c FROM player_match_stats").fetchone()["c"]
    n_teams = conn.execute("SELECT COUNT(*) c FROM team_match_stats").fetchone()["c"]
    assert mid
    assert n_players == 3 and n_teams == 2
    sui = conn.execute(
        "SELECT passes_attempted FROM team_match_stats t JOIN teams x ON x.team_id=t.team_id "
        "WHERE x.name='Switzerland'"
    ).fetchone()
    assert sui["passes_attempted"] == 163
