from tracker.authors import get_author


def site_author(request):
    """Expose the default site author to every template.

    Lets shared pages (e.g. about, blog list) render bylines and editorial
    notes from authors.json instead of hard-coding the name, handle, and links.
    """
    return {"site_author": get_author()}
