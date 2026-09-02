import time
import requests
from passmodel import config, db
from passmodel.util import normalize_name


def parse_match_json(data):
    out = []
    stats_by_player = (data.get("content") or {}).get("playerStats") or {}
    for _pid, pdata in stats_by_player.items():
        passes = minutes = None
        for section in pdata.get("stats", []):
            for label, entry in (section.get("stats") or {}).items():
                stat = (entry or {}).get("stat") or {}
                if label == "Accurate passes" and "total" in stat:
                    passes = int(stat["total"])
                if label == "Minutes played" and "value" in stat:
                    minutes = int(stat["value"])
        if passes is not None:
            out.append(
                {
                    "name": pdata.get("name", ""),
                    "passes_attempted": passes,
                    "minutes": minutes or 0,
                }
            )
    return out


def ingest_match(conn, match_id, data):
    """Attach FotMob rows to players already known from FBref, matched by name."""
    known = conn.execute(
        """SELECT p.player_id, p.norm_name, s.team_id FROM player_match_stats s
           JOIN players p ON p.player_id = s.player_id
           WHERE s.match_id=? AND s.source='fbref'""",
        (match_id,),
    ).fetchall()
    by_norm = {r["norm_name"]: r for r in known}
    for pl in parse_match_json(data):
        row = by_norm.get(normalize_name(pl["name"]))
        if row is None:
            continue
        db.upsert_player_stat(
            conn,
            match_id,
            row["player_id"],
            row["team_id"],
            "fotmob",
            minutes=pl["minutes"],
            passes_attempted=pl["passes_attempted"],
        )


def cross_check(conn, match_id):
    """Compare FBref vs FotMob passes for one match.

    Flags are persisted, not just returned: the projection engine reads them to
    force a LOW confidence tag, which is the entire point of scraping a second
    source. Returning them alone would leave the check decorative.
    """
    rows = conn.execute(
        """SELECT a.player_id, a.passes_attempted fb, b.passes_attempted fm
           FROM player_match_stats a
           JOIN player_match_stats b
             ON a.match_id=b.match_id AND a.player_id=b.player_id
           WHERE a.match_id=? AND a.source='fbref' AND b.source='fotmob'""",
        (match_id,),
    ).fetchall()
    flags = []
    for r in rows:
        diff = abs((r["fb"] or 0) - (r["fm"] or 0))
        if diff > config.SOURCE_DISAGREE_PASSES:
            flags.append({"player_id": r["player_id"], "diff": diff})
            db.flag_data_quality(
                conn,
                match_id,
                r["player_id"],
                "source_disagreement",
                f"fbref={r['fb']} fotmob={r['fm']} diff={diff}",
            )
    return flags


def fetch_match_json(fotmob_match_id):
    time.sleep(config.FOTMOB_DELAY_SECONDS)
    resp = requests.get(
        f"https://www.fotmob.com/api/matchDetails?matchId={fotmob_match_id}",
        headers={**config.DEFAULT_HEADERS, "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_matches_by_date(date):
    """FotMob's schedule endpoint, keyed by a plain YYYYMMDD date."""
    time.sleep(config.FOTMOB_DELAY_SECONDS)
    resp = requests.get(
        f"https://www.fotmob.com/api/matches?date={date.replace('-', '')}",
        headers={**config.DEFAULT_HEADERS, "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def parse_matches_by_date(data):
    """Flatten the leagues->matches nesting into one list of id/home/away."""
    out = []
    for league in data.get("leagues", []) or []:
        for m in league.get("matches", []) or []:
            out.append(
                {
                    "id": m.get("id"),
                    "home": (m.get("home") or {}).get("name", ""),
                    "away": (m.get("away") or {}).get("name", ""),
                }
            )
    return out


def find_fotmob_match_id(data, home, away):
    """Match on normalized team names only -- the schedule endpoint is already
    scoped to a single date, so date+teams is enough and avoids depending on
    exact kickoff-time formatting."""
    home_n, away_n = normalize_name(home), normalize_name(away)
    for m in parse_matches_by_date(data):
        if normalize_name(m["home"]) == home_n and normalize_name(m["away"]) == away_n:
            # str(): matches.fotmob_match_id is TEXT and sqlite coerces a
            # stored int to its text form, so a cache hit would otherwise
            # come back a different type than a fresh resolve.
            return str(m["id"])
    return None


def resolve_match_id(conn, match_id, fetch=None):
    """Find and persist the FotMob id for an already-known FBref match.

    Cached on matches.fotmob_match_id so a match is only looked up once; a
    miss is left uncached (not None-cached) since the schedule endpoint may
    simply not have posted the fixture yet when we first tried.
    """
    fetch = fetch or fetch_matches_by_date
    row = conn.execute(
        """SELECT fotmob_match_id, date, home_team_id, away_team_id FROM matches
           WHERE match_id=?""",
        (match_id,),
    ).fetchone()
    if row is None:
        return None
    if row["fotmob_match_id"]:
        return row["fotmob_match_id"]
    home = conn.execute(
        "SELECT name FROM teams WHERE team_id=?", (row["home_team_id"],)
    ).fetchone()
    away = conn.execute(
        "SELECT name FROM teams WHERE team_id=?", (row["away_team_id"],)
    ).fetchone()
    if home is None or away is None:
        return None
    data = fetch(row["date"])
    fotmob_id = find_fotmob_match_id(data, home["name"], away["name"])
    if fotmob_id is not None:
        db.set_fotmob_match_id(conn, match_id, fotmob_id)
    return fotmob_id


def update_fotmob(conn, fetch_matches=None, fetch_match=None):
    """Resolve, ingest, and cross-check FotMob data for every match FBref has
    stats for but FotMob doesn't yet.

    Matches already carrying a 'fotmob' row are skipped -- a rerun should not
    re-hit the network for a result that cannot change.
    """
    fetch_matches = fetch_matches or fetch_matches_by_date
    fetch_match = fetch_match or fetch_match_json
    rows = conn.execute(
        """SELECT DISTINCT match_id FROM player_match_stats WHERE source='fbref'
           AND match_id NOT IN (SELECT match_id FROM player_match_stats WHERE source='fotmob')"""
    ).fetchall()
    n_matches = n_flags = 0
    for r in rows:
        mid = r["match_id"]
        fotmob_id = resolve_match_id(conn, mid, fetch=fetch_matches)
        if fotmob_id is None:
            continue
        data = fetch_match(fotmob_id)
        ingest_match(conn, mid, data)
        n_flags += len(cross_check(conn, mid))
        n_matches += 1
    return n_matches, n_flags
