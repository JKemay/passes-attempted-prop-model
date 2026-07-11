import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from passmodel import config, db
from passmodel.model import engine


def main():
    conn = db.get_conn()
    db.init_db(conn)
    if not config.PARAMS_PATH.exists():
        print("No fitted params. Run scripts/fit.py first.")
        return
    fitted = json.loads(config.PARAMS_PATH.read_text())
    today = datetime.date.today().isoformat()
    rows = engine.project_slate(
        conn,
        fitted,
        today=today,
        created_at=datetime.datetime.now().isoformat(timespec="seconds"),
    )
    rows.sort(key=lambda r: r["edge"], reverse=True)
    for r in rows:
        print(
            f'{r["player_name"]:<28} line {r["line"]:>5}  mu {r["mu"]:>5.1f}  '
            f'P(over) {r["p_over"]:.3f}  edge {r["edge"]:+.3f}  {r["confidence"]}'
        )
    print(f"\n{len(rows)} props projected. Open the dashboard to explore.")


if __name__ == "__main__":
    main()
