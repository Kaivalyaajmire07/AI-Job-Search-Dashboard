"""Skill extraction.

Scans a job's title + description for a known list of tech skills and
returns whichever ones appear, for display as tags and for use in the
ranking engine's skill-match scoring.
"""

SKILL_KEYWORDS = [
    "Python", "SQL", "Excel", "Power BI", "Tableau", "TensorFlow", "PyTorch",
    "Java", "C++", "JavaScript", "TypeScript", "React", "Node.js", "AWS",
    "Azure", "GCP", "Docker", "Kubernetes", "Git", "Machine Learning",
    "Deep Learning", "NLP", "Computer Vision", "Spark", "Hadoop", "Kafka",
    "Airflow", "Scikit-learn", "Pandas", "NumPy", "R", "Linux", "MongoDB",
    "PostgreSQL", "MySQL", "REST API", "GraphQL", "CI/CD", "Terraform",
    "Django", "Flask", "FastAPI",
]


def extract_skills(text: str) -> list:
    """Case-insensitive substring match against SKILL_KEYWORDS. Returns
    matched skills in their canonical (display) casing, no duplicates.
    """
    if not text:
        return []
    lowered = text.lower()
    return [skill for skill in SKILL_KEYWORDS if skill.lower() in lowered]


def extract_skills_from_job(job: dict) -> list:
    combined = f"{job.get('job_title', '')} {job.get('job_description', '')}"
    return extract_skills(combined)