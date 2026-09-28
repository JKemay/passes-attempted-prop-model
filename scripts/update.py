"""Fetch new data. Each source is isolated: one failure never kills the rest."""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from passmodel import db
from passmodel.scrapers import fbref, fotmob, oddsapi, prizepicks

COMPETITIONS = [
    (
        "https://fbref.com/en/comps/1/schedule/World-Cup-Scores-and-Fixtures",
        "World Cup",
        0,
    ),
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
        # Cross-checks FBref matches against FotMob; a disagreement is what lets
        # the engine downgrade a player's projection to LOW confidence.
        n_matches, n_flags = fotmob.update_fotmob(conn)
        db.log_scrape(
            conn, now, "fotmob", True, f"{n_matches} matches cross-checked, {n_flags} flags"
        )
        print(f"[ok] fotmob: {n_matches} matches cross-checked, {n_flags} flags")
    except Exception as e:
        db.log_scrape(conn, now, "fotmob", False, str(e))
        print(f"[FAIL] fotmob: {e}")
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
