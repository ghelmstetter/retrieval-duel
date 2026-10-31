"""Settings, read from environment variables or a .env file in the project folder."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # python-dotenv is optional
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("RDUEL_DATA_DIR", ROOT / "data"))
DATASETS_DIR = DATA_DIR / "datasets"
CACHE_DIR = DATA_DIR / "cache"
DEMO_DIR = ROOT / "demo"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()

# Cheap, fast model for the bulk work: graph extraction, community summaries, routing, judging.
WORK_MODEL = os.getenv("RDUEL_WORK_MODEL", "claude-haiku-5-5")
# Stronger model that writes the answers you compare.
ANSWER_MODEL = os.getenv("RDUEL_ANSWER_MODEL", "claude-sonnet-5-5")

# Prices in US dollars per million tokens, used only for estimates.
# Check current prices at https://www.anthropic.com/pricing and update if they change.
PRICES = {
    WORK_MODEL: (float(os.getenv("RDUEL_WORK_PRICE_IN", "0.10")), float(os.getenv("RDUEL_WORK_PRICE_OUT", "0.50"))),
    ANSWER_MODEL: (float(os.getenv("RDUEL_ANSWER_PRICE_IN", "2.00")), float(os.getenv("RDUEL_ANSWER_PRICE_OUT", "10.00"))),
}

# Stop an indexing run if it would spend more than this many dollars.
MAX_INDEX_DOLLARS = float(os.getenv("RDUEL_MAX_INDEX_DOLLARS", "2.00"))

# "auto" uses fastembed if installed, otherwise a simple word-matching (TF-IDF) fallback.
EMBED_BACKEND = os.getenv("RDUEL_EMBED_BACKEND", "auto")
EMBED_MODEL = os.getenv("RDUEL_EMBED_MODEL", "BAAI/bge-small-en-v1.5")

# Retrieval settings.
TOP_K = int(os.getenv("RDUEL_TOP_K", "5"))
GRAPH_HOPS = int(os.getenv("RDUEL_GRAPH_HOPS", "2"))
GRAPH_MAX_FACTS = int(os.getenv("RDUEL_GRAPH_MAX_FACTS", "30"))

# For tests: a stand-in for Claude that returns canned JSON, so no key or network is needed.
FAKE_LLM = os.getenv("RDUEL_FAKE_LLM", "") == "1"

PORT = int(os.getenv("RDUEL_PORT", "8000"))


def has_key() -> bool:
    return bool(ANTHROPIC_API_KEY) or FAKE_LLM
