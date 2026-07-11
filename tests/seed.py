"""Seed a small deterministic Switzerland history for model tests."""
from passmodel import db


def make_history(conn, n_matches=12, team_passes=500, akanji_base=60):
    sui = db.get_or_create_team(conn, "Switzerland")
    akanji = db.get_or_create_player(conn, "Manuel Akanji", sui, position="CB")
    xhaka = db.get_or_create_player(conn, "Granit Xhaka", sui, position="MF")
    for i in range(n_matches):
        opp = db.get_or_create_team(conn, f"Opponent {i}")
        date = f"2026-01-{i + 1:02d}"
        m = db.get_or_create_match(
            conn, date, "Qualifiers", sui, opp, is_friendly=1 if i % 4 == 0 else 0
        )
        db.upsert_team_stat(conn, m, sui, "fbref", team_passes)
        db.upsert_team_stat(conn, m, opp, "fbref", 350)
        db.upsert_player_stat(
            conn,
            m,
            akanji,
            sui,
            "fbref",
            minutes=90,
            passes_attempted=akanji_base + i,
            started=1,
            position="CB",
        )
        db.upsert_player_stat(
            conn,
            m,
            xhaka,
            sui,
            "fbref",
            minutes=90,
            passes_attempted=80,
            started=1,
            position="MF",
        )
    return {"sui": sui, "akanji": akanji, "xhaka": xhaka}
