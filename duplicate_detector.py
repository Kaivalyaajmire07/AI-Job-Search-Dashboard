"""Duplicate detection using fuzzy string matching.

Compares title + company + location (and falls back to apply-link exact
match) to catch near-duplicate postings that a plain dict-key dedup
would miss — e.g. the same job re-posted with slightly different
whitespace or a trailing "(Remote)" in the title.

Uses RapidFuzz when it's installed (fast, small, pure-C — not a heavy
ML dependency) and falls back to Python's built-in difflib if it isn't,
so this module works either way.
"""
import difflib

try:
    from rapidfuzz import fuzz as _rapidfuzz
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False

DEFAULT_SIMILARITY_THRESHOLD = 90  # 0-100


def _signature(job: dict) -> str:
    return " ".join([
        (job.get("job_title") or "").lower().strip(),
        (job.get("employer_name") or "").lower().strip(),
        (job.get("job_city") or "").lower().strip(),
    ])


def _similarity(a: str, b: str) -> float:
    if _HAS_RAPIDFUZZ:
        return _rapidfuzz.token_sort_ratio(a, b)
    return difflib.SequenceMatcher(None, a, b).ratio() * 100


def remove_duplicates(jobs: list, threshold: int = DEFAULT_SIMILARITY_THRESHOLD) -> list:
    """O(n^2) fuzzy dedup — fine for the result-set sizes this project
    deals with (tens to low hundreds of jobs per search).
    """
    unique: list = []
    unique_signatures: list = []

    for job in jobs:
        apply_link = job.get("job_apply_link")
        signature = _signature(job)

        is_duplicate = False
        for existing, existing_signature in zip(unique, unique_signatures):
            if apply_link and apply_link == existing.get("job_apply_link"):
                is_duplicate = True
                break
            if _similarity(signature, existing_signature) >= threshold:
                is_duplicate = True
                break

        if not is_duplicate:
            unique.append(job)
            unique_signatures.append(signature)

    return unique
