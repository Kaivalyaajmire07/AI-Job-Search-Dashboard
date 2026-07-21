"""AI job ranking.

Produces a 0-100 "Match Score" per job from a weighted combination of:
  * role/title keyword overlap        (40 pts)
  * skill overlap vs. skills implied  (20 pts)
    by the searched role
  * remote match                      (15 pts)
  * location match                    (15 pts)
  * experience match                  (10 pts)

Honest implementation note: this is a transparent, explainable heuristic
scorer — not a Sentence-Transformers/BERT embedding similarity. See
nlp_engine.py for why: dependency size and the project's own sub-second
performance target. The weighting is intentionally simple so the "Why
Recommended" reasons (recommendation_engine.py) can point at exactly
which criteria contributed to the score.
"""
from filters import job_matches_experience, job_matches_location
from skills_extractor import extract_skills_from_job

TITLE_WEIGHT = 40
SKILL_WEIGHT = 20
REMOTE_WEIGHT = 15
LOCATION_WEIGHT = 15
EXPERIENCE_WEIGHT = 10


def _title_overlap_score(job: dict, role: str) -> float:
    title = (job.get("job_title") or "").lower()
    terms = [t for t in role.lower().split() if len(t) > 2]
    if not terms:
        return TITLE_WEIGHT * 0.5  # no usable terms -> neutral credit
    hits = sum(1 for t in terms if t in title)
    return TITLE_WEIGHT * (hits / len(terms))


def _skill_overlap_score(job_skills: list, wanted_skills: list) -> float:
    if not wanted_skills:
        return SKILL_WEIGHT * 0.5  # neutral credit when no skill list was given
    job_skill_set = {s.lower() for s in job_skills}
    wanted_set = {s.lower() for s in wanted_skills}
    matched = job_skill_set & wanted_set
    return SKILL_WEIGHT * (len(matched) / len(wanted_set))


def compute_match_score(job: dict, role: str, wanted_skills: list, remote_only: bool,
                         experience_filter: str, locations: list) -> int:
    """Returns an integer 0-100. Filters that weren't actually applied
    (e.g. Remote Only left unchecked) contribute full neutral credit
    rather than penalizing the job.
    """
    job_skills = extract_skills_from_job(job)

    score = _title_overlap_score(job, role)
    score += _skill_overlap_score(job_skills, wanted_skills)

    if remote_only:
        score += REMOTE_WEIGHT if job.get("job_is_remote") else 0
    else:
        score += REMOTE_WEIGHT

    if locations:
        score += LOCATION_WEIGHT if job_matches_location(job, locations) else 0
    else:
        score += LOCATION_WEIGHT

    if experience_filter != "Any Experience":
        score += EXPERIENCE_WEIGHT if job_matches_experience(job, experience_filter) else 0
    else:
        score += EXPERIENCE_WEIGHT

    max_possible = TITLE_WEIGHT + SKILL_WEIGHT + REMOTE_WEIGHT + LOCATION_WEIGHT + EXPERIENCE_WEIGHT
    return round(min(score, max_possible) / max_possible * 100)


def rank_jobs(jobs: list, role: str, wanted_skills: list, remote_only: bool,
              experience_filter: str, locations: list) -> list:
    """Annotates every job dict in-place with `_match_score` and
    `_skills`, and returns the list sorted by score descending.
    """
    for job in jobs:
        job["_skills"] = extract_skills_from_job(job)
        job["_match_score"] = compute_match_score(
            job, role, wanted_skills, remote_only, experience_filter, locations
        )
    return sorted(jobs, key=lambda j: j["_match_score"], reverse=True)