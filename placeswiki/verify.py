"""Verify an export against Google's own protobuf definitions.

Shape claims are cheap. This module makes the claim checkable: it parses the
payload with ``google.maps.places_v1`` — the same generated messages Google's
Python client uses — and reports anything the real parser rejects.

The dependency is optional so the crawler still runs on the standard library:

    pip install google-maps-places
"""

from __future__ import annotations

import json


class MissingDependency(RuntimeError):
    """google-maps-places is not installed."""


def _google():
    try:
        from google.maps import places_v1
        from google.protobuf import json_format
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise MissingDependency(
            "install google-maps-places to verify: python -m pip install google-maps-places"
        ) from exc
    return places_v1, json_format


def _new(cls):
    """Build an empty protobuf message.

    proto-plus returns the generated *class* from ``.pb()``; older/newer
    variants may return an instance. Accept both, because parsing into the
    class itself is the mistake that makes every field look unparseable.
    """
    proto = cls.pb()
    return proto() if isinstance(proto, type) else proto


def verify_payload(payload, photo_index=None):
    """Parse ``{"places": [...]}`` with Google's messages.

    Returns ``{"places", "parsed", "problems"}``. Empty ``problems`` means the
    payload is structurally a valid Places API (New) response.
    """
    places_v1, json_format = _google()

    if not isinstance(payload, dict) or "places" not in payload:
        return {
            "places": 0,
            "parsed": 0,
            "problems": [("payload", "expected an object with a 'places' array")],
        }

    problems = []
    parsed = 0
    for place in payload["places"]:
        try:
            json_format.ParseDict(place, _new(places_v1.Place))
            parsed += 1
        except Exception as exc:  # ParseError, AttributeError, TypeError
            problems.append((place.get("id", "?"), type(exc).__name__ + ": " + str(exc)[:200]))

    # The envelope must work for both search responses; they share a shape but
    # are distinct messages, and a client may parse either.
    for cls in (places_v1.SearchTextResponse, places_v1.SearchNearbyResponse):
        try:
            json_format.ParseDict(payload, _new(cls))
        except Exception as exc:
            problems.append((cls.__name__, type(exc).__name__ + ": " + str(exc)[:200]))

    if photo_index is not None:
        names = {photo["name"] for place in payload["places"] for photo in place.get("photos", [])}
        unresolved = sorted(names - set(photo_index))
        for name in unresolved:
            problems.append((name, "photo reference missing from index"))

    return {
        "places": len(payload["places"]),
        "parsed": parsed,
        "problems": problems,
    }


def verify_files(payload_path, photo_index_path=None):
    with open(payload_path, encoding="utf-8") as handle:
        payload = json.load(handle)
    index = None
    if photo_index_path:
        with open(photo_index_path, encoding="utf-8") as handle:
            index = json.load(handle)
    return verify_payload(payload, index)


def format_report(result):
    lines = [
        "parsed %(parsed)d/%(places)d places with google.maps.places_v1" % result,
        "envelope: SearchTextResponse + SearchNearbyResponse"
        if not result["problems"]
        else "envelope: FAILED",
    ]
    for where, detail in result["problems"]:
        lines.append("  problem %s: %s" % (where, detail))
    lines.append("OK" if not result["problems"] else "FAILED")
    return "\n".join(lines)
