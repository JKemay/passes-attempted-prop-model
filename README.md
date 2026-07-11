# Passes-Attempted Prop Model

Finds edges in soccer passes-attempted props: projects each player's passes as a
distribution, computes P(over the line), and ranks props by edge vs breakeven.

## Daily Use

1. Double-click `update.bat` to scrape new matches, prop lines, odds, refit, and project.
2. Double-click `dashboard.bat` to open the value board at http://127.0.0.1:8710.
3. Click any row for the full factor breakdown.

## Setup

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
set ODDS_API_KEY=your_key_here
```

`ODDS_API_KEY` is optional, but recommended for game-script inputs. The free tier is
available at The Odds API.

## Adding Fit Data

Edit `COMPETITIONS` in `scripts/update.py` and add FBref "Scores & Fixtures" URLs
for qualifiers, Nations League, Euros, Copa America, and other international data.
More history means better fitted coefficients.

## Honest-Model Checklist

- Backtest tab: Observed should track Predicted per bucket. If not, do not trust the board.
- LOW confidence tags mean thin or unstable data; treat edges there as noise.
- Model breakeven is `0.52`. Change `BREAKEVEN_PROB` in `passmodel/config.py` if your book differs.

## Architecture

```text
FBref + FotMob + PrizePicks + Odds API -> SQLite -> model engine -> FastAPI dashboard
```

The structural projection is:

```text
projected_passes = (expected_minutes / 90) * projected_team_passes * player_pass_share
```

Team volume is fitted from history, player share is shrunk toward a position prior, and
a Negative Binomial distribution converts the mean projection into P(over).

## Project Docs

- `HANDOFF.md`: orientation, constraints, and definition of done.
- `docs/superpowers/specs/2026-07-09-passes-attempted-model-design.md`: full design spec.
- `docs/superpowers/plans/2026-07-09-passes-attempted-model.md`: implementation work order.
