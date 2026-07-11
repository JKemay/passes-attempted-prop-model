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
        (ids["akanji"],),
    )
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
    assert board["data_as_of"]


def test_board_reports_latest_scrape_failures(conn):
    def prep():
        db.log_scrape(conn, "2026-02-28T10:00:00", "fbref:World Cup", True, "ok")
        db.log_scrape(conn, "2026-02-28T10:00:00", "oddsapi", False, "ODDS_API_KEY not set")
        return conn

    client = TestClient(create_app(prep))
    board = client.get("/api/board").json()
    assert board["scrape_as_of"] == "2026-02-28T10:00:00"
    assert board["source_failures"] == [
        {"source": "oddsapi", "detail": "ODDS_API_KEY not set"}
    ]
