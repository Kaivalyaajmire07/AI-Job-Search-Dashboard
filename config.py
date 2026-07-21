"""Central configuration: environment variables and static option lists.

Pure constants — no network calls, no Streamlit, no session state. Safe
to import from every other module.
"""
import logging
import os

from dotenv import load_dotenv

load_dotenv()

# ---------------- Shared logger ---------------- #
# api.py and cache.py both log through this — defined here so every
# module gets the same handler/format without configuring logging twice.
logger = logging.getLogger("job_dashboard")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

# ---------------- API credentials & key rotation ---------------- #
API_HOST = os.getenv("RAPIDAPI_HOST", "jsearch.p.rapidapi.com")
API_URL = "https://jsearch.p.rapidapi.com/search-v2"

# Reads RAPIDAPI_KEY1 .. RAPIDAPI_KEY5 from .env (any that are unset are
# skipped). Falls back to plain RAPIDAPI_KEY for backward compatibility
# with a single-key .env file.
_ROTATION_KEYS = [os.getenv(f"RAPIDAPI_KEY{i}") for i in range(1, 6)]
API_KEYS = [k for k in _ROTATION_KEYS if k] or ([os.getenv("RAPIDAPI_KEY")] if os.getenv("RAPIDAPI_KEY") else [])

REQUEST_TIMEOUT = 15          # seconds, per HTTP request
CACHE_TTL_SECONDS = 600       # identical searches reuse cached results for 10 min
RATE_LIMIT_RETRY_DELAY = 2    # seconds to wait before retrying the SAME key once
API_REQUEST_DEBOUNCE_SECONDS = 1  # minimum gap enforced between real requests

# ThreadPoolExecutor cap for parallel multi-location search. Used by
# api.py (sizes the connection pool) and cache.py (sizes the executor).
MAX_PARALLEL_LOCATIONS = 5

ALL_KEYS_EXHAUSTED_MESSAGE = "All API Keys have reached their request limit.\nPlease try again later."
RATE_LIMIT_FALLBACK_MESSAGE = "JSearch API rate limit reached. Showing previously loaded results."

# ---------------- Pagination ---------------- #
PAGE_SIZE = 10
NUM_API_PAGES = 10       # practical max per single request; local pagination
                          # handles everything beyond that — never a 2nd request
                          # for the same (query, country) pair.
MAX_RECENT_SEARCHES = 10
MAX_SUGGESTIONS = 5

# ---------------- Search filter options ---------------- #
COUNTRY_CODES = {
    "India": "in",
    "United States": "us",
    "Canada": "ca",
    "United Kingdom": "gb",
    "Australia": "au",
}

EMPLOYMENT_TYPES = ["All", "Full-time", "Part-time", "Internship", "Contract"]

EXPERIENCE_LEVELS = [
    "Any Experience", "Fresher", "Entry Level", "0-1 Years",
    "1-2 Years", "2-3 Years", "3-5 Years", "5+ Years",
]

# (min_months, max_months_or_None) — used only when a job explicitly
# states its required experience. Missing data never excludes a job.
EXPERIENCE_RANGES_MONTHS = {
    "Fresher": (0, 0),
    "Entry Level": (0, 12),
    "0-1 Years": (0, 12),
    "1-2 Years": (12, 24),
    "2-3 Years": (24, 36),
    "3-5 Years": (36, 60),
    "5+ Years": (60, None),
}

POSTED_FILTER_HOURS = {
    "Any Time": None,
    "Today": 24,
    "3 Days": 72,
    "7 Days": 168,
    "14 Days": 336,
    "30 Days": 720,
}

SORT_OPTIONS = ["Best Match", "Newest", "Oldest", "Salary (High to Low)", "Company (A-Z)"]

POPULAR_CITIES = ["Bangalore", "Mumbai", "Pune", "Hyderabad", "Delhi"]

ROLE_SUGGESTIONS = [
    "Data Analyst", "Data Scientist", "Machine Learning Engineer",
    "Python Developer", "Software Engineer", "Full Stack Developer",
    "Business Analyst", "Cloud Engineer", "DevOps Engineer",
    "AI Engineer", "Frontend Developer", "Backend Developer",
    "Product Manager", "QA Engineer", "UI/UX Designer",
]

QUICK_TIPS = [
    "Combine a job title with a city for more precise results.",
    "Use the Remote Only filter to see remote-friendly roles.",
    "Narrow results with the Posted Within filter for fresh listings.",
    "Click a recent search to instantly re-run it.",
    "Sort by Best Match to see the highest-scoring roles first.",
]