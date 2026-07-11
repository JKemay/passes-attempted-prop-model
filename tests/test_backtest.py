from passmodel import backtest
from passmodel.model import engine
from tests.seed import make_history


def test_calibration_buckets_sum_to_total(conn):
    make_history(conn, n_matches=12)
    fitted = engine.fit_all(conn)
    report = backtest.calibration(conn, fitted, start_date="2026-01-06")
    assert report["n"] > 0
    assert sum(b["count"] for b in report["buckets"]) == report["n"]
    for b in report["buckets"]:
        assert 0.0 <= b["predicted"] <= 1.0
        assert b["count"] == 0 or 0.0 <= b["observed"] <= 1.0
