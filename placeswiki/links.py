"""Explicit links between clean Wikimedia places and Google place ids.

A nullable ``places.google_place_id`` column hides three problems: you cannot
record *why* a link exists, you cannot keep a rejected candidate, and you cannot
express two Google records for one place (a monument and its museum, say).

``place_links`` is therefore the source of truth: one row per (place, Google id)
pair, carrying method, confidence, evidence and a primary flag. The column on
``places`` is a denormalised cache of the primary link, and
:func:`check_integrity` proves the two never diverge.
"""

from __future__ import annotations

import json
import re
import time

GOOGLE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,300}$")

LINKS_DDL = """
CREATE TABLE IF NOT EXISTS place_links (
    place_id        TEXT NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    google_place_id TEXT NOT NULL,
    is_primary      INTEGER NOT NULL DEFAULT 0,
    method          TEXT NOT NULL,          -- searchText | import | manual
    confidence      REAL,
    evidence        TEXT,                   -- JSON: query, distance, source
    verified        INTEGER NOT NULL DEFAULT 0,
    created_at      REAL,
    PRIMARY KEY (place_id, google_place_id)
);
CREATE INDEX IF NOT EXISTS idx_links_google ON place_links (google_place_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_links_one_primary
    ON place_links (place_id) WHERE is_primary = 1;

CREATE VIEW IF NOT EXISTS v_places_google AS
SELECT p.id AS place_id, p.name, p.lat, p.lng,
       l.google_place_id, l.method, l.confidence, l.verified
FROM places p
JOIN place_links l ON l.place_id = p.id AND l.is_primary = 1;
"""


class LinkError(ValueError):
    """A Google place id or link row is not usable."""


def validate_google_id(value):
    """Normalise and sanity-check a Google place id.

    Place ids are opaque strings; they are not all ``ChIJ…``, so the check is
    on charset and length rather than prefix. A non-``ChIJ`` id is accepted but
    flagged by :func:`check_integrity` so a typo'd import is visible.
    """
    text = (value or "").strip().strip('"').strip("'")
    if not text:
        raise LinkError("empty google place id")
    if not GOOGLE_ID_RE.match(text):
        raise LinkError("not a plausible google place id: %r" % value)
    return text


def add_link(
    conn, place_id, google_place_id, method, confidence=None, evidence=None, make_primary=None
):
    """Insert or refresh one link. Returns True when it became the primary.

    ``make_primary=None`` promotes the link only if the place has no primary
    yet, so a better-scoring candidate can still win later via
    :func:`set_primary`.
    """
    google_place_id = validate_google_id(google_place_id)
    stamp = time.time()
    has_primary = conn.execute(
        "SELECT 1 FROM place_links WHERE place_id = ? AND is_primary = 1", (place_id,)
    ).fetchone()
    primary = (not has_primary) if make_primary is None else bool(make_primary)

    conn.execute(
        """
        INSERT INTO place_links (place_id, google_place_id, is_primary, method,
                                 confidence, evidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(place_id, google_place_id) DO UPDATE SET
            method=excluded.method,
            confidence=COALESCE(excluded.confidence, place_links.confidence),
            evidence=COALESCE(excluded.evidence, place_links.evidence)
        """,
        (
            place_id,
            google_place_id,
            1 if primary else 0,
            method,
            confidence,
            json.dumps(evidence, ensure_ascii=False) if evidence else None,
            stamp,
        ),
    )
    if primary:
        conn.execute(
            "UPDATE place_links SET is_primary = 0 WHERE place_id = ? AND google_place_id != ?",
            (place_id, google_place_id),
        )
        conn.execute(
            "UPDATE place_links SET is_primary = 1 WHERE place_id = ? AND google_place_id = ?",
            (place_id, google_place_id),
        )
        sync_cache(conn, place_id=place_id)
    return primary


def set_primary(conn, place_id, google_place_id):
    """Promote an existing link to primary (e.g. after human review)."""
    google_place_id = validate_google_id(google_place_id)
    row = conn.execute(
        "SELECT 1 FROM place_links WHERE place_id = ? AND google_place_id = ?",
        (place_id, google_place_id),
    ).fetchone()
    if not row:
        raise LinkError("no such link: %s -> %s" % (place_id, google_place_id))
    conn.execute("UPDATE place_links SET is_primary = 0 WHERE place_id = ?", (place_id,))
    conn.execute(
        "UPDATE place_links SET is_primary = 1 WHERE place_id = ? AND google_place_id = ?",
        (place_id, google_place_id),
    )
    sync_cache(conn, place_id=place_id)


def remove_link(conn, place_id, google_place_id):
    """Delete a link; if it was primary, promote the best remaining candidate."""
    google_place_id = validate_google_id(google_place_id)
    row = conn.execute(
        "SELECT is_primary FROM place_links WHERE place_id = ? AND google_place_id = ?",
        (place_id, google_place_id),
    ).fetchone()
    if not row:
        raise LinkError("no such link: %s -> %s" % (place_id, google_place_id))

    conn.execute(
        "DELETE FROM place_links WHERE place_id = ? AND google_place_id = ?",
        (place_id, google_place_id),
    )
    if row["is_primary"]:
        replacement = conn.execute(
            "SELECT google_place_id FROM place_links WHERE place_id = ?"
            " ORDER BY verified DESC, confidence DESC LIMIT 1",
            (place_id,),
        ).fetchone()
        if replacement:
            set_primary(conn, place_id, replacement["google_place_id"])
        else:
            sync_cache(conn, place_id=place_id)
    return True


def mark_verified(conn, place_id, google_place_id, verified=True):
    conn.execute(
        "UPDATE place_links SET verified = ? WHERE place_id = ? AND google_place_id = ?",
        (1 if verified else 0, place_id, google_place_id),
    )


def sync_cache(conn, place_id=None):
    """Make ``places.google_place_id`` mirror the primary link."""
    where = "WHERE p.id = ?" if place_id else ""
    params = (place_id,) if place_id else ()
    conn.execute(
        """
        UPDATE places
        SET google_place_id = (
            SELECT l.google_place_id FROM place_links l
            WHERE l.place_id = places.id AND l.is_primary = 1
        ),
        match_confidence = (
            SELECT l.confidence FROM place_links l
            WHERE l.place_id = places.id AND l.is_primary = 1
        ),
        match_method = (
            SELECT l.method FROM place_links l
            WHERE l.place_id = places.id AND l.is_primary = 1
        )
        WHERE id IN (SELECT id FROM places p %s)
        """
        % where,
        params,
    )


def import_links(conn, rows, method="import", dry_run=False):
    """Attach ids from an external file (CSV/JSON rows).

    Each row must carry a Google id and identify our place by ``place_id`` or
    ``title``. Returns ``{"added", "skipped", "errors"}``; errors never abort
    the whole import, because one bad row shouldn't hide the other 4 000.
    """
    index = {}
    for row in conn.execute("SELECT id, name FROM places"):
        index[row["id"]] = row["id"]
        if row["name"]:
            index[row["name"].lower()] = row["id"]

    summary = {"added": 0, "skipped": 0, "errors": []}
    for number, row in enumerate(rows, start=1):
        google_id = row.get("google_place_id") or row.get("google_id") or row.get("place_id_google")
        key = row.get("place_id") or row.get("wiki_place_id") or row.get("title") or row.get("name")
        if not google_id or not key:
            summary["errors"].append((number, "row needs google id and place id/title"))
            continue
        target = index.get(key) or index.get(str(key).lower())
        if not target:
            summary["errors"].append((number, "unknown place: %r" % key))
            continue
        try:
            validate_google_id(google_id)
        except LinkError as exc:
            summary["errors"].append((number, str(exc)))
            continue
        if dry_run:
            summary["added"] += 1
            continue
        already = conn.execute(
            "SELECT 1 FROM place_links WHERE place_id = ? AND google_place_id = ?",
            (target, google_id),
        ).fetchone()
        add_link(
            conn,
            target,
            google_id,
            method=method,
            confidence=float(row["confidence"]) if row.get("confidence") else None,
            evidence={"imported": True, "row": number, "source": method},
        )
        summary["skipped" if already else "added"] += 1
    if not dry_run:
        conn.commit()
    return summary


def link_report(conn):
    """Counts for the places/links/photos chain."""
    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM places) AS places,
            (SELECT COUNT(DISTINCT place_id) FROM place_links) AS places_linked,
            (SELECT COUNT(*) FROM place_links) AS links,
            (SELECT COUNT(*) FROM place_links WHERE is_primary = 1) AS primary_links,
            (SELECT COUNT(*) FROM place_links l JOIN places p ON p.id = l.place_id
                AND l.is_primary = 1 AND l.google_place_id = p.google_place_id) AS cache_in_sync,
            (SELECT COUNT(*) FROM place_photos) AS photos,
            (SELECT COUNT(*) FROM place_photos ph JOIN place_links l
                ON l.place_id = ph.place_id AND l.is_primary = 1) AS photos_linked
        """
    ).fetchone()
    return dict(row)


def check_integrity(conn):
    """Return a list of ``(severity, message)`` problems, empty when healthy."""
    problems = []

    for row in conn.execute(
        """
        SELECT p.id, p.google_place_id,
               (SELECT l.google_place_id FROM place_links l
                WHERE l.place_id = p.id AND l.is_primary = 1) AS primary_id
        FROM places p
        WHERE COALESCE(p.google_place_id, '') != COALESCE(
            (SELECT l.google_place_id FROM place_links l
             WHERE l.place_id = p.id AND l.is_primary = 1), '')
        """
    ):
        problems.append(("error", "cache diverges from primary link for %s" % row["id"]))

    for row in conn.execute(
        "SELECT place_id, COUNT(*) AS n FROM place_links WHERE is_primary = 1"
        " GROUP BY place_id HAVING n > 1"
    ):
        problems.append(("error", "%s has %d primary links" % (row["place_id"], row["n"])))

    for row in conn.execute(
        "SELECT place_id, google_place_id FROM place_links WHERE is_primary = 0"
    ):
        duplicate = conn.execute(
            "SELECT 1 FROM place_links WHERE place_id = ? AND is_primary = 1",
            (row["place_id"],),
        ).fetchone()
        if not duplicate:
            problems.append(
                (
                    "warn",
                    "%s has links but no primary (%s)" % (row["place_id"], row["google_place_id"]),
                )
            )

    for row in conn.execute("SELECT place_id, google_place_id FROM place_links"):
        try:
            validate_google_id(row["google_place_id"])
        except LinkError as exc:
            problems.append(("error", "bad id on %s: %s" % (row["place_id"], exc)))
        if not row["google_place_id"].startswith("ChIJ"):
            problems.append(("warn", "id does not start with ChIJ: %s" % row["google_place_id"]))

    orphan_photos = conn.execute(
        """
        SELECT COUNT(*) FROM place_photos ph
        LEFT JOIN places p ON p.id = ph.place_id
        WHERE p.id IS NULL
        """
    ).fetchone()[0]
    if orphan_photos:
        problems.append(("error", "%d photos reference a missing place" % orphan_photos))

    return problems


def export_links(conn, include_unlinked=True):
    """The explicit chain: wiki place -> google id -> photos."""
    linked = []
    for row in conn.execute(
        """
        SELECT p.id AS place_id, p.name, p.lat, p.lng,
               l.google_place_id, l.method, l.confidence, l.verified
        FROM places p
        JOIN place_links l ON l.place_id = p.id AND l.is_primary = 1
        ORDER BY p.name
        """
    ):
        photos = [
            dict(photo)
            for photo in conn.execute(
                "SELECT id, name, url, license, author_name, width_px, height_px"
                " FROM place_photos WHERE place_id = ? ORDER BY position, id",
                (row["place_id"],),
            )
        ]
        linked.append(
            {
                "wiki_place_id": row["place_id"],
                "google_place_id": row["google_place_id"],
                "name": row["name"],
                "location": {"latitude": row["lat"], "longitude": row["lng"]},
                "method": row["method"],
                "confidence": row["confidence"],
                "verified": bool(row["verified"]),
                "photos": photos,
                "photo_count": len(photos),
            }
        )

    payload = {"linked": linked}
    if include_unlinked:
        payload["unlinked"] = [
            dict(row)
            for row in conn.execute(
                """
                SELECT p.id AS wiki_place_id, p.name, p.lat, p.lng,
                       (SELECT COUNT(*) FROM place_photos ph WHERE ph.place_id = p.id) AS photo_count
                FROM places p
                LEFT JOIN place_links l ON l.place_id = p.id AND l.is_primary = 1
                WHERE l.place_id IS NULL
                ORDER BY p.name
                """
            )
        ]
    return payload
