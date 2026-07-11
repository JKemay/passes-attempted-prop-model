import requests
from passmodel import config
from passmodel.util import normalize_name

URL = "https://api.prizepicks.com/projections"


def parse_projections(payload):
    names = {
        inc["id"]: inc["attributes"].get("display_name", "")
        for inc in payload.get("included", [])
        if inc.get("type") == "new_player"
    }
    out = []
    for item in payload.get("data", []):
        attrs = item.get("attributes", {})
        if attrs.get("stat_type") != "Passes Attempted":
            continue
        rel = (((item.get("relationships") or {}).get("new_player") or {}).get("data") or {})
        out.append(
            {
                "player_name": names.get(rel.get("id"), ""),
                "stat_type": "Passes Attempted",
                "line": float(attrs["line_score"]),
            }
        )
    return out


def ingest_lines(conn, payload, fetched_at):
    for ln in parse_projections(payload):
        row = conn.execute(
            "SELECT player_id FROM players WHERE norm_name=?",
            (normalize_name(ln["player_name"]),),
        ).fetchone()
        conn.execute(
            """INSERT INTO prop_lines(fetched_at, source, player_name, player_id,
               stat_type, line) VALUES(?,?,?,?,?,?)""",
            (
                fetched_at,
                "prizepicks",
                ln["player_name"],
                row["player_id"] if row else None,
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
