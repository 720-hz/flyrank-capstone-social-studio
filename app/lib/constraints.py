"""Deterministic per-platform constraint checking.

check_variant() is the ONLY place these rules are evaluated. Every other
module (ingestion, review, scheduling) reads the stored constraint_violations
list back out of the database rather than re-deriving it — a variant's
"is this clean" answer is computed exactly once, at generation time, and
never silently re-checked (and possibly silently fixed) somewhere else.
"""
import re

from app.config import CONSTRAINT_PROFILES

_SHOUTING_WORD = re.compile(r"\b[A-Z]{4,}\b")


def check_variant(platform: str, body_text: str, hashtags: list[str]) -> list[str]:
    """Returns a list of violated rule names. Empty list = clean."""
    if platform not in CONSTRAINT_PROFILES:
        return [f"unknown_platform:{platform}"]

    profile = CONSTRAINT_PROFILES[platform]
    violations = []

    if len(body_text) > profile["max_length"]:
        violations.append(
            f"max_length: {len(body_text)} chars exceeds {profile['max_length']}"
        )

    if len(hashtags) > profile["max_hashtags"]:
        violations.append(
            f"max_hashtags: {len(hashtags)} exceeds {profile['max_hashtags']}"
        )

    if profile.get("forbid_shouting") and _SHOUTING_WORD.search(body_text):
        word = _SHOUTING_WORD.search(body_text).group(0)
        violations.append(f"forbid_shouting: ALL-CAPS word '{word}' not allowed")

    return violations
