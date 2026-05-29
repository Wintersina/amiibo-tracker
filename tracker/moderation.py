"""Lightweight comment moderation.

We block racist/ethnic slurs only. Ordinary profanity and rude-but-not-hateful
comments are allowed by design — cussing is fine. Matching is delegated to
``better-profanity`` seeded with a curated slur list (``data/blocked_terms.txt``)
instead of its default profanity set, so swearing passes straight through.

Known limitation: this is a basic word-level filter. It catches casing and
simple leetspeak (e.g. ``0`` for ``o``) but not deliberate separator evasion
(e.g. inserting hyphens between every letter). It is a first line of defence,
not a complete solution.
"""

import base64
from functools import lru_cache
from pathlib import Path

from better_profanity import Profanity

_TERMS_PATH = Path(__file__).parent / "data" / "blocked_terms.txt"


def _load_terms() -> list[str]:
    terms = []
    for line in _TERMS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            terms.append(base64.b64decode(line).decode("utf-8"))
        except Exception:
            # Skip any malformed entry rather than break moderation entirely.
            continue
    return terms


@lru_cache(maxsize=1)
def _filter() -> Profanity:
    return Profanity(_load_terms())


def contains_hate_speech(text: str) -> bool:
    """Return True if ``text`` contains a blocked slur.

    Case-insensitive and tolerant of simple character substitution. Returns
    False for empty input and for ordinary profanity.
    """
    if not text:
        return False
    return _filter().contains_profanity(text)
