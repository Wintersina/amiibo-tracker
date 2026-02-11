"""
Custom sitemap view that allows search engine indexing.

Django's default sitemap view adds X-Robots-Tag: noindex header which prevents
Google from properly indexing the site. This custom view removes that header
to allow proper SEO indexing while keeping all other sitemap functionality.

Reference: https://forum.djangoproject.com/t/sitemap-possible-bug-seo-noindex-x-robot-tag/6562
"""
import datetime
from dataclasses import dataclass

from django.contrib.sites.shortcuts import get_current_site
from django.core.paginator import EmptyPage, PageNotAnInteger
from django.http import Http404
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.http import http_date


@dataclass
class SitemapIndexItem:
    location: str
    last_mod: bool = None


def _get_latest_lastmod(current_lastmod, new_lastmod):
    """
    Returns the latest `lastmod` where `lastmod` can be either a date or a
    datetime.
    """
    if not isinstance(new_lastmod, datetime.datetime):
        new_lastmod = datetime.datetime.combine(new_lastmod, datetime.time.min)
    if timezone.is_naive(new_lastmod):
        new_lastmod = timezone.make_aware(new_lastmod, datetime.timezone.utc)
    return new_lastmod if current_lastmod is None else max(current_lastmod, new_lastmod)


def sitemap(
    request,
    sitemaps,
    section=None,
    template_name="sitemap.xml",
    content_type="application/xml",
):
    """
    Custom sitemap view WITHOUT the X-Robots-Tag noindex header.

    This is a copy of Django's sitemap view but without the @x_robots_tag decorator
    that adds the noindex header. This allows search engines to properly crawl and
    index the site.
    """
    req_protocol = request.scheme
    req_site = get_current_site(request)

    if section is not None:
        if section not in sitemaps:
            raise Http404("No sitemap available for section: %r" % section)
        maps = [sitemaps[section]]
    else:
        maps = sitemaps.values()
    page = request.GET.get("p", 1)

    lastmod = None
    all_sites_lastmod = True
    urls = []
    for site in maps:
        try:
            if callable(site):
                site = site()
            urls.extend(site.get_urls(page=page, site=req_site, protocol=req_protocol))
            if all_sites_lastmod:
                site_lastmod = getattr(site, "latest_lastmod", None)
                if site_lastmod is not None:
                    lastmod = _get_latest_lastmod(lastmod, site_lastmod)
                else:
                    all_sites_lastmod = False
        except EmptyPage:
            raise Http404("Page %s empty" % page)
        except PageNotAnInteger:
            raise Http404("No page '%s'" % page)
    # If lastmod is defined for all sites, set header so as
    # ConditionalGetMiddleware is able to send 304 NOT MODIFIED
    if all_sites_lastmod:
        headers = {"Last-Modified": http_date(lastmod.timestamp())} if lastmod else None
    else:
        headers = None
    return TemplateResponse(
        request,
        template_name,
        {"urlset": urls},
        content_type=content_type,
        headers=headers,
    )
