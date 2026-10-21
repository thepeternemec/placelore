"""wikicrawl - a small, polite crawler for Wikipedia places and photos."""

__version__ = "0.1.0"

from .api import APIError, MediaWiki
from .crawl import GeoResult, crawl_category, crawl_links, geosearch
from .extract import parse_infobox, strip_markup, summary
from .pages import fetch_pages
from .store import Store

__all__ = [
    "APIError",
    "GeoResult",
    "MediaWiki",
    "Store",
    "crawl_category",
    "crawl_links",
    "fetch_pages",
    "geosearch",
    "parse_infobox",
    "strip_markup",
    "summary",
    "__version__",
]
