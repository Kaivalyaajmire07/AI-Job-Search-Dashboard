"""API — the ONLY module that talks to JSearch over HTTP.

  * requests.Session() reused for the whole process -> HTTP keep-alive.
  * HTTPAdapter with a sized connection pool.
  * urllib3 Retry strategy for transient network errors (502/503/504).
  * Explicit timeout on every request.
  * st.cache_data (via cache-style decorator below) so an identical
    search never re-hits the network within the TTL window.
  * API key rotation across up to 5 keys — a single flat loop, switches
    ONLY on 429. Every other status raises its specific, friendly error
    immediately; a real network failure (DNS/connect/timeout) is the
    ONLY thing that produces the "Could not reach the JSearch API"
    message — it is never shown for a rate limit, auth, or server
    error.
"""
from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor

import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    API_KEYS,
    API_HOST,
    API_URL,
    CACHE_TTL_SECONDS,
    MAX_PARALLEL_LOCATIONS,
    NUM_API_PAGES,
    REQUEST_TIMEOUT,
    logger,
)

# Exact message required once every configured key has returned 429.
ALL_KEYS_EXHAUSTED_MESSAGE = "RapidAPI request limit reached."

MAX_CACHE_ENTRIES = 256


# ---------------------------------------------------------------------
# Exceptions — one per user-facing failure mode, never a raw traceback
# ---------------------------------------------------------------------

class JSearchError(Exception):
    """Base class for all JSearch API errors."""


class AllKeysExhaustedError(JSearchError):
    """Every configured API key returned 429."""


class JSearchAuthError(JSearchError):
    """401 — invalid/missing credentials."""


class JSearchClientError(JSearchError):
    """403 / 404 / 500 / 502 / 503 / other non-2xx, non-429, non-401 status."""


class JSearchConnectionError(JSearchError):
    """Could not reach the API at all — DNS failure, connection refused,
    or timeout. This is the ONLY exception that should ever surface the
    "Could not reach the JSearch API" message, and it is only raised
    when requests itself couldn't complete the round trip.
    """


# Friendly, user-facing messages for every non-429 status we handle.
# A lookup table (rather than an if/elif ladder) keeps the rotation
# loop below a single flat loop with no nested conditionals.
_STATUS_ERROR_MAP: dict[int, str] = {
    401: "Invalid API Key.",
    403: "API subscription problem.",
    404: "The requested resource was not found.",
    500: "Server error.",
    502: "Server error.",
    503: "Server error.",
}


# ---------------------------------------------------------------------
# Session with connection pooling + keep-alive + transient-error retry
# ---------------------------------------------------------------------

_session: requests.Session | None = None
_session_lock = threading.Lock()
_POOL_SIZE = max(MAX_PARALLEL_LOCATIONS, 10) + 5


def get_session() -> requests.Session:
    """Lazily build a single shared, pooled, keep-alive Session for the
    whole process (thread-safe, built at most once).
    """
    global _session
    if _session is not None:
        return _session

    with _session_lock:
        if _session is not None:
            return _session

        session = requests.Session()
        session.headers.update({"Connection": "keep-alive"})

        retry_strategy = Retry(
            total=3,
            connect=3,
            read=2,
            backoff_factor=0.5,
            status_forcelist=[502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            pool_connections=_POOL_SIZE,
            pool_maxsize=_POOL_SIZE,
            max_retries=retry_strategy,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        _session = session

    return _session


# ---------------------------------------------------------------------
# Key rotation — one flat loop, switches keys ONLY on 429
# ---------------------------------------------------------------------

def _request_with_key_rotation(params: dict) -> dict:
    """Walk API_KEYS in order, starting at KEY1.

    * HTTP 200            -> return the parsed JSON immediately.
    * HTTP 429             -> move on to the next key (no message shown
                               per key — only if every key is
                               exhausted does the caller see anything).
    * Any other bad status -> raise the matching friendly error right
                               away (never rotate keys for these).
    * Every key gave 429   -> raise AllKeysExhaustedError.
    * Network/timeout failure -> JSearchConnectionError, the only path
      that can ever produce "Could not reach the JSearch API".
    """
    if not API_KEYS:
        raise JSearchAuthError("No RapidAPI keys configured.")

    session = get_session()

    for key_index, api_key in enumerate(API_KEYS, start=1):
        headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": API_HOST}

        try:
            response = session.get(API_URL, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.Timeout as exc:
            raise JSearchConnectionError(
                "Could not reach the JSearch API. Check your internet connection."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise JSearchConnectionError(
                "Could not reach the JSearch API. Check your internet connection."
            ) from exc

        logger.info(
            "[JSearch API] key=%d/%d status=%d url=%s",
            key_index, len(API_KEYS), response.status_code, response.url,
        )

        if response.status_code == 200:
            return response.json()

        if response.status_code == 429:
            logger.info("[JSearch API] key=%d/%d rate limited, rotating to next key", key_index, len(API_KEYS))
            continue

        message = _STATUS_ERROR_MAP.get(response.status_code, f"Unexpected API error (HTTP {response.status_code}).")
        if response.status_code == 401:
            raise JSearchAuthError(message)
        raise JSearchClientError(message)

    logger.info("[JSearch API] all %d key(s) rate limited", len(API_KEYS))
    raise AllKeysExhaustedError(ALL_KEYS_EXHAUSTED_MESSAGE)


# ---------------------------------------------------------------------
# In-flight request de-duplication + st.cache_data
# ---------------------------------------------------------------------
# Guards against firing two real network calls for the exact same
# (query, country, num_pages) at the same moment. st.cache_data only
# de-dupes *completed* results; this closes the gap for calls still in
# flight (e.g. two locations normalizing to the same query, or several
# parallel location threads finishing near-simultaneously).

_inflight_lock = threading.Lock()
_inflight_futures: dict[tuple, Future] = {}
_dedup_executor = ThreadPoolExecutor(max_workers=_POOL_SIZE, thread_name_prefix="jsearch-fetch")


def _fetch_jobs_network(query: str, country_code: str, num_pages: int) -> list[dict]:
    """The actual network call. Never call directly — go through
    fetch_jobs_single so in-flight de-duplication is applied first.
    """
    params = {
        "query": query,
        "country": country_code,
        "page": "1",
        "num_pages": str(num_pages),
        "date_posted": "all",
    }
    data = _request_with_key_rotation(params)
    jobs = data.get("data", {}).get("jobs", [])
    logger.info("[JSearch API] query=%r returned %d job(s)", query, len(jobs))
    return jobs


_cached_fetch_jobs_network = st.cache_data(
    ttl=CACHE_TTL_SECONDS, max_entries=MAX_CACHE_ENTRIES, show_spinner=False
)(_fetch_jobs_network)


def fetch_jobs_single(query: str, country_code: str, num_pages: int = NUM_API_PAGES) -> list[dict]:
    """Fetch jobs for one query string.

    Duplicate-request protection happens in two layers:
      1. st.cache_data — repeating an identical search within
         CACHE_TTL_SECONDS never touches the network at all.
      2. In-flight de-dup — if this exact (query, country, num_pages)
         is already being fetched by another thread right now, this
         call waits on that result instead of starting a second
         network request.
    """
    fingerprint = (query, country_code, num_pages)

    with _inflight_lock:
        future = _inflight_futures.get(fingerprint)
        is_owner = future is None
        if is_owner:
            future = _dedup_executor.submit(_cached_fetch_jobs_network, query, country_code, num_pages)
            _inflight_futures[fingerprint] = future

    try:
        return future.result()
    finally:
        if is_owner:
            with _inflight_lock:
                _inflight_futures.pop(fingerprint, None)