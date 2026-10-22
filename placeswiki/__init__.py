"""placeswiki - open historical places, keyed to Google ids, served locally."""

__version__ = "3.0.0"

from .api import APIError, MediaWiki
from .crawl import GeoResult, crawl_category, crawl_links, geosearch
from .extract import parse_infobox, strip_markup, summary
from .google import PlacesClient, PlacesError, match_places
from .normalize import normalize
from .pages import fetch_pages
from .schema import ensure_schema, place_to_google, places_response
from .store import Store

__all__ = [
    "APIError",
    "PlacesClient",
    "PlacesError",
    "GeoResult",
    "MediaWiki",
    "Store",
    "crawl_category",
    "crawl_links",
    "ensure_schema",
    "fetch_pages",
    "match_places",
    "normalize",
    "geosearch",
    "parse_infobox",
    "place_to_google",
    "places_response",
    "strip_markup",
    "summary",
    "__version__",
]
