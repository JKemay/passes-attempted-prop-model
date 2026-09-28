import sqlite3
from passmodel import db


def test_init_db_migrates_matches_table_missing_fotmob_column(tmp_path):
    """A populated DB from before fotmob_match_id existed must gain the column
    (via ALTER TABLE, since CREATE TABLE IF NOT EXISTS is a no-op on an
    existing table) without losing its data."""
    conn = sqlite3.connect(tmp_path / "legacy.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE teams(team_id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
        CREATE TABLE matches(
          match_id INTEGER PRIMARY KEY,
          fbref_match_id TEXT UNIQUE,
          date TEXT NOT NULL,
          competition TEXT NOT NULL,
          stage TEXT DEFAULT '',
          is_friendly INTEGER DEFAULT 0,
          is_knockout INTEGER DEFAULT 0,
          home_team_id INTEGER REFERENCES teams(team_id),
          away_team_id INTEGER REFERENCES teams(team_id),
          UNIQUE(date, home_team_id, away_team_id)
        );
        INSERT INTO teams(team_id, name) VALUES (1, 'Switzerland'), (2, 'Colombia');
        INSERT INTO matches(match_id, fbref_match_id, date, competition, home_team_id, away_team_id)
          VALUES (1, 'm123', '2026-06-20', 'World Cup', 1, 2);
        """
    )
    conn.commit()

    db.init_db(conn)  # must not raise, and must add the missing column

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(matches)").fetchall()}
    assert "fotmob_match_id" in cols
    row = conn.execute("SELECT * FROM matches WHERE match_id=1").fetchone()
    assert row["fbref_match_id"] == "m123"
    assert row["fotmob_match_id"] is None
    conn.close()


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
