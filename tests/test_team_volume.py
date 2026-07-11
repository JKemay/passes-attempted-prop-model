from passmodel.model import team_volume
from tests.seed import make_history


def test_fit_and_predict_roundtrip(conn):
    make_history(conn, n_matches=12, team_passes=500)
    df = team_volume.build_training_frame(conn)
    assert len(df) > 0
    fitted = team_volume.fit(df)
    pred = team_volume.predict(fitted, base=500, opp=500, spread=None, total=None)
    assert abs(pred - 500) < 25


def test_predict_uses_imputation_when_market_missing(conn):
    make_history(conn)
    fitted = team_volume.fit(team_volume.build_training_frame(conn))
    a = team_volume.predict(fitted, base=500, opp=350)
    assert a is not None


def test_fit_empty_frame_returns_default_model(conn):
    fitted = team_volume.fit(team_volume.build_training_frame(conn))
    assert fitted["n"] == 0
    assert team_volume.predict(fitted, base=500, opp=350) == 500
