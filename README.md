# Passes-Attempted Prop Model

A local tool that finds the best **value discrepancies in soccer "passes attempted" player props** (starting with the 2026 World Cup). It scrapes match data + posted prop lines, projects each player's passes attempted as a **probability distribution**, converts that to **P(over the line)**, and ranks every prop on a slate by **edge**. A local web dashboard shows a sortable value board and a click-in breakdown per prop.

> **Status:** design + full implementation plan complete. Code not yet built — execution is task-by-task from the plan below.

## The core idea

Hit rates lie. The real projection is structural:

```
projected_passes = (expected_minutes / 90) × projected_team_passes × player_pass_share
```

Team passes depend on possession baseline, opponent suppression, and game script (anchored by the betting market's spread/total). Player share is shrunk toward a positional prior so thin samples don't fool us. A **Negative Binomial** distribution around the mean yields P(over) — because edge needs a distribution, not a point estimate. Adjustment weights are **fitted from historical international data**, not hand-tuned.

Before it's trusted live, it must pass a **calibration backtest**: when it says 60% over, it should hit ~60%.

## Start here

| Doc | Purpose |
|-----|---------|
| [`HANDOFF.md`](HANDOFF.md) | **Entry point for any agent/dev.** Orientation, constraints, known iteration points. |
| [`docs/superpowers/specs/2026-07-09-passes-attempted-model-design.md`](docs/superpowers/specs/2026-07-09-passes-attempted-model-design.md) | Full design spec. |
| [`docs/superpowers/plans/2026-07-09-passes-attempted-model.md`](docs/superpowers/plans/2026-07-09-passes-attempted-model.md) | **The work order** — 15 TDD tasks with exact files, code, tests, commits. |

## Architecture

```
[1] Scrapers → [2] SQLite DB → [3] Model engine → [4] FastAPI dashboard
```

FBref (backbone) + FotMob (cross-check) + PrizePicks (lines) + The Odds API (game script) → SQLite → `fit_all()` / `project_slate()` → value board.

Tech: Python 3.11+, requests, beautifulsoup4, pandas, numpy, scipy, statsmodels, FastAPI, pytest.

## Collaboration model

This repo is worked by two agents: an **orchestrator** (planning, architecture, review) and an **executor** (implementation). Both read `HANDOFF.md` first. Executor works the plan task by task — each task ends with passing tests and a commit. No automated betting is ever in scope.
