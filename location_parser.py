"""Location parsing & lightweight normalization.

Accepts unlimited comma-separated locations, cleans whitespace, removes
duplicates, and maps a small set of common aliases to a canonical form
(e.g. "Bombay" -> "Mumbai"). This is a plain lookup table, not a
restriction: any city not in the table passes through unchanged, so
every city worldwide is supported.
"""

# Canonical name for common aliases. Add more here freely — this is the
# ONLY place location synonyms need to be maintained.
LOCATION_SYNONYMS = {
    "bombay": "Mumbai",
    "bangalore": "Bengaluru",
    "banglore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "delhi ncr": "NCR",
    "new delhi": "Delhi",
    "gurgaon": "Gurugram",
    "calcutta": "Kolkata",
    "madras": "Chennai",
    "poona": "Pune",
}


def normalize_location(raw: str) -> str:
    """Clean extra whitespace and map known aliases to a canonical name.
    Unknown cities are returned as-is (title-cased whitespace only).
    """
    cleaned = " ".join(raw.strip().split())
    canonical = LOCATION_SYNONYMS.get(cleaned.lower())
    return canonical if canonical else cleaned


def parse_locations(location_text: str) -> list:
    """Split, normalize, and deduplicate a comma-separated location
    string. Order-preserving; case-insensitive dedup.

    "Pune,Mumbai, Pune ,Nagpur" -> ["Pune", "Mumbai", "Nagpur"]
    "Bombay, Bangalore" -> ["Mumbai", "Bengaluru"]
    "" -> []
    """
    if not location_text:
        return []

    seen = set()
    result = []
    for part in location_text.split(","):
        part = part.strip()
        if not part:
            continue
        normalized = normalize_location(part)
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result