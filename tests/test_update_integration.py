"""End-to-end, offline: FotMob ingestion (as wired into scripts/update.py via
fotmob.update_fotmob) writes a disagreement flag that project_slate then
turns into a LOW confidence projection. This is the whole point of the
producing half of the cross-check loop -- prove it actually reaches the
engine, not just that the pieces work in isolation."""
import json
from pathlib import Path
from passmodel import db
from passmodel.model import engine
from passmodel.scrapers import fotmob
from tests.seed import make_history

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_fotmob_disagreement_reaches_project_slate_as_low_through_update_path(conn):
    ids = make_history(conn, n_matches=12, team_passes=500, akanji_base=64)

    # make_history's first game is Switzerland vs "Opponent 0" on 2026-01-01,
    # with Akanji at fbref passes_attempted=64 -- matches the by-date fixture.
    matches_by_date = _load("fotmob_matches_by_date.json")
    match_json = _load("fotmob_match.json")  # Akanji at 74 passes -> diff=10 > threshold

    n_matches, n_flags = fotmob.update_fotmob(
        conn,
        fetch_matches=lambda date: matches_by_date,
        fetch_match=lambda fotmob_id: match_json,
    )
    assert n_matches == 1  # only the one match resolves against the fixture
    assert n_flags == 1

    # Upcoming match + a live prop line, same shape as the model tests.
    col = db.get_or_create_team(conn, "Colombia")
    db.get_or_create_match(conn, "2026-03-01", "World Cup", ids["sui"], col)
    conn.execute(
        """INSERT INTO prop_lines(fetched_at, source, player_name, player_id, stat_type, line)
           VALUES('2026-02-28T12:00:00','prizepicks','Manuel Akanji',?, 'Passes Attempted', 64.5)""",
        (ids["akanji"],),
    )
    conn.commit()

    fitted = engine.fit_all(conn)
    projections = engine.project_slate(conn, fitted, today="2026-02-28", save=False)

    assert len(projections) == 1
    assert projections[0]["confidence"] == "LOW"
