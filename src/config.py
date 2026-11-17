"""Central config. Change values here; nowhere else."""
import os
from dotenv import load_dotenv

load_dotenv()

# Production defaults — override per-run via --limit / --max-cost flags if needed
MAX_ROWS_PER_RUN = 100_000
MAX_COST_USD_PER_RUN = 500.0
MAX_CONCURRENT_LLM_CALLS = 10
MAX_PLANNER_RETRIES = 1
MAX_EXTRACTOR_RETRIES = 1
MAX_LOCATION_EXTRACTOR_CALLS_PER_RUN = 100_000

# Concurrency
HTTPX_CONCURRENCY = 25   # Lowered from 75 — chunk 1 IP-blocked at 30 concurrent. Stay under that ceiling.
PLAYWRIGHT_CONCURRENCY = 25  # persistent browser pool makes contexts cheap (~100MB each); match main concurrency to eliminate queue pressure

# Model
MODEL = "claude-sonnet-4-6"

# Timeouts (seconds)
HTTPX_TIMEOUT = 15
PLAYWRIGHT_TIMEOUT = 30

# Paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
LLM_LOG_PATH = os.path.join(DATA_DIR, "llm_log.jsonl")

# Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "site-agent")

# Whether LangSmith tracing is active (requires key + env var)
LANGSMITH_ENABLED = bool(LANGSMITH_API_KEY and os.getenv("LANGSMITH_TRACING", "").lower() == "true")
