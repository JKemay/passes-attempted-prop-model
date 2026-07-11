import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from passmodel import db

STATIC = Path(__file__).parent / "static"


def create_app(conn_factory=db.get_conn):
    app = FastAPI(title="passmodel")
    conn = conn_factory()
    db.init_db(conn)

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
               ORDER BY pr.edge DESC"""
        ).fetchall()
        latest = conn.execute("SELECT MAX(created_at) t FROM projections").fetchone()
        latest_scrape = conn.execute("SELECT MAX(run_at) t FROM scrape_log").fetchone()
        scrape_as_of = latest_scrape["t"] if latest_scrape else None
        failures = []
        if scrape_as_of:
            failures = [
                {"source": r["source"], "detail": r["detail"]}
                for r in conn.execute(
                    """SELECT source, detail FROM scrape_log
                       WHERE run_at=? AND ok=0
                       ORDER BY source""",
                    (scrape_as_of,),
                ).fetchall()
            ]
        return {
            "data_as_of": latest["t"] if latest else None,
            "scrape_as_of": scrape_as_of,
            "source_failures": failures,
            "props": [dict(r) for r in rows],
        }

    @app.get("/api/prop/{projection_id}")
    def prop(projection_id: int):
        row = conn.execute(
            """SELECT pr.*, p.name player_name, p.position
               FROM projections pr JOIN players p ON p.player_id=pr.player_id
               WHERE pr.projection_id=?""",
            (projection_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(404)
        d = dict(row)
        d["notes"] = json.loads(d["notes"] or "{}")
        return d

    @app.get("/api/backtest")
    def backtest_report():
        from passmodel import backtest as bt
        from passmodel.model import engine

        first = conn.execute("SELECT MIN(date) d FROM matches").fetchone()
        if not first or first["d"] is None:
            return {"n": 0, "buckets": []}
        fitted = engine.fit_all(conn)
        return bt.calibration(conn, fitted, start_date=first["d"])

    if STATIC.exists():
        app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


app = create_app()
