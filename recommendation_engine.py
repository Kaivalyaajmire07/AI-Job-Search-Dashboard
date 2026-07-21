"""AI recommendations: turns a job's match score into a human-readable
star rating and a short list of "Why Recommended" reasons.
"""


def star_rating(match_score: int) -> str:
    if match_score >= 90:
        return "⭐⭐⭐⭐⭐ Excellent Match"
    if match_score >= 75:
        return "⭐⭐⭐⭐ Good Match"
    if match_score >= 50:
        return "⭐⭐⭐ Average Match"
    return "⭐⭐ Possible Match"


def why_recommended(job: dict, role: str, wanted_skills: list, remote_only: bool,
                     experience_filter: str, locations: list) -> list:
    """Short, explainable bullet list — each line traces directly back
    to one of the ranking_engine scoring criteria.
    """
    from filters import job_matches_experience, job_matches_location

    reasons = []
    job_skills = {s.lower() for s in job.get("_skills", [])}

    for skill in wanted_skills:
        if skill.lower() in job_skills:
            reasons.append(f"✔ {skill} matched")

    title = (job.get("job_title") or "").lower()
    role_terms = [t for t in role.lower().split() if len(t) > 2]
    if role_terms and all(t in title for t in role_terms):
        reasons.append("✔ Title closely matches your search")

    if remote_only and job.get("job_is_remote"):
        reasons.append("✔ Remote")

    req = job.get("job_required_experience") or {}
    if req.get("no_experience_required"):
        reasons.append("✔ Fresher Friendly")

    if job.get("job_min_salary") and job.get("job_max_salary"):
        reasons.append("✔ Good Salary Disclosed")

    if locations and job_matches_location(job, locations):
        reasons.append("✔ Location Match")

    if experience_filter != "Any Experience" and job_matches_experience(job, experience_filter):
        reasons.append("✔ Experience Match")

    return reasons[:6]