from passmodel import config


def _recent_team_rows(conn, team_id, before_date, n):
    return conn.execute(
        """SELECT s.passes_attempted, m.is_friendly FROM team_match_stats s
           JOIN matches m ON m.match_id = s.match_id
           WHERE s.team_id=? AND s.source='fbref' AND m.date < ?
           ORDER BY m.date DESC LIMIT ?""",
        (team_id, before_date, n),
    ).fetchall()


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
    """Average passes attempted by this team's opponents: what this team allows."""
    rows = conn.execute(
        """SELECT s.passes_attempted, m.is_friendly FROM team_match_stats s
           JOIN matches m ON m.match_id = s.match_id
           WHERE s.source='fbref' AND m.date < ? AND s.team_id != ?
             AND (m.home_team_id=? OR m.away_team_id=?)
           ORDER BY m.date DESC LIMIT ?""",
        (before_date, team_id, team_id, team_id, n),
    ).fetchall()
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
        (player_id, before_date, n),
    ).fetchall()
    out = []
    for r in rows:
        if not r["t_att"]:
            continue
        share = (r["p_att"] / r["t_att"]) * (90.0 / max(r["minutes"], 1))
        out.append(
            {
                "share": share,
                "minutes": r["minutes"],
                "date": r["date"],
                "passes": r["p_att"],
                "team_passes": r["t_att"],
                "weight": config.FRIENDLY_WEIGHT if r["is_friendly"] else 1.0,
            }
        )
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
        (player_id, before_date, n),
    ).fetchall()
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
        (position, before_date),
    ).fetchall()
    shares = [
        (r["p_att"] / r["t_att"]) * (90.0 / r["minutes"]) for r in rows if r["t_att"]
    ]
    return sum(shares) / len(shares) if shares else 0.08
