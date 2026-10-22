"""A drop-in Nearby Search server over a local database.

The idea is that an application already written against
``places.googleapis.com/v1`` changes one constant — the base URL — and keeps
working: same paths, same request bodies, same ``X-Goog-FieldMask`` header, same
response envelope. What it hits is a SQLite file instead of a metered API.

Deliberate differences, all documented in ``docs/API.md``:

* ``place_id`` values are ours (``wc:…``) unless ``--prefer-google-ids`` is set
  and a Google id has been linked, in which case the Google id is returned.
* No pagination tokens; results are nearest-first and capped at
  ``maxResultCount`` (20, as Google's Nearby Search caps).
* No price levels, opening hours, reviews or ratings unless they were imported.

Run it:

    python3 -m placeswiki serve --db world.sqlite --port 8080
    curl -s localhost:8080/v1/places:searchNearby -d '{"locationRestriction": ...}'
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

MAX_RESULTS = 20
EARTH_RADIUS_M = 6371000.0

# Fields Google returns by default when no field mask is supplied.
DEFAULT_FIELDS = (
    "id",
    "displayName",
    "formattedAddress",
    "location",
    "types",
    "primaryType",
    "businessStatus",
    "photos",
)


def haversine_m(lat1, lon1, lat2, lon2):
    lon1, lat1, lon2, lat2 = map(math.radians, (lon1, lat1, lon2, lat2))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


class BadRequest(ValueError):
    """Maps to a 400 INVALID_ARGUMENT, as the real API does."""

    status = "INVALID_ARGUMENT"


class NotFound(LookupError):
    """Maps to a 404 NOT_FOUND."""

    status = "NOT_FOUND"


def parse_field_mask(header):
    """``places.id,places.photos.name`` -> ``{"id": set(), "photos": {"name"}}``.

    An empty set means "the whole field"; Google's mask syntax is dotted, and
    ``*`` means everything.
    """
    if not header or not header.strip():
        return None
    mask = {}
    for path in header.split(","):
        parts = [part.strip() for part in path.split(".") if part.strip()]
        if not parts:
            continue
        if parts[0] == "*":
            return None
        if parts[0] == "places":
            parts = parts[1:]
        if not parts or parts == ["*"]:
            return None
        node = mask
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if node == set():  # already fully included
                break
        else:
            if parts[-1] == "*":
                node.clear()
            else:
                node.setdefault(parts[-1], set())
    return mask


def apply_mask(place, mask):
    """Project a place onto a parsed field mask."""
    if mask is None:
        return place
    out = {}
    for key, sub in mask.items():
        if key not in place:
            continue
        if not sub:
            out[key] = place[key]
        elif isinstance(place[key], list):
            out[key] = [apply_mask(item, sub) for item in place[key]]
        elif isinstance(place[key], dict):
            out[key] = apply_mask(place[key], sub)
    return out


class PlaceIndex:
    """Read-only queries over a slim database."""

    def __init__(self, db_path, prefer_google_ids=False):
        self.conn = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.prefer_google_ids = prefer_google_ids

    def close(self):
        self.conn.close()

    # -- rows -> Places API payload ----------------------------------

    def _place(self, row, photos):
        place_id = row["id"]
        if self.prefer_google_ids and row["google_place_id"]:
            place_id = row["google_place_id"]
        place = {
            "id": place_id,
            "displayName": {"text": row["name"], "languageCode": row["language_code"] or "en"},
            "location": {"latitude": row["lat"], "longitude": row["lng"]},
            "types": json.loads(row["types"] or "[]"),
        }
        if row["primary_type"]:
            place["primaryType"] = row["primary_type"]
        if row["business_status"]:
            place["businessStatus"] = row["business_status"]
        if row["formatted_address"]:
            place["formattedAddress"] = row["formatted_address"]
        if row["short_formatted_address"]:
            place["shortFormattedAddress"] = row["short_formatted_address"]
        if row["adr_format_address"]:
            place["adrFormatAddress"] = row["adr_format_address"]
        if row["website_uri"]:
            place["websiteUri"] = row["website_uri"]
        if row["google_maps_uri"]:
            place["googleMapsUri"] = row["google_maps_uri"]
        if row["rating"] is not None:
            place["rating"] = row["rating"]
        if row["user_rating_count"] is not None:
            place["userRatingCount"] = row["user_rating_count"]

        if photos:
            place["photos"] = [
                {
                    "name": photo["name"],
                    "widthPx": photo["width_px"],
                    "heightPx": photo["height_px"],
                    **(
                        {
                            "authorAttributions": [
                                {"displayName": photo["author_name"], "uri": photo["author_uri"]}
                            ]
                        }
                        if photo["author_name"]
                        else {}
                    ),
                }
                for photo in photos
            ]
        return place

    def _photos(self, place_id):
        return self.conn.execute(
            "SELECT * FROM place_photos WHERE place_id = ? ORDER BY position, id LIMIT 10",
            (place_id,),
        ).fetchall()

    def _rows_in_box(self, lat, lon, radius_m):
        dlat = radius_m / 111320.0
        dlon = radius_m / (111320.0 * max(0.01, abs(math.cos(math.radians(lat)))))
        return self.conn.execute(
            "SELECT * FROM places WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
            (lat - dlat, lat + dlat, lon - dlon, lon + dlon),
        ).fetchall()

    # -- endpoints ---------------------------------------------------

    def nearby(self, lat, lon, radius_m, included_types=None, limit=MAX_RESULTS):
        if not (0 < radius_m <= 50000):
            raise BadRequest("locationRestriction.circle.radius must be 1..50000")
        limit = max(1, min(int(limit or MAX_RESULTS), MAX_RESULTS))

        scored = []
        for row in self._rows_in_box(lat, lon, radius_m):
            distance = haversine_m(lat, lon, row["lat"], row["lng"])
            if distance > radius_m:
                continue
            if included_types:
                types = json.loads(row["types"] or "[]")
                if row["primary_type"]:
                    types.append(row["primary_type"])
                if not set(included_types) & set(types):
                    continue
            scored.append((distance, row))

        scored.sort(key=lambda pair: pair[0])
        return [self._place(row, self._photos(row["id"])) for _distance, row in scored[:limit]]

    def text_search(self, query, lat=None, lon=None, limit=MAX_RESULTS):
        if not query or not query.strip():
            raise BadRequest("textQuery must not be empty")
        limit = max(1, min(int(limit or MAX_RESULTS), MAX_RESULTS))
        pattern = "%" + query.strip().replace("%", "").replace("_", " ") + "%"
        rows = self.conn.execute(
            "SELECT * FROM places WHERE name LIKE ? COLLATE NOCASE LIMIT 200", (pattern,)
        ).fetchall()
        if lat is not None and lon is not None:
            rows = sorted(rows, key=lambda row: haversine_m(lat, lon, row["lat"], row["lng"]))
        return [self._place(row, self._photos(row["id"])) for row in rows[:limit]]

    def get(self, place_id):
        row = self.conn.execute(
            "SELECT * FROM places WHERE id = ? OR google_place_id = ?", (place_id, place_id)
        ).fetchone()
        if not row:
            raise NotFound("no place with id %s" % place_id)
        return self._place(row, self._photos(row["id"]))

    def stats(self):
        places = self.conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
        photos = self.conn.execute("SELECT COUNT(*) FROM place_photos").fetchone()[0]
        linked = self.conn.execute(
            "SELECT COUNT(*) FROM places WHERE google_place_id IS NOT NULL"
        ).fetchone()[0]
        return {"places": places, "photos": photos, "google_linked": linked}


ROUTE_NEARBY = re.compile(r"^/v1/places:searchNearby$")
ROUTE_TEXT = re.compile(r"^/v1/places:searchText$")
ROUTE_GET = re.compile(r"^/v1/places/([^/]+)$")


def make_handler(index):
    class Handler(BaseHTTPRequestHandler):
        server_version = "placeswiki/2.0"

        def log_message(self, fmt, *args):  # quieter default logging
            pass

        def _send(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status, message, kind="INVALID_ARGUMENT"):
            self._send(status, {"error": {"code": status, "status": kind, "message": message}})

        def _body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                raise BadRequest("invalid JSON body: %s" % exc) from exc

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/health", "/healthz"):
                return self._send(200, {"status": "ok", **index.stats()})
            if path == "/v1/meta":
                return self._send(
                    200, {"dataset": index.stats(), "protocol": "places.googleapis.com/v1"}
                )
            match = ROUTE_GET.match(path)
            if match:
                mask = parse_field_mask(self.headers.get("X-Goog-FieldMask"))
                try:
                    place = index.get(match.group(1))
                except NotFound as exc:
                    return self._error(404, str(exc), "NOT_FOUND")
                return self._send(200, apply_mask(place, mask))
            return self._error(404, "unknown path %s" % path, "NOT_FOUND")

        def do_POST(self):
            path = urlparse(self.path).path
            mask = parse_field_mask(self.headers.get("X-Goog-FieldMask"))
            try:
                body = self._body()
                if ROUTE_NEARBY.match(path):
                    circle = (body.get("locationRestriction") or {}).get("circle") or {}
                    center = circle.get("center") or {}
                    if "latitude" not in center or "longitude" not in center:
                        raise BadRequest("locationRestriction.circle.center is required")
                    places = index.nearby(
                        float(center["latitude"]),
                        float(center["longitude"]),
                        float(circle.get("radius", 500)),
                        body.get("includedTypes") or body.get("includedPrimaryTypes") or None,
                        body.get("maxResultCount", MAX_RESULTS),
                    )
                elif ROUTE_TEXT.match(path):
                    bias = ((body.get("locationBias") or {}).get("circle") or {}).get(
                        "center"
                    ) or {}
                    places = index.text_search(
                        body.get("textQuery", ""),
                        bias.get("latitude"),
                        bias.get("longitude"),
                        body.get("pageSize", MAX_RESULTS),
                    )
                else:
                    return self._error(404, "unknown path %s" % path, "NOT_FOUND")
            except BadRequest as exc:
                return self._error(400, str(exc))
            except (TypeError, ValueError) as exc:
                return self._error(400, "invalid request: %s" % exc)
            return self._send(200, {"places": [apply_mask(place, mask) for place in places]})

    return Handler


def make_server(db_path, host="127.0.0.1", port=8080, prefer_google_ids=False):
    index = PlaceIndex(db_path, prefer_google_ids=prefer_google_ids)
    server = ThreadingHTTPServer((host, port), make_handler(index))
    server.index = index
    return server
