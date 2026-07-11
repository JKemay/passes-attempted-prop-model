from passmodel.model import features
from tests.seed import make_history


def test_team_baseline_weighted(conn):
    make_history(conn, n_matches=12, team_passes=500)
    base = features.team_baseline(conn, team_id=1, before_date="2026-02-01")
    assert abs(base - 500) < 1e-6


def test_opp_allowed_baseline(conn):
    make_history(conn)
    allowed = features.opp_allowed_baseline(conn, team_id=1, before_date="2026-02-01")
    assert abs(allowed - 350) < 1e-6


def test_player_share_and_shrinkage(conn):
    ids = make_history(conn, n_matches=12, team_passes=500, akanji_base=60)
    games = features.player_share_games(conn, ids["akanji"], before_date="2026-02-01")
    assert len(games) == 12
    raw = sum(g["share"] for g in games) / len(games)
    shrunk = features.shrunk_share(games, prior=0.08)
    assert abs(shrunk - raw) < abs(0.08 - raw)


def test_expected_minutes(conn):
    ids = make_history(conn)
    em = features.expected_minutes(conn, ids["akanji"], before_date="2026-02-01")
    assert em == 90


def test_position_prior_share(conn):
    make_history(conn)
    prior_cb = features.position_prior_share(conn, "CB", before_date="2026-02-01")
    prior_mf = features.position_prior_share(conn, "MF", before_date="2026-02-01")
    assert prior_mf > prior_cb
