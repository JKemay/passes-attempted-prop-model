from pathlib import Path
from passmodel.scrapers import fbref

FIX = Path(__file__).parent / "fixtures"


def test_parse_match_extracts_teams_and_players():
    html = (FIX / "fbref_match.html").read_text(encoding="utf-8")
    teams = fbref.parse_match(html)
    assert len(teams) == 2
    sui = teams[0]
    assert sui["name"] == "Switzerland"
    akanji = sui["players"][0]
    assert akanji["name"] == "Manuel Akanji"
    assert akanji["fbref_id"] == "aaa111"
    assert akanji["passes_attempted"] == 78
    assert akanji["minutes"] == 90
    assert akanji["position"] == "CB"
    assert akanji["started"] == 1
    assert sui["team_passes"] == 78 + 85
