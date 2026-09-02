from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "passmodel.db"
PARAMS_PATH = ROOT / "model_params.json"

# --- scraping ---
FBREF_DELAY_SECONDS = 6.0          # FBref rate limit: be polite or get banned
FOTMOB_DELAY_SECONDS = 3.0         # same courtesy for FotMob's undocumented API
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) passmodel/0.1"
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_SPORT_KEY = "soccer_fifa_world_cup"
PRIZEPICKS_LEAGUE_ID = 82          # soccer

# --- model tunables ---
SHRINKAGE_K = 5          # games of "prior weight" when shrinking player share
FRIENDLY_WEIGHT = 0.5    # friendlies count half in fitting/baselines
BASELINE_WINDOW = 10     # matches for team rolling baselines
SHARE_WINDOW = 15        # matches for player share
MINUTES_WINDOW = 5       # matches for expected minutes
BREAKEVEN_PROB = 0.52    # implied prob a pick must beat (PrizePicks-ish)
SOURCE_DISAGREE_PASSES = 5   # flag if FBref vs FotMob differ by more than this
