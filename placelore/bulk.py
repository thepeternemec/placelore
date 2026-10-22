"""Bulk pipeline: stage a worldwide place list, then enrich it into ``places``.

Two phases, deliberately separated:

``stage``
    SPARQL only. Writes one row per Wikidata item to ``wd_places``. No
    per-place API calls, so 2.2 M rows cost ~2.2 M/500 requests (4 420), not
    2.2 M. Resumable per country.

``enrich``
    Resolves each staged row's Commons image (``P18``) in batches of 50 and
    writes clean ``places`` rows with id ``wc:Q…``. Skips anything already
    enriched, so it can be stopped and restarted at any point.

The point of the split is that the expensive, failure-prone network work
happens once per place down a path that can be interrupted.
"""

from __future__ import annotations

import json
import time

from .images import fetch_imageinfo
from .schema import infer_types, slugify
from .wikidata import heritage_query, parse_row

WD_DDL = """
CREATE TABLE IF NOT EXISTS wd_places (
    qid              TEXT PRIMARY KEY,
    label            TEXT,
    lat              REAL,
    lon              REAL,
    enwiki_title     TEXT,
    image_file       TEXT,
    commons_category TEXT,
    heritage         TEXT,
    country          TEXT,
    status           TEXT NOT NULL DEFAULT 'pending',
    place_id         TEXT,
    error            TEXT,
    fetched_at       REAL
);
CREATE INDEX IF NOT EXISTS idx_wd_status ON wd_places (status);
CREATE INDEX IF NOT EXISTS idx_wd_country ON wd_places (country);
"""

BATCH = 500


def ensure_wd_schema(conn):
    conn.executescript(WD_DDL)


def stage(conn, client, country=None, page_size=BATCH, limit=None, log=None):
    """Fetch one page (or all pages) of the heritage list into ``wd_places``.

    Rows are merged by QID: an item with three heritage designations arrives as
    three SPARQL solutions, and we want one staging row. ``ORDER BY ?item``
    keeps those solutions adjacent, so merging inside a page covers almost
    everything; the remainder is merged on conflict.

    Returns ``{"rows", "requests", "done"}``.
    """
    ensure_wd_schema(conn)
    rows_total = 0
    requests = 0
    offset = 0
    stamp = time.time()

    while True:
        size = page_size if limit is None else min(page_size, limit - rows_total)
        if size <= 0:
            break
        payload = client.query(heritage_query(limit=size, offset=offset, country=country))
        requests += 1
        if not payload:
            break

        merged = {}
        for raw in payload:
            record = parse_row(raw)
            if not record["qid"] or record["lat"] is None or record["lon"] is None:
                continue
            current = merged.setdefault(record["qid"], dict(record, heritage=[]))
            if record["heritage"]:
                current["heritage"].append(record["heritage"])
            for field in ("label", "image_file", "commons_category", "enwiki_title", "country"):
                if not current.get(field) and record.get(field):
                    current[field] = record[field]

        for record in merged.values():
            existing = conn.execute(
                "SELECT heritage FROM wd_places WHERE qid = ?", (record["qid"],)
            ).fetchone()
            heritage = set(json.loads(existing[0])) if existing and existing[0] else set()
            heritage.update(record["heritage"])
            conn.execute(
                """
                INSERT INTO wd_places (qid, label, lat, lon, enwiki_title, image_file,
                                       commons_category, heritage, country, status,
                                       fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                ON CONFLICT(qid) DO UPDATE SET
                    label=excluded.label, lat=excluded.lat, lon=excluded.lon,
                    enwiki_title=COALESCE(excluded.enwiki_title, wd_places.enwiki_title),
                    image_file=COALESCE(excluded.image_file, wd_places.image_file),
                    commons_category=COALESCE(excluded.commons_category, wd_places.commons_category),
                    heritage=excluded.heritage, country=excluded.country
                """,
                (
                    record["qid"],
                    record["label"],
                    record["lat"],
                    record["lon"],
                    record["enwiki_title"],
                    record["image_file"],
                    record["commons_category"],
                    json.dumps(sorted(heritage)),
                    record["country"],
                    stamp,
                ),
            )
            rows_total += 1
        conn.commit()
        offset += len(payload)
        if log:
            log("staged %d items (offset %d)" % (rows_total, offset))
        if len(payload) < size:
            break
    return {"rows": rows_total, "requests": requests, "done": True}


def stage_countries(conn, client, page_size=BATCH, limit=None, log=None):
    """Stage every country, largest first. Resumable: countries already staged
    are skipped by qid de-duplication, not by bookkeeping."""
    from .wikidata import countries_query

    total = {"rows": 0, "requests": 0, "countries": 0}
    for row in client.query(countries_query()):
        country = (row.get("country") or "").rsplit("/", 1)[-1]
        if not country:
            continue
        result = stage(conn, client, country=country, page_size=page_size, limit=limit, log=log)
        total["rows"] += result["rows"]
        total["requests"] += result["requests"]
        total["countries"] += 1
        if log:
            log("country %s: +%d rows" % (country, result["rows"]))
        if limit and total["rows"] >= limit:
            break
    return total


def pending(conn, limit=None):
    sql = "SELECT * FROM wd_places WHERE status = 'pending' ORDER BY qid"
    if limit:
        sql += " LIMIT %d" % int(limit)
    return conn.execute(sql).fetchall()


def enrich(conn, commons, limit=None, log=None):
    """Turn staged rows into clean ``places`` (+ photos) and mark them done.

    Only ``P18`` images are resolved, because they are already in the SPARQL
    result — using Commons categories would cost one request per place instead
    of one per fifty.
    """
    rows = pending(conn, limit)
    if not rows:
        return {"places": 0, "photos": 0, "requests": 0}

    files = [row["image_file"] for row in rows if row["image_file"]]
    images = {}
    if files:
        for record in fetch_imageinfo(commons, files):
            images[record["file"]] = record

    stamp = time.time()
    created = photos = 0
    for row in rows:
        place_id = "wc:" + row["qid"]
        types = infer_types(
            {
                "title": row["label"] or row["enwiki_title"],
                "categories": [row["commons_category"]] if row["commons_category"] else [],
                "infobox": {},
            }
        )
        heritage = json.loads(row["heritage"] or "[]")
        conn.execute(
            """
            INSERT INTO places (id, name, language_code, lat, lng, types, primary_type,
                                wikidata_id, wikipedia_url, commons_category,
                                heritage_designations, source, created_at, updated_at)
            VALUES (?, ?, 'en', ?, ?, ?, ?, ?, ?, ?, ?, 'wikidata', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name, lat=excluded.lat, lng=excluded.lng,
                types=excluded.types, primary_type=excluded.primary_type,
                commons_category=excluded.commons_category,
                heritage_designations=excluded.heritage_designations,
                updated_at=excluded.updated_at
            """,
            (
                place_id,
                row["label"] or row["enwiki_title"] or row["qid"],
                row["lat"],
                row["lon"],
                json.dumps(types),
                types[0] if types else None,
                row["qid"],
                ("https://en.wikipedia.org/wiki/" + row["enwiki_title"].replace(" ", "_"))
                if row["enwiki_title"]
                else None,
                row["commons_category"] or None,
                json.dumps(heritage),
                stamp,
                stamp,
            ),
        )
        created += 1

        image = images.get(row["image_file"])
        if image:
            photo_id = "commons:" + row["image_file"][5:]
            conn.execute(
                """
                INSERT INTO place_photos (id, place_id, name, url, description_url,
                                          width_px, height_px, author_name, author_uri,
                                          license, position, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(place_id, id) DO UPDATE SET
                    url=excluded.url, license=excluded.license,
                    author_name=excluded.author_name
                """,
                (
                    photo_id,
                    place_id,
                    "places/%s/photos/%s" % (place_id, slugify(photo_id)),
                    image["url"],
                    image.get("description_url"),
                    image.get("width"),
                    image.get("height"),
                    image.get("artist"),
                    None,
                    image.get("license"),
                    stamp,
                ),
            )
            photos += 1

        conn.execute(
            "UPDATE wd_places SET status='enriched', place_id=?, error=NULL WHERE qid=?",
            (place_id, row["qid"]),
        )

    conn.commit()
    if log:
        log("enriched %d places, %d photos" % (created, photos))
    return {"places": created, "photos": photos, "requests": 0}


def status(conn):
    """Counts per staging status, plus what has made it into ``places``."""
    ensure_wd_schema(conn)
    counts = {}
    for row in conn.execute("SELECT status, COUNT(*) FROM wd_places GROUP BY status"):
        counts[row[0]] = row[1]
    return {
        "staged": sum(counts.values()),
        "pending": counts.get("pending", 0),
        "enriched": counts.get("enriched", 0),
        "failed": counts.get("failed", 0),
        "places": conn.execute("SELECT COUNT(*) FROM places").fetchone()[0],
        "photos": conn.execute("SELECT COUNT(*) FROM place_photos").fetchone()[0],
    }
