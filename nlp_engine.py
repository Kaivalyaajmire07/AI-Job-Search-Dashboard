"""Query expansion ("AI Search" / "NLP Search").

Honest implementation note: this intentionally does NOT load Sentence-
Transformers, spaCy, or a BERT model. Those add hundreds of MB to a
couple of GB of dependencies, a real (multi-second, sometimes
multi-minute on first run) model download/load, and directly conflict
with the "<1 second cached search" performance target and the
"no huge app.py / keep it fast" goals stated for this project.

Instead, this uses a curated related-role dictionary: a fast, zero-extra-
dependency lookup that expands a role like "Data Science" into the
related titles a recruiter would also tag a matching job with. It's a
heuristic, not true semantic search — but it's real, it runs in
microseconds, and it materially improves recall for the common tech-role
searches this dashboard targets.

If true embedding-based semantic search is wanted later, this module is
the only place that needs to change — every downstream module just
consumes the plain query string this returns.
"""

ROLE_EXPANSIONS = {
    "data science": [
        "Data Scientist", "Machine Learning Engineer", "AI Engineer",
        "ML Engineer", "Analytics Engineer", "Business Intelligence",
        "Business Analyst", "Data Analyst", "Deep Learning Engineer",
    ],
    "data scientist": [
        "Data Scientist", "Machine Learning Engineer", "AI Engineer",
        "Analytics Engineer", "Deep Learning Engineer",
    ],
    "data analyst": [
        "Data Analyst", "Business Analyst", "Reporting Analyst", "BI Analyst",
    ],
    "machine learning": [
        "Machine Learning Engineer", "ML Engineer", "AI Engineer",
        "Deep Learning Engineer", "NLP Engineer", "Computer Vision Engineer",
    ],
    "ai": [
        "AI Engineer", "Machine Learning Engineer", "NLP Engineer",
        "Computer Vision Engineer", "AI Intern", "Machine Learning Intern",
    ],
    "python developer": [
        "Python Developer", "Backend Developer", "Software Engineer",
        "Python Data Developer",
    ],
    "web developer": [
        "Web Developer", "Frontend Developer", "Full Stack Developer",
    ],
    "software engineer": [
        "Software Engineer", "Software Developer", "Backend Developer",
        "Full Stack Developer",
    ],
    "cloud engineer": [
        "Cloud Engineer", "DevOps Engineer", "Site Reliability Engineer",
        "Platform Engineer",
    ],
    "business analyst": [
        "Business Analyst", "Data Analyst", "Business Intelligence Analyst",
    ],
}


def expand_query(role: str, max_extra_terms: int = 4) -> str:
    """Return the role, optionally OR-combined with a few closely
    related titles pulled from ROLE_EXPANSIONS. Falls back to the
    original role unchanged if nothing matches.
    """
    key = role.strip().lower()
    if not key:
        return role

    related = ROLE_EXPANSIONS.get(key)
    if not related:
        for dict_key, values in ROLE_EXPANSIONS.items():
            if dict_key in key or key in dict_key:
                related = values
                break

    if not related:
        return role

    extra_terms = [term for term in related if term.lower() != key][:max_extra_terms]
    if not extra_terms:
        return role

    return role + " OR " + " OR ".join(extra_terms)