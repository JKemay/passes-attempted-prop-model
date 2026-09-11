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
            "team_name": "",
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


def _projection_payload(new_player_attrs=None, new_player_rel=None, extra_included=None):
    """Build a minimal one-projection PrizePicks payload for a given player."""
    included = [
        {
            "id": "p1",
            "type": "new_player",
            "attributes": new_player_attrs or {"display_name": "Manuel Akanji"},
            **({"relationships": new_player_rel} if new_player_rel else {}),
        }
    ]
    included.extend(extra_included or [])
    return {
        "data": [
            {
                "id": "1",
                "type": "projection",
                "attributes": {"line_score": 12.5, "stat_type": "Passes Attempted"},
                "relationships": {"new_player": {"data": {"id": "p1", "type": "new_player"}}},
            }
        ],
        "included": included,
    }


def test_ingest_disambiguates_same_name_by_team(conn):
    """Two same-named players on different national teams must not collide."""
    sui = db.get_or_create_team(conn, "Switzerland")
    col = db.get_or_create_team(conn, "Colombia")
    pid_sui = db.get_or_create_player(conn, "Manuel Akanji", sui)
    db.get_or_create_player(conn, "Manuel Akanji", col)

    payload = _projection_payload(
        new_player_rel={"team": {"data": {"id": "t1", "type": "team"}}},
        extra_included=[{"id": "t1", "type": "team", "attributes": {"name": "Switzerland"}}],
    )
    prizepicks.ingest_lines(conn, payload, fetched_at="2026-07-09T12:00:00")
    row = conn.execute("SELECT player_id FROM prop_lines").fetchone()
    assert row["player_id"] == pid_sui


def test_ingest_leaves_ambiguous_same_name_unmatched(conn, capsys):
    """No team on the payload and >1 players share the name -- must not guess."""
    sui = db.get_or_create_team(conn, "Switzerland")
    col = db.get_or_create_team(conn, "Colombia")
    db.get_or_create_player(conn, "Manuel Akanji", sui)
    db.get_or_create_player(conn, "Manuel Akanji", col)

    payload = _projection_payload()  # no team relationship at all
    prizepicks.ingest_lines(conn, payload, fetched_at="2026-07-09T12:00:00")
    row = conn.execute("SELECT player_id, line FROM prop_lines").fetchone()
    assert row["player_id"] is None
    assert row["line"] == 12.5
    assert "ambiguous" in capsys.readouterr().err
