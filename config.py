"""Application configuration. Every value can be overridden with an environment
variable (see .env.example); a local .env file is loaded if python-dotenv exists."""
import os
from pathlib import Path

try:  # optional convenience
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT_DIR = Path(__file__).resolve().parent

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", ROOT_DIR / "regtech.db"))
SAMPLE_CSV_PATH = ROOT_DIR / "data" / "sample_transactions.csv"

# --- Monitoring rule parameters (illustrative defaults; not tuned on real data) ---
LOOKBACK_STEPS = int(os.getenv("LOOKBACK_STEPS", "24"))  # PaySim: 1 step = 1 hour
HIGH_VALUE_THRESHOLD = float(os.getenv("HIGH_VALUE_THRESHOLD", "200000"))
REPEATED_TRANSACTION_COUNT = int(os.getenv("REPEATED_TRANSACTION_COUNT", "3"))
DRAIN_RATIO = float(os.getenv("DRAIN_RATIO", "0.99"))
DRAIN_MIN_AMOUNT = float(os.getenv("DRAIN_MIN_AMOUNT", "10000"))
PASS_THROUGH_STEPS = int(os.getenv("PASS_THROUGH_STEPS", "6"))

# --- Web app ---
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "0").lower() in {"1", "true", "yes"}
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "5000"))
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000
