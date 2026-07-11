import time
import requests
from bs4 import BeautifulSoup
from passmodel import config


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
    resp = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.text
