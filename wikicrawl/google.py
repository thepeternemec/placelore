"""Google Places API (New) client and place matcher.

Two separate concerns, deliberately split:

* :class:`PlacesClient` talks to ``places.googleapis.com/v1`` and returns the
  response untouched.
* :func:`match_places` links a clean Wikimedia row to a Google place id, using
  name similarity plus distance, and stores **only the id** by default.

Why only the id: Google's terms let you store ``places[].id`` indefinitely, but
other Place content may not be cached beyond the allowed window. So the matcher
records ``google_place_id`` (durable) and leaves ratings, addresses and photos
alone unless you explicitly ask for them with ``store_fields=True``, which also
stamps ``google_fetched_at`` so ``v_google_stale`` can find rows to refresh.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import time
import urllib.error
import urllib.request

BASE_URL = "https://places.googleapis.com/v1"

DEFAULT_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.types",
        "places.primaryType",
        "places.businessStatus",
        "places.googleMapsUri",
        "places.photos.name",
        "places.photos.widthPx",
        "places.photos.heightPx",
        "places.photos.authorAttributions",
    ]
)

MAX_NEARBY_RESULTS = 20
MAX_RADIUS_M = 50000


class PlacesError(RuntimeError):
    """Non-success response from the Places API."""


def transport(url, body, headers, timeout=30):
    """Default HTTP transport: POST JSON, return decoded JSON."""
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _error_body(exc):
    """Best-effort error body; HTTPError without a file object has none."""
    if getattr(exc, "fp", None) is None:
        return ""
    try:
        raw = exc.read() or b""
    except Exception:  # pragma: no cover - defensive, transport dependent
        return ""
    return (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw))[:500]


class PlacesClient:
    """Minimal client for Nearby Search and Text Search (New)."""

    def __init__(
        self,
        api_key,
        send=transport,
        base_url=BASE_URL,
        field_mask=DEFAULT_FIELD_MASK,
        language="en",
    ):
        if not api_key:
            raise ValueError("a Places API key is required")
        self.api_key = api_key
        self._send = send
        self.base_url = base_url.rstrip("/")
        self.field_mask = field_mask
        self.language = language
        self.requests = []

    # -- requests ------------------------------------------------------

    def _headers(self, field_mask):
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": field_mask,
        }

    def _post(self, path, body, field_mask=None):
        mask = field_mask or self.field_mask
        url = "%s/%s" % (self.base_url, path)
        self.requests.append({"url": url, "body": body, "field_mask": mask})
        try:
            return self._send(url, body, self._headers(mask))
        except urllib.error.HTTPError as exc:
            raise PlacesError("HTTP %s: %s" % (exc.code, _error_body(exc))) from exc

    def search_nearby(
        self, lat, lon, radius_m=500, included_types=None, max_results=20, field_mask=None
    ):
        """POST places:searchNearby; returns the raw response dict."""
        if not 0 < radius_m <= MAX_RADIUS_M:
            raise ValueError("radius_m must be 1..%d" % MAX_RADIUS_M)
        if max_results > MAX_NEARBY_RESULTS:
            max_results = MAX_NEARBY_RESULTS
        body = {
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": float(radius_m),
                }
            },
            "maxResultCount": int(max_results),
            "languageCode": self.language,
        }
        if included_types:
            body["includedTypes"] = list(included_types)
        return self._post("places:searchNearby", body, field_mask)

    def search_text(
        self,
        query,
        lat=None,
        lon=None,
        radius_m=5000,
        max_results=10,
        field_mask=None,
        strict=False,
    ):
        """POST places:searchText, optionally biased to a circle."""
        body = {
            "textQuery": query,
            "pageSize": min(int(max_results), 20),
            "languageCode": self.language,
        }
        if lat is not None and lon is not None:
            body["locationBias"] = {
                "circle": {
                    "center": {"latitude": lat, "longitude": lon},
                    "radius": float(radius_m),
                }
            }
        if strict:
            body["strictTypeFiltering"] = True
        return self._post("places:searchText", body, field_mask)


# -- matching ---------------------------------------------------------

NORMALISE_RE = re.compile(r"[^a-z0-9 ]+")


def normalise_name(name):
    """Lowercase, strip punctuation and generic suffixes, collapse spaces."""
    name = (name or "").lower()
    name = NORMALISE_RE.sub(" ", name)
    for noise in ("the ", "saint ", "st ", "basilica of", "church of"):
        if name.startswith(noise):
            name = name[len(noise) :]
    return re.sub(r"\s+", " ", name).strip()


def name_similarity(left, right):
    """0..1 blend of sequence ratio and token containment."""
    a, b = normalise_name(left), normalise_name(right)
    if not a or not b:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()), set(b.split())
    containment = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return round(0.6 * ratio + 0.4 * containment, 4)


def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres."""
    lon1, lat1, lon2, lat2 = map(math.radians, (lon1, lat1, lon2, lat2))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def score_pair(our_name, our_lat, our_lng, candidate, max_distance_m=1000.0):
    """Score one candidate against our place; 0 when too far away."""
    display = (candidate.get("displayName") or {}).get("text", "")
    location = candidate.get("location") or {}
    lat, lon = location.get("latitude"), location.get("longitude")
    if lat is None or lon is None:
        return 0.0
    distance = distance_m(our_lat, our_lng, lat, lon)
    if distance > max_distance_m:
        return 0.0
    name_score = name_similarity(our_name, display)
    proximity = 1.0 - (distance / max_distance_m)
    return round(0.7 * name_score + 0.3 * proximity, 4)


def best_candidate(our_name, our_lat, our_lng, response, max_distance_m=1000.0):
    """Return ``(candidate, score)`` for the highest scoring Google place."""
    best, best_score = None, 0.0
    for candidate in (response or {}).get("places", []):
        score = score_pair(our_name, our_lat, our_lng, candidate, max_distance_m)
        if score > best_score:
            best, best_score = candidate, score
    return best, best_score


def match_places(
    conn,
    client,
    limit=None,
    threshold=0.55,
    radius_m=500,
    store_fields=False,
    dry_run=False,
    log=print,
):
    """Link clean places to Google place ids.

    Returns ``{"matched", "rejected", "requests"}``. With ``dry_run`` nothing is
    written and the request bodies are returned for inspection.
    """
    sql = "SELECT id, name, lat, lng FROM places WHERE google_place_id IS NULL"
    if limit:
        sql += " LIMIT %d" % int(limit)
    rows = conn.execute(sql).fetchall()

    summary = {"matched": 0, "rejected": 0, "requests": 0}
    stamp = time.time()

    for row in rows:
        place_id, name, lat, lng = row[0], row[1], row[2], row[3]
        if dry_run:
            summary["requests"] += 1
            log("would search: %r at %s,%s (r=%sm)" % (name, lat, lng, radius_m))
            continue

        response = client.search_text(name, lat=lat, lon=lng, radius_m=radius_m)
        summary["requests"] += 1
        candidate, score = best_candidate(name, lat, lng, response)

        if candidate is None or score < threshold:
            summary["rejected"] += 1
            conn.execute(
                "INSERT OR REPLACE INTO google_matches (place_id, google_place_id, score, method, query, matched_at)"
                " VALUES (?, NULL, ?, 'searchText', ?, ?)",
                (place_id, score, name, stamp),
            )
            continue

        google_id = candidate.get("id")
        conn.execute(
            """
            UPDATE places SET google_place_id=?, match_confidence=?, match_method=?,
                              google_fetched_at=?
            WHERE id=?
            """,
            (google_id, score, "searchText", stamp, place_id),
        )
        if store_fields:
            _store_google_fields(conn, place_id, candidate)
        conn.execute(
            "INSERT OR REPLACE INTO google_matches (place_id, google_place_id, score, method, query, matched_at)"
            " VALUES (?, ?, ?, 'searchText', ?, ?)",
            (place_id, google_id, score, name, stamp),
        )
        summary["matched"] += 1

    if not dry_run:
        conn.commit()
    return summary


def _store_google_fields(conn, place_id, candidate):
    """Write Google-sourced fields and stamp the refresh clock.

    Only call this when you accept the caching obligation: ``v_google_stale``
    surfaces rows whose Google content is older than the refresh window.
    """
    conn.execute(
        """
        UPDATE places SET formatted_address=?, short_formatted_address=?,
                          website_uri=COALESCE(?, website_uri),
                          google_maps_uri=?, primary_type=COALESCE(?, primary_type),
                          business_status=COALESCE(?, business_status)
        WHERE id=?
        """,
        (
            candidate.get("formattedAddress"),
            candidate.get("shortFormattedAddress"),
            candidate.get("websiteUri"),
            candidate.get("googleMapsUri"),
            candidate.get("primaryType"),
            candidate.get("businessStatus"),
            place_id,
        ),
    )
    # The Google coordinate is intentionally not written over ours: this
    # database's geometry comes from Wikimedia, and silently mixing the two
    # would make distances unauditable.
