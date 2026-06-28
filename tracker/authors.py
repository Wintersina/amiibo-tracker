import json
from pathlib import Path


AUTHORS_PATH = Path(__file__).parent / "data" / "authors.json"
DEFAULT_AUTHOR_SLUG = "sina"


def load_authors():
    """Load author metadata keyed by slug."""
    try:
        with AUTHORS_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
            return data.get("authors", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_author(slug=None):
    """Return one author, falling back to the default site author."""
    authors = load_authors()
    return authors.get(slug or DEFAULT_AUTHOR_SLUG) or authors.get(DEFAULT_AUTHOR_SLUG)
