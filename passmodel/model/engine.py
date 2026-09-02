import json
import statistics
from passmodel import config, db
from passmodel.model import features, team_volume, distribution


def fit_all(conn):
    df = team_volume.build_training_frame(conn)
    team_model = team_volume.fit(df)
    mus_by_pos, acts_by_pos = {}, {}
    rows = conn.execute(
        """SELECT p.player_id, p.passes_attempted, p.minutes, p.position, m.date, m.match_id,
                  p.team_id
           FROM player_match_stats p JOIN matches m ON m.match_id=p.match_id
           WHERE p.source='fbref' AND p.minutes >= 45"""
    ).fetchall()
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
    alpha_by_pos = {
        "default": distribution.fit_alpha(
            [m for v in mus_by_pos.values() for m in v],
            [a for v in acts_by_pos.values() for a in v],
        )
    }
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
           ORDER BY date LIMIT 1""",
        (today, team_id, team_id),
    ).fetchone()


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
    # Players whose two sources disagree on passes are not trustworthy inputs
    # regardless of sample size, so they are forced to LOW below.
    disagreeing = db.flagged_player_ids(conn, "source_disagreement")
    for ln in _latest_lines(conn):
        if ln["player_id"] is None:
            continue
        player = conn.execute(
            "SELECT * FROM players WHERE player_id=?", (ln["player_id"],)
        ).fetchone()
        # prop_lines.player_id carries no foreign key, so a line can outlive the
        # player row it points at. One stale line must not kill the whole slate.
        if player is None or player["team_id"] is None:
            continue
        match = _next_match(conn, player["team_id"], today)
        if match is None:
            continue
        opp_id = (
            match["away_team_id"]
            if match["home_team_id"] == player["team_id"]
            else match["home_team_id"]
        )
        sign = 1 if match["home_team_id"] == player["team_id"] else -1
        base = features.team_baseline(conn, player["team_id"], today)
        if base is None:
            continue
        opp = features.opp_allowed_baseline(conn, opp_id, today)
        if opp is None:
            opp = base
        odds = conn.execute(
            """SELECT home_spread, total FROM market_odds WHERE match_id=?
               ORDER BY fetched_at DESC LIMIT 1""",
            (match["match_id"],),
        ).fetchone()
        spread = sign * odds["home_spread"] if odds and odds["home_spread"] is not None else None
        total = odds["total"] if odds else None
        team_pred = team_volume.predict(fitted["team_model"], base, opp, spread, total)
        games = features.player_share_games(conn, player["player_id"], today)
        prior = features.position_prior_share(conn, player["position"], today)
        share = features.shrunk_share(games, prior)
        exp_min = features.expected_minutes(conn, player["player_id"], today)
        mu = (exp_min / 90.0) * team_pred * share
        alpha = fitted["alpha_by_pos"].get(
            player["position"], fitted["alpha_by_pos"]["default"]
        )
        if match["is_knockout"]:
            alpha *= 1.5
        p = distribution.p_over(mu, alpha, ln["line"])
        edge = p - config.BREAKEVEN_PROB
        notes = {
            "baseline_games": [
                {
                    "date": g["date"],
                    "passes": g["passes"],
                    "team_passes": g["team_passes"],
                    "share": round(g["share"], 4),
                }
                for g in games
            ],
            "team_baseline": round(base, 1),
            "opp_allowed": round(opp, 1),
            "spread": spread,
            "total": total,
            "team_pred": round(team_pred, 1),
            "share": round(share, 4),
            "exp_minutes": round(exp_min, 1),
            "team_passes_needed": round(ln["line"] / share, 0) if share > 0 else None,
        }
        row = {
            "player_id": player["player_id"],
            "player_name": player["name"],
            "match_id": match["match_id"],
            "line": ln["line"],
            "exp_minutes": exp_min,
            "team_p90": team_pred,
            "share": share,
            "mu": mu,
            "alpha": alpha,
            "p_over": p,
            "edge": edge,
            "confidence": _confidence(
                len(games),
                [g["minutes"] for g in games],
                player["player_id"] in disagreeing,
            ),
            "notes": json.dumps(notes),
        }
        out.append(row)
        if save:
            conn.execute(
                """INSERT INTO projections(created_at, player_id, match_id, line, exp_minutes,
                   team_p90, share, mu, alpha, p_over, edge, confidence, notes)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    created_at or today,
                    row["player_id"],
                    row["match_id"],
                    row["line"],
                    row["exp_minutes"],
                    row["team_p90"],
                    row["share"],
                    row["mu"],
                    row["alpha"],
                    row["p_over"],
                    row["edge"],
                    row["confidence"],
                    row["notes"],
                ),
            )
    if save:
        conn.commit()
    return out
