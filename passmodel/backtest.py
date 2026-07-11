"""Calibration via pseudo-lines.

For each historical player-match, the line is the player's trailing median passes.
This validates P(over) honesty until real prop-line history accumulates.
"""
import statistics
from passmodel.model import features, team_volume, distribution


def calibration(conn, fitted, start_date, min_prior_games=4):
    events = []
    rows = conn.execute(
        """SELECT p.player_id, p.team_id, p.position, p.passes_attempted, p.minutes,
                  m.date, m.match_id, m.home_team_id, m.away_team_id
           FROM player_match_stats p JOIN matches m ON m.match_id=p.match_id
           WHERE p.source='fbref' AND m.date >= ? AND p.minutes >= 45
           ORDER BY m.date""",
        (start_date,),
    ).fetchall()
    for r in rows:
        games = features.player_share_games(conn, r["player_id"], r["date"])
        if len(games) < min_prior_games:
            continue
        pseudo_line = statistics.median(g["passes"] for g in games) + 0.5
        base = features.team_baseline(conn, r["team_id"], r["date"])
        opp_team = (
            r["away_team_id"] if r["home_team_id"] == r["team_id"] else r["home_team_id"]
        )
        opp = features.opp_allowed_baseline(conn, opp_team, r["date"])
        if opp is None:
            opp = base
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
        buckets.append(
            {
                "range": f"{lo:.1f}-{hi:.1f}",
                "predicted": (sum(p for p, _ in inb) / len(inb)) if inb else (lo + hi) / 2,
                "observed": (sum(o for _, o in inb) / len(inb)) if inb else None,
                "count": len(inb),
            }
        )
    return {"n": len(events), "buckets": buckets}
