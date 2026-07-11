import json
from passmodel import db
from passmodel.model import engine
from tests.seed import make_history


def _add_upcoming(conn, date="2026-03-01"):
    sui = db.get_or_create_team(conn, "Switzerland")
    col = db.get_or_create_team(conn, "Colombia")
    return db.get_or_create_match(conn, date, "World Cup", sui, col)


def test_fit_all_returns_team_model_and_alphas(conn):
    make_history(conn)
    fitted = engine.fit_all(conn)
    assert "team_model" in fitted and "alpha_by_pos" in fitted
    assert fitted["alpha_by_pos"]["default"] > 0


def test_project_slate_produces_projection(conn):
    ids = make_history(conn, n_matches=12, team_passes=500, akanji_base=64)
    _add_upcoming(conn)
    conn.execute(
        """INSERT INTO prop_lines(fetched_at, source, player_name, player_id, stat_type, line)
           VALUES('2026-02-28T12:00:00','prizepicks','Manuel Akanji',?, 'Passes Attempted', 64.5)""",
        (ids["akanji"],),
    )
    conn.commit()
    fitted = engine.fit_all(conn)
    projections = engine.project_slate(conn, fitted, today="2026-02-28")
    assert len(projections) == 1
    pr = projections[0]
    assert pr["mu"] > 0 and 0 < pr["p_over"] < 1
    assert pr["confidence"] in ("HIGH", "MEDIUM", "LOW")
    notes = json.loads(pr["notes"])
    assert "team_passes_needed" in notes
    saved = conn.execute("SELECT COUNT(*) c FROM projections").fetchone()["c"]
    assert saved == 1


def test_unmatched_player_line_is_skipped_not_fatal(conn):
    make_history(conn)
    _add_upcoming(conn)
    conn.execute(
        """INSERT INTO prop_lines(fetched_at, source, player_name, player_id, stat_type, line)
           VALUES('2026-02-28T12:00:00','prizepicks','Unknown Guy', NULL, 'Passes Attempted', 50.5)"""
    )
    conn.commit()
    fitted = engine.fit_all(conn)
    assert engine.project_slate(conn, fitted, today="2026-02-28") == []
