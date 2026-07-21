"""Job Search Dashboard — main entry point.

Run with:
    streamlit run app.py

UI is intentionally unchanged from the previous build (same theme via
.streamlit/config.toml, same hero/search-card/sidebar/pagination
layout) — only backend/search logic changed:
  * No more "(auto-retries once per key, rotates keys on rate limits)"
    text anywhere.
  * "Could not reach the JSearch API..." is only ever shown for a real
    network exception — never for a rate limit, auth, or server error.
  * Empty Location = whole-country search, never a default city.
  * Job cards show the summary first; full description/skills/
    responsibilities/benefits/qualifications live behind "View Details".
  * 401 / 403 / 429 / 500 all get their own specific, friendly message.

Module map:
  config.py                 env/secrets + constants (incl. API key rotation list)
  models.py                 SearchParams / MatchResult dataclasses
  utils.py                  formatting, job identity, CSV export
  location_parser.py        multi-location parsing + normalization
  nlp_engine.py              lightweight query expansion ("AI Search")
  skills_extractor.py        keyword-based skill tag extraction
  filters.py                  local filtering & sorting (no API calls)
  ranking_engine.py           match-score computation
  recommendation_engine.py    star ratings + "why recommended"
  duplicate_detector.py       fuzzy near-duplicate removal
  api.py                      key-rotating single-query API client
  cache.py                    parallel multi-location fetch orchestration
  pagination.py                local pagination
  styles.py                     HTML-free Streamlit UI components

-----------------------------------------------------------------------
STARTUP CONFIG VALIDATION
-----------------------------------------------------------------------
Everything below the imports of `streamlit` runs BEFORE any other
project module is imported, since config.py resolves its secrets at
import time.

Secrets/env resolution (see config.get_secret()):
  * Streamlit Community Cloud -> read from st.secrets (the app's
    Secrets page).
  * Local machine             -> read from a .env file via
    load_dotenv(), or from real environment variables.
A missing .env file is NOT an error — it's the expected case on Cloud.
The only thing that IS validated is that RAPIDAPI_HOST and at least one
RAPIDAPI_KEY* actually resolved to a value, from whichever source.
"""
import time
from datetime import datetime

import streamlit as st

st.set_page_config(page_title="Job Search Dashboard", page_icon="💼", layout="wide")

EXPECTED_RAPIDAPI_HOST = "jsearch.p.rapidapi.com"

# ---------------------------------------------------------------------
# 1) Import config first — this is where RAPIDAPI_HOST / RAPIDAPI_KEY1..5
#    get resolved (st.secrets on Cloud, .env/os.getenv() locally). The
#    shared logger also lives there, so every module (including this
#    one) logs through the same handler/format without reconfiguring it.
# ---------------------------------------------------------------------
from config import (
    API_HOST,
    API_KEYS,
    API_REQUEST_DEBOUNCE_SECONDS,
    COUNTRY_CODES,
    EMPLOYMENT_TYPES,
    EXPERIENCE_LEVELS,
    MAX_RECENT_SEARCHES,
    MAX_SUGGESTIONS,
    NUM_API_PAGES,
    PAGE_SIZE,
    POPULAR_CITIES,
    POSTED_FILTER_HOURS,
    QUICK_TIPS,
    ROLE_SUGGESTIONS,
    SORT_OPTIONS,
    logger,
)


def _validate_startup_config() -> None:
    """Fail fast with a friendly message if required config is missing.

    Only validates that values *resolved* to something — never that a
    .env file exists on disk (st.secrets is the expected source on
    Streamlit Community Cloud).
    """
    if API_HOST != EXPECTED_RAPIDAPI_HOST:
        logger.error("Unexpected RAPIDAPI_HOST: %r", API_HOST)
        st.error(
            f"RAPIDAPI_HOST is set to \"{API_HOST}\", but this app requires "
            f"\"{EXPECTED_RAPIDAPI_HOST}\". Please fix RAPIDAPI_HOST in your "
            "Streamlit Cloud secrets, or in your local .env file."
        )
        st.stop()

    if not API_KEYS:
        logger.error("No RapidAPI keys resolved from secrets or environment.")
        st.error(
            "No RapidAPI keys found. Add RAPIDAPI_KEY1 through RAPIDAPI_KEY5 "
            "(or at least one of them) to your Streamlit Cloud app secrets, "
            "or to a local .env file."
        )
        st.stop()


_validate_startup_config()

_loaded_host: str = API_HOST
_loaded_key_count: int = len(API_KEYS)

logger.info("Loaded Host: %s", _loaded_host)
logger.info("Loaded Keys Count: %d", _loaded_key_count)

# ---------------------------------------------------------------------
# 2) Only now import the rest of the project modules.
# ---------------------------------------------------------------------
from api import ALL_KEYS_EXHAUSTED_MESSAGE, AllKeysExhaustedError, JSearchAuthError, JSearchClientError
from cache import fetch_jobs_multi_location
from duplicate_detector import remove_duplicates
from filters import apply_local_filters, process_jobs, sort_jobs
from location_parser import parse_locations
from models import SearchParams
from nlp_engine import expand_query
from pagination import clamp_page, page_range_text, page_slice, total_pages
from ranking_engine import rank_jobs
from skills_extractor import extract_skills
from styles import render_ai_metric_cards, render_job_card, render_metric_cards, render_pagination_controls
from utils import get_job_key, jobs_to_csv

# ---------------- Session State ---------------- #
DEFAULT_STATE = {
    "search": False,
    "country": "India",
    "employment": "All",
    "experience": "Any Experience",
    "location": "",
    "company": "",
    "min_salary": 0,
    "sort_by": "Best Match",
    "posted_filter_value": "Any Time",
    "fetched_jobs": [],          # deduped, ranked jobs, before local filters
    "all_jobs": [],              # fetched_jobs after local filters + sort
    "current_page": 1,
    "total_jobs": 0,
    "total_pages_count": 0,
    "last_fetch_params": None,        # fingerprint of filters that require an API call
    "last_search_trigger_time": 0.0,  # for the 1-second debounce
    "last_search_completed_at": "",
    "recent_searches": [],
    "pending_job_role": None,
    "auto_search": False,
    "bookmarks": {},             # {job_key: job_dict} — "Save Job"
    "view_mode": "search",       # "search" or "bookmarks"
}
for key, value in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = value

if st.session_state.pending_job_role is not None:
    st.session_state["job_role_input"] = st.session_state.pending_job_role
    st.session_state.pending_job_role = None


# ---------------- Search Orchestration ---------------- #

def build_job_query(role: str, employment: str, remote_only: bool, locations: list) -> str:
    """AI-expanded role + filters, folded into ONE query string per
    location. If `locations` is empty, NO city is added to the query —
    e.g. "Data Analyst India", never "Data Analyst Pune".
    """
    expanded_role = expand_query(role)
    query = expanded_role
    if employment and employment != "All":
        query += " " + employment
    if remote_only:
        query += " remote"
    if locations:
        query += " " + " ".join(locations)
    return query


def add_recent_search(role: str) -> None:
    """Push `role` onto the recent-searches stack (most-recent-first).

    No-ops for a blank role, and skips the push entirely if it's an
    exact (case-insensitive) repeat of the most recent entry, so
    re-running the same search doesn't spam the sidebar list. The list
    is capped at MAX_RECENT_SEARCHES entries.
    """
    role = role.strip()
    if not role:
        return
    history = st.session_state.recent_searches
    if history and history[0]["role"].lower() == role.lower():
        return
    entry = {"role": role, "time": datetime.now().strftime("%H:%M")}
    st.session_state.recent_searches = [entry] + history[:MAX_RECENT_SEARCHES - 1]


def apply_filters_and_paginate(params: SearchParams) -> None:
    """Apply local (non-API) filters/sort to the cached fetched_jobs
    and refresh the pagination state that depends on the result count.

    This is separate from the API fetch itself so that filter-only
    changes (posted-within, experience, salary, company, sort) can be
    re-applied without re-hitting the JSearch API.
    """
    filtered = apply_local_filters(
        st.session_state.fetched_jobs,
        st.session_state.posted_filter_value,
        params.experience,
        min_salary=params.min_salary,
        company_filter=params.company,
    )
    filtered = sort_jobs(filtered, st.session_state.sort_by)

    st.session_state.all_jobs = filtered
    st.session_state.total_jobs = len(filtered)
    st.session_state.total_pages_count = total_pages(len(filtered), PAGE_SIZE)
    st.session_state.current_page = clamp_page(
        st.session_state.current_page, st.session_state.total_pages_count
    )


def _friendly_message_for_error(error: Exception) -> str:
    """Map a caught API exception to a user-friendly message.

    401 -> "Invalid API Key."
    403 -> "API subscription problem."
    500 -> "Server error."
    A real network failure -> the connection message (api.py only
    raises that for an actual requests exception, never for a rate
    limit or HTTP error status).
    """
    if isinstance(error, AllKeysExhaustedError):
        return ALL_KEYS_EXHAUSTED_MESSAGE
    if isinstance(error, JSearchAuthError):
        return str(error)  # "Invalid API Key."
    if isinstance(error, JSearchClientError):
        return str(error)  # "API subscription problem." / "Server error." / etc.
    return str(error)


def run_search(params: SearchParams) -> None:
    """Fetch (only if needed) and rank jobs, then store the results.

    * Debounced: two triggers within 1 second are coalesced.
    * Only re-fetches when role/country/employment/remote/locations
      differ from the last successful fetch.
    * Empty Location -> ONE whole-country search, no default city.
    * Multiple locations are fetched in PARALLEL, each independently —
      one bad/rate-limited/empty city never stops the rest.
    * On total failure, previously loaded results are kept on screen.
    """
    # NOTE: this is a short (<=1s), user-triggered wait that gates a
    # single outgoing network call — not a loop or background task —
    # so a blocking sleep here is the simplest correct option. Streamlit
    # reruns the whole script top-to-bottom on each interaction, so
    # there's no separate "request thread" to defer this onto without
    # changing the debounce behavior itself.
    now = time.time()
    elapsed = now - st.session_state.last_search_trigger_time
    if elapsed < API_REQUEST_DEBOUNCE_SECONDS:
        time.sleep(API_REQUEST_DEBOUNCE_SECONDS - elapsed)
    st.session_state.last_search_trigger_time = time.time()

    fetch_fp = params.fetch_fingerprint()

    st.session_state.search = True
    st.session_state.country = params.country
    st.session_state.employment = params.employment
    st.session_state.experience = params.experience
    st.session_state.location = ", ".join(params.locations)
    st.session_state.company = params.company
    st.session_state.min_salary = params.min_salary or 0
    st.session_state.posted_filter_value = params.posted_filter
    st.session_state.current_page = 1

    if fetch_fp != st.session_state.last_fetch_params:
        country_code = COUNTRY_CODES[params.country]
        had_previous_results = bool(st.session_state.fetched_jobs)

        def query_builder(location: str) -> str:
            locs = [location] if location else []
            return build_job_query(params.role, params.employment, params.remote_only, locs)

        logger.info(
            "[Search] role=%r country=%r employment=%r remote=%s locations=%s",
            params.role, params.country, params.employment, params.remote_only, params.locations,
        )

        try:
            with st.spinner("Searching jobs..."):
                raw_jobs, errors = fetch_jobs_multi_location(
                    query_builder, country_code, NUM_API_PAGES, params.locations
                )
        except Exception as exc:
            # Deliberately broad: fetch_jobs_multi_location already
            # translates every known JSearch failure mode (auth, rate
            # limit, server error, network error) into `errors` below.
            # Anything raised past that point is a genuinely unexpected
            # crash, so it's logged and surfaced rather than narrowed
            # to a specific type we can't predict.
            logger.exception("Unexpected error during job search")
            st.exception(exc)
            return

        if raw_jobs:
            failed_locations = [loc for loc, _ in errors if loc]
            if failed_locations:
                st.info(
                    f"Couldn't fetch results for: {', '.join(failed_locations)}. "
                    "Showing jobs from the rest."
                )

            deduped = process_jobs(raw_jobs, params.remote_only, params.locations)
            deduped = remove_duplicates(deduped)

            wanted_skills = extract_skills(params.role)
            ranked = rank_jobs(
                deduped, params.role, wanted_skills, params.remote_only,
                params.experience, params.locations,
            )

            st.session_state.fetched_jobs = ranked
            st.session_state.last_fetch_params = fetch_fp
            st.session_state.last_search_completed_at = datetime.now().strftime("%H:%M:%S")

        elif errors:
            all_rate_limited = all(isinstance(exc, AllKeysExhaustedError) for _, exc in errors)

            if all_rate_limited and had_previous_results:
                st.warning(f"{ALL_KEYS_EXHAUSTED_MESSAGE} Showing previously loaded results.")
            elif all_rate_limited:
                st.error(ALL_KEYS_EXHAUSTED_MESSAGE)
                return
            else:
                _, first_error = errors[0]
                message = _friendly_message_for_error(first_error)

                if had_previous_results:
                    st.warning(f"{message} Showing previously loaded results.")
                else:
                    st.error(message)
                    return

    if not st.session_state.fetched_jobs:
        st.warning("No Jobs Found")

    apply_filters_and_paginate(params)


def toggle_bookmark(job: dict) -> None:
    """Add `job` to session bookmarks if not already saved, else remove it."""
    key = get_job_key(job)
    if key in st.session_state.bookmarks:
        del st.session_state.bookmarks[key]
    else:
        st.session_state.bookmarks[key] = job


def clear_recent_searches() -> None:
    """Empty the recent-searches sidebar list."""
    st.session_state.recent_searches = []


def jump_to_page(page_number: int) -> None:
    """Set current_page (clamped to the valid range) and rerun the app."""
    st.session_state.current_page = clamp_page(int(page_number), st.session_state.total_pages_count)
    st.rerun()


# ---------------- Header ---------------- #
st.title("💼 Job Search Dashboard")
st.caption("AI-powered real-time job listings from multiple companies, all in one place.")
st.divider()

# ---------------- Search Section ---------------- #
search_area = st.container(border=True)
with search_area:
    left, middle, right = st.columns([3, 2, 2])

    with left:
        job_role = st.text_input("🔍 Job Role", key="job_role_input", placeholder="Data Analyst")

        if job_role.strip():
            matches = [
                r for r in ROLE_SUGGESTIONS
                if r.lower().startswith(job_role.strip().lower()) and r.lower() != job_role.strip().lower()
            ][:MAX_SUGGESTIONS]
            if matches:
                st.caption("Suggestions:")
                chip_cols = st.columns(len(matches))
                for chip_col, suggestion in zip(chip_cols, matches):
                    if chip_col.button(suggestion, key=f"suggestion_{suggestion}", use_container_width=True):
                        st.session_state.pending_job_role = suggestion
                        st.rerun()

    with middle:
        employment = st.selectbox("💼 Employment", EMPLOYMENT_TYPES)

    with right:
        country = st.selectbox(
            "🌍 Country", list(COUNTRY_CODES.keys()),
            index=list(COUNTRY_CODES.keys()).index(st.session_state.country),
        )

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        location = st.text_input(
            "📍 Location (optional)", value=st.session_state.location,
            placeholder=f"e.g. {', '.join(POPULAR_CITIES)}",
            help='Leave empty to search the entire country. Enter one or more cities '
                 'separated by commas, e.g. "Pune, Mumbai, Nagpur" — searched in parallel.',
        )
    with col2:
        experience = st.selectbox(
            "🎯 Experience", EXPERIENCE_LEVELS,
            index=EXPERIENCE_LEVELS.index(st.session_state.experience),
        )
    with col3:
        posted_filter = st.selectbox("📅 Posted Within", list(POSTED_FILTER_HOURS.keys()))

    col4, col5, col6 = st.columns([1, 2, 1])
    with col4:
        remote_only = st.checkbox("🌐 Remote Only")
    with col5:
        company = st.text_input("🏢 Company (optional)", value=st.session_state.company, placeholder="e.g. Google")
    with col6:
        min_salary = st.number_input(
            "💰 Min Salary (optional)", min_value=0, step=10000,
            value=int(st.session_state.min_salary or 0),
        )

    search_clicked = st.button("🔍 Search Jobs", use_container_width=True)

# ---------------- Handle Search ---------------- #
if search_clicked or st.session_state.auto_search:
    st.session_state.auto_search = False

    if job_role.strip() == "":
        st.warning("Please enter a job role.")
        st.stop()

    st.session_state.view_mode = "search"
    search_params = SearchParams(
        role=job_role,
        country=country,
        employment=employment,
        experience=experience,
        posted_filter=posted_filter,
        remote_only=remote_only,
        locations=parse_locations(location),
        min_salary=min_salary or None,
        company=company,
    )
    run_search(search_params)
    add_recent_search(job_role)

# ==============================
# SIDEBAR
# ==============================
with st.sidebar:
    st.subheader("📋 About")
    st.caption(
        "This dashboard aggregates real-time job listings from multiple "
        "companies using AI-assisted search and ranking."
    )

    st.divider()

    st.subheader("📊 Dashboard Summary")
    if st.session_state.search and st.session_state.all_jobs:
        summary_col1, summary_col2 = st.columns(2)
        summary_col1.metric("Jobs", st.session_state.total_jobs)
        summary_col2.metric(
            "Companies",
            len(set(j.get("employer_name", "") for j in st.session_state.all_jobs)),
        )
    else:
        st.caption("Run a search to see a summary here.")

    st.divider()

    st.subheader("💡 Quick Tips")
    for tip in QUICK_TIPS:
        st.caption(f"• {tip}")

    st.divider()

    st.subheader("🔎 Recent Searches")
    history = st.session_state.recent_searches
    if not history:
        st.caption("No recent searches.")
    else:
        for idx, entry in enumerate(history):
            label = f"🕒 {entry['time']}  —  {entry['role']}"
            if st.button(label, key=f"recent_search_{idx}", use_container_width=True):
                st.session_state.pending_job_role = entry["role"]
                st.session_state.auto_search = True
                st.rerun()

        st.button(
            "🗑 Clear History", use_container_width=True,
            on_click=clear_recent_searches,
        )

    st.divider()

    bookmark_count = len(st.session_state.bookmarks)
    st.subheader(f"🔖 Saved Jobs ({bookmark_count})")
    if st.session_state.view_mode == "bookmarks":
        if st.button("⬅ Back to Search", use_container_width=True):
            st.session_state.view_mode = "search"
            st.rerun()
    else:
        if st.button("View Saved Jobs", use_container_width=True, disabled=bookmark_count == 0):
            st.session_state.view_mode = "bookmarks"
            st.rerun()

    if st.session_state.search:
        st.divider()
        with st.expander("🛠 Debug Info"):
            st.write(f"Jobs after dedup/ranking: **{len(st.session_state.fetched_jobs)}**")
            st.write(f"Locations searched: **{st.session_state.location or 'entire country'}**")
            st.write(f"Loaded Host: **{_loaded_host}**")
            st.write(f"Loaded Keys Count: **{_loaded_key_count}**")
            st.caption("Detailed request logs are printed to the terminal running `streamlit run app.py`.")

# ==============================
# BOOKMARKS ("SAVED JOBS") VIEW
# ==============================
if st.session_state.view_mode == "bookmarks":
    st.subheader(f"🔖 Saved Jobs ({len(st.session_state.bookmarks)})")

    if not st.session_state.bookmarks:
        st.info("You haven't saved any jobs yet. Save a job from your search results to see it here.")
    else:
        saved_jobs = list(st.session_state.bookmarks.values())

        csv_bytes = jobs_to_csv(saved_jobs)
        st.download_button(
            "⬇️ Export Saved Jobs to CSV", data=csv_bytes,
            file_name="saved_jobs.csv", mime="text/csv",
        )
        st.divider()

        for job in saved_jobs:
            render_job_card(
                job, bookmarked=True, on_toggle_bookmark=toggle_bookmark,
                role=st.session_state.get("job_role_input", ""), wanted_skills=[],
                remote_only=False, experience_filter="Any Experience", locations=[],
            )

# ==============================
# DASHBOARD + JOB LISTING (search view)
# ==============================
elif st.session_state.search and st.session_state.all_jobs:
    all_jobs = st.session_state.all_jobs
    total_jobs = st.session_state.total_jobs
    pages_count = st.session_state.total_pages_count
    current_page = st.session_state.current_page

    companies = len(set(job.get("employer_name", "") for job in all_jobs))
    render_metric_cards(total_jobs, companies, pages_count, current_page)

    st.divider()

    avg_match = round(sum(j.get("_match_score", 0) for j in all_jobs) / len(all_jobs)) if all_jobs else 0
    remote_count = sum(1 for j in all_jobs if j.get("job_is_remote"))
    internship_count = sum(1 for j in all_jobs if "intern" in (j.get("job_employment_type") or "").lower())
    fresher_count = sum(
        1 for j in all_jobs if (j.get("job_required_experience") or {}).get("no_experience_required")
    )
    render_ai_metric_cards(
        avg_match, remote_count, internship_count, fresher_count,
        st.session_state.last_search_completed_at or "just now",
    )

    st.divider()

    control_col1, control_col2 = st.columns([1, 3])
    with control_col1:
        sort_by = st.selectbox("Sort By", SORT_OPTIONS, index=SORT_OPTIONS.index(st.session_state.sort_by))
        if sort_by != st.session_state.sort_by:
            st.session_state.sort_by = sort_by
            st.session_state.all_jobs = sort_jobs(st.session_state.all_jobs, sort_by)
            st.rerun()
    with control_col2:
        csv_bytes = jobs_to_csv(all_jobs)
        st.download_button(
            "⬇️ Export Results to CSV", data=csv_bytes,
            file_name="job_search_results.csv", mime="text/csv",
        )

    st.divider()

    page_jobs = page_slice(all_jobs, current_page, PAGE_SIZE)
    current_locations = parse_locations(st.session_state.location)

    for job in page_jobs:
        is_bookmarked = get_job_key(job) in st.session_state.bookmarks
        render_job_card(
            job, bookmarked=is_bookmarked, on_toggle_bookmark=toggle_bookmark,
            role=st.session_state.get("job_role_input", ""),
            wanted_skills=extract_skills(st.session_state.get("job_role_input", "")),
            remote_only=False, experience_filter=st.session_state.experience,
            locations=current_locations,
        )

    range_start, range_end = page_range_text(current_page, PAGE_SIZE, total_jobs)
    prev_clicked, next_clicked = render_pagination_controls(
        current_page, pages_count, range_start, range_end, total_jobs, jump_to_page
    )

    if prev_clicked:
        st.session_state.current_page -= 1
        st.rerun()
    if next_clicked:
        st.session_state.current_page += 1
        st.rerun()