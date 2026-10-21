"""Publish a redistributable open-data bundle.

"Open source for everyone" is a property of the artefact, not the repository:
someone must be able to download a directory, verify it, read the terms, and
attribute the photographers without asking us anything.

A bundle contains the payload, the photo index, the link chain, a generated
attribution file, and a Frictionless ``datapackage.json`` carrying row counts
and SHA-256 hashes for every file.
"""

from __future__ import annotations

import hashlib
import json
import os
import time

from .schema import photo_index, place_to_google
from .store import Store

BUNDLE_VERSION = "1"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _places(conn):
    for row in conn.execute("SELECT * FROM places ORDER BY name"):
        photos = conn.execute(
            "SELECT * FROM place_photos WHERE place_id = ? ORDER BY position, id", (row["id"],)
        ).fetchall()
        yield place_to_google(dict(row), [dict(p) for p in photos])


def _write_jsonl(path, records):
    count = 0
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def attribution_markdown(conn):
    """Per-photo attribution, which CC BY-SA actually requires you to ship."""
    photos = conn.execute(
        """
        SELECT ph.id, ph.name AS resource_name, ph.url, ph.description_url, ph.license,
               ph.author_name, ph.author_uri, p.name AS place_name
        FROM place_photos ph
        JOIN places p ON p.id = ph.place_id
        ORDER BY ph.license, ph.author_name, ph.id
        """
    ).fetchall()

    by_license = {}
    for photo in photos:
        by_license.setdefault(photo["license"] or "unknown", 0)
        by_license[photo["license"] or "unknown"] += 1

    lines = [
        "# Attribution",
        "",
        "Text and place descriptions: Wikipedia contributors, CC BY-SA 4.0.",
        "Photographs: the licence shown for each file, attributed below.",
        "Place identifiers: Google, used as a join key only.",
        "",
        "## Photos by licence",
        "",
        "| Licence | Files |",
        "| --- | --- |",
    ]
    for license_name, count in sorted(by_license.items(), key=lambda item: -item[1]):
        lines.append("| %s | %d |" % (license_name, count))

    lines += [
        "",
        "## Files",
        "",
        "Each line: photo resource name in the payload — Commons file — author — licence — source.",
        "",
    ]
    for photo in photos:
        author = photo["author_name"] or "unknown author"
        if photo["author_uri"]:
            author = "[%s](%s)" % (author, photo["author_uri"])
        source = photo["description_url"] or photo["url"]
        lines.append(
            "- `%s` — %s — %s — %s — %s"
            % (
                photo["resource_name"],
                photo["id"].replace("commons:", ""),
                author,
                photo["license"] or "unknown",
                source,
            )
        )
    lines.append("")
    return "\n".join(lines)


def _resource(name, path, rows, schema_fields, description):
    return {
        "name": name,
        "path": os.path.basename(path),
        "profile": "tabular-data-resource",
        "description": description,
        "format": "jsonl" if path.endswith(".jsonl") else "json",
        "mediatype": "application/x-ndjson" if path.endswith(".jsonl") else "application/json",
        "bytes": os.path.getsize(path),
        "hash": "sha256:" + sha256(path),
        "row_count": rows,
        "schema": {"fields": schema_fields},
    }


PLACE_FIELDS = [
    {"name": "id", "type": "string", "description": "Stable place id: wc:Q… or wc:<wiki>:<pageid>"},
    {"name": "displayName", "type": "object", "description": "Places API displayName shape"},
    {"name": "location", "type": "object", "description": "latitude / longitude"},
    {"name": "types", "type": "array", "description": "Google Places type vocabulary"},
    {"name": "primaryType", "type": "string"},
    {"name": "formattedAddress", "type": "string", "description": "Google-sourced, time-limited"},
    {"name": "businessStatus", "type": "string"},
    {"name": "photos", "type": "array", "description": "Resource names; URLs in photos.json"},
]


def publish(db_path, out_dir, name="wikicrawl-places", title=None, version=None):
    """Write a complete, verifiable bundle. Returns its manifest."""
    os.makedirs(out_dir, exist_ok=True)
    with Store(db_path) as store:
        conn = store.conn
        places_path = os.path.join(out_dir, "places.jsonl")
        place_count = _write_jsonl(places_path, _places(conn))

        from .schema import places_response

        envelope_path = os.path.join(out_dir, "places.json")
        with open(envelope_path, "w", encoding="utf-8") as handle:
            json.dump(places_response(_places(conn)), handle, ensure_ascii=False, indent=2)

        photos = [dict(row) for row in conn.execute("SELECT * FROM place_photos ORDER BY id")]
        photos_path = os.path.join(out_dir, "photos.json")
        with open(photos_path, "w", encoding="utf-8") as handle:
            json.dump(photo_index(photos), handle, ensure_ascii=False, indent=2)

        links = [
            dict(row)
            for row in conn.execute(
                "SELECT place_id, google_place_id, is_primary, method, confidence, verified"
                " FROM place_links ORDER BY place_id"
            )
        ]
        links_path = os.path.join(out_dir, "links.json")
        with open(links_path, "w", encoding="utf-8") as handle:
            json.dump({"links": links}, handle, ensure_ascii=False, indent=2)

        attribution_path = os.path.join(out_dir, "ATTRIBUTION.md")
        with open(attribution_path, "w", encoding="utf-8") as handle:
            handle.write(attribution_markdown(conn))

        counts = {
            "places": place_count,
            "photos": len(photos),
            "links": len(links),
            "photos_with_author": sum(1 for p in photos if p["author_name"]),
        }

    stamp = time.strftime("%Y-%m-%d", time.gmtime())
    manifest = {
        "name": name,
        "title": title or "%s — open places dataset" % name,
        "version": version or "%s-%s" % (stamp, BUNDLE_VERSION),
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "licenses": [
            {
                "name": "CC-BY-SA-4.0",
                "title": "Creative Commons Attribution-ShareAlike 4.0",
                "path": "https://creativecommons.org/licenses/by-sa/4.0/",
            },
            {
                "name": "ODC-By-1.0",
                "title": "Open Data Commons Attribution License",
                "path": "https://opendatacommons.org/licenses/by/1-0/",
            },
        ],
        "sources": [
            {"title": "Wikipedia", "path": "https://www.wikipedia.org"},
            {"title": "Wikidata", "path": "https://www.wikidata.org"},
            {"title": "Wikimedia Commons", "path": "https://commons.wikimedia.org"},
            {
                "title": "Google Places (identifiers only)",
                "path": "https://developers.google.com/maps/documentation/places",
            },
        ],
        "contributors": [{"title": "Wikimedia contributors", "role": "author"}],
        "counts": counts,
        "resources": [
            _resource(
                "places",
                places_path,
                counts["places"],
                PLACE_FIELDS,
                "One place per line, Places API (New) shape",
            ),
            _resource(
                "places_envelope",
                envelope_path,
                counts["places"],
                PLACE_FIELDS,
                "Same places wrapped as a search response",
            ),
            _resource(
                "photos",
                photos_path,
                counts["photos"],
                [
                    {"name": "name", "type": "string"},
                    {"name": "url", "type": "string"},
                    {"name": "license", "type": "string"},
                ],
                "Photo resource name -> URL, licence and author",
            ),
            _resource(
                "links",
                links_path,
                counts["links"],
                [
                    {"name": "place_id", "type": "string"},
                    {"name": "google_place_id", "type": "string"},
                    {"name": "confidence", "type": "number"},
                ],
                "Wiki place id -> Google place id",
            ),
        ],
        "attribution": "ATTRIBUTION.md",
        "notes": (
            "Photographs remain under their own licences; see ATTRIBUTION.md. "
            "Google place ids may be stored indefinitely under Google's terms; "
            "any other Google-sourced field is time-limited and must be refreshed."
        ),
    }
    manifest_path = os.path.join(out_dir, "datapackage.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    readme_path = os.path.join(out_dir, "README.md")
    with open(readme_path, "w", encoding="utf-8") as handle:
        handle.write(_bundle_readme(manifest))
    return manifest


def _bundle_readme(manifest):
    counts = manifest["counts"]
    return """# %s

%s

- **%d places**, **%d photos**, **%d Google links**
- Licence: CC BY-SA 4.0 (text), per-file for photographs — see `ATTRIBUTION.md`
- Schema: `datapackage.json` (Frictionless), with SHA-256 for every file

## Files

| File | What |
|---|---|
| `places.jsonl` | one place per line, Places API (New) shape |
| `places.json` | the same wrapped as a search response |
| `photos.json` | photo resource name -> URL, licence, author |
| `links.json` | wiki place id -> Google place id |
| `ATTRIBUTION.md` | required attribution for every photograph |
| `datapackage.json` | counts, hashes, licences, field types |

Built %s.
""" % (
        manifest["title"],
        manifest["notes"],
        counts["places"],
        counts["photos"],
        counts["links"],
        manifest["created"],
    )
