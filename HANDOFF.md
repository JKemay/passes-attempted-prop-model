# Handoff — Passes-Attempted Prop Model

**For:** the Codex executor agent
**Role:** you are the implementer. Fable/Opus is the orchestrator; it planned this and will review your output. Do not redesign — build what the plan says. Flag disagreements, don't silently deviate.

---

## What we're building (one paragraph)

A local tool that finds the best **value discrepancies in soccer "passes attempted" player props** (starting with the 2026 World Cup). It scrapes match data + posted prop lines, projects each player's passes attempted as a **probability distribution**, converts that to **P(over the line)**, and ranks every prop on a slate by **edge vs. the line**. A local web dashboard shows a sortable value board and a click-in breakdown for each prop. This replaces a manual handicapping process (baseline → team volume → player share → role → opponent press/block → game script) by encoding that same logic as a **fitted statistical model**.

## Why it's built this way (the core insight)

Hit rates lie. A player who is 10/13 on a line tells you nothing about the *next* matchup. The real projection is structural:

```
projected_passes = (expected_minutes / 90) × projected_team_passes × player_pass_share
```

- **Team passes** depends on possession baseline, the opponent's suppression profile, and expected game script (a team that goes up early sits back and passes less). We anchor game script with the betting market's spread/total.
- **Player share** is that player's slice of team passes, shrunk toward a positional prior so thin samples don't fool us.
- We then wrap a **Negative Binomial distribution** around the mean to get P(over), because that's what edge actually requires — not a point estimate.

The adjustment weights (how much game script / opponent block actually move volume) are **fitted from historical international data**, not hand-tuned. That's the "hybrid" in the design.

## The honest-broker requirement

Before this model is trusted live, it must pass a **calibration backtest**: when it says 60% over, it should hit ~60%. This is non-negotiable and is a first-class feature (backtest tab), not an afterthought. If calibration is off, the model is wrong, not the market.

---

## Read these next (in order)

1. **`docs/superpowers/specs/2026-07-09-passes-attempted-model-design.md`** — the full design/spec. Model core (§2), World Cup adaptations (§2.4), architecture (§3), backtest gates (§4), data-quality rules (§5), what's out of scope (§6).
2. **`docs/superpowers/plans/2026-07-09-passes-attempted-model.md`** — the **step-by-step implementation plan**. 15 tasks, TDD, each with exact file paths, complete code, tests, and commit commands. **This is your primary work order.** Execute it task by task.

The plan is self-contained and assumes zero repo context — everything you need is in it. Follow it in order; each task ends green (tests pass) and commits.

## Architecture at a glance

```
[1] Scrapers → [2] SQLite DB → [3] Model engine → [4] FastAPI dashboard
```

- **Scrapers** (`passmodel/scrapers/`): FBref (backbone — passes, minutes, team totals), FotMob (cross-check), PrizePicks (lines), The Odds API (spread/total). Each isolated so one breaking never kills the others.
- **DB** (`passmodel/db.py`): single SQLite file, no server.
- **Engine** (`passmodel/model/`): `fit_all()` fits coefficients from history; `project_slate()` projects every posted line → P(over), edge, confidence tag.
- **Dashboard** (`webapp/`): FastAPI + one vanilla-JS page. Value board + detail view + backtest tab.

Tech: Python 3.11+, requests, beautifulsoup4+lxml, pandas, numpy, scipy, statsmodels, FastAPI, pytest.

---

## Non-negotiable constraints (the orchestrator will check these)

1. **TDD, fixture-driven scrapers.** Parsers are pure functions tested against saved HTML/JSON fixtures in `tests/fixtures/`. **Never test against the live web.** When a live page breaks a parser, save the real (trimmed) response as a new fixture, update the test to match reality, then fix the parser. Never hand-edit parsed output to make a test pass.
2. **FBref rate limit is real — never set `FBREF_DELAY_SECONDS` below 6.** Scraping too fast gets banned. A full backfill is slow by design; run it once.
3. **Data quality is visible, never silent.** Scraper failure → dashboard shows "data stale as of X." Source disagreement (FBref vs FotMob) → both stored, flagged. Thin sample → wider distribution + LOW confidence tag. The model must never present a shaky edge as a smash.
4. **No automated betting. Ever.** Out of scope, permanently.
5. **One SQLite connection per app instance; every DB test uses the `conn` tmp fixture**, never the real `data/passmodel.db`.
6. **Don't touch project code during environment/tool setup.** (Relevant to the Codex-setup step that precedes this.)

## Known iteration points (expected, not failures)

- **Live-scrape shakedown:** fixture-tested parsers *will* need selector tweaks against real FBref/FotMob/PrizePicks responses. Normal. Handle per constraint #1.
- **FotMob may 403** without signed headers — it's a *secondary* source. Log and continue; wire it in only after the FBref flow works end to end.
- **Club-season share priors (spec §2.4)** are deliberately deferred to v1.1. v1 uses a position-group average prior (`position_prior_share`). This degrades gracefully (thin-sample players just get LOW confidence). It's the only spec item not fully covered in v1 — this is intentional.
- **Backtest uses pseudo-lines** (player's trailing median) because we have no archive of historical PrizePicks lines. This validates the *probability model*. Real beat-the-line P&L accrues automatically once `prop_lines` fills daily. The backtest page states this.

## Definition of done for v1

- All 15 plan tasks complete, `python -m pytest -q` fully green.
- `update.bat` → `dashboard.bat` runs end to end; board loads (empty DB shows a "no projections yet" banner, which is correct).
- Calibration backtest tab renders. (Real-data calibration quality is a *tuning* concern for after the pipeline runs against live data — the mechanism just needs to work.)

## When you finish a task

Run the task's tests, confirm green, commit with the message the plan specifies. Then stop and let the orchestrator (Fable/Opus) review before moving on — it inspects your output rather than accepting it blindly. If a plan step is wrong or a parser can't match real data, say so explicitly with the evidence; don't paper over it.
