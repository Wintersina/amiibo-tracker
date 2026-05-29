"""Tests for the racism-only comment moderation filter.

Policy: block racial/ethnic slurs; allow ordinary profanity and rude comments.
We avoid hardcoding real slurs in this file by decoding a single term from the
actual (base64-encoded) blocklist at runtime to exercise the positive path.
"""

import base64
from pathlib import Path

import pytest

from tracker import moderation


ALLOWED = [
    "I love this Leon amiibo, it looks amazing",
    "this damn figure is so freaking expensive",
    "honestly a stupid ugly design and you have terrible taste",
    "what the hell, this shipping is bullshit",
    "",
    "the association classifies these by series",  # benign substring guard
]


@pytest.mark.parametrize("text", ALLOWED)
def test_allows_clean_rude_and_profane(text):
    assert moderation.contains_hate_speech(text) is False


def _first_blocklist_term() -> str:
    path = Path(moderation.__file__).parent / "data" / "blocked_terms.txt"
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return base64.b64decode(line).decode("utf-8")
    raise AssertionError("blocklist is empty")


def test_blocks_real_slur_from_blocklist():
    term = _first_blocklist_term()
    assert moderation.contains_hate_speech(f"you are such a {term} honestly") is True


def test_blocking_is_case_insensitive():
    term = _first_blocklist_term()
    assert moderation.contains_hate_speech(term.upper()) is True
