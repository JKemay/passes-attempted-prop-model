# Passes-Attempted Prop Model — Design Spec

**Date:** 2026-07-09
**Status:** Approved pending user review
**v1 scope:** World Cup 2026 (and international matches feeding it), passes-attempted props only.

## 1. Purpose

Find the best discrepancies (edges) in soccer passes-attempted props by projecting each player's
passes as a probability distribution, converting it to P(over the posted line), and ranking props
by edge versus the line's implied probability. Replaces a manual process (baseline → team volume →
player share → role → opponent press/block → game script → fail paths) with the same logic encoded
as a fitted model, plus a dashboard for slate-wide scanning and per-prop deep dives.

## 2. Model core

### 2.1 Structural decomposition

```
projected_passes = E[minutes]/90 × E[team_passes_per90] × E[player_share]
```

Each factor is modeled independently and shown in the UI:

- **E[team_passes_per90]** — fitted regression: team possession/passing baseline,
  opponent passes-allowed profile (suppression), opponent block/press profile, and
  expected game script anchored by the betting market (match spread and total).
- **E[player_share]** — player's rolling share of team passes, shrunk toward a
  positional/role prior. Block-type interaction (e.g. mid-block boosts CB share,
  low-block mutes it) is a fitted coefficient, not a hand-set adjustment.
- **E[minutes]** — starter probability and expected minutes; rotation/sub risk.

### 2.2 Distribution and edge

- Outcome modeled as **Negative Binomial** (count data, overdispersed): mean = structural
  projection; dispersion fitted from player-level game-to-game variance.
- `P(over) = 1 − CDF(line)`. Edge = model P(over) − implied probability of the posted line.
- Wide distributions (thin samples, rotation risk) automatically shrink confidence — bait
  lines with suppressed projections surface as traps, not values.

### 2.3 Hybrid fitting

Structural form is fixed (interpretable); coefficients (game-script effect, block-type
effects, suppression weights, lead/trail 2H volume decay) are **fitted from historical
match data** rather than eyeballed. Refit is a separate offline step ("fit mode").

### 2.4 World Cup adaptations

- **Fitting corpus:** all internationals from ~2024 onward — WC qualifiers, Nations League,
  Euros, Copa América, AFCON, Gold Cup, friendlies. Coefficients are pooled across teams,
  so sparse per-team samples still yield stable structural weights.
- **Friendlies down-weighted** in fitting (mass substitutions, low intensity).
- **Club-season priors for player share:** international share samples are tiny, so shrink
  toward a club-informed prior weighted by role similarity (position, formation).
- **Tournament-stage features:** group-game-3 rotation risk feeds the minutes model;
  knockout matches widen the distribution (extra-time possibility).
- **Mismatch anchoring:** market spread/total anchors extreme possession-split games.

## 3. Architecture

```
[1] Data pipeline (scrapers) → [2] SQLite DB → [3] Model engine → [4] Dashboard (FastAPI)
```

### 3.1 Data pipeline

- **FBref** — backbone: player match logs (passes attempted, minutes), team totals,
  opponent defensive/pressing stats, historical internationals.
- **FotMob** — secondary source and cross-check; both counts stored, disagreements flagged.
- **Props/odds** — PrizePicks public endpoint for lines; odds API (free trial, e.g.
  The Odds API) for match spread/total feeding game script.
- Each scraper isolated; one command (`update.bat` → Python) fetches all new data and
  logs per-source success/failure.

### 3.2 Database (SQLite, single file)

Tables: `matches`, `player_match_stats` (per-source columns), `team_match_stats`,
`prop_lines`, `market_odds`, `projections`, `players` (club↔NT identity mapping),
`teams`, plus `picks` reserved for future bet tracking.

### 3.3 Model engine

- **Fit mode** (occasional): refits coefficients from all historical data in the DB.
- **Project mode** (per slate): for every player with a posted line, produce projection,
  distribution, P(over), edge, and a confidence tag (sample size, minutes certainty,
  source agreement).

### 3.4 Dashboard (local web, FastAPI + simple frontend)

- **Value board:** all slate props, sortable/filterable by edge; color-coded
  playable / thin / trap; confidence tags visible.
- **Detail view:** per-prop factor breakdown — last-15 baseline chart vs. line, team
  volume required to clear (line ÷ share), share trend, opponent suppression profile,
  block/press read, game-script warning, minutes risk. Every input the model used.
- **Backtest page:** calibration plot and beat-the-line P&L (see §4).

## 4. Backtest & validation

Replay historical slates using only pre-kickoff data. Two gates before live use:

1. **Calibration** — predicted P(over) buckets must match observed frequencies.
2. **Beat-the-line** — flagged edges evaluated against actual lines/closing numbers.

If calibration fails, fix the model before trusting the board.

## 5. Error handling & data quality

- Scraper failure → dashboard banner "data stale as of X"; never silently project on
  old data.
- Source disagreement (FBref vs FotMob) → store both; flag the prop when the gap is
  large enough to change the read.
- Thin samples / role changes → wider distribution + explicit low-confidence tag.
- Player identity mapping (club vs NT names, accents) handled via a persistent
  `players` mapping table with manual-override support.

## 6. Out of scope for v1

- Additional leagues/competitions (architecture supports them later).
- Other prop types (shots, tackles, passes completed) — same pipeline, new columns.
- Auto-refresh/alerting, line-movement tracking, bet tracking UI.
- Any automated bet placement (never in scope).

## 7. Tech summary

Python 3.11+, `requests`/`httpx` + parsing for scrapers, `pandas`, `statsmodels`/`scipy`
(NB fitting), SQLite via `sqlite3`/SQLAlchemy, FastAPI + a lightweight HTML/JS frontend
(no heavy framework), Windows-friendly one-command entry points. Built for a user who
codes some but isn't Python-fluent: clear module boundaries, plain-English config, and
run scripts over notebooks.
