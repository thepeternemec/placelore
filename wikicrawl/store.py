"""SQLite persistence: resumable, queryable, no server required.

The store is deliberately boring: one table for pages, one for their
categories, one for crawl bookkeeping. That is enough to resume a crawl,
de-duplicate across strategies, and run bounding-box queries offline.
"""

from __future__ import annotations

import csv
import json
import math
import sqlite3
import time


def photo_key(name):
    """Canonical key for a file name.

    MediaWiki titles ignore the case of the first letter and treat ``_`` as a
    space, so pageimages and Commons disagree often enough that both sides
    must be normalised before they can be joined.
    """
    name = (name or "").strip().replace("_", " ")
    if name.lower().startswith("file:"):
        name = name[5:].strip()
    return name[:1].upper() + name[1:] if name else ""


SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    pageid      INTEGER PRIMARY KEY,
    title       TEXT UNIQUE NOT NULL,
    url         TEXT,
    lat         REAL,
    lon         REAL,
    coord_source TEXT,
    extract     TEXT,
    summary     TEXT,
    image       TEXT,
    image_url   TEXT,
    infobox     TEXT,
    fetched_at  REAL
);
CREATE TABLE IF NOT EXISTS page_categories (
    pageid   INTEGER NOT NULL,
    category TEXT NOT NULL,
    PRIMARY KEY (pageid, category)
);
CREATE TABLE IF NOT EXISTS visited (
    title    TEXT PRIMARY KEY,
    source   TEXT,
    visited_at REAL
);
CREATE INDEX IF NOT EXISTS idx_pages_geo ON pages (lat, lon);
CREATE TABLE IF NOT EXISTS photos (
    file            TEXT PRIMARY KEY,
    url             TEXT,
    width           INTEGER,
    height          INTEGER,
    mime            TEXT,
    license         TEXT,
    artist          TEXT,
    credit          TEXT,
    description     TEXT,
    description_url TEXT
);
"""


class Store:
    """A crawl database, usable as a context manager."""

    def __init__(self, path="crawl.sqlite"):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.conn.commit()
        self.conn.close()

    # -- pages ---------------------------------------------------------

    def upsert_page(self, record):
        """Insert or update one page record; returns True if it was new."""
        cursor = self.conn.execute("SELECT pageid FROM pages WHERE title = ?", (record["title"],))
        existed = cursor.fetchone() is not None
        self.conn.execute(
            """
            INSERT INTO pages (pageid, title, url, lat, lon, coord_source, extract,
                               summary, image, image_url, infobox, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pageid) DO UPDATE SET
                title=excluded.title, url=excluded.url, lat=excluded.lat,
                lon=excluded.lon, coord_source=excluded.coord_source,
                extract=excluded.extract, summary=excluded.summary,
                image=excluded.image, image_url=excluded.image_url,
                infobox=excluded.infobox, fetched_at=excluded.fetched_at
            """,
            (
                record["pageid"],
                record["title"],
                record.get("url", ""),
                record.get("lat"),
                record.get("lon"),
                record.get("coord_source", ""),
                record.get("extract", ""),
                record.get("summary", ""),
                photo_key(record.get("image", "")),
                record.get("image_url", ""),
                json.dumps(record.get("infobox", {}), ensure_ascii=False),
                time.time(),
            ),
        )
        for category in record.get("categories", []):
            self.conn.execute(
                "INSERT OR IGNORE INTO page_categories (pageid, category) VALUES (?, ?)",
                (record["pageid"], category),
            )
        return not existed

    def mark_visited(self, title, source=""):
        self.conn.execute(
            "INSERT OR IGNORE INTO visited (title, source, visited_at) VALUES (?, ?, ?)",
            (title, source, time.time()),
        )

    def was_visited(self, title):
        row = self.conn.execute("SELECT 1 FROM visited WHERE title = ?", (title,)).fetchone()
        return row is not None

    def upsert_photo(self, record):
        """Store one Commons image record (keyed by its File: title)."""
        self.conn.execute(
            """
            INSERT INTO photos (file, url, width, height, mime, license, artist,
                                credit, description, description_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file) DO UPDATE SET
                url=excluded.url, width=excluded.width, height=excluded.height,
                mime=excluded.mime, license=excluded.license, artist=excluded.artist,
                credit=excluded.credit, description=excluded.description,
                description_url=excluded.description_url
            """,
            (
                "File:" + photo_key(record.get("file", "")),
                record.get("url", ""),
                record.get("width"),
                record.get("height"),
                record.get("mime", ""),
                record.get("license", ""),
                record.get("artist", ""),
                record.get("credit", ""),
                record.get("description", ""),
                record.get("description_url", ""),
            ),
        )

    def pending_image_files(self, limit=None):
        """Page lead-image names that have not been resolved on Commons yet."""
        sql = """
            SELECT DISTINCT p.image FROM pages p
            LEFT JOIN photos ph ON ph.file = 'File:' || p.image
            WHERE p.image != '' AND ph.file IS NULL
            ORDER BY p.image
        """
        if limit:
            sql += " LIMIT %d" % int(limit)
        return [row["image"] for row in self.conn.execute(sql)]

    # -- queries -------------------------------------------------------

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]

    def stats(self):
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS pages,
                   SUM(CASE WHEN lat IS NOT NULL THEN 1 ELSE 0 END) AS geo,
                   SUM(CASE WHEN image != '' THEN 1 ELSE 0 END) AS with_image,
                   SUM(CASE WHEN infobox NOT IN ('', '{}') THEN 1 ELSE 0 END) AS with_infobox,
                   (SELECT COUNT(*) FROM photos) AS photos
            FROM pages
            """
        ).fetchone()
        return dict(row)

    def in_bbox(self, south, west, north, east, limit=None):
        sql = "SELECT * FROM pages WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?"
        params = [south, north, west, east]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        return [dict(row) for row in self.conn.execute(sql, params)]

    def near(self, lat, lon, radius_km=1.0):
        """Rough radius filter on a bounding box, then exact haversine."""
        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * max(0.01, abs(math.cos(math.radians(lat)))))
        rows = self.in_bbox(lat - dlat, lon - dlon, lat + dlat, lon + dlon)
        out = []
        for row in rows:
            distance = _haversine(lat, lon, row["lat"], row["lon"])
            if distance <= radius_km:
                row["distance_km"] = round(distance, 3)
                out.append(row)
        return sorted(out, key=lambda r: r["distance_km"])

    # -- export --------------------------------------------------------

    def export_jsonl(self, path):
        with open(path, "w", encoding="utf-8") as handle:
            for record in self._records():
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def export_csv(self, path):
        records = list(self._records())
        with open(path, "w", encoding="utf-8", newline="") as handle:
            if not records:
                handle.write("pageid,title,url,lat,lon,summary,image_url\n")
                return
            writer = csv.DictWriter(handle, fieldnames=list(records[0].keys()))
            writer.writeheader()
            writer.writerows(records)

    def _records(self):
        sql = """
            SELECT p.*, ph.url AS photo_url, ph.width AS photo_width,
                   ph.height AS photo_height, ph.license AS photo_license,
                   ph.artist AS photo_artist, ph.credit AS photo_credit,
                   ph.description_url AS photo_page
            FROM pages p
            LEFT JOIN photos ph ON ph.file = 'File:' || p.image
            ORDER BY p.title
        """
        for row in self.conn.execute(sql):
            record = dict(row)
            record["infobox"] = json.loads(record.get("infobox") or "{}")
            photo = {
                k[len("photo_") :]: record.pop(k) for k in list(record) if k.startswith("photo_")
            }
            record["photo"] = photo if photo.get("url") else {}
            categories = self.conn.execute(
                "SELECT category FROM page_categories WHERE pageid = ? ORDER BY category",
                (record["pageid"],),
            ).fetchall()
            record["categories"] = [c["category"] for c in categories]
            yield record


def _haversine(lat1, lon1, lat2, lon2):
    from math import asin, cos, radians, sin, sqrt

    lon1, lat1, lon2, lat2 = map(radians, (lon1, lat1, lon2, lat2))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(h))
