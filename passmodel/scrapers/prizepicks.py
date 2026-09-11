import sys

import requests
from passmodel import config
from passmodel.util import normalize_name

URL = "https://api.prizepicks.com/projections"


def parse_projections(payload):
    included = payload.get("included", [])
    team_names = {
        inc["id"]: inc["attributes"].get("name", "")
        for inc in included
        if inc.get("type") == "team"
    }
    players = {}
    for inc in included:
        if inc.get("type") != "new_player":
            continue
        team_rel = (((inc.get("relationships") or {}).get("team") or {}).get("data") or {})
        players[inc["id"]] = {
            "display_name": inc["attributes"].get("display_name", ""),
            "team_name": team_names.get(team_rel.get("id"), ""),
        }
    out = []
    for item in payload.get("data", []):
        attrs = item.get("attributes", {})
        if attrs.get("stat_type") != "Passes Attempted":
            continue
        rel = (((item.get("relationships") or {}).get("new_player") or {}).get("data") or {})
        player = players.get(rel.get("id"), {})
        out.append(
            {
                "player_name": player.get("display_name", ""),
                "team_name": player.get("team_name", ""),
                "stat_type": "Passes Attempted",
                "line": float(attrs["line_score"]),
            }
        )
    return out


def _resolve_player_id(conn, player_name, team_name):
    """Match a PrizePicks line to a `players` row, disambiguating by team.

    `players` is UNIQUE(norm_name, team_id) -- with 32+ World Cup squads in
    the table, two same-named players on different national teams both match
    on name alone. When the payload names the player's team, filter on it
    directly. When it doesn't (or that team isn't in our `teams` table), fall
    back to name-only matching -- but refuse to guess: more than one candidate
    is left unmatched (player_id=None, the same outcome `ingest_lines` already
    uses for "no match found") instead of silently taking the first row, and
    the collision is logged so it stays visible instead of being swallowed.
    """
    norm = normalize_name(player_name)
    if team_name:
        row = conn.execute(
            """SELECT p.player_id FROM players p
               JOIN teams t ON t.team_id = p.team_id
               WHERE p.norm_name=? AND t.name=?""",
            (norm, team_name),
        ).fetchone()
        return row["player_id"] if row else None
    rows = conn.execute(
        "SELECT player_id FROM players WHERE norm_name=?", (norm,)
    ).fetchall()
    if len(rows) > 1:
        print(
            f"prizepicks: ambiguous match for {player_name!r} "
            f"({len(rows)} players share this name and the payload carries no "
            "team) -- leaving unmatched",
            file=sys.stderr,
        )
        return None
    return rows[0]["player_id"] if rows else None


def ingest_lines(conn, payload, fetched_at):
    for ln in parse_projections(payload):
        player_id = _resolve_player_id(conn, ln["player_name"], ln.get("team_name", ""))
        conn.execute(
            """INSERT INTO prop_lines(fetched_at, source, player_name, player_id,
               stat_type, line) VALUES(?,?,?,?,?,?)""",
            (
                fetched_at,
                "prizepicks",
                ln["player_name"],
                player_id,
                ln["stat_type"],
                ln["line"],
            ),
        )
    conn.commit()


def fetch_projections():
    headers = {
        **config.DEFAULT_HEADERS,
        "Accept": "application/json",
        "Origin": "https://app.prizepicks.com",
        "Referer": "https://app.prizepicks.com/",
    }
    resp = requests.get(
        URL,
        params={"league_id": config.PRIZEPICKS_LEAGUE_ID, "per_page": 500},
        headers=headers,
        timeout=30,
    )
    if resp.status_code == 403:
        raise RuntimeError(
            "PrizePicks returned 403. Live fetching may require browser-like signed headers; "
            "fixture parser remains usable."
        )
    resp.raise_for_status()
    return resp.json()
