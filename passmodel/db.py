import sqlite3
from passmodel import config
from passmodel.util import normalize_name

SCHEMA = """
CREATE TABLE IF NOT EXISTS teams(
  team_id INTEGER PRIMARY KEY,
  name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS players(
  player_id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  norm_name TEXT NOT NULL,
  fbref_id TEXT,
  team_id INTEGER REFERENCES teams(team_id),
  position TEXT DEFAULT '',
  UNIQUE(norm_name, team_id)
);
CREATE TABLE IF NOT EXISTS matches(
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
CREATE TABLE IF NOT EXISTS team_match_stats(
  match_id INTEGER, team_id INTEGER, source TEXT,
  passes_attempted INTEGER, possession REAL,
  PRIMARY KEY(match_id, team_id, source)
);
CREATE TABLE IF NOT EXISTS player_match_stats(
  match_id INTEGER, player_id INTEGER, source TEXT,
  team_id INTEGER, minutes INTEGER DEFAULT 0, started INTEGER DEFAULT 0,
  passes_attempted INTEGER, position TEXT DEFAULT '',
  PRIMARY KEY(match_id, player_id, source)
);
CREATE TABLE IF NOT EXISTS prop_lines(
  line_id INTEGER PRIMARY KEY,
  fetched_at TEXT NOT NULL, source TEXT NOT NULL,
  player_name TEXT NOT NULL, player_id INTEGER,
  stat_type TEXT NOT NULL, line REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS market_odds(
  match_id INTEGER, fetched_at TEXT NOT NULL,
  home_spread REAL, total REAL,
  PRIMARY KEY(match_id, fetched_at)
);
CREATE TABLE IF NOT EXISTS projections(
  projection_id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL, player_id INTEGER, match_id INTEGER,
  line REAL, exp_minutes REAL, team_p90 REAL, share REAL,
  mu REAL, alpha REAL, p_over REAL, edge REAL,
  confidence TEXT DEFAULT '', notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS scrape_log(
  run_at TEXT, source TEXT, ok INTEGER, detail TEXT
);
"""


def get_conn(path=None):
    target = path or config.DB_PATH
    if path is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def get_or_create_team(conn, name):
    name = name.strip()
    row = conn.execute("SELECT team_id FROM teams WHERE name=?", (name,)).fetchone()
    if row:
        return row["team_id"]
    cur = conn.execute("INSERT INTO teams(name) VALUES(?)", (name,))
    conn.commit()
    return cur.lastrowid


def get_or_create_player(conn, name, team_id, fbref_id=None, position=None):
    norm = normalize_name(name)
    row = conn.execute(
        "SELECT player_id FROM players WHERE norm_name=? AND team_id=?", (norm, team_id)
    ).fetchone()
    if row:
        if position:
            conn.execute(
                "UPDATE players SET position=? WHERE player_id=? AND position=''",
                (position, row["player_id"]),
            )
            conn.commit()
        return row["player_id"]
    cur = conn.execute(
        "INSERT INTO players(name, norm_name, fbref_id, team_id, position) VALUES(?,?,?,?,?)",
        (name.strip(), norm, fbref_id, team_id, position or ""),
    )
    conn.commit()
    return cur.lastrowid


def get_or_create_match(
    conn,
    date,
    competition,
    home_team_id,
    away_team_id,
    fbref_match_id=None,
    stage="",
    is_friendly=0,
    is_knockout=0,
):
    row = conn.execute(
        "SELECT match_id FROM matches WHERE date=? AND home_team_id=? AND away_team_id=?",
        (date, home_team_id, away_team_id),
    ).fetchone()
    if row:
        return row["match_id"]
    cur = conn.execute(
        """INSERT INTO matches(fbref_match_id, date, competition, stage, is_friendly,
           is_knockout, home_team_id, away_team_id) VALUES(?,?,?,?,?,?,?,?)""",
        (
            fbref_match_id,
            date,
            competition,
            stage,
            is_friendly,
            is_knockout,
            home_team_id,
            away_team_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def upsert_player_stat(
    conn,
    match_id,
    player_id,
    team_id,
    source,
    minutes=0,
    passes_attempted=None,
    started=0,
    position="",
):
    conn.execute(
        """INSERT INTO player_match_stats(match_id, player_id, source, team_id, minutes,
           started, passes_attempted, position) VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(match_id, player_id, source) DO UPDATE SET
           minutes=excluded.minutes, started=excluded.started,
           passes_attempted=excluded.passes_attempted, position=excluded.position""",
        (match_id, player_id, source, team_id, minutes, started, passes_attempted, position),
    )
    conn.commit()


def upsert_team_stat(conn, match_id, team_id, source, passes_attempted, possession=None):
    conn.execute(
        """INSERT INTO team_match_stats(match_id, team_id, source, passes_attempted, possession)
           VALUES(?,?,?,?,?)
           ON CONFLICT(match_id, team_id, source) DO UPDATE SET
           passes_attempted=excluded.passes_attempted, possession=excluded.possession""",
        (match_id, team_id, source, passes_attempted, possession),
    )
    conn.commit()


def log_scrape(conn, run_at, source, ok, detail=""):
    conn.execute(
        "INSERT INTO scrape_log(run_at, source, ok, detail) VALUES(?,?,?,?)",
        (run_at, source, int(ok), detail),
    )
    conn.commit()
