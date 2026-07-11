from passmodel import db


def test_get_or_create_team_is_idempotent(conn):
    a = db.get_or_create_team(conn, "Switzerland")
    b = db.get_or_create_team(conn, "Switzerland")
    assert a == b


def test_get_or_create_player_matches_normalized_name(conn):
    t = db.get_or_create_team(conn, "Switzerland")
    a = db.get_or_create_player(conn, "Manuel Akanji", t, position="CB")
    b = db.get_or_create_player(conn, "manuel akanji", t)
    assert a == b


def test_upsert_player_stat_overwrites_same_source(conn):
    t = db.get_or_create_team(conn, "Switzerland")
    p = db.get_or_create_player(conn, "Manuel Akanji", t)
    m = db.get_or_create_match(conn, "2026-06-20", "World Cup", t, t)
    db.upsert_player_stat(conn, m, p, t, "fbref", minutes=90, passes_attempted=70, started=1)
    db.upsert_player_stat(conn, m, p, t, "fbref", minutes=90, passes_attempted=78, started=1)
    row = conn.execute("SELECT passes_attempted FROM player_match_stats").fetchone()
    assert row["passes_attempted"] == 78
