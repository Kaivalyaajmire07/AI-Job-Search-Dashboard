"""CACHE — parallel multi-location search orchestration.

Layered on top of api.fetch_jobs_single (which already has st.cache_data
+ in-flight de-duplication + key rotation baked in). This module's only
job is: given a role/filter query and 0..N locations, fetch every
location IN PARALLEL and merge the results, without letting one bad
location take down the whole search.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from api import fetch_jobs_single
from config import MAX_PARALLEL_LOCATIONS, NUM_API_PAGES, logger


def fetch_jobs_multi_location(
    query_builder: Callable[[str | None], str],
    country_code: str,
    num_pages: int = NUM_API_PAGES,
    locations: list[str] | None = None,
) -> tuple[list[dict], list[tuple[str | None, Exception]]]:
    """Fetch jobs for every requested location IN PARALLEL and merge.

    * `locations` empty/None -> exactly ONE country-wide search, with
      `query_builder(None)` producing a query that contains NO city at
      all (e.g. "Data Analyst India", never "Data Analyst Pune").
    * `locations` with 1+ entries -> one request per location, run
      concurrently via ThreadPoolExecutor, results merged in the order
      they complete.
    * A failure in one location is recorded but never aborts the
      others — the remaining locations still get searched. Only if
      EVERY requested location fails does the returned job list come
      back empty.

    Returns (jobs, errors) where errors is a list of (location, exc)
    tuples. `location` is None for the country-wide case.
    """
    locations = locations or []

    if not locations:
        query = query_builder(None)
        try:
            jobs = fetch_jobs_single(query, country_code, num_pages)
            return jobs, []
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller via the errors list
            logger.warning("[Search] country-wide fetch failed: %s", exc)
            return [], [(None, exc)]

    all_jobs: list[dict] = []
    errors: list[tuple[str | None, Exception]] = []
    max_workers = max(1, min(MAX_PARALLEL_LOCATIONS, len(locations)))

    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="jsearch-location") as executor:
        future_to_location = {
            executor.submit(fetch_jobs_single, query_builder(location), country_code, num_pages): location
            for location in locations
        }
        for future in as_completed(future_to_location):
            location = future_to_location[future]
            try:
                all_jobs.extend(future.result())
            except Exception as exc:  # noqa: BLE001 - one bad city never blocks the rest
                logger.warning("[Search] location=%r failed: %s", location, exc)
                errors.append((location, exc))

    return all_jobs, errors