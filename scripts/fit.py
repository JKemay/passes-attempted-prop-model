import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from passmodel import config, db
from passmodel.model import engine


def main():
    conn = db.get_conn()
    db.init_db(conn)
    fitted = engine.fit_all(conn)
    config.PARAMS_PATH.write_text(json.dumps(fitted, indent=2))
    print(f"fitted on n={fitted['team_model']['n']} team-matches -> {config.PARAMS_PATH}")


if __name__ == "__main__":
    main()
