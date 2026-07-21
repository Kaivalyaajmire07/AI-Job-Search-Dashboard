"""Local filtering & sorting.

Everything here operates on jobs already in memory — none of it ever
makes a network call, so changing Posted Within, Experience, Salary,
Company, or Sort By is instant and never re-hits the API.

Guiding rule: a job is only removed when its data EXPLICITLY mismatches
a filter. Missing data never excludes a job.
"""
from datetime import datetime, timedelta, timezone

from config import EXPERIENCE_RANGES_MONTHS, POSTED_FILTER_HOURS
from utils import average_salary, get_job_key, get_posted_timestamp, is_job_expired


def job_matches_location(job: dict, locations: list) -> bool:
    if not locations:
        return True
    fields = [
        (job.get("job_city") or "").lower(),
        (job.get("job_state") or "").lower(),
        (job.get("job_country") or "").lower(),
    ]
    return any(loc.lower() in field for loc in locations for field in fields)


def job_matches_remote(job: dict, remote_only: bool) -> bool:
    if not remote_only:
        return True
    return job.get("job_is_remote") is not False


def job_matches_posted_filter(job: dict, posted_filter: str) -> bool:
    hours = POSTED_FILTER_HOURS.get(posted_filter)
    if hours is None:
        return True
    timestamp = get_posted_timestamp(job)
    if not timestamp:
        return True
    posted_dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return posted_dt >= cutoff


def job_matches_experience(job: dict, experience_filter: str) -> bool:
    if experience_filter == "Any Experience":
        return True
    req = job.get("job_required_experience") or {}
    months = req.get("required_experience_in_months")
    if months is None:
        return True
    lo, hi = EXPERIENCE_RANGES_MONTHS[experience_filter]
    if hi is None:
        return months >= lo
    return lo <= months <= hi


def job_matches_min_salary(job: dict, min_salary) -> bool:
    if not min_salary:
        return True
    avg = average_salary(job)
    if avg is None:
        return True  # missing salary data -> never excluded
    return avg >= min_salary


def job_matches_company(job: dict, company_filter: str) -> bool:
    if not company_filter:
        return True
    employer = (job.get("employer_name") or "").lower()
    return company_filter.strip().lower() in employer


def process_jobs(raw_jobs: list, remote_only: bool, locations: list) -> list:
    """Deduplicate (exact key match) and drop only HARD-filter failures:
    duplicates, expired listings, no apply link, explicitly non-remote
    (if Remote Only is on), or an explicit location mismatch.
    """
    seen_keys = set()
    processed = []
    for job in raw_jobs:
        key = get_job_key(job)
        if key in seen_keys:
            continue
        if is_job_expired(job):
            continue
        if not job_matches_remote(job, remote_only):
            continue
        if not job_matches_location(job, locations):
            continue
        if not job.get("job_apply_link"):
            continue
        seen_keys.add(key)
        processed.append(job)
    return processed


def apply_local_filters(jobs: list, posted_filter: str, experience_filter: str,
                         min_salary=None, company_filter: str = "") -> list:
    """Every filter that never requires a re-fetch, applied together."""
    return [
        job for job in jobs
        if job_matches_posted_filter(job, posted_filter)
        and job_matches_experience(job, experience_filter)
        and job_matches_min_salary(job, min_salary)
        and job_matches_company(job, company_filter)
    ]


def sort_jobs(jobs: list, sort_by: str) -> list:
    if sort_by == "Best Match":
        return sorted(jobs, key=lambda j: j.get("_match_score", 0), reverse=True)
    if sort_by == "Oldest":
        return sorted(jobs, key=get_posted_timestamp)
    if sort_by == "Salary (High to Low)":
        return sorted(
            jobs,
            key=lambda j: (average_salary(j) is not None, average_salary(j) or 0),
            reverse=True,
        )
    if sort_by == "Company (A-Z)":
        return sorted(jobs, key=lambda j: (j.get("employer_name") or "").lower())
    return sorted(jobs, key=get_posted_timestamp, reverse=True)  # Newest (default)