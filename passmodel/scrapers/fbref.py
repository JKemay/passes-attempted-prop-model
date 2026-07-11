import time
import requests
from bs4 import BeautifulSoup
from passmodel import config, db
from passmodel.util import normalize_name


def _uncomment(html: str) -> str:
    # FBref ships most stat tables inside HTML comments.
    return html.replace("<!--", "").replace("-->", "")


def _cell(row, stat):
    el = row.find(attrs={"data-stat": stat})
    return el.get_text(strip=True) if el else ""


def parse_match(html: str):
    soup = BeautifulSoup(_uncomment(html), "lxml")
    teams = []
    for table in soup.select('table[id$="_passing"]'):
        caption = table.find("caption")
        name = caption.get_text(strip=True).replace(" Passing Table", "") if caption else ""
        players = []
        body = table.find("tbody")
        for i, row in enumerate(body.find_all("tr") if body else []):
            pcell = row.find("th", attrs={"data-stat": "player"})
            if pcell is None or not pcell.get_text(strip=True):
                continue
            link = pcell.find("a")
            fbref_id = link["href"].split("/")[3] if link else None
            try:
                passes = int(_cell(row, "passes") or 0)
                minutes = int(_cell(row, "minutes") or 0)
            except ValueError:
                continue
            players.append(
                {
                    "name": pcell.get_text(strip=True),
                    "fbref_id": fbref_id,
                    "position": _cell(row, "position"),
                    "minutes": minutes,
                    "passes_attempted": passes,
                    "started": 1 if i < 11 else 0,
                }
            )
        teams.append(
            {
                "name": name,
                "players": players,
                "team_passes": sum(p["passes_attempted"] for p in players),
            }
        )
    return teams


def fetch_html(url: str) -> str:
    time.sleep(config.FBREF_DELAY_SECONDS)
    headers = {**config.DEFAULT_HEADERS, "Referer": "https://fbref.com/"}
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code == 403:
        raise RuntimeError(
            "FBref returned 403. Live fetching may require a browser/session fetch; "
            "keep parser changes fixture-driven."
        )
    resp.raise_for_status()
    return resp.text


def parse_fixtures(html: str):
    soup = BeautifulSoup(_uncomment(html), "lxml")
    out = []
    table = soup.select_one('table[id^="sched"]')
    if table is None:
        return out
    body = table.find("tbody")
    for row in body.find_all("tr") if body else []:
        date = _cell(row, "date")
        home = _cell(row, "home_team")
        away = _cell(row, "away_team")
        if not (date and home and away):
            continue
        rep = row.find(attrs={"data-stat": "match_report"})
        link = rep.find("a") if rep else None
        url = link["href"] if link else None
        fbref_match_id = url.split("/")[3] if url else None
        out.append(
            {
                "date": date,
                "home": home,
                "away": away,
                "match_url": url,
                "fbref_match_id": fbref_match_id,
            }
        )
    return out


def ingest_match(
    conn,
    html,
    date,
    competition,
    home,
    away,
    fbref_match_id=None,
    stage="",
    is_friendly=0,
    is_knockout=0,
):
    teams = parse_match(html)
    home_id = db.get_or_create_team(conn, home)
    away_id = db.get_or_create_team(conn, away)
    mid = db.get_or_create_match(
        conn,
        date,
        competition,
        home_id,
        away_id,
        fbref_match_id=fbref_match_id,
        stage=stage,
        is_friendly=is_friendly,
        is_knockout=is_knockout,
    )
    by_norm = {normalize_name(home): home_id, normalize_name(away): away_id}
    for t in teams:
        team_id = by_norm.get(normalize_name(t["name"]))
        if team_id is None:
            team_id = db.get_or_create_team(conn, t["name"])
        db.upsert_team_stat(conn, mid, team_id, "fbref", t["team_passes"])
        for p in t["players"]:
            pid = db.get_or_create_player(
                conn, p["name"], team_id, fbref_id=p["fbref_id"], position=p["position"]
            )
            db.upsert_player_stat(
                conn,
                mid,
                pid,
                team_id,
                "fbref",
                minutes=p["minutes"],
                passes_attempted=p["passes_attempted"],
                started=p["started"],
                position=p["position"],
            )
    return mid


def update_competition(conn, sched_url, competition, is_friendly=0):
    """Fetch schedule page, ingest played matches, and register upcoming matches."""
    rows = parse_fixtures(fetch_html(sched_url))
    ingested = 0
    for r in rows:
        home_id = db.get_or_create_team(conn, r["home"])
        away_id = db.get_or_create_team(conn, r["away"])
        if r["match_url"] is None:
            db.get_or_create_match(
                conn, r["date"], competition, home_id, away_id, is_friendly=is_friendly
            )
            continue
        exists = conn.execute(
            "SELECT 1 FROM matches WHERE fbref_match_id=?", (r["fbref_match_id"],)
        ).fetchone()
        if exists:
            continue
        html = fetch_html("https://fbref.com" + r["match_url"])
        ingest_match(
            conn,
            html,
            r["date"],
            competition,
            r["home"],
            r["away"],
            fbref_match_id=r["fbref_match_id"],
            is_friendly=is_friendly,
        )
        ingested += 1
    return ingested
