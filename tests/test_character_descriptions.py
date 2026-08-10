"""Guards the curated character descriptions against database drift.

New amiibos arrive through the automated "Update amiibo database from live API"
pull request. Nothing there writes a description, so a new figure silently falls
back to the generic "X is a character from the Y series." sentence in
AmiiboDetailView._get_character_description — which is how Grace Ashcroft, Leon
S. Kennedy and Terry Bogard went unnoticed. This test makes that gap show up on
the sync PR instead of on the live page.
"""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "tracker" / "data"


def load_amiibos():
    payload = json.loads((DATA / "amiibo_database.json").read_text(encoding="utf-8"))
    return payload.get("amiibo") if isinstance(payload, dict) else payload


def load_descriptions():
    return json.loads(
        (DATA / "character_descriptions.json").read_text(encoding="utf-8")
    )


def resolve_description(amiibo, descriptions):
    """Mirror the view's lookup order: amiibo id, then name, then character."""
    amiibo_id = f"{amiibo.get('head', '')}-{amiibo.get('tail', '')}"
    for key in (amiibo_id, amiibo.get("name"), amiibo.get("character")):
        if key and key in descriptions:
            return descriptions[key]
    return None


def test_every_amiibo_resolves_a_curated_description():
    descriptions = load_descriptions()

    missing = [
        f"{amiibo.get('head', '')}-{amiibo.get('tail', '')} {amiibo.get('name')}"
        for amiibo in load_amiibos()
        if resolve_description(amiibo, descriptions) is None
    ]

    assert not missing, (
        "These amiibos fall back to the generic description. Add an entry to "
        "tracker/data/character_descriptions.json keyed by amiibo id:\n  "
        + "\n  ".join(sorted(missing))
    )


def test_newest_resident_evil_and_terry_descriptions_are_specific():
    descriptions = load_descriptions()
    by_id = {
        amiibo.get("head", "") + "-" + amiibo.get("tail", ""): amiibo
        for amiibo in load_amiibos()
    }

    expectations = {
        "35400000-05032002": "Grace Ashcroft",
        "35410000-05042002": "Leon S. Kennedy",
        "3c800000-03a40002": "Terry Bogard",
    }

    for amiibo_id, name in expectations.items():
        text = resolve_description(by_id[amiibo_id], descriptions)
        assert text, amiibo_id
        assert name.split()[0] in text, amiibo_id
        # The generic fallback is one flat sentence; curated copy says more.
        assert len(text) > 120, amiibo_id
        assert not text.endswith(f"is a character from the {name} series.")


def test_descriptions_are_non_empty_strings():
    for key, value in load_descriptions().items():
        assert isinstance(value, str), key
        assert value.strip(), key
