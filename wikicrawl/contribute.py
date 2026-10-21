"""Turn database gaps into actionable upstream work.

This project reads Wikimedia and writes nothing back. That is deliberate — no
bot edits, no API writes, no surprise changes to someone else's encyclopaedia.

What it can do is say precisely what is missing and where to fix it, so a human
editor can add the photograph on Commons, the `P18` on Wikidata, or the
attribution line on a file page. :func:`collect_gaps` produces that list;
:func:`render_markdown` makes it readable enough to paste into a WikiProject.
"""

from __future__ import annotations

import json

WIKIDATA = "https://www.wikidata.org/wiki/"
COMMONS = "https://commons.wikimedia.org/wiki/"

SECTIONS = (
    (
        "no_photo",
        "Missing a photograph",
        "Add a `P18` image on Wikidata, or upload one to Commons and link it.",
    ),
    (
        "no_category",
        "Missing a Commons category",
        "Add `P373` so future crawls can find the curated photo set.",
    ),
    (
        "no_article",
        "No English Wikipedia article",
        "Create the article, or add the item to Wikidata's `P31`/`P1435` if it exists under another name.",
    ),
    (
        "no_designation",
        "No heritage designation recorded",
        "Add `P1435` with the national register item, if one exists.",
    ),
    (
        "no_coords",
        "No coordinates",
        "Add `P625`; without it the place cannot be crawled or matched.",
    ),
    (
        "photo_no_author",
        "Photograph missing attribution",
        "Fix the author field on the Commons file page — the licence usually requires it.",
    ),
    (
        "photo_no_licence",
        "Photograph missing a licence",
        "Check the Commons file page: an unlicensed file cannot be redistributed.",
    ),
)


def _qid(place_id):
    if place_id.startswith("wc:Q"):
        return place_id[3:]
    return ""


def _place_row(row, reason):
    qid = _qid(row["id"])
    return {
        "place_id": row["id"],
        "name": row["name"],
        "reason": reason,
        "wikidata": WIKIDATA + qid if qid else "",
        "photos": row["photo_count"],
    }


def collect_gaps(conn, limit=100):
    """Return ``{section: {"title", "hint", "count", "items"}}``.

    ``count`` is the true number of rows; ``items`` is capped at ``limit`` so the
    report stays usable when the database holds two million places.
    """
    queries = {
        "no_photo": (
            """SELECT p.id, p.name, 0 AS photo_count FROM places p
               LEFT JOIN place_photos ph ON ph.place_id = p.id
               WHERE ph.place_id IS NULL ORDER BY p.name"""
        ),
        "no_category": (
            """SELECT p.id, p.name, 0 AS photo_count FROM places p
               WHERE p.commons_category IS NULL OR p.commons_category = ''
               ORDER BY p.name"""
        ),
        "no_article": (
            """SELECT p.id, p.name, 0 AS photo_count FROM places p
               WHERE p.wikipedia_url IS NULL OR p.wikipedia_url = '' ORDER BY p.name"""
        ),
        "no_designation": (
            """SELECT p.id, p.name, 0 AS photo_count FROM places p
               WHERE p.heritage_designations IS NULL
                  OR p.heritage_designations IN ('', '[]') ORDER BY p.name"""
        ),
        "no_coords": (
            """SELECT p.id, p.name, 0 AS photo_count FROM places p
               WHERE p.lat IS NULL OR p.lng IS NULL ORDER BY p.name"""
        ),
        "photo_no_author": (
            """SELECT p.id, p.name, 0 AS photo_count FROM places p
               JOIN place_photos ph ON ph.place_id = p.id
               WHERE ph.author_name IS NULL OR ph.author_name = '' ORDER BY p.name"""
        ),
        "photo_no_licence": (
            """SELECT p.id, p.name, 0 AS photo_count FROM places p
               JOIN place_photos ph ON ph.place_id = p.id
               WHERE ph.license IS NULL OR ph.license = '' ORDER BY p.name"""
        ),
    }

    gaps = {}
    for key, title, hint in SECTIONS:
        rows = [dict(r) for r in conn.execute(queries[key])]
        gaps[key] = {
            "title": title,
            "hint": hint,
            "count": len(rows),
            "items": [_place_row(row, key) for row in rows[:limit]],
        }
    return gaps


def render_markdown(gaps, source="database", generated=None):
    total = sum(gaps[key]["count"] for key in gaps if key != "photo_no_author")
    lines = [
        "# Upstream gaps",
        "",
        "What is missing from **%s**, and where to fix it. Nothing here is a bug "
        "in the crawler: these are gaps in Wikidata, Wikipedia or Commons, and "
        "they are fixed by editing upstream." % source,
        "",
        "See [CONTRIBUTING-TO-WIKIMEDIA.md](CONTRIBUTING-TO-WIKIMEDIA.md) for how "
        "to make each edit. Your fix reaches every future crawl.",
    ]
    if generated:
        lines += ["", "_Generated %s._" % generated]

    lines += ["", "| Gap | Count |", "| --- | --- |"]
    for section in gaps.values():
        lines.append("| %s | %d |" % (section["title"], section["count"]))
    lines += ["", "Sections below are capped; counts above are complete.", ""]

    for section in gaps.values():
        if not section["count"]:
            continue
        lines += ["## %s (%d)" % (section["title"], section["count"]), "", section["hint"], ""]
        lines += ["| Place | Wikidata |", "| --- | --- |"]
        for item in section["items"]:
            name = item["name"] or item["place_id"]
            link = (
                "[%s](%s)" % (item["place_id"], item["wikidata"])
                if item["wikidata"]
                else item["place_id"]
            )
            lines.append("| %s | %s |" % (name.replace("|", "/"), link))
        hidden = section["count"] - len(section["items"])
        if hidden > 0:
            lines.append("| _… %d more_ | |" % hidden)
        lines.append("")

    lines += [
        "---",
        "",
        "Total places examined: %d gaps across %d sections."
        % (total, sum(1 for s in gaps.values() if s["count"])),
        "",
        "This project writes nothing to Wikimedia. Every fix is a human edit, "
        "made under the account of the person who makes it.",
    ]
    return "\n".join(lines)


def render_json(gaps):
    return json.dumps(
        {
            key: {"title": value["title"], "count": value["count"], "items": value["items"]}
            for key, value in gaps.items()
        },
        indent=2,
        ensure_ascii=False,
    )
