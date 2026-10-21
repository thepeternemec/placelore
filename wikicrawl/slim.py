"""Build a slim, read-only database for serving.

The crawl database is a workshop: provenance tables, category links, infobox
JSON, visit bookkeeping. None of that belongs in a server's hot path, and all of
it costs page cache.

``slim`` copies exactly the columns the API can return, rebuilds indexes for
spatial and id lookups, and vacuums the result. Same places, a fraction of the
bytes.
"""

from __future__ import annotations

import os
import sqlite3

SLIM_DDL = """
CREATE TABLE places (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    language_code TEXT,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    types TEXT NOT NULL DEFAULT '[]',
    primary_type TEXT,
    business_status TEXT,
    formatted_address TEXT,
    short_formatted_address TEXT,
    adr_format_address TEXT,
    website_uri TEXT,
    google_maps_uri TEXT,
    rating REAL,
    user_rating_count INTEGER,
    google_place_id TEXT UNIQUE
);
CREATE TABLE place_photos (
    place_id TEXT NOT NULL,
    id TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    width_px INTEGER,
    height_px INTEGER,
    author_name TEXT,
    author_uri TEXT,
    license TEXT,
    position INTEGER DEFAULT 0,
    PRIMARY KEY (place_id, id)
);
"""

PLACE_COLUMNS = (
    "id",
    "name",
    "language_code",
    "lat",
    "lng",
    "types",
    "primary_type",
    "business_status",
    "formatted_address",
    "short_formatted_address",
    "adr_format_address",
    "website_uri",
    "google_maps_uri",
    "rating",
    "user_rating_count",
    "google_place_id",
)

PHOTO_COLUMNS = (
    "place_id",
    "id",
    "name",
    "url",
    "width_px",
    "height_px",
    "author_name",
    "author_uri",
    "license",
    "position",
)


def build_slim(source_db, out_db, overwrite=False):
    """Create ``out_db`` from ``source_db``; returns size statistics."""
    if os.path.exists(out_db):
        if not overwrite:
            raise FileExistsError("%s exists; pass --force to replace" % out_db)
        os.unlink(out_db)

    source = sqlite3.connect(source_db)
    source.row_factory = sqlite3.Row
    try:
        out = sqlite3.connect(out_db)
        out.executescript(SLIM_DDL)

        place_sql = "INSERT INTO places (%s) SELECT %s FROM source.places" % (
            ", ".join(PLACE_COLUMNS),
            ", ".join(PLACE_COLUMNS),
        )
        photo_sql = "INSERT INTO place_photos (%s) SELECT %s FROM source.place_photos" % (
            ", ".join(PHOTO_COLUMNS),
            ", ".join(PHOTO_COLUMNS),
        )

        out.execute("ATTACH DATABASE ? AS source", (source_db,))
        out.execute(place_sql)
        out.execute(photo_sql)
        out.executescript(
            """
            CREATE INDEX idx_places_geo ON places (lat, lng);
            CREATE INDEX idx_places_google ON places (google_place_id);
            CREATE INDEX idx_photos_place ON place_photos (place_id, position);
            """
        )
        out.commit()
        out.execute("DETACH DATABASE source")
        out.execute("VACUUM")
        out.commit()

        places = out.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        photos = out.execute("SELECT COUNT(*) FROM place_photos").fetchone()[0]
        out.close()
    finally:
        source.close()

    return {
        "places": places,
        "photos": photos,
        "source_bytes": os.path.getsize(source_db),
        "slim_bytes": os.path.getsize(out_db),
        "ratio": round(os.path.getsize(out_db) / max(1, os.path.getsize(source_db)), 3),
    }
