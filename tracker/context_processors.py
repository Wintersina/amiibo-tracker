import os

from tracker.authors import get_author


DEFAULT_SUPPORT_URL = "https://github.com/sponsors/Wintersina"


def site_author(request):
    """Expose the default site author to every template.

    Lets shared pages (e.g. about, blog list) render bylines and editorial
    notes from authors.json instead of hard-coding the name, handle, and links.
    """
    return {"site_author": get_author()}


def support_links(request):
    """Expose the sponsorship destination to every template.

    Lives here rather than being hard-coded in base.html and index.html so the
    nav button and the homepage support band can never drift apart, and so the
    URL can be swapped through the environment without a redeploy of templates.
    """
    return {"support_url": os.environ.get("SUPPORT_URL") or DEFAULT_SUPPORT_URL}
