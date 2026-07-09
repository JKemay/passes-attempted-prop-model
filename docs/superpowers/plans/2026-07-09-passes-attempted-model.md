# Passes-Attempted Prop Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local system that scrapes soccer data + prop lines, projects passes attempted as a Negative Binomial distribution per player, ranks props by edge, and serves a value board + per-prop breakdown dashboard.

**Architecture:** Scrapers (FBref backbone, FotMob cross-check, PrizePicks lines, Odds API game script) write to a single SQLite DB. A model engine fits coefficients from history (fit mode) and projects slates (project mode): `mu = exp_minutes/90 × team_passes_pred × player_share`, NB distribution → P(over) → edge. FastAPI serves a vanilla-JS dashboard.

**Tech Stack:** Python 3.11+, requests, beautifulsoup4+lxml, pandas, numpy, scipy, statsmodels, FastAPI+uvicorn, SQLite (stdlib sqlite3), pytest.

**Design rules for the executor:**
- Scraper *fetchers* are thin (network only). *Parsers* are pure functions tested against fixture HTML/JSON in `tests/fixtures/`. Never test against the live web.
- All dates are ISO strings (`YYYY-MM-DD`). All probability math in floats.
- Every DB-touching test uses the `conn` fixture (tmp SQLite), never the real DB.
- Frontend: all scraped/DB strings pass through the `esc()` helper before HTML interpolation (names come from scraped pages — treat as untrusted).
- Run all tests from repo root: `python -m pytest -q`.

**Spec deviation (backtest, agreed direction):** We have no archive of historical PrizePicks lines, so v1 calibration uses *pseudo-lines* (player's trailing median) — this validates the probability model. Real beat-the-line P&L accrues automatically once `prop_lines` starts filling daily. The backtest page states this.

---

## File structure

```
passmodel/
  __init__.py
  config.py            # paths + tunables, plain-English comments
  util.py              # name normalization
  db.py                # schema + upsert helpers
  scrapers/
    __init__.py
    fbref.py           # parse + fetch FBref match pages & fixtures
    fotmob.py          # parse FotMob match JSON, cross-check
    prizepicks.py      # prop lines
    oddsapi.py         # spread/total
  model/
    __init__.py
    features.py        # rolling baselines, share, minutes from DB
    team_volume.py     # fitted team-passes regression
    distribution.py    # negative binomial P(over)
    engine.py          # fit mode / project mode
  backtest.py
webapp/
  main.py              # FastAPI app
  static/index.html    # board + detail + backtest (inline JS/CSS)
scripts/
  update.py            # orchestrates all scrapers
  fit.py               # refit coefficients
  project.py           # project current slate
update.bat  dashboard.bat
tests/  (mirrors package)
requirements.txt
```

---

### Task 1: Project skeleton

**Files:**
- Create: `requirements.txt`, `passmodel/__init__.py`, `passmodel/config.py`, `passmodel/util.py`, `passmodel/scrapers/__init__.py`, `passmodel/model/__init__.py`, `tests/__init__.py`, `tests/test_util.py`, `.gitignore`

- [ ] **Step 1: Create requirements and install**

`requirements.txt`:
```
requests
beautifulsoup4
lxml
pandas
numpy
scipy
statsmodels
fastapi
uvicorn
httpx
pytest
```

Run: `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`
(All later commands assume `.venv\Scripts\python` / activate the venv.)

- [ ] **Step 2: Create `.gitignore`**

```
.venv/
__pycache__/
data/
*.pyc
.pytest_cache/
model_params.json
```

- [ ] **Step 3: Write failing test for name normalization**

`tests/test_util.py`:
```python
from passmodel.util import normalize_name

def test_strips_accents_and_case():
    assert normalize_name("Manuel Akanji") == "manuel akanji"
    assert normalize_name("  Rúben  Días ") == "ruben dias"
```

Run: `python -m pytest tests/test_util.py -q` — Expected: FAIL (module missing).

- [ ] **Step 4: Implement config + util**

`passmodel/config.py`:
```python
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "passmodel.db"
PARAMS_PATH = ROOT / "model_params.json"

# --- scraping ---
FBREF_DELAY_SECONDS = 6.0          # FBref rate limit: be polite or get banned
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) passmodel/0.1"
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_SPORT_KEY = "soccer_fifa_world_cup"
PRIZEPICKS_LEAGUE_ID = 82          # soccer

# --- model tunables ---
SHRINKAGE_K = 5          # games of "prior weight" when shrinking player share
FRIENDLY_WEIGHT = 0.5    # friendlies count half in fitting/baselines
BASELINE_WINDOW = 10     # matches for team rolling baselines
SHARE_WINDOW = 15        # matches for player share
MINUTES_WINDOW = 5       # matches for expected minutes
BREAKEVEN_PROB = 0.52    # implied prob a pick must beat (PrizePicks-ish)
SOURCE_DISAGREE_PASSES = 5   # flag if FBref vs FotMob differ by more than this
```

`passmodel/util.py`:
```python
import unicodedata


def normalize_name(name: str) -> str:
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    return " ".join(n.lower().split())
```

`passmodel/__init__.py`, `passmodel/scrapers/__init__.py`, `passmodel/model/__init__.py`, `tests/__init__.py`: empty files.

- [ ] **Step 5: Run test — PASS, then commit**

Run: `python -m pytest -q` — Expected: 1 passed.
```bash
git add -A && git commit -m "feat: project skeleton, config, name normalization"
```

---

### Task 2: Database schema and helpers

**Files:**
- Create: `passmodel/db.py`, `tests/conftest.py`, `tests/test_db.py`

- [ ] **Step 1: Write conftest + failing tests**

`tests/conftest.py`:
```python
import pytest
from passmodel import db


@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(tmp_path / "test.db")
    db.init_db(c)
    yield c
    c.close()
```

`tests/test_db.py`:
```python
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
```

Run: `python -m pytest tests/test_db.py -q` — Expected: FAIL.

- [ ] **Step 2: Implement `passmodel/db.py`**

```python
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
            conn.execute("UPDATE players SET position=? WHERE player_id=? AND position=''",
                         (position, row["player_id"]))
            conn.commit()
        return row["player_id"]
    cur = conn.execute(
        "INSERT INTO players(name, norm_name, fbref_id, team_id, position) VALUES(?,?,?,?,?)",
        (name.strip(), norm, fbref_id, team_id, position or ""),
    )
    conn.commit()
    return cur.lastrowid


def get_or_create_match(conn, date, competition, home_team_id, away_team_id,
                        fbref_match_id=None, stage="", is_friendly=0, is_knockout=0):
    row = conn.execute(
        "SELECT match_id FROM matches WHERE date=? AND home_team_id=? AND away_team_id=?",
        (date, home_team_id, away_team_id),
    ).fetchone()
    if row:
        return row["match_id"]
    cur = conn.execute(
        """INSERT INTO matches(fbref_match_id, date, competition, stage, is_friendly,
           is_knockout, home_team_id, away_team_id) VALUES(?,?,?,?,?,?,?,?)""",
        (fbref_match_id, date, competition, stage, is_friendly, is_knockout,
         home_team_id, away_team_id),
    )
    conn.commit()
    return cur.lastrowid


def upsert_player_stat(conn, match_id, player_id, team_id, source,
                       minutes=0, passes_attempted=None, started=0, position=""):
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
    conn.execute("INSERT INTO scrape_log(run_at, source, ok, detail) VALUES(?,?,?,?)",
                 (run_at, source, int(ok), detail))
    conn.commit()
```

- [ ] **Step 3: Run tests — PASS, commit**

Run: `python -m pytest -q` — Expected: all pass.
```bash
git add -A && git commit -m "feat: sqlite schema and upsert helpers"
```

---

### Task 3: FBref match parser (fixture-driven)

FBref hides stat tables inside HTML comments; parser must un-comment first. Player passing tables have ids ending `_passing`, cells carry `data-stat` attributes (`player`, `minutes`, `passes` = attempted, `position`). First 11 tbody rows of a team's table are the starters.

**Files:**
- Create: `passmodel/scrapers/fbref.py`, `tests/fixtures/fbref_match.html`, `tests/test_fbref_parser.py`

- [ ] **Step 1: Create fixture `tests/fixtures/fbref_match.html`**

```html
<html><body>
<div>
<!--
<table id="stats_abc111_passing">
<caption>Switzerland Passing Table</caption>
<tbody>
<tr><th data-stat="player"><a href="/en/players/aaa111/Manuel-Akanji">Manuel Akanji</a></th>
<td data-stat="position">CB</td><td data-stat="minutes">90</td>
<td data-stat="passes_completed">72</td><td data-stat="passes">78</td></tr>
<tr><th data-stat="player"><a href="/en/players/bbb222/Granit-Xhaka">Granit Xhaka</a></th>
<td data-stat="position">MF</td><td data-stat="minutes">90</td>
<td data-stat="passes_completed">80</td><td data-stat="passes">85</td></tr>
</tbody>
</table>
-->
</div>
<div>
<!--
<table id="stats_def222_passing">
<caption>Colombia Passing Table</caption>
<tbody>
<tr><th data-stat="player"><a href="/en/players/ccc333/James-Rodriguez">James Rodríguez</a></th>
<td data-stat="position">AM</td><td data-stat="minutes">78</td>
<td data-stat="passes_completed">30</td><td data-stat="passes">41</td></tr>
</tbody>
</table>
-->
</div>
</body></html>
```

- [ ] **Step 2: Write failing test**

`tests/test_fbref_parser.py`:
```python
from pathlib import Path
from passmodel.scrapers import fbref

FIX = Path(__file__).parent / "fixtures"


def test_parse_match_extracts_teams_and_players():
    html = (FIX / "fbref_match.html").read_text(encoding="utf-8")
    teams = fbref.parse_match(html)
    assert len(teams) == 2
    sui = teams[0]
    assert sui["name"] == "Switzerland"
    akanji = sui["players"][0]
    assert akanji["name"] == "Manuel Akanji"
    assert akanji["fbref_id"] == "aaa111"
    assert akanji["passes_attempted"] == 78
    assert akanji["minutes"] == 90
    assert akanji["position"] == "CB"
    assert akanji["started"] == 1          # row index < 11
    assert sui["team_passes"] == 78 + 85   # sum of player rows
```

Run: `python -m pytest tests/test_fbref_parser.py -q` — Expected: FAIL.

- [ ] **Step 3: Implement parser in `passmodel/scrapers/fbref.py`**

```python
import time
import requests
from bs4 import BeautifulSoup
from passmodel import config


def _uncomment(html: str) -> str:
    # FBref ships most stat tables inside HTML comments
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
            players.append({
                "name": pcell.get_text(strip=True),
                "fbref_id": fbref_id,
                "position": _cell(row, "position"),
                "minutes": minutes,
                "passes_attempted": passes,
                "started": 1 if i < 11 else 0,
            })
        teams.append({
            "name": name,
            "players": players,
            "team_passes": sum(p["passes_attempted"] for p in players),
        })
    return teams


def fetch_html(url: str) -> str:
    time.sleep(config.FBREF_DELAY_SECONDS)
    resp = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.text
```

- [ ] **Step 4: Run tests — PASS, commit**

Run: `python -m pytest -q`
```bash
git add -A && git commit -m "feat: fbref match parser with fixture test"
```

---

### Task 4: FBref fixtures parser + ingest

**Files:**
- Modify: `passmodel/scrapers/fbref.py` (append)
- Create: `tests/fixtures/fbref_sched.html`, `tests/test_fbref_ingest.py`

- [ ] **Step 1: Create fixture `tests/fixtures/fbref_sched.html`**

```html
<html><body>
<table id="sched_2026_1">
<tbody>
<tr><td data-stat="date">2026-06-20</td>
<td data-stat="home_team"><a href="/x">Switzerland</a></td>
<td data-stat="away_team"><a href="/y">Colombia</a></td>
<td data-stat="match_report"><a href="/en/matches/m123/report">Match Report</a></td></tr>
<tr><td data-stat="date">2026-06-21</td>
<td data-stat="home_team"><a href="/x">Spain</a></td>
<td data-stat="away_team"><a href="/y">Ghana</a></td>
<td data-stat="match_report"><a href="/en/matches/m456/report">Match Report</a></td></tr>
<tr><td data-stat="date">2026-07-15</td>
<td data-stat="home_team"><a href="/x">France</a></td>
<td data-stat="away_team"><a href="/y">Brazil</a></td>
<td data-stat="match_report"></td></tr>
</tbody>
</table>
</body></html>
```

- [ ] **Step 2: Write failing tests**

`tests/test_fbref_ingest.py`:
```python
from pathlib import Path
from passmodel.scrapers import fbref

FIX = Path(__file__).parent / "fixtures"


def test_parse_fixtures_returns_played_and_upcoming():
    html = (FIX / "fbref_sched.html").read_text(encoding="utf-8")
    rows = fbref.parse_fixtures(html)
    assert len(rows) == 3
    assert rows[0] == {"date": "2026-06-20", "home": "Switzerland", "away": "Colombia",
                       "match_url": "/en/matches/m123/report", "fbref_match_id": "m123"}
    assert rows[2]["match_url"] is None   # not played yet


def test_ingest_match_writes_all_tables(conn):
    html = (FIX / "fbref_match.html").read_text(encoding="utf-8")
    mid = fbref.ingest_match(conn, html, date="2026-06-20", competition="World Cup",
                             home="Switzerland", away="Colombia", fbref_match_id="m123")
    n_players = conn.execute("SELECT COUNT(*) c FROM player_match_stats").fetchone()["c"]
    n_teams = conn.execute("SELECT COUNT(*) c FROM team_match_stats").fetchone()["c"]
    assert n_players == 3 and n_teams == 2
    sui = conn.execute(
        "SELECT passes_attempted FROM team_match_stats t JOIN teams x ON x.team_id=t.team_id "
        "WHERE x.name='Switzerland'").fetchone()
    assert sui["passes_attempted"] == 163
```

Run: `python -m pytest tests/test_fbref_ingest.py -q` — Expected: FAIL.

- [ ] **Step 3: Append to `passmodel/scrapers/fbref.py`**

```python
from passmodel import db
from passmodel.util import normalize_name


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
        out.append({"date": date, "home": home, "away": away,
                    "match_url": url, "fbref_match_id": fbref_match_id})
    return out


def ingest_match(conn, html, date, competition, home, away, fbref_match_id=None,
                 stage="", is_friendly=0, is_knockout=0):
    teams = parse_match(html)
    home_id = db.get_or_create_team(conn, home)
    away_id = db.get_or_create_team(conn, away)
    mid = db.get_or_create_match(conn, date, competition, home_id, away_id,
                                 fbref_match_id=fbref_match_id, stage=stage,
                                 is_friendly=is_friendly, is_knockout=is_knockout)
    by_norm = {normalize_name(home): home_id, normalize_name(away): away_id}
    for t in teams:
        team_id = by_norm.get(normalize_name(t["name"]))
        if team_id is None:
            team_id = db.get_or_create_team(conn, t["name"])
        db.upsert_team_stat(conn, mid, team_id, "fbref", t["team_passes"])
        for p in t["players"]:
            pid = db.get_or_create_player(conn, p["name"], team_id,
                                          fbref_id=p["fbref_id"], position=p["position"])
            db.upsert_player_stat(conn, mid, pid, team_id, "fbref",
                                  minutes=p["minutes"],
                                  passes_attempted=p["passes_attempted"],
                                  started=p["started"], position=p["position"])
    return mid


def update_competition(conn, sched_url, competition, is_friendly=0):
    """Fetch schedule page, ingest any played match not already in DB.
    Also registers upcoming matches (no stats) so projections can find them."""
    rows = parse_fixtures(fetch_html(sched_url))
    ingested = 0
    for r in rows:
        home_id = db.get_or_create_team(conn, r["home"])
        away_id = db.get_or_create_team(conn, r["away"])
        if r["match_url"] is None:
            db.get_or_create_match(conn, r["date"], competition, home_id, away_id,
                                   is_friendly=is_friendly)
            continue
        exists = conn.execute("SELECT 1 FROM matches WHERE fbref_match_id=?",
                              (r["fbref_match_id"],)).fetchone()
        if exists:
            continue
        html = fetch_html("https://fbref.com" + r["match_url"])
        ingest_match(conn, html, r["date"], competition, r["home"], r["away"],
                     fbref_match_id=r["fbref_match_id"], is_friendly=is_friendly)
        ingested += 1
    return ingested
```

- [ ] **Step 4: Run tests — PASS, commit**

Run: `python -m pytest -q`
```bash
git add -A && git commit -m "feat: fbref schedule parsing and match ingest"
```

---

### Task 5: FotMob cross-check

FotMob's JSON (`https://www.fotmob.com/api/matchDetails?matchId=N`) nests player stats; "Accurate passes" carries `{"value": completed, "total": attempted}`. FotMob may require signed headers — fetch failures must be logged, never fatal (it's a secondary source).

**Files:**
- Create: `passmodel/scrapers/fotmob.py`, `tests/fixtures/fotmob_match.json`, `tests/test_fotmob.py`

- [ ] **Step 1: Create fixture `tests/fixtures/fotmob_match.json`**

```json
{"content": {"playerStats": {
  "101": {"name": "Manuel Akanji", "teamId": 1,
    "stats": [{"title": "Top stats", "stats": {
      "Accurate passes": {"stat": {"value": 70, "total": 74}},
      "Minutes played": {"stat": {"value": 90}}}}]},
  "102": {"name": "Granit Xhaka", "teamId": 1,
    "stats": [{"title": "Top stats", "stats": {
      "Accurate passes": {"stat": {"value": 79, "total": 83}},
      "Minutes played": {"stat": {"value": 90}}}}]}
}}}
```

- [ ] **Step 2: Write failing tests**

`tests/test_fotmob.py`:
```python
import json
from pathlib import Path
from passmodel import db
from passmodel.scrapers import fotmob

FIX = Path(__file__).parent / "fixtures"


def _load():
    return json.loads((FIX / "fotmob_match.json").read_text(encoding="utf-8"))


def test_parse_match_json():
    players = fotmob.parse_match_json(_load())
    assert players[0] == {"name": "Manuel Akanji", "passes_attempted": 74, "minutes": 90}


def test_cross_check_flags_disagreement(conn):
    t = db.get_or_create_team(conn, "Switzerland")
    p = db.get_or_create_player(conn, "Manuel Akanji", t)
    m = db.get_or_create_match(conn, "2026-06-20", "World Cup", t, t)
    db.upsert_player_stat(conn, m, p, t, "fbref", minutes=90, passes_attempted=78)
    db.upsert_player_stat(conn, m, p, t, "fotmob", minutes=90, passes_attempted=70)
    flags = fotmob.cross_check(conn, m)
    assert len(flags) == 1 and flags[0]["diff"] == 8
```

Run: `python -m pytest tests/test_fotmob.py -q` — Expected: FAIL.

- [ ] **Step 3: Implement `passmodel/scrapers/fotmob.py`**

```python
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
            out.append({"name": pdata.get("name", ""), "passes_attempted": passes,
                        "minutes": minutes or 0})
    return out


def ingest_match(conn, match_id, data):
    """Attach fotmob rows to players already known from fbref (matched by name)."""
    known = conn.execute(
        """SELECT p.player_id, p.norm_name, s.team_id FROM player_match_stats s
           JOIN players p ON p.player_id = s.player_id
           WHERE s.match_id=? AND s.source='fbref'""", (match_id,)).fetchall()
    by_norm = {r["norm_name"]: r for r in known}
    for pl in parse_match_json(data):
        row = by_norm.get(normalize_name(pl["name"]))
        if row is None:
            continue
        db.upsert_player_stat(conn, match_id, row["player_id"], row["team_id"], "fotmob",
                              minutes=pl["minutes"], passes_attempted=pl["passes_attempted"])


def cross_check(conn, match_id):
    rows = conn.execute(
        """SELECT a.player_id, a.passes_attempted fb, b.passes_attempted fm
           FROM player_match_stats a
           JOIN player_match_stats b
             ON a.match_id=b.match_id AND a.player_id=b.player_id
           WHERE a.match_id=? AND a.source='fbref' AND b.source='fotmob'""",
        (match_id,)).fetchall()
    flags = []
    for r in rows:
        diff = abs((r["fb"] or 0) - (r["fm"] or 0))
        if diff > config.SOURCE_DISAGREE_PASSES:
            flags.append({"player_id": r["player_id"], "diff": diff})
    return flags


def fetch_match_json(fotmob_match_id):
    resp = requests.get(f"https://www.fotmob.com/api/matchDetails?matchId={fotmob_match_id}",
                        headers={"User-Agent": config.USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 4: Run tests — PASS, commit**

```bash
git add -A && git commit -m "feat: fotmob parser, ingest, source cross-check"
```

---

### Task 6: PrizePicks lines scraper

**Files:**
- Create: `passmodel/scrapers/prizepicks.py`, `tests/fixtures/prizepicks.json`, `tests/test_prizepicks.py`

- [ ] **Step 1: Create fixture `tests/fixtures/prizepicks.json`**

```json
{"data": [
  {"id": "1", "type": "projection",
   "attributes": {"line_score": 64.5, "stat_type": "Passes Attempted"},
   "relationships": {"new_player": {"data": {"id": "p1", "type": "new_player"}}}},
  {"id": "2", "type": "projection",
   "attributes": {"line_score": 2.5, "stat_type": "Shots"},
   "relationships": {"new_player": {"data": {"id": "p1", "type": "new_player"}}}}
],
"included": [
  {"id": "p1", "type": "new_player", "attributes": {"display_name": "Manuel Akanji"}}
]}
```

- [ ] **Step 2: Write failing tests**

`tests/test_prizepicks.py`:
```python
import json
from pathlib import Path
from passmodel import db
from passmodel.scrapers import prizepicks

FIX = Path(__file__).parent / "fixtures"


def _load():
    return json.loads((FIX / "prizepicks.json").read_text(encoding="utf-8"))


def test_parse_filters_to_passes_attempted():
    lines = prizepicks.parse_projections(_load())
    assert lines == [{"player_name": "Manuel Akanji", "stat_type": "Passes Attempted",
                      "line": 64.5}]


def test_ingest_matches_known_player(conn):
    t = db.get_or_create_team(conn, "Switzerland")
    pid = db.get_or_create_player(conn, "Manuel Akanji", t)
    prizepicks.ingest_lines(conn, _load(), fetched_at="2026-07-09T12:00:00")
    row = conn.execute("SELECT player_id, line FROM prop_lines").fetchone()
    assert row["player_id"] == pid and row["line"] == 64.5
```

Run: `python -m pytest tests/test_prizepicks.py -q` — Expected: FAIL.

- [ ] **Step 3: Implement `passmodel/scrapers/prizepicks.py`**

```python
import requests
from passmodel import config
from passmodel.util import normalize_name

URL = "https://api.prizepicks.com/projections"


def parse_projections(payload):
    names = {inc["id"]: inc["attributes"].get("display_name", "")
             for inc in payload.get("included", []) if inc.get("type") == "new_player"}
    out = []
    for item in payload.get("data", []):
        attrs = item.get("attributes", {})
        if attrs.get("stat_type") != "Passes Attempted":
            continue
        rel = (((item.get("relationships") or {}).get("new_player") or {}).get("data") or {})
        out.append({"player_name": names.get(rel.get("id"), ""),
                    "stat_type": "Passes Attempted",
                    "line": float(attrs["line_score"])})
    return out


def ingest_lines(conn, payload, fetched_at):
    for ln in parse_projections(payload):
        row = conn.execute("SELECT player_id FROM players WHERE norm_name=?",
                           (normalize_name(ln["player_name"]),)).fetchone()
        conn.execute(
            """INSERT INTO prop_lines(fetched_at, source, player_name, player_id,
               stat_type, line) VALUES(?,?,?,?,?,?)""",
            (fetched_at, "prizepicks", ln["player_name"],
             row["player_id"] if row else None, ln["stat_type"], ln["line"]))
    conn.commit()


def fetch_projections():
    resp = requests.get(URL, params={"league_id": config.PRIZEPICKS_LEAGUE_ID,
                                     "per_page": 500},
                        headers={"User-Agent": config.USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 4: Run tests — PASS, commit**

```bash
git add -A && git commit -m "feat: prizepicks lines scraper"
```

---

### Task 7: Odds API client (game script)

**Files:**
- Create: `passmodel/scrapers/oddsapi.py`, `tests/fixtures/oddsapi.json`, `tests/test_oddsapi.py`

- [ ] **Step 1: Create fixture `tests/fixtures/oddsapi.json`**

```json
[{"home_team": "Switzerland", "away_team": "Colombia",
  "commence_time": "2026-07-10T19:00:00Z",
  "bookmakers": [{"key": "draftkings", "markets": [
    {"key": "spreads", "outcomes": [
      {"name": "Switzerland", "point": -0.5}, {"name": "Colombia", "point": 0.5}]},
    {"key": "totals", "outcomes": [
      {"name": "Over", "point": 2.5}, {"name": "Under", "point": 2.5}]}]}]}]
```

- [ ] **Step 2: Write failing tests**

`tests/test_oddsapi.py`:
```python
import json
from pathlib import Path
from passmodel import db
from passmodel.scrapers import oddsapi

FIX = Path(__file__).parent / "fixtures"


def _load():
    return json.loads((FIX / "oddsapi.json").read_text(encoding="utf-8"))


def test_parse_odds():
    rows = oddsapi.parse_odds(_load())
    assert rows == [{"home": "Switzerland", "away": "Colombia", "date": "2026-07-10",
                     "home_spread": -0.5, "total": 2.5}]


def test_ingest_attaches_to_match(conn):
    h = db.get_or_create_team(conn, "Switzerland")
    a = db.get_or_create_team(conn, "Colombia")
    m = db.get_or_create_match(conn, "2026-07-10", "World Cup", h, a)
    oddsapi.ingest_odds(conn, _load(), fetched_at="2026-07-09T12:00:00")
    row = conn.execute("SELECT * FROM market_odds WHERE match_id=?", (m,)).fetchone()
    assert row["home_spread"] == -0.5 and row["total"] == 2.5
```

Run: `python -m pytest tests/test_oddsapi.py -q` — Expected: FAIL.

- [ ] **Step 3: Implement `passmodel/scrapers/oddsapi.py`**

```python
import requests
from passmodel import config
from passmodel.util import normalize_name


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
        rows.append({"home": home, "away": away,
                     "date": game["commence_time"][:10],
                     "home_spread": spread, "total": total})
    return rows


def ingest_odds(conn, payload, fetched_at):
    for r in parse_odds(payload):
        match = conn.execute(
            """SELECT m.match_id FROM matches m
               JOIN teams h ON h.team_id=m.home_team_id
               JOIN teams a ON a.team_id=m.away_team_id
               WHERE m.date=? AND h.name=? AND a.name=?""",
            (r["date"], r["home"], r["away"])).fetchone()
        if match is None:
            continue
        conn.execute(
            """INSERT OR REPLACE INTO market_odds(match_id, fetched_at, home_spread, total)
               VALUES(?,?,?,?)""",
            (match["match_id"], fetched_at, r["home_spread"], r["total"]))
    conn.commit()


def fetch_odds():
    if not config.ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY not set — skipping odds fetch")
    resp = requests.get(
        f"https://api.the-odds-api.com/v4/sports/{config.ODDS_SPORT_KEY}/odds",
        params={"apiKey": config.ODDS_API_KEY, "regions": "us",
                "markets": "spreads,totals"}, timeout=30)
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 4: Run tests — PASS, commit**

```bash
git add -A && git commit -m "feat: odds api client for spread/total"
```

---

### Task 8: Feature builders (baselines, share, minutes)

**Files:**
- Create: `passmodel/model/features.py`, `tests/seed.py`, `tests/test_features.py`

- [ ] **Step 1: Create `tests/seed.py` (deterministic history helper)**

```python
"""Seeds a small deterministic history: Switzerland vs a rotating set of opponents.
Akanji plays 90' every match with linearly rising passes; team passes fixed per match."""
from passmodel import db


def make_history(conn, n_matches=12, team_passes=500, akanji_base=60):
    sui = db.get_or_create_team(conn, "Switzerland")
    akanji = db.get_or_create_player(conn, "Manuel Akanji", sui, position="CB")
    xhaka = db.get_or_create_player(conn, "Granit Xhaka", sui, position="MF")
    for i in range(n_matches):
        opp = db.get_or_create_team(conn, f"Opponent {i}")
        date = f"2026-01-{i + 1:02d}"
        m = db.get_or_create_match(conn, date, "Qualifiers", sui, opp,
                                   is_friendly=1 if i % 4 == 0 else 0)
        db.upsert_team_stat(conn, m, sui, "fbref", team_passes)
        db.upsert_team_stat(conn, m, opp, "fbref", 350)
        db.upsert_player_stat(conn, m, akanji, sui, "fbref", minutes=90,
                              passes_attempted=akanji_base + i, started=1, position="CB")
        db.upsert_player_stat(conn, m, xhaka, sui, "fbref", minutes=90,
                              passes_attempted=80, started=1, position="MF")
    return {"sui": sui, "akanji": akanji, "xhaka": xhaka}
```

- [ ] **Step 2: Write failing tests**

`tests/test_features.py`:
```python
from passmodel.model import features
from tests.seed import make_history


def test_team_baseline_weighted(conn):
    make_history(conn, n_matches=12, team_passes=500)
    base = features.team_baseline(conn, team_id=1, before_date="2026-02-01")
    assert abs(base - 500) < 1e-6   # constant series -> baseline equals it


def test_opp_allowed_baseline(conn):
    make_history(conn)
    # every opponent allowed Switzerland 500 passes; SUI 'allows' 350
    allowed = features.opp_allowed_baseline(conn, team_id=1, before_date="2026-02-01")
    assert abs(allowed - 350) < 1e-6


def test_player_share_and_shrinkage(conn):
    ids = make_history(conn, n_matches=12, team_passes=500, akanji_base=60)
    games = features.player_share_games(conn, ids["akanji"], before_date="2026-02-01")
    assert len(games) == 12
    raw = sum(g["share"] for g in games) / len(games)
    shrunk = features.shrunk_share(games, prior=0.08)
    # shrinkage pulls toward prior but with 12 games stays near raw
    assert abs(shrunk - raw) < abs(0.08 - raw)


def test_expected_minutes(conn):
    ids = make_history(conn)
    em = features.expected_minutes(conn, ids["akanji"], before_date="2026-02-01")
    assert em == 90


def test_position_prior_share(conn):
    make_history(conn)
    prior_cb = features.position_prior_share(conn, "CB", before_date="2026-02-01")
    prior_mf = features.position_prior_share(conn, "MF", before_date="2026-02-01")
    assert prior_mf > prior_cb   # xhaka's 80 vs akanji's ~65 avg on 500 team passes
```

Run: `python -m pytest tests/test_features.py -q` — Expected: FAIL.

Note: `player_share_games` uses window `n=SHARE_WINDOW=15`, so all 12 seeded games return.

- [ ] **Step 3: Implement `passmodel/model/features.py`**

```python
from passmodel import config


def _recent_team_rows(conn, team_id, before_date, n):
    return conn.execute(
        """SELECT s.passes_attempted, m.is_friendly FROM team_match_stats s
           JOIN matches m ON m.match_id = s.match_id
           WHERE s.team_id=? AND s.source='fbref' AND m.date < ?
           ORDER BY m.date DESC LIMIT ?""",
        (team_id, before_date, n)).fetchall()


def _weighted_avg(rows):
    num = den = 0.0
    for r in rows:
        w = config.FRIENDLY_WEIGHT if r["is_friendly"] else 1.0
        num += w * r["passes_attempted"]
        den += w
    return num / den if den else None


def team_baseline(conn, team_id, before_date, n=config.BASELINE_WINDOW):
    return _weighted_avg(_recent_team_rows(conn, team_id, before_date, n))


def opp_allowed_baseline(conn, team_id, before_date, n=config.BASELINE_WINDOW):
    """Average passes attempted BY this team's opponents (what this team allows)."""
    rows = conn.execute(
        """SELECT s.passes_attempted, m.is_friendly FROM team_match_stats s
           JOIN matches m ON m.match_id = s.match_id
           WHERE s.source='fbref' AND m.date < ? AND s.team_id != ?
             AND (m.home_team_id=? OR m.away_team_id=?)
           ORDER BY m.date DESC LIMIT ?""",
        (before_date, team_id, team_id, team_id, n)).fetchall()
    return _weighted_avg(rows)


def player_share_games(conn, player_id, before_date, n=config.SHARE_WINDOW):
    rows = conn.execute(
        """SELECT p.passes_attempted p_att, p.minutes, t.passes_attempted t_att,
                  m.is_friendly, m.date
           FROM player_match_stats p
           JOIN team_match_stats t ON t.match_id=p.match_id AND t.team_id=p.team_id
                                   AND t.source='fbref'
           JOIN matches m ON m.match_id = p.match_id
           WHERE p.player_id=? AND p.source='fbref' AND m.date < ? AND p.minutes > 0
           ORDER BY m.date DESC LIMIT ?""",
        (player_id, before_date, n)).fetchall()
    out = []
    for r in rows:
        if not r["t_att"]:
            continue
        # per-90 share: what fraction of team volume he'd take across a full match
        share = (r["p_att"] / r["t_att"]) * (90.0 / max(r["minutes"], 1))
        out.append({"share": share, "minutes": r["minutes"], "date": r["date"],
                    "passes": r["p_att"], "team_passes": r["t_att"],
                    "weight": config.FRIENDLY_WEIGHT if r["is_friendly"] else 1.0})
    return out


def shrunk_share(games, prior, k=config.SHRINKAGE_K):
    if not games:
        return prior
    num = sum(g["share"] * g["weight"] for g in games) + prior * k
    den = sum(g["weight"] for g in games) + k
    return num / den


def expected_minutes(conn, player_id, before_date, n=config.MINUTES_WINDOW):
    rows = conn.execute(
        """SELECT p.minutes FROM player_match_stats p
           JOIN matches m ON m.match_id=p.match_id
           WHERE p.player_id=? AND p.source='fbref' AND m.date < ?
           ORDER BY m.date DESC LIMIT ?""",
        (player_id, before_date, n)).fetchall()
    if not rows:
        return 0.0
    return sum(r["minutes"] for r in rows) / len(rows)


def position_prior_share(conn, position, before_date):
    rows = conn.execute(
        """SELECT p.passes_attempted p_att, p.minutes, t.passes_attempted t_att
           FROM player_match_stats p
           JOIN team_match_stats t ON t.match_id=p.match_id AND t.team_id=p.team_id
                                   AND t.source='fbref'
           JOIN matches m ON m.match_id=p.match_id
           WHERE p.position=? AND p.source='fbref' AND m.date < ? AND p.minutes >= 45""",
        (position, before_date)).fetchall()
    shares = [(r["p_att"] / r["t_att"]) * (90.0 / r["minutes"])
              for r in rows if r["t_att"]]
    return sum(shares) / len(shares) if shares else 0.08  # league-ish fallback
```

- [ ] **Step 4: Run tests — PASS, commit**

```bash
git add -A && git commit -m "feat: feature builders for baselines, share, minutes"
```

---

### Task 9: Team volume regression

**Files:**
- Create: `passmodel/model/team_volume.py`, `tests/test_team_volume.py`

- [ ] **Step 1: Write failing tests**

`tests/test_team_volume.py`:
```python
from passmodel.model import team_volume
from tests.seed import make_history


def test_fit_and_predict_roundtrip(conn):
    make_history(conn, n_matches=12, team_passes=500)
    df = team_volume.build_training_frame(conn)
    assert len(df) > 0
    fitted = team_volume.fit(df)
    pred = team_volume.predict(fitted, base=500, opp=500, spread=None, total=None)
    # constant world: prediction should be near the constant
    assert abs(pred - 500) < 25


def test_predict_uses_imputation_when_market_missing(conn):
    make_history(conn)
    fitted = team_volume.fit(team_volume.build_training_frame(conn))
    a = team_volume.predict(fitted, base=500, opp=350)
    assert a is not None
```

Run: `python -m pytest tests/test_team_volume.py -q` — Expected: FAIL.

- [ ] **Step 2: Implement `passmodel/model/team_volume.py`**

```python
import json
import pandas as pd
import statsmodels.api as sm
from passmodel import config
from passmodel.model import features


def build_training_frame(conn):
    rows = []
    matches = conn.execute("SELECT * FROM matches ORDER BY date").fetchall()
    for m in matches:
        pairs = ((m["home_team_id"], m["away_team_id"], 1),
                 (m["away_team_id"], m["home_team_id"], -1))
        for team_id, opp_id, sign in pairs:
            stat = conn.execute(
                """SELECT passes_attempted FROM team_match_stats
                   WHERE match_id=? AND team_id=? AND source='fbref'""",
                (m["match_id"], team_id)).fetchone()
            if stat is None:
                continue
            base = features.team_baseline(conn, team_id, m["date"])
            opp = features.opp_allowed_baseline(conn, opp_id, m["date"])
            if base is None or opp is None:
                continue
            odds = conn.execute(
                """SELECT home_spread, total FROM market_odds WHERE match_id=?
                   ORDER BY fetched_at DESC LIMIT 1""", (m["match_id"],)).fetchone()
            spread = (sign * odds["home_spread"]
                      if odds and odds["home_spread"] is not None else None)
            total = odds["total"] if odds else None
            rows.append({"y": stat["passes_attempted"], "base": base, "opp": opp,
                         "spread": spread, "total": total,
                         "w": config.FRIENDLY_WEIGHT if m["is_friendly"] else 1.0})
    return pd.DataFrame(rows)


def fit(df):
    impute = {
        "spread": float(df["spread"].dropna().mean()) if df["spread"].notna().any() else 0.0,
        "total": float(df["total"].dropna().mean()) if df["total"].notna().any() else 2.5,
    }
    X = df[["base", "opp", "spread", "total"]].fillna(value=impute)
    X = sm.add_constant(X, has_constant="add")
    res = sm.WLS(df["y"], X, weights=df["w"]).fit()
    return {"params": {k: float(v) for k, v in res.params.items()},
            "impute": impute, "n": int(len(df))}


def predict(fitted, base, opp, spread=None, total=None):
    p, imp = fitted["params"], fitted["impute"]
    spread = imp["spread"] if spread is None else spread
    total = imp["total"] if total is None else total
    return (p.get("const", 0.0) + p["base"] * base + p["opp"] * opp
            + p["spread"] * spread + p["total"] * total)


def save(fitted, path=config.PARAMS_PATH):
    path.write_text(json.dumps(fitted, indent=2))


def load(path=config.PARAMS_PATH):
    return json.loads(path.read_text())
```

- [ ] **Step 3: Run tests — PASS, commit**

Note: with the tiny constant seed, `WLS` may warn about collinearity — warnings are fine, failures are not.
```bash
git add -A && git commit -m "feat: fitted team volume regression with market imputation"
```

---

### Task 10: Negative Binomial distribution

**Files:**
- Create: `passmodel/model/distribution.py`, `tests/test_distribution.py`

- [ ] **Step 1: Write failing tests**

`tests/test_distribution.py`:
```python
from passmodel.model import distribution


def test_p_over_monotonic_in_mu():
    lo = distribution.p_over(mu=55, alpha=0.01, line=64.5)
    hi = distribution.p_over(mu=75, alpha=0.01, line=64.5)
    assert 0 < lo < hi < 1


def test_higher_alpha_widens_distribution():
    tight = distribution.p_over(mu=60, alpha=0.001, line=80.5)
    wide = distribution.p_over(mu=60, alpha=0.05, line=80.5)
    assert wide > tight   # fat tail reaches a distant line more often


def test_fit_alpha_positive_floor():
    # actuals equal to mus -> zero residual var -> alpha floored, not negative
    assert distribution.fit_alpha([50, 60], [50, 60]) >= 1e-6


def test_fit_alpha_recovers_overdispersion():
    mus = [60.0] * 200
    acts = [40, 80] * 100          # variance 400 >> mean 60
    alpha = distribution.fit_alpha(mus, acts)
    assert alpha > 0.05
```

Run: `python -m pytest tests/test_distribution.py -q` — Expected: FAIL.

- [ ] **Step 2: Implement `passmodel/model/distribution.py`**

```python
import math
import numpy as np
from scipy.stats import nbinom, poisson


def p_over(mu, alpha, line):
    """P(passes > line) under NB(mean=mu, var=mu+alpha*mu^2). Poisson if alpha ~ 0."""
    if mu <= 0:
        return 0.0
    k = math.floor(line)
    if alpha < 1e-9:
        return float(1 - poisson.cdf(k, mu))
    n = 1.0 / alpha
    p = n / (n + mu)
    return float(1 - nbinom.cdf(k, n, p))


def fit_alpha(mus, actuals):
    """Method of moments on pooled residuals: var = mu + alpha*mu^2."""
    mus = np.asarray(mus, dtype=float)
    acts = np.asarray(actuals, dtype=float)
    if len(mus) == 0:
        return 0.02   # sane default overdispersion
    resid_var = float(np.mean((acts - mus) ** 2))
    mean_mu = float(np.mean(mus))
    if mean_mu <= 0:
        return 1e-6
    return max((resid_var - mean_mu) / (mean_mu ** 2), 1e-6)
```

- [ ] **Step 3: Run tests — PASS, commit**

```bash
git add -A && git commit -m "feat: negative binomial p_over and dispersion fitting"
```

---

### Task 11: Engine — fit mode and project mode

**Files:**
- Create: `passmodel/model/engine.py`, `tests/test_engine.py`

- [ ] **Step 1: Write failing tests**

`tests/test_engine.py`:
```python
import json
from passmodel import db
from passmodel.model import engine
from tests.seed import make_history


def _add_upcoming(conn, date="2026-03-01"):
    sui = db.get_or_create_team(conn, "Switzerland")
    col = db.get_or_create_team(conn, "Colombia")
    return db.get_or_create_match(conn, date, "World Cup", sui, col)


def test_fit_all_returns_team_model_and_alphas(conn):
    make_history(conn)
    fitted = engine.fit_all(conn)
    assert "team_model" in fitted and "alpha_by_pos" in fitted
    assert fitted["alpha_by_pos"]["default"] > 0


def test_project_slate_produces_projection(conn):
    ids = make_history(conn, n_matches=12, team_passes=500, akanji_base=64)
    _add_upcoming(conn)
    conn.execute(
        """INSERT INTO prop_lines(fetched_at, source, player_name, player_id, stat_type, line)
           VALUES('2026-02-28T12:00:00','prizepicks','Manuel Akanji',?, 'Passes Attempted', 64.5)""",
        (ids["akanji"],))
    conn.commit()
    fitted = engine.fit_all(conn)
    projections = engine.project_slate(conn, fitted, today="2026-02-28")
    assert len(projections) == 1
    pr = projections[0]
    assert pr["mu"] > 0 and 0 < pr["p_over"] < 1
    assert pr["confidence"] in ("HIGH", "MEDIUM", "LOW")
    notes = json.loads(pr["notes"])
    assert "team_passes_needed" in notes   # line / share, the Akanji math
    saved = conn.execute("SELECT COUNT(*) c FROM projections").fetchone()["c"]
    assert saved == 1


def test_unmatched_player_line_is_skipped_not_fatal(conn):
    make_history(conn)
    _add_upcoming(conn)
    conn.execute(
        """INSERT INTO prop_lines(fetched_at, source, player_name, player_id, stat_type, line)
           VALUES('2026-02-28T12:00:00','prizepicks','Unknown Guy', NULL, 'Passes Attempted', 50.5)""")
    conn.commit()
    fitted = engine.fit_all(conn)
    assert engine.project_slate(conn, fitted, today="2026-02-28") == []
```

Run: `python -m pytest tests/test_engine.py -q` — Expected: FAIL.

- [ ] **Step 2: Implement `passmodel/model/engine.py`**

```python
import json
import statistics
from passmodel import config
from passmodel.model import features, team_volume, distribution


def fit_all(conn):
    df = team_volume.build_training_frame(conn)
    team_model = team_volume.fit(df)
    # dispersion: predict mu for every historical player-match, pool residuals by position
    mus_by_pos, acts_by_pos = {}, {}
    rows = conn.execute(
        """SELECT p.player_id, p.passes_attempted, p.minutes, p.position, m.date, m.match_id,
                  p.team_id
           FROM player_match_stats p JOIN matches m ON m.match_id=p.match_id
           WHERE p.source='fbref' AND p.minutes >= 45""").fetchall()
    for r in rows:
        games = features.player_share_games(conn, r["player_id"], r["date"])
        if len(games) < 3:
            continue
        prior = features.position_prior_share(conn, r["position"], r["date"])
        share = features.shrunk_share(games, prior)
        base = features.team_baseline(conn, r["team_id"], r["date"])
        if base is None:
            continue
        mu = (r["minutes"] / 90.0) * base * share
        pos = r["position"] or "default"
        mus_by_pos.setdefault(pos, []).append(mu)
        acts_by_pos.setdefault(pos, []).append(r["passes_attempted"])
    alpha_by_pos = {"default": distribution.fit_alpha(
        [m for v in mus_by_pos.values() for m in v],
        [a for v in acts_by_pos.values() for a in v])}
    for pos in mus_by_pos:
        if len(mus_by_pos[pos]) >= 30:
            alpha_by_pos[pos] = distribution.fit_alpha(mus_by_pos[pos], acts_by_pos[pos])
    return {"team_model": team_model, "alpha_by_pos": alpha_by_pos}


def _latest_lines(conn):
    return conn.execute(
        """SELECT * FROM prop_lines WHERE fetched_at =
           (SELECT MAX(fetched_at) FROM prop_lines) AND stat_type='Passes Attempted'"""
    ).fetchall()


def _next_match(conn, team_id, today):
    return conn.execute(
        """SELECT * FROM matches WHERE date >= ? AND (home_team_id=? OR away_team_id=?)
           ORDER BY date LIMIT 1""", (today, team_id, team_id)).fetchone()


def _confidence(n_games, minutes_list, disagree):
    if disagree:
        return "LOW"
    if n_games >= 8 and minutes_list and statistics.pstdev(minutes_list) <= 10:
        return "HIGH"
    if n_games >= 5:
        return "MEDIUM"
    return "LOW"


def project_slate(conn, fitted, today, save=True, created_at=None):
    out = []
    for ln in _latest_lines(conn):
        if ln["player_id"] is None:
            continue   # unmatched name; visible via prop_lines table, not projectable
        player = conn.execute("SELECT * FROM players WHERE player_id=?",
                              (ln["player_id"],)).fetchone()
        match = _next_match(conn, player["team_id"], today)
        if match is None:
            continue
        opp_id = (match["away_team_id"] if match["home_team_id"] == player["team_id"]
                  else match["home_team_id"])
        sign = 1 if match["home_team_id"] == player["team_id"] else -1
        base = features.team_baseline(conn, player["team_id"], today)
        opp = features.opp_allowed_baseline(conn, opp_id, today)
        if base is None or opp is None:
            continue
        odds = conn.execute(
            """SELECT home_spread, total FROM market_odds WHERE match_id=?
               ORDER BY fetched_at DESC LIMIT 1""", (match["match_id"],)).fetchone()
        spread = sign * odds["home_spread"] if odds and odds["home_spread"] is not None else None
        total = odds["total"] if odds else None
        team_pred = team_volume.predict(fitted["team_model"], base, opp, spread, total)
        games = features.player_share_games(conn, player["player_id"], today)
        prior = features.position_prior_share(conn, player["position"], today)
        share = features.shrunk_share(games, prior)
        exp_min = features.expected_minutes(conn, player["player_id"], today)
        mu = (exp_min / 90.0) * team_pred * share
        alpha = fitted["alpha_by_pos"].get(player["position"],
                                           fitted["alpha_by_pos"]["default"])
        if match["is_knockout"]:
            alpha *= 1.5   # extra-time possibility widens the distribution
        p = distribution.p_over(mu, alpha, ln["line"])
        edge = p - config.BREAKEVEN_PROB
        notes = {
            "baseline_games": [{"date": g["date"], "passes": g["passes"],
                                "team_passes": g["team_passes"], "share": round(g["share"], 4)}
                               for g in games],
            "team_baseline": round(base, 1), "opp_allowed": round(opp, 1),
            "spread": spread, "total": total,
            "team_pred": round(team_pred, 1), "share": round(share, 4),
            "exp_minutes": round(exp_min, 1),
            "team_passes_needed": round(ln["line"] / share, 0) if share > 0 else None,
        }
        row = {"player_id": player["player_id"], "player_name": player["name"],
               "match_id": match["match_id"], "line": ln["line"],
               "exp_minutes": exp_min, "team_p90": team_pred, "share": share,
               "mu": mu, "alpha": alpha, "p_over": p, "edge": edge,
               "confidence": _confidence(len(games), [g["minutes"] for g in games], False),
               "notes": json.dumps(notes)}
        out.append(row)
        if save:
            conn.execute(
                """INSERT INTO projections(created_at, player_id, match_id, line, exp_minutes,
                   team_p90, share, mu, alpha, p_over, edge, confidence, notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (created_at or today, row["player_id"], row["match_id"], row["line"],
                 row["exp_minutes"], row["team_p90"], row["share"], row["mu"], row["alpha"],
                 row["p_over"], row["edge"], row["confidence"], row["notes"]))
    if save:
        conn.commit()
    return out
```

- [ ] **Step 3: Run tests — PASS, commit**

```bash
git add -A && git commit -m "feat: model engine fit and project modes"
```

---

### Task 12: Backtest (calibration with pseudo-lines)

**Files:**
- Create: `passmodel/backtest.py`, `tests/test_backtest.py`

- [ ] **Step 1: Write failing test**

`tests/test_backtest.py`:
```python
from passmodel import backtest
from passmodel.model import engine
from tests.seed import make_history


def test_calibration_buckets_sum_to_total(conn):
    make_history(conn, n_matches=12)
    fitted = engine.fit_all(conn)
    report = backtest.calibration(conn, fitted, start_date="2026-01-06")
    assert report["n"] > 0
    assert sum(b["count"] for b in report["buckets"]) == report["n"]
    for b in report["buckets"]:
        assert 0.0 <= b["predicted"] <= 1.0
        assert b["count"] == 0 or 0.0 <= b["observed"] <= 1.0
```

Run: `python -m pytest tests/test_backtest.py -q` — Expected: FAIL.

- [ ] **Step 2: Implement `passmodel/backtest.py`**

```python
"""Calibration via pseudo-lines: for each historical player-match, the 'line' is the
player's trailing median passes. Validates P(over) honesty. Real line P&L accrues once
prop_lines fills daily."""
import statistics
from passmodel.model import features, team_volume, distribution


def calibration(conn, fitted, start_date, min_prior_games=4):
    events = []   # (p_over_predicted, went_over_actual)
    rows = conn.execute(
        """SELECT p.player_id, p.team_id, p.position, p.passes_attempted, p.minutes,
                  m.date, m.match_id, m.home_team_id, m.away_team_id
           FROM player_match_stats p JOIN matches m ON m.match_id=p.match_id
           WHERE p.source='fbref' AND m.date >= ? AND p.minutes >= 45
           ORDER BY m.date""", (start_date,)).fetchall()
    for r in rows:
        games = features.player_share_games(conn, r["player_id"], r["date"])
        if len(games) < min_prior_games:
            continue
        pseudo_line = statistics.median(g["passes"] for g in games) + 0.5
        base = features.team_baseline(conn, r["team_id"], r["date"])
        opp_team = (r["away_team_id"] if r["home_team_id"] == r["team_id"]
                    else r["home_team_id"])
        opp = features.opp_allowed_baseline(conn, opp_team, r["date"])
        if base is None or opp is None:
            continue
        team_pred = team_volume.predict(fitted["team_model"], base, opp)
        prior = features.position_prior_share(conn, r["position"], r["date"])
        share = features.shrunk_share(games, prior)
        exp_min = features.expected_minutes(conn, r["player_id"], r["date"])
        mu = (exp_min / 90.0) * team_pred * share
        alpha = fitted["alpha_by_pos"].get(r["position"], fitted["alpha_by_pos"]["default"])
        p = distribution.p_over(mu, alpha, pseudo_line)
        events.append((p, 1 if r["passes_attempted"] > pseudo_line else 0))
    buckets = []
    edges = [i / 10 for i in range(11)]
    for lo, hi in zip(edges[:-1], edges[1:]):
        inb = [(p, o) for p, o in events if lo <= p < hi]
        buckets.append({
            "range": f"{lo:.1f}-{hi:.1f}",
            "predicted": (sum(p for p, _ in inb) / len(inb)) if inb else (lo + hi) / 2,
            "observed": (sum(o for _, o in inb) / len(inb)) if inb else None,
            "count": len(inb)})
    return {"n": len(events), "buckets": buckets}
```

- [ ] **Step 3: Run tests — PASS, commit**

```bash
git add -A && git commit -m "feat: pseudo-line calibration backtest"
```

---

### Task 13: FastAPI endpoints

**Files:**
- Create: `webapp/__init__.py`, `webapp/main.py`, `tests/test_api.py`

- [ ] **Step 1: Write failing tests**

`tests/test_api.py`:
```python
import json
from fastapi.testclient import TestClient
from passmodel import db
from passmodel.model import engine
from tests.seed import make_history
from webapp.main import create_app


def _prepped(conn):
    ids = make_history(conn)
    sui = db.get_or_create_team(conn, "Switzerland")
    col = db.get_or_create_team(conn, "Colombia")
    db.get_or_create_match(conn, "2026-03-01", "World Cup", sui, col)
    conn.execute(
        """INSERT INTO prop_lines(fetched_at, source, player_name, player_id, stat_type, line)
           VALUES('2026-02-28T12:00:00','prizepicks','Manuel Akanji',?,'Passes Attempted',64.5)""",
        (ids["akanji"],))
    conn.commit()
    fitted = engine.fit_all(conn)
    engine.project_slate(conn, fitted, today="2026-02-28")
    return conn


def test_board_and_detail_endpoints(conn):
    client = TestClient(create_app(lambda: _prepped(conn)))
    board = client.get("/api/board").json()
    assert len(board["props"]) == 1
    pid = board["props"][0]["projection_id"]
    detail = client.get(f"/api/prop/{pid}").json()
    assert detail["player_name"] == "Manuel Akanji"
    assert "baseline_games" in detail["notes"]


def test_board_reports_freshness(conn):
    client = TestClient(create_app(lambda: _prepped(conn)))
    board = client.get("/api/board").json()
    assert board["data_as_of"]   # scrape/projection freshness surfaced to UI
```

Run: `python -m pytest tests/test_api.py -q` — Expected: FAIL.

- [ ] **Step 2: Implement `webapp/main.py`** (and empty `webapp/__init__.py`)

```python
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from passmodel import db

STATIC = Path(__file__).parent / "static"


def create_app(conn_factory=db.get_conn):
    app = FastAPI(title="passmodel")
    # one connection per app instance; sqlite is fine for a single local user
    conn = conn_factory()

    @app.get("/api/board")
    def board():
        rows = conn.execute(
            """SELECT pr.projection_id, pr.line, pr.mu, pr.p_over, pr.edge, pr.confidence,
                      pr.created_at, p.name player_name, p.position,
                      h.name home, a.name away, m.date match_date
               FROM projections pr
               JOIN players p ON p.player_id = pr.player_id
               JOIN matches m ON m.match_id = pr.match_id
               JOIN teams h ON h.team_id = m.home_team_id
               JOIN teams a ON a.team_id = m.away_team_id
               WHERE pr.created_at = (SELECT MAX(created_at) FROM projections)
               ORDER BY pr.edge DESC""").fetchall()
        latest = conn.execute("SELECT MAX(created_at) t FROM projections").fetchone()
        return {"data_as_of": latest["t"] if latest else None,
                "props": [dict(r) for r in rows]}

    @app.get("/api/prop/{projection_id}")
    def prop(projection_id: int):
        row = conn.execute(
            """SELECT pr.*, p.name player_name, p.position
               FROM projections pr JOIN players p ON p.player_id=pr.player_id
               WHERE pr.projection_id=?""", (projection_id,)).fetchone()
        if row is None:
            raise HTTPException(404)
        d = dict(row)
        d["notes"] = json.loads(d["notes"] or "{}")
        return d

    @app.get("/api/backtest")
    def backtest_report():
        from passmodel import backtest as bt
        from passmodel.model import engine
        fitted = engine.fit_all(conn)
        first = conn.execute("SELECT MIN(date) d FROM matches").fetchone()
        if not first or first["d"] is None:
            return {"n": 0, "buckets": []}
        return bt.calibration(conn, fitted, start_date=first["d"])

    if STATIC.exists():
        app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


app = create_app()
```

- [ ] **Step 3: Run tests — PASS, commit**

```bash
git add -A && git commit -m "feat: fastapi board, detail, backtest endpoints"
```

---

### Task 14: Dashboard frontend

No unit tests (vanilla static page); verified via smoke test + manual browser check in Task 15. **Security rule:** every string that originated outside this codebase (player names, team names — scraped data) goes through `esc()` before HTML interpolation. Numbers are formatted with `toFixed`/arithmetic, which coerces or yields `NaN`, so they are safe.

**Files:**
- Create: `webapp/static/index.html`, `tests/test_static.py`

- [ ] **Step 1: Write failing smoke test**

`tests/test_static.py`:
```python
from pathlib import Path


def test_index_exists_and_wires_endpoints():
    html = (Path("webapp/static/index.html")).read_text(encoding="utf-8")
    for needle in ["/api/board", "/api/prop/", "/api/backtest", "function esc("]:
        assert needle in html
```

Run: `python -m pytest tests/test_static.py -q` — Expected: FAIL.

- [ ] **Step 2: Create `webapp/static/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Passes Attempted — Value Board</title>
<style>
  :root { --bg:#0f1115; --card:#181b22; --text:#e8eaf0; --dim:#8a90a0;
          --green:#3fb26f; --amber:#d9a441; --red:#d05555; }
  body { margin:0; font:14px/1.45 system-ui, sans-serif; background:var(--bg); color:var(--text); }
  header { padding:14px 20px; border-bottom:1px solid #262a33; display:flex; gap:16px;
           align-items:baseline; }
  h1 { font-size:16px; margin:0; }
  #asof { color:var(--dim); font-size:12px; }
  nav a { color:var(--dim); margin-right:12px; cursor:pointer; }
  nav a.active { color:var(--text); }
  main { padding:16px 20px; }
  table { border-collapse:collapse; width:100%; }
  th, td { text-align:left; padding:7px 10px; border-bottom:1px solid #232732; }
  th { color:var(--dim); cursor:pointer; user-select:none; }
  tr.row:hover { background:#1d212b; cursor:pointer; }
  .tag { padding:1px 8px; border-radius:9px; font-size:11px; }
  .HIGH { background:#1d3a2a; color:var(--green); }
  .MEDIUM { background:#3a331d; color:var(--amber); }
  .LOW { background:#3a1d1d; color:var(--red); }
  .pos { color:var(--green); } .neg { color:var(--red); }
  #detail { background:var(--card); border:1px solid #262a33; border-radius:8px;
            padding:16px; margin-top:16px; display:none; }
  .factors { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
             gap:10px; margin:12px 0; }
  .factor { background:#12141a; border-radius:6px; padding:10px; }
  .factor b { display:block; font-size:18px; }
  .factor span { color:var(--dim); font-size:11px; }
  svg text { fill:var(--dim); font-size:10px; }
</style>
</head>
<body>
<header>
  <h1>Passes Attempted — Value Board</h1>
  <nav><a id="tab-board" class="active">Board</a><a id="tab-backtest">Backtest</a></nav>
  <span id="asof"></span>
</header>
<main>
  <div id="board-view">
    <table id="board">
      <thead><tr>
        <th data-k="player_name">Player</th><th data-k="match_date">Match</th>
        <th data-k="line">Line</th><th data-k="mu">Proj</th>
        <th data-k="p_over">P(over)</th><th data-k="edge">Edge</th>
        <th data-k="confidence">Conf</th>
      </tr></thead>
      <tbody></tbody>
    </table>
    <div id="detail"></div>
  </div>
  <div id="backtest-view" style="display:none"></div>
</main>
<script>
let props = [], sortKey = "edge", sortDir = -1;

// All scraped strings (names, dates) pass through esc() before interpolation.
function esc(s){
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function fmtPct(x){ return (100*x).toFixed(1) + "%"; }
const CONF = ["HIGH","MEDIUM","LOW"];   // whitelist for class names

async function loadBoard(){
  const res = await fetch("/api/board"); const data = await res.json();
  props = data.props;
  document.getElementById("asof").textContent =
    data.data_as_of ? "projections as of " + data.data_as_of : "no projections yet — run update + project";
  render();
}

function render(){
  props.sort((a,b)=> (a[sortKey] > b[sortKey] ? 1 : -1) * sortDir);
  const tb = document.querySelector("#board tbody");
  tb.innerHTML = props.map(p => {
    const conf = CONF.includes(p.confidence) ? p.confidence : "LOW";
    return `
    <tr class="row" data-id="${Number(p.projection_id)}">
      <td>${esc(p.player_name)} <span style="color:var(--dim)">${esc(p.position)}</span></td>
      <td>${esc(p.home)} v ${esc(p.away)} <span style="color:var(--dim)">${esc(p.match_date)}</span></td>
      <td>${Number(p.line)}</td><td>${p.mu.toFixed(1)}</td><td>${fmtPct(p.p_over)}</td>
      <td class="${p.edge>=0?"pos":"neg"}">${(100*p.edge).toFixed(1)}</td>
      <td><span class="tag ${conf}">${conf}</span></td>
    </tr>`;
  }).join("");
  tb.querySelectorAll("tr.row").forEach(tr =>
    tr.addEventListener("click", () => showDetail(tr.dataset.id)));
}

document.querySelectorAll("th").forEach(th => th.addEventListener("click", () => {
  const k = th.dataset.k;
  sortDir = (sortKey === k) ? -sortDir : -1; sortKey = k; render();
}));

async function showDetail(id){
  const d = await (await fetch("/api/prop/" + Number(id))).json();
  const n = d.notes;
  const games = n.baseline_games || [];
  const maxP = Math.max(d.line, ...games.map(g=>Number(g.passes)||0), 1);
  const bars = games.slice().reverse().map((g,i) => {
    const passes = Number(g.passes) || 0;
    const h = 90 * passes / maxP;
    const over = passes > d.line;
    return `<rect x="${i*34+4}" y="${100-h}" width="26" height="${h}"
            fill="${over ? "var(--green)" : "#3a4152"}"></rect>
            <text x="${i*34+8}" y="${96-h}">${passes}</text>`;
  }).join("");
  const lineY = 100 - 90 * d.line / maxP;
  const num = v => (v === null || v === undefined) ? "—" : Number(v);
  document.getElementById("detail").style.display = "block";
  document.getElementById("detail").innerHTML = `
    <h2 style="margin:0 0 4px">${esc(d.player_name)} — O/U ${Number(d.line)}</h2>
    <div class="factors">
      <div class="factor"><b>${d.mu.toFixed(1)}</b><span>projected passes</span></div>
      <div class="factor"><b>${fmtPct(d.p_over)}</b><span>P(over)</span></div>
      <div class="factor"><b>${(100*d.edge).toFixed(1)}</b><span>edge vs breakeven</span></div>
      <div class="factor"><b>${num(n.exp_minutes)}</b><span>expected minutes</span></div>
      <div class="factor"><b>${(100*n.share).toFixed(1)}%</b><span>team-pass share</span></div>
      <div class="factor"><b>${num(n.team_pred)}</b><span>projected team passes</span></div>
      <div class="factor"><b>${num(n.team_passes_needed)}</b><span>team passes needed to clear</span></div>
      <div class="factor"><b>${num(n.opp_allowed)}</b><span>opp passes allowed (baseline)</span></div>
      <div class="factor"><b>${num(n.spread)}</b><span>market spread (team persp.)</span></div>
      <div class="factor"><b>${num(n.total)}</b><span>market total</span></div>
    </div>
    <svg viewBox="0 0 ${Math.max(games.length*34+8, 200)} 110" style="width:100%;max-width:700px">
      ${bars}
      <line x1="0" x2="100%" y1="${lineY}" y2="${lineY}"
            stroke="var(--amber)" stroke-dasharray="4 3"></line>
    </svg>
    <p style="color:var(--dim);font-size:12px">Bars: passes attempted, oldest → newest.
    Dashed line: current prop line. Green bars cleared it.</p>`;
}

async function loadBacktest(){
  const r = await (await fetch("/api/backtest")).json();
  const rows = r.buckets.map(b => `
    <tr><td>${esc(b.range)}</td><td>${(100*b.predicted).toFixed(0)}%</td>
    <td>${b.observed === null ? "—" : (100*b.observed).toFixed(0)+"%"}</td>
    <td>${Number(b.count)}</td></tr>`).join("");
  document.getElementById("backtest-view").innerHTML = `
    <p style="color:var(--dim)">Calibration on pseudo-lines (trailing player median).
    An honest model shows Observed ≈ Predicted per bucket. n=${Number(r.n)}</p>
    <table><thead><tr><th>P(over) bucket</th><th>Predicted</th><th>Observed</th>
    <th>Count</th></tr></thead><tbody>${rows}</tbody></table>`;
}

document.getElementById("tab-board").onclick = () => {
  document.getElementById("board-view").style.display = "";
  document.getElementById("backtest-view").style.display = "none";
  document.getElementById("tab-board").classList.add("active");
  document.getElementById("tab-backtest").classList.remove("active");
};
document.getElementById("tab-backtest").onclick = () => {
  document.getElementById("board-view").style.display = "none";
  document.getElementById("backtest-view").style.display = "";
  document.getElementById("tab-backtest").classList.add("active");
  document.getElementById("tab-board").classList.remove("active");
  loadBacktest();
};

loadBoard();
</script>
</body>
</html>
```

- [ ] **Step 3: Run tests — PASS, commit**

Run: `python -m pytest -q` — Expected: all pass.
```bash
git add -A && git commit -m "feat: value board dashboard with detail and backtest views"
```

---

### Task 15: CLI scripts, bat launchers, README

**Files:**
- Create: `scripts/update.py`, `scripts/fit.py`, `scripts/project.py`, `update.bat`, `dashboard.bat`, `README.md`

- [ ] **Step 1: Create `scripts/update.py`**

```python
"""Fetch everything new. Each source is isolated: one failing never kills the rest."""
import sys
import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from passmodel import db, config
from passmodel.scrapers import fbref, prizepicks, oddsapi

# Competition schedule pages to keep synced. Add lines here to expand coverage.
COMPETITIONS = [
    # (FBref "Scores & Fixtures" URL, competition label, is_friendly)
    ("https://fbref.com/en/comps/1/schedule/World-Cup-Scores-and-Fixtures",
     "World Cup", 0),
    # add qualifiers / Nations League / Euros / Copa America pages for fit data
]


def main():
    conn = db.get_conn()
    db.init_db(conn)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for url, label, friendly in COMPETITIONS:
        try:
            n = fbref.update_competition(conn, url, label, is_friendly=friendly)
            db.log_scrape(conn, now, f"fbref:{label}", True, f"{n} matches ingested")
            print(f"[ok] fbref {label}: {n} new matches")
        except Exception as e:
            db.log_scrape(conn, now, f"fbref:{label}", False, str(e))
            print(f"[FAIL] fbref {label}: {e}")
    try:
        prizepicks.ingest_lines(conn, prizepicks.fetch_projections(), fetched_at=now)
        db.log_scrape(conn, now, "prizepicks", True)
        print("[ok] prizepicks lines")
    except Exception as e:
        db.log_scrape(conn, now, "prizepicks", False, str(e))
        print(f"[FAIL] prizepicks: {e}")
    try:
        oddsapi.ingest_odds(conn, oddsapi.fetch_odds(), fetched_at=now)
        db.log_scrape(conn, now, "oddsapi", True)
        print("[ok] market odds")
    except Exception as e:
        db.log_scrape(conn, now, "oddsapi", False, str(e))
        print(f"[FAIL] oddsapi: {e}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Create `scripts/fit.py` and `scripts/project.py`**

`scripts/fit.py`:
```python
import sys
import json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from passmodel import db, config
from passmodel.model import engine


def main():
    conn = db.get_conn()
    fitted = engine.fit_all(conn)
    config.PARAMS_PATH.write_text(json.dumps(fitted, indent=2))
    print(f"fitted on n={fitted['team_model']['n']} team-matches -> {config.PARAMS_PATH}")


if __name__ == "__main__":
    main()
```

`scripts/project.py`:
```python
import sys
import json
import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from passmodel import db, config
from passmodel.model import engine


def main():
    conn = db.get_conn()
    if not config.PARAMS_PATH.exists():
        print("No fitted params. Run scripts/fit.py first.")
        return
    fitted = json.loads(config.PARAMS_PATH.read_text())
    today = datetime.date.today().isoformat()
    rows = engine.project_slate(conn, fitted, today=today,
                                created_at=datetime.datetime.now().isoformat(timespec="seconds"))
    rows.sort(key=lambda r: r["edge"], reverse=True)
    for r in rows:
        print(f'{r["player_name"]:<28} line {r["line"]:>5}  mu {r["mu"]:>5.1f}  '
              f'P(over) {r["p_over"]:.3f}  edge {r["edge"]:+.3f}  {r["confidence"]}')
    print(f"\n{len(rows)} props projected. Open the dashboard to explore.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Create bat launchers**

`update.bat`:
```bat
@echo off
call .venv\Scripts\activate
python scripts\update.py
python scripts\fit.py
python scripts\project.py
pause
```

`dashboard.bat`:
```bat
@echo off
call .venv\Scripts\activate
start http://127.0.0.1:8710
python -m uvicorn webapp.main:app --port 8710
```

- [ ] **Step 4: Write `README.md`**

```markdown
# Passes-Attempted Prop Model

Finds edges in soccer passes-attempted props: projects each player's passes as a
distribution, computes P(over the line), ranks by edge vs breakeven.

## Daily use
1. Double-click `update.bat` — scrapes new matches, prop lines, odds; refits; projects.
2. Double-click `dashboard.bat` — opens the value board at http://127.0.0.1:8710.
3. Click any row for the full factor breakdown.

## Setup (once)
    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt
    set ODDS_API_KEY=your_key_here   (optional but recommended — free tier at the-odds-api.com)

## Adding fit data
Edit `COMPETITIONS` in `scripts/update.py` — add FBref "Scores & Fixtures" URLs for
qualifiers, Nations League, Euros, Copa America. More history = better coefficients.

## Honest-model checklist
- Backtest tab: Observed should track Predicted per bucket. If not, don't bet it.
- LOW confidence tags mean thin data — treat edges there as noise.
- Model breakeven is 0.52 (PrizePicks-ish); change `BREAKEVEN_PROB` in
  `passmodel/config.py` if your book differs.
```

- [ ] **Step 5: Full test run + manual smoke, commit**

Run: `python -m pytest -q` — Expected: all pass.
Manual: `dashboard.bat` → page loads with "no projections yet" banner (empty DB is fine).
```bash
git add -A && git commit -m "feat: cli scripts, launchers, readme"
```

---

## Post-plan notes for the executor

1. **Live-scrape shakedown (expected iteration).** Fixture-tested parsers WILL need selector tweaks against real FBref/FotMob/PrizePicks responses. That's normal. When a live page breaks a parser: save the real response into `tests/fixtures/` (trimmed), adjust the test to the real structure, fix the parser, keep the fixture. Never hand-edit parsed output.
2. **FBref rate limit is real.** Never lower `FBREF_DELAY_SECONDS` below 6. A full competition backfill takes a while — that's fine, run it once overnight.
3. **FotMob may 403** without signed headers; it's a secondary source — log and continue (update.py already isolates it; wire it in only after FBref flow works end-to-end).
4. **Knockout alpha widening (×1.5)** is a stated heuristic, not fitted — revisit post-v1.
5. **Spec §2.4 club-share priors** are deliberately deferred: v1 prior = position-group average (implemented in `position_prior_share`). Club-season ingestion is a v1.1 task once the international pipeline is proven. This is the only spec item not fully covered, and it degrades gracefully (wider LOW-confidence tags on thin-sample players).
