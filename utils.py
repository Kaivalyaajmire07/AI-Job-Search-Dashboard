"""utils.py — job identity, date, and display-formatting helpers.

Pure functions of their inputs — no network calls, no Streamlit, no
config-dependent behavior. This module previously existed but was
missing from the project, which is why `from utils import ...` in
filters.py and app.py raised ModuleNotFoundError.
"""
import csv
import io
from datetime import datetime, timezone


# =====================================================================
# JOB IDENTITY / DEDUP
# =====================================================================

def get_job_key(job: dict) -> str:
    """Stable identifier used for dedup, bookmarking, and widget keys.
    Falls back to a composite of company + title + location + apply
    link when the API doesn't provide a job_id.
    """
    job_id = job.get("job_id")
    if job_id:
        return f"id:{job_id}"

    apply_link = job.get("job_apply_link")
    company = (job.get("employer_name") or "").strip().lower()
    title = (job.get("job_title") or "").strip().lower()
    location = format_location(job).lower()

    if apply_link:
        return f"link:{apply_link}|{company}|{title}|{location}"

    return f"composite:{company}|{title}|{location}"


def is_job_expired(job: dict) -> bool:
    """True only if the job's application window has clearly passed.
    Missing/unparseable expiry data is never treated as expired.
    """
    expiry = job.get("job_offer_expiration_datetime_utc")
    if not expiry:
        return False
    try:
        expiry_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
        return expiry_dt < datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


def get_posted_timestamp(job: dict) -> float:
    """Sortable timestamp used for the Newest/Oldest sort and the
    Posted Within filter."""
    timestamp = job.get("job_posted_at_timestamp")
    if timestamp:
        return timestamp

    posted = job.get("job_posted_at_datetime_utc")
    if not posted:
        return 0
    try:
        return datetime.fromisoformat(posted.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0


# =====================================================================
# DISPLAY FORMATTING
# =====================================================================

def format_location(job: dict) -> str:
    parts = [job.get("job_city"), job.get("job_state"), job.get("job_country")]
    location_str = ", ".join(p for p in parts if p)
    return location_str or "Location Not Provided"


def format_salary(job: dict) -> str:
    if job.get("job_min_salary") and job.get("job_max_salary"):
        currency = job.get("job_salary_currency", "") or ""
        return (
            f"{currency} {job.get('job_min_salary'):,} - {job.get('job_max_salary'):,}"
        ).strip()
    return "Salary Not Available"


def format_experience(job: dict) -> str:
    req = job.get("job_required_experience") or {}
    if req.get("no_experience_required"):
        return "Fresher / No Experience Required"

    months = req.get("required_experience_in_months")
    if months:
        years = months / 12
        if years < 1:
            return f"{months} month(s)"
        return f"{years:.1f}".rstrip("0").rstrip(".") + " year(s)"

    return "Experience Not Mentioned"


def average_salary(job: dict):
    """Sortable numeric salary, or None if unavailable."""
    lo = job.get("job_min_salary")
    hi = job.get("job_max_salary")
    if lo and hi:
        return (lo + hi) / 2
    return None


# =====================================================================
# CSV EXPORT
# =====================================================================

def jobs_to_csv(jobs: list) -> bytes:
    """Build a downloadable CSV (as bytes) from a list of job dicts."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Job Title", "Company", "Location", "Employment Type",
        "Experience", "Salary", "Match Score", "Posted Date",
        "Publisher", "Apply Link",
    ])
    for job in jobs:
        writer.writerow([
            job.get("job_title", ""),
            job.get("employer_name", ""),
            format_location(job),
            job.get("job_employment_type", ""),
            format_experience(job),
            format_salary(job),
            job.get("_match_score", ""),
            (job.get("job_posted_at_datetime_utc") or "")[:10],
            job.get("job_publisher", ""),
            job.get("job_apply_link", ""),
        ])
    return output.getvalue().encode("utf-8")