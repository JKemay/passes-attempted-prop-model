import json
import pandas as pd
import statsmodels.api as sm
from passmodel import config
from passmodel.model import features


def build_training_frame(conn):
    rows = []
    matches = conn.execute("SELECT * FROM matches ORDER BY date").fetchall()
    for m in matches:
        pairs = ((m["home_team_id"], m["away_team_id"], 1), (m["away_team_id"], m["home_team_id"], -1))
        for team_id, opp_id, sign in pairs:
            stat = conn.execute(
                """SELECT passes_attempted FROM team_match_stats
                   WHERE match_id=? AND team_id=? AND source='fbref'""",
                (m["match_id"], team_id),
            ).fetchone()
            if stat is None:
                continue
            base = features.team_baseline(conn, team_id, m["date"])
            opp = features.opp_allowed_baseline(conn, opp_id, m["date"])
            if opp is None:
                opp = base
            if base is None or opp is None:
                continue
            odds = conn.execute(
                """SELECT home_spread, total FROM market_odds WHERE match_id=?
                   ORDER BY fetched_at DESC LIMIT 1""",
                (m["match_id"],),
            ).fetchone()
            spread = sign * odds["home_spread"] if odds and odds["home_spread"] is not None else None
            total = odds["total"] if odds else None
            rows.append(
                {
                    "y": stat["passes_attempted"],
                    "base": base,
                    "opp": opp,
                    "spread": spread,
                    "total": total,
                    "w": config.FRIENDLY_WEIGHT if m["is_friendly"] else 1.0,
                }
            )
    return pd.DataFrame(rows)


def fit(df):
    impute = {
        "spread": float(df["spread"].dropna().mean()) if df["spread"].notna().any() else 0.0,
        "total": float(df["total"].dropna().mean()) if df["total"].notna().any() else 2.5,
    }
    X = df[["base", "opp", "spread", "total"]].fillna(value=impute).astype(float)
    X = sm.add_constant(X, has_constant="add")
    res = sm.WLS(df["y"].astype(float), X, weights=df["w"].astype(float)).fit()
    return {
        "params": {k: float(v) for k, v in res.params.items()},
        "impute": impute,
        "n": int(len(df)),
    }


def predict(fitted, base, opp, spread=None, total=None):
    p, imp = fitted["params"], fitted["impute"]
    spread = imp["spread"] if spread is None else spread
    total = imp["total"] if total is None else total
    return (
        p.get("const", 0.0)
        + p["base"] * base
        + p["opp"] * opp
        + p["spread"] * spread
        + p["total"] * total
    )


def save(fitted, path=config.PARAMS_PATH):
    path.write_text(json.dumps(fitted, indent=2))


def load(path=config.PARAMS_PATH):
    return json.loads(path.read_text())
