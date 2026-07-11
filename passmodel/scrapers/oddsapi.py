import requests
from passmodel import config


def parse_odds(payload):
    rows = []
    for game in payload:
        home, away = game["home_team"], game["away_team"]
        spread = total = None
        for book in game.get("bookmakers", []):
            for market in book.get("markets", []):
                if market["key"] == "spreads" and spread is None:
                    for o in market["outcomes"]:
                        if o["name"] == home:
                            spread = float(o["point"])
                if market["key"] == "totals" and total is None:
                    for o in market["outcomes"]:
                        if o["name"] == "Over":
                            total = float(o["point"])
        rows.append(
            {
                "home": home,
                "away": away,
                "date": game["commence_time"][:10],
                "home_spread": spread,
                "total": total,
            }
        )
    return rows


def ingest_odds(conn, payload, fetched_at):
    for r in parse_odds(payload):
        match = conn.execute(
            """SELECT m.match_id FROM matches m
               JOIN teams h ON h.team_id=m.home_team_id
               JOIN teams a ON a.team_id=m.away_team_id
               WHERE m.date=? AND h.name=? AND a.name=?""",
            (r["date"], r["home"], r["away"]),
        ).fetchone()
        if match is None:
            continue
        conn.execute(
            """INSERT OR REPLACE INTO market_odds(match_id, fetched_at, home_spread, total)
               VALUES(?,?,?,?)""",
            (match["match_id"], fetched_at, r["home_spread"], r["total"]),
        )
    conn.commit()


def fetch_odds():
    if not config.ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY not set - skipping odds fetch")
    resp = requests.get(
        f"https://api.the-odds-api.com/v4/sports/{config.ODDS_SPORT_KEY}/odds",
        params={
            "apiKey": config.ODDS_API_KEY,
            "regions": "us",
            "markets": "spreads,totals",
        },
        headers=config.DEFAULT_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()
