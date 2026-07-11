from pathlib import Path


def test_index_exists_and_wires_endpoints():
    html = Path("webapp/static/index.html").read_text(encoding="utf-8")
    for needle in ["/api/board", "/api/prop/", "/api/backtest", "function esc("]:
        assert needle in html
