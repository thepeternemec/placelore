"""Build the clean, Google-shaped layer from crawl tables.

``pages`` is provenance: it holds what a wiki said. ``places`` is the clean
product: Google Places field names, stable ids, one row per place, photos
attached with licence and attribution intact.
"""

from __future__ import annotations

import html
import json
import re
import time

from .schema import ensure_schema, infer_types, photo_resource_name, slugify

TAG_RE = re.compile(r"<[^>]+>")
WIKI_HOSTS = {
    "en.wikipedia.org": "enwiki",
    "de.wikipedia.org": "dewiki",
    "fr.wikipedia.org": "frwiki",
    "sl.wikipedia.org": "slwiki",
    "it.wikipedia.org": "itwiki",
    "es.wikipedia.org": "eswiki",
}


def wiki_key(url, fallback="enwiki"):
    """``https://de.wikipedia.org/wiki/X`` -> ``dewiki``."""
    host = (url or "").split("//")[-1].split("/")[0].lower()
    return WIKI_HOSTS.get(host, fallback)


def place_id_for(wiki, pageid, wikidata_id=None):
    """Stable, namespaced place id.

    Wikidata QIDs are preferred because they survive article renames, page
    merges and cross-language moves; otherwise the page id of the source wiki
    is used, which is stable for the lifetime of that page.
    """
    if wikidata_id:
        return "wc:" + wikidata_id
    return "wc:%s:%s" % (wiki, pageid)


def clean_author(value):
    """Commons artist values are HTML; keep the text and any profile URL."""
    if not value:
        return "", ""
    match = re.search(r'href="([^"]+)"', value)
    uri = match.group(1) if match else ""
    if uri.startswith("//"):
        uri = "https:" + uri
    text = html.unescape(TAG_RE.sub("", value)).strip()
    return text, uri


def _dedupe_key(name, lat, lng):
    return (slugify(name, 40), round(lat or 0, 4), round(lng or 0, 4))


def normalize(conn, dedupe=True, drop_missing_coords=True):
    """Populate ``places`` and ``place_photos`` from ``pages``/``photos``.

    Returns a summary dict. Safe to run repeatedly: rows are upserted by id.
    """
    ensure_schema(conn)
    pages = conn.execute(
        """
        SELECT p.*, ph.url AS photo_url, ph.width AS photo_w, ph.height AS photo_h,
               ph.license AS photo_license, ph.artist AS photo_artist,
               ph.description_url AS photo_desc
        FROM pages p
        LEFT JOIN photos ph ON ph.file = 'File:' || p.image
        ORDER BY p.title
        """
    ).fetchall()

    categories = {}
    for row in conn.execute("SELECT pageid, category FROM page_categories"):
        categories.setdefault(row[0], []).append(row[1])

    summary = {"places": 0, "photos": 0, "skipped": 0, "duplicates": 0}
    seen = {}
    stamp = time.time()

    for page in pages:
        record = dict(page)
        if drop_missing_coords and (record.get("lat") is None or record.get("lon") is None):
            summary["skipped"] += 1
            continue

        name = (record.get("title") or "").strip()
        if not name:
            summary["skipped"] += 1
            continue

        key = _dedupe_key(name, record.get("lat"), record.get("lon"))
        if dedupe and key in seen:
            summary["duplicates"] += 1
            continue
        seen[key] = True

        wiki = wiki_key(record.get("url"))
        place_id = place_id_for(wiki, record.get("pageid"), record.get("wikidata_id"))
        types = infer_types(
            {
                "title": name,
                "categories": categories.get(record.get("pageid"), []),
                "infobox": _infobox(record),
            }
        )

        conn.execute(
            """
            INSERT INTO places (id, name, language_code, formatted_address,
                                short_formatted_address, adr_format_address,
                                lat, lng, types, primary_type, business_status,
                                website_uri, google_maps_uri, google_place_id,
                                google_fetched_at, match_confidence, match_method,
                                wikidata_id, wikipedia_url, commons_category,
                                country_code, source, created_at, updated_at)
            VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?, ?, ?, 'OPERATIONAL',
                    NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, NULL, NULL,
                    'wikimedia', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, lat=excluded.lat, lng=excluded.lng,
                types=excluded.types, primary_type=excluded.primary_type,
                wikipedia_url=excluded.wikipedia_url, updated_at=excluded.updated_at
            """,
            (
                place_id,
                name,
                "en",
                record.get("lat"),
                record.get("lon"),
                json.dumps(types),
                types[0] if types else None,
                record.get("wikidata_id"),
                record.get("url"),
                stamp,
                stamp,
            ),
        )
        summary["places"] += 1

        if record.get("photo_url"):
            photo_id = "commons:" + (record.get("image") or "").replace("_", " ")
            author, author_uri = clean_author(record.get("photo_artist"))
            conn.execute(
                """
                INSERT INTO place_photos (id, place_id, name, google_photo_reference,
                                          url, description_url, width_px, height_px,
                                          author_name, author_uri, license,
                                          html_attributions, position, created_at)
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(place_id, id) DO UPDATE SET
                    url=excluded.url,
                    width_px=excluded.width_px, height_px=excluded.height_px,
                    author_name=excluded.author_name, author_uri=excluded.author_uri,
                    license=excluded.license
                """,
                (
                    photo_id,
                    place_id,
                    photo_resource_name(place_id, photo_id),
                    record.get("photo_url"),
                    record.get("photo_desc"),
                    record.get("photo_w"),
                    record.get("photo_h"),
                    author,
                    author_uri,
                    record.get("photo_license"),
                    json.dumps([author] if author else []),
                    stamp,
                ),
            )
            summary["photos"] += 1

    conn.commit()
    return summary


def _infobox(record):
    raw = record.get("infobox") or "{}"
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}
