"""Fetch structured page records in API batches.

One ``action=query`` call carries coordinates, lead image, categories, extract
and wikitext for up to 20 titles at a time (20 because ``prop=extracts``
accepts at most 20 titles per request when returning plain text).
"""

from __future__ import annotations

from .extract import parse_infobox, summary

BATCH = 20
MAX_BATCH = 20


def batched(items, size=BATCH):
    """Yield lists of at most ``size`` items from any iterable."""
    chunk = []
    for item in items:
        chunk.append(item)
        if len(chunk) >= size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def fetch_pages(api, titles, with_wikitext=True, batch=MAX_BATCH):
    """Return page records for ``titles``; missing pages are skipped."""
    records = []
    for chunk in batched(list(titles), min(batch, MAX_BATCH)):
        params = {
            "action": "query",
            "titles": "|".join(chunk),
            "prop": "coordinates|pageimages|categories|extracts",
            "colimit": "max",
            "cllimit": "max",
            "exintro": 1,
            "explaintext": 1,
            "exlimit": "max",
            "piprop": "name|original",
            "pithumbsize": 640,
            "redirects": 1,
        }
        if with_wikitext:
            params["prop"] += "|revisions"
            # rvlimit must not be combined with multiple titles, so leave it at
            # the default (one revision per page)
            params.update({"rvprop": "content", "rvslots": "main"})

        payload = api.get(params)
        for page in payload.get("query", {}).get("pages", []):
            if page.get("missing") or page.get("invalid"):
                continue
            coords = page.get("coordinates") or []
            primary = next((c for c in coords if c.get("primary")), coords[0] if coords else {})
            image = (page.get("pageimage") or "").strip()

            wikitext = ""
            if with_wikitext:
                revisions = page.get("revisions") or []
                if revisions:
                    slots = revisions[0].get("slots", {})
                    wikitext = (slots.get("main") or {}).get("content", "") or ""

            records.append(
                {
                    "pageid": page.get("pageid"),
                    "title": page.get("title", ""),
                    "lat": primary.get("lat"),
                    "lon": primary.get("lon"),
                    "coord_source": "api" if coords else "",
                    "image": image,
                    "image_url": (page.get("original") or {}).get("source", ""),
                    "extract": (page.get("extract") or "").strip(),
                    "summary": summary(wikitext) if wikitext else (page.get("extract") or "")[:500],
                    "categories": [c["title"] for c in page.get("categories", [])],
                    "infobox": parse_infobox(wikitext) if wikitext else {},
                    "wikitext": wikitext if with_wikitext else "",
                    "url": "https://en.wikipedia.org/wiki/"
                    + (page.get("title", "") or "").replace(" ", "_"),
                }
            )
    return records
