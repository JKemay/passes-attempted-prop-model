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
    return flags


def fetch_match_json(fotmob_match_id):
    resp = requests.get(
        f"https://www.fotmob.com/api/matchDetails?matchId={fotmob_match_id}",
        headers={"User-Agent": config.USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
