"""Google Places-shaped schema and serialisers.

The clean layer mirrors ``places.googleapis.com/v1`` field names exactly, so a
row can be emitted as a strict Places API (New) payload:

    places.id                       -> id
    places.displayName.text         -> name
    places.formattedAddress         -> formatted_address
    places.location                 -> lat / lng
    places.types                    -> types (JSON array)
    places.photos[].name            -> photo resource names
    places.photos[].authorAttributions

Field names and types are taken from Google's discovery document
(``https://places.googleapis.com/$discovery/rest?version=v1``), revision
20261019, not from the legacy Web Service docs.
"""

from __future__ import annotations

import json
import re
import time

# Places API (New) accepts these; unknown strings make the API reject a
# request, so every inferred type must come from this vocabulary.
GOOGLE_TYPES = {
    "tourist_attraction",
    "historical_landmark",
    "museum",
    "art_gallery",
    "church",
    "mosque",
    "synagogue",
    "hindu_temple",
    "place_of_worship",
    "cemetery",
    "city_hall",
    "courthouse",
    "library",
    "park",
    "national_park",
    "zoo",
    "aquarium",
    "stadium",
    "bridge",
    "point_of_interest",
    "establishment",
    "university",
    "school",
    "hospital",
    "train_station",
    "transit_station",
    "subway_station",
    "lodging",
    "restaurant",
    "cafe",
    "bar",
    "store",
    "locality",
}

# Keyword -> Google type, matched against categories and infobox values.
CATEGORY_RULES = (
    ("archaeological", "tourist_attraction"),
    ("amphitheatre", "historical_landmark"),
    ("amphitheater", "historical_landmark"),
    ("amphitheater", "historical_landmark"),
    ("castle", "historical_landmark"),
    ("fortress", "historical_landmark"),
    ("palace", "historical_landmark"),
    ("monument", "historical_landmark"),
    ("memorial", "historical_landmark"),
    ("ruins", "historical_landmark"),
    ("heritage", "historical_landmark"),
    ("historic", "historical_landmark"),
    ("museum", "museum"),
    ("art gallery", "art_gallery"),
    ("gallery", "art_gallery"),
    ("cathedral", "church"),
    ("basilica", "church"),
    ("church", "church"),
    ("chapel", "church"),
    ("monastery", "place_of_worship"),
    ("mosque", "mosque"),
    ("synagogue", "synagogue"),
    ("hindu temple", "hindu_temple"),
    ("hindu", "hindu_temple"),
    ("temple", "historical_landmark"),
    ("cemetery", "cemetery"),
    ("city hall", "city_hall"),
    ("courthouse", "courthouse"),
    ("library", "library"),
    ("park", "park"),
    ("garden", "park"),
    ("zoo", "zoo"),
    ("aquarium", "aquarium"),
    ("stadium", "stadium"),
    ("bridge", "bridge"),
    ("arch", "historical_landmark"),
    ("obelisk", "historical_landmark"),
    ("tower", "historical_landmark"),
    ("gate", "historical_landmark"),
    ("fountain", "tourist_attraction"),
    ("forum", "historical_landmark"),
    ("baths", "historical_landmark"),
    ("university", "university"),
    ("school", "school"),
)

BUSINESS_STATUSES = {
    "OPERATIONAL",
    "CLOSED_TEMPORARILY",
    "CLOSED_PERMANENTLY",
    "FUTURE_OPENING",
    "BUSINESS_STATUS_UNSPECIFIED",
}

PLACES_DDL = """
CREATE TABLE IF NOT EXISTS places (
    id                  TEXT PRIMARY KEY,      -- namespaced id, e.g. wc:Q10285
    name                TEXT NOT NULL,
    language_code       TEXT DEFAULT 'en',
    formatted_address   TEXT,                  -- Google-only, may be NULL
    short_formatted_address TEXT,
    adr_format_address  TEXT,
    lat                 REAL NOT NULL,
    lng                 REAL NOT NULL,
    types               TEXT NOT NULL DEFAULT '[]',   -- JSON array
    primary_type        TEXT,
    business_status     TEXT DEFAULT 'OPERATIONAL',
    website_uri         TEXT,
    google_maps_uri     TEXT,
    rating              REAL,                  -- Google-only
    user_rating_count   INTEGER,               -- Google-only
    google_place_id     TEXT UNIQUE,           -- may be cached indefinitely
    google_fetched_at   REAL,                  -- when Google fields were refreshed
    match_confidence    REAL,
    match_method        TEXT,
    wikidata_id         TEXT,
    wikipedia_url       TEXT,
    commons_category    TEXT,
    country_code        TEXT,
    source              TEXT DEFAULT 'wikimedia',
    created_at          REAL,
    updated_at          REAL
);
CREATE INDEX IF NOT EXISTS idx_places_geo ON places (lat, lng);
CREATE INDEX IF NOT EXISTS idx_places_qid ON places (wikidata_id);

CREATE TABLE IF NOT EXISTS place_photos (
    id              TEXT PRIMARY KEY,          -- commons:File:...
    place_id        TEXT NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,             -- resource name: places/{id}/photos/{slug}
    google_photo_reference TEXT,               -- set only after a Google match
    url             TEXT NOT NULL,             -- direct upload URL
    description_url TEXT,
    width_px        INTEGER,
    height_px       INTEGER,
    author_name     TEXT,
    author_uri      TEXT,
    license         TEXT,
    html_attributions TEXT,                    -- JSON array
    position        INTEGER DEFAULT 0,
    created_at      REAL
);
CREATE INDEX IF NOT EXISTS idx_photos_place ON place_photos (place_id, position);

CREATE TABLE IF NOT EXISTS google_matches (
    place_id        TEXT NOT NULL,
    google_place_id TEXT,
    score           REAL,
    method          TEXT,
    query           TEXT,
    matched_at      REAL,
    PRIMARY KEY (place_id, google_place_id)
);

-- Everything Google-sourced must be refreshed: the term limit is 30 days,
-- and place ids are the only field exempt from it.
CREATE VIEW IF NOT EXISTS v_google_stale AS
SELECT id, name, google_place_id, google_fetched_at,
       (strftime('%s','now') - google_fetched_at) / 86400.0 AS age_days
FROM places
WHERE google_place_id IS NOT NULL
  AND (google_fetched_at IS NULL
       OR google_fetched_at < strftime('%s','now') - 30 * 86400);
"""


def ensure_schema(conn):
    """Create the clean layer if it is not there yet."""
    conn.executescript(PLACES_DDL)


def slugify(text, limit=60):
    """Lowercase, hyphenated, ASCII-ish slug for use inside resource names."""
    text = (text or "").strip().lower()
    text = re.sub(r"^file:", "", text)
    text = re.sub(r"\.[a-z0-9]{2,5}$", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:limit] or "photo"


def photo_resource_name(place_id, photo_id):
    """Places API photo names look like ``places/{place}/photos/{ref}``."""
    return "places/%s/photos/%s" % (place_id, slugify(photo_id))


MAINTENANCE_PREFIXES = (
    "pages using",
    "articles",
    "all articles",
    "cs1 ",
    "commons ",
    "commons link",
    "coordinates on wikidata",
    "short description",
    "webarchive",
    "use dmy",
    "use mdy",
    "wikipedia ",
    "template:",
    "module:",
    "good articles",
    "featured articles",
    "harv and sfn",
    "pages with",
)

# Infobox keys that describe the template, not the place.
INFOBOX_META_KEYS = (
    "image",
    "caption",
    "name",
    "mapframe",
    "pushpin",
    "map_",
    "coordinates",
    "coords",
    "locator",
    "label",
    "zoom",
    "marker",
    "embedded",
    "designation",
)

INFOBOX_TYPE_KEYS = (
    "type",
    "building_type",
    "architectural_type",
    "functional_status",
    "category",
)


def _usable_category(name):
    lowered = name.lower()
    if lowered.startswith("category:"):
        lowered = lowered[9:]
    return not any(lowered.startswith(prefix) for prefix in MAINTENANCE_PREFIXES)


def _keyword_hit(keyword, haystack):
    """Word match that tolerates plurals but not unrelated compounds.

    'zoo' must not fire on 'mapframe-zoom'; 'amphitheatre' must fire on
    'amphitheatres'. Hence a boundary on both sides plus an optional plural.
    """
    pattern = r"(?<![a-z])" + re.escape(keyword) + r"(?:s|es)?(?![a-z])"
    return re.search(pattern, haystack) is not None


def infer_types(record):
    """Map categories/infobox onto the Google type vocabulary.

    Only semantic input is used: the title, non-maintenance categories, and
    infobox keys that describe the subject. Template plumbing such as
    ``mapframe-zoom`` and bookkeeping categories such as "Pages using gallery"
    are ignored, because both produced confident nonsense ("zoo", "art
    gallery") on the first real crawl.
    """
    categories = [c for c in record.get("categories", []) if _usable_category(c)]
    infobox = record.get("infobox") or {}
    semantic = [
        "%s %s" % (key, value)
        for key, value in infobox.items()
        if any(key.lower().startswith(k) for k in INFOBOX_TYPE_KEYS)
    ]
    haystack = " ".join([record.get("title", "")] + categories + semantic).lower()

    found = []
    for keyword, google_type in CATEGORY_RULES:
        if google_type in found:
            continue
        if _keyword_hit(keyword, haystack):
            found.append(google_type)

    if not found:
        found.append("tourist_attraction")
    return [t for t in found if t in GOOGLE_TYPES][:4]


def place_to_google(row, photos=()):
    """Serialise one clean row as a strict Places API (New) ``Place``.

    Unset fields are omitted, which is what the real API does with protobuf
    JSON: a field that was not requested, or is empty, does not appear.
    """
    place = {"id": row["id"], "types": json.loads(row["types"] or "[]")}

    if row.get("name"):
        place["displayName"] = {
            "text": row["name"],
            "languageCode": row.get("language_code") or "en",
        }
    if row.get("formatted_address"):
        place["formattedAddress"] = row["formatted_address"]
    if row.get("short_formatted_address"):
        place["shortFormattedAddress"] = row["short_formatted_address"]
    if row.get("adr_format_address"):
        place["adrFormatAddress"] = row["adr_format_address"]
    if row.get("lat") is not None and row.get("lng") is not None:
        place["location"] = {"latitude": row["lat"], "longitude": row["lng"]}
    if row.get("primary_type"):
        place["primaryType"] = row["primary_type"]
    if row.get("website_uri"):
        place["websiteUri"] = row["website_uri"]
    if row.get("google_maps_uri"):
        place["googleMapsUri"] = row["google_maps_uri"]
    if row.get("rating") is not None:
        place["rating"] = row["rating"]
    if row.get("user_rating_count") is not None:
        place["userRatingCount"] = row["user_rating_count"]
    if row.get("business_status") in BUSINESS_STATUSES:
        place["businessStatus"] = row["business_status"]

    photo_payloads = []
    for photo in photos:
        payload = {"name": photo["name"]}
        if photo.get("width_px") is not None:
            payload["widthPx"] = photo["width_px"]
        if photo.get("height_px") is not None:
            payload["heightPx"] = photo["height_px"]
        author = {}
        if photo.get("author_name"):
            author["displayName"] = photo["author_name"]
        if photo.get("author_uri"):
            author["uri"] = photo["author_uri"]
        if author:
            payload["authorAttributions"] = [author]
        photo_payloads.append(payload)
    if photo_payloads:
        place["photos"] = photo_payloads

    return place


def places_response(places):
    """Wrap serialised places in the exact Nearby/Text Search envelope."""
    return {"places": list(places)}


def photo_index(rows):
    """Sidecar map: photo name -> Commons URL and attribution.

    Google's payload deliberately carries no image URL (clients fetch bytes by
    resource name), so the URLs that Wikimedia gives us live here instead of
    polluting a payload that must stay parseable.
    """
    index = {}
    for row in rows:
        name = row["name"]
        index[name] = {
            "url": row["url"],
            "description_url": row.get("description_url"),
            "license": row.get("license"),
            "author": row.get("author_name"),
            "width_px": row.get("width_px"),
            "height_px": row.get("height_px"),
        }
    return index


def now():
    return time.time()
