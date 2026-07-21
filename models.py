"""Lightweight typed models.

Job listings themselves are kept as plain dicts (they're consumed
directly as returned by JSearch throughout the project) — these two
dataclasses cover the two places a structured type genuinely helps:
describing a search, and describing an AI match result.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class SearchParams:
    """Everything the user chose for one search."""
    role: str
    country: str
    employment: str
    experience: str
    posted_filter: str
    remote_only: bool
    locations: List[str] = field(default_factory=list)
    min_salary: Optional[int] = None
    company: str = ""

    def fetch_fingerprint(self) -> Tuple:
        """Identifies which filters actually require a new API call.
        Posted Within / Experience / Salary / Company / Sort are all
        applied locally, so they're intentionally excluded here.
        """
        return (self.role, self.country, self.employment, self.remote_only, tuple(self.locations))


@dataclass
class MatchResult:
    """The AI ranking/recommendation output for one job."""
    job: dict
    score: int                 # 0-100
    rating_label: str          # e.g. "⭐⭐⭐⭐⭐ Excellent Match"
    reasons: List[str]         # e.g. ["✔ Python matched", "✔ Remote"]
    skills: List[str]          # extracted skill tags