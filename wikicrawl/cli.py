"""Command line interface.

wikicrawl collect --category "Category:Colosseum" --depth 1 --db rome.sqlite
wikicrawl collect --lat 41.8902 --lon 12.4922 --radius 400 --db rome.sqlite
wikicrawl export --db rome.sqlite --out rome.jsonl
wikicrawl near --db rome.sqlite --lat 41.89 --lon 12.49 --radius-km 1
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import sys

from . import __version__
from .api import DEFAULT_UA, MediaWiki
from .bulk import enrich as bulk_enrich
from .bulk import stage as bulk_stage
from .bulk import stage_countries as bulk_stage_countries
from .bulk import status as bulk_status
from .contribute import collect_gaps, render_json, render_markdown
from .crawl import crawl_category, crawl_links, geosearch
from .google import PlacesClient, match_places
from .images import COMMONS_API, fetch_imageinfo
from .links import (
    check_integrity,
    export_links,
    import_links,
    link_report,
    remove_link,
    set_primary,
    validate_google_id,
)
from .normalize import normalize
from .pages import fetch_pages
from .publish import publish as publish_bundle
from .schema import (
    ensure_schema,
    photo_index,
    place_to_google,
    places_response,
    rebuild_schema,
)
from .store import Store
from .verify import MissingDependency, format_report, verify_files
from .wikidata import SparqlClient


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="wikicrawl",
        description="Polite crawler for Wikipedia articles, coordinates and lead images.",
    )
    parser.add_argument("--version", action="version", version="wikicrawl " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default="crawl.sqlite", help="SQLite file (created if absent)")
    common.add_argument("--api-url", default="https://en.wikipedia.org/w/api.php")
    common.add_argument(
        "--user-agent",
        default=DEFAULT_UA,
        help="identify yourself; Wikimedia policy requires a contact",
    )
    common.add_argument(
        "--min-interval",
        type=float,
        default=0.2,
        help="minimum seconds between requests (default 0.2)",
    )
    common.add_argument("--quiet", action="store_true")

    collect = sub.add_parser(
        "collect", parents=[common], help="walk a category tree, a link graph, or a geo grid"
    )
    collect.add_argument(
        "--category", action="append", default=[], help="root category, repeatable"
    )
    collect.add_argument(
        "--depth", type=int, default=1, help="subcategory hops for --category, link hops for --seed"
    )
    collect.add_argument(
        "--seed", action="append", default=[], help="seed article for link crawling, repeatable"
    )
    collect.add_argument("--lat", type=float)
    collect.add_argument("--lon", type=float)
    collect.add_argument("--radius", type=float, default=500, help="metres, max 10000")
    collect.add_argument(
        "--cell",
        type=float,
        default=100,
        help="grid cell in metres; keep results under the 500 cap",
    )
    collect.add_argument("--limit", type=int, default=500, help="stop after N pages")
    collect.add_argument(
        "--no-wikitext", action="store_true", help="skip revisions (much smaller responses)"
    )
    collect.add_argument("--force", action="store_true", help="re-fetch visited pages")

    export = sub.add_parser("export", parents=[common], help="write pages to a file")
    export.add_argument("--out", default="pages.jsonl")
    export.add_argument(
        "--linked-only",
        action="store_false",
        dest="include_unlinked",
        default=True,
        help="for --format links: omit places with no google id",
    )
    export.add_argument(
        "--verify",
        action="store_true",
        help="parse the result with Google's protobuf messages (needs google-maps-places)",
    )
    export.add_argument(
        "--format",
        choices=("jsonl", "csv", "google", "photo-index", "links"),
        default="jsonl",
        help="google = strict Places API (New) payload",
    )

    norm = sub.add_parser(
        "normalize", parents=[common], help="build the Google-shaped places/place_photos layer"
    )
    norm.add_argument(
        "--no-dedupe", action="store_true", help="keep places sharing a name and a ~10 m cell"
    )
    norm.add_argument(
        "--rebuild", action="store_true", help="drop and recreate the clean layer first"
    )

    match = sub.add_parser("google-match", parents=[common], help="link places to Google place ids")
    match.add_argument(
        "--api-key",
        default=os.environ.get("GOOGLE_MAPS_API_KEY", ""),
        help="Places API key (or set GOOGLE_MAPS_API_KEY)",
    )
    match.add_argument("--limit", type=int, default=100)
    match.add_argument(
        "--threshold", type=float, default=0.55, help="minimum score to accept a match (0..1)"
    )
    match.add_argument("--radius", type=float, default=500, help="bias circle in metres")
    match.add_argument(
        "--store-fields",
        action="store_true",
        help="also store Google address fields (refresh within 30 days)",
    )
    match.add_argument("--dry-run", action="store_true")

    photos = sub.add_parser(
        "photos", parents=[common], help="resolve lead images to upload URLs and licences"
    )
    photos.add_argument("--limit", type=int, default=500, help="resolve at most N images")
    photos.add_argument("--commons-url", default=COMMONS_API)

    near = sub.add_parser("near", parents=[common], help="pages within a radius of a point")
    near.add_argument("--lat", type=float, required=True)
    near.add_argument("--lon", type=float, required=True)
    near.add_argument("--radius-km", type=float, default=1.0)
    near.add_argument("--limit", type=int, default=20)

    link = sub.add_parser("link", parents=[common], help="manage wiki place <-> google id links")
    link.add_argument("action", choices=("import", "export", "check", "stats", "promote", "remove"))
    link.add_argument("--file", help="CSV or JSON rows for import")
    link.add_argument("--out", help="destination for export")
    link.add_argument("--method", default="import", help="provenance label for imported links")
    link.add_argument("--dry-run", action="store_true")
    link.add_argument("--place", help="wiki place id for promote")
    link.add_argument("--google-id", help="google place id for promote")
    link.add_argument(
        "--linked-only",
        action="store_false",
        dest="include_unlinked",
        default=True,
        help="omit places with no google id from the export",
    )

    bulk = sub.add_parser("bulk", parents=[common], help="worldwide build from Wikidata")
    bulk.add_argument("action", choices=("fetch", "enrich", "status"))
    bulk.add_argument("--country", help="Wikidata country QID, e.g. Q215 (Slovenia)")
    bulk.add_argument(
        "--all-countries", action="store_true", help="loop every country, largest first"
    )
    bulk.add_argument("--page-size", type=int, default=500)
    bulk.add_argument("--limit", type=int, help="stop after N rows")
    bulk.add_argument("--endpoint", default="qlever", help="qlever | wdqs | URL")
    bulk.add_argument("--dry-run", action="store_true", help="build the query without sending it")

    publish = sub.add_parser(
        "publish", parents=[common], help="write a redistributable open-data bundle"
    )
    publish.add_argument("--out", required=True, help="output directory")
    publish.add_argument("--name", default="wikicrawl-places")
    publish.add_argument("--title")
    publish.add_argument("--version")

    gaps = sub.add_parser("gaps", parents=[common], help="list what is missing upstream, per place")
    gaps.add_argument("--out", help="write the report here (default: stdout)")
    gaps.add_argument("--format", choices=("md", "json"), default="md")
    gaps.add_argument("--limit", type=int, default=100, help="rows per section")

    verify = sub.add_parser(
        "verify", parents=[common], help="parse an export with Google's protobuf messages"
    )
    verify.add_argument("--file", required=True, help="places payload written by export")
    verify.add_argument("--photo-index", help="optional photo index to cross-check")
    verify.add_argument("--quiet-ok", action="store_true", help="print nothing on success")

    sub.add_parser("stats", parents=[common], help="summarise the database")
    return parser


def _log(args, message):
    if not args.quiet:
        print(message, file=sys.stderr)


def _collect_titles(args, api):
    """Yield page titles according to the chosen strategy."""
    if args.category:
        for title in crawl_category(api, args.category, depth=args.depth):
            yield title
    if args.seed:
        for title in crawl_links(api, args.seed, depth=args.depth):
            yield title
    if args.lat is not None and args.lon is not None:
        result = geosearch(api, args.lat, args.lon, radius=args.radius, cell=args.cell)
        _log(
            args,
            "geo: %d pages in %d cells @%dm%s"
            % (
                len(result),
                result.cells,
                int(result.cell_size),
                ""
                if result.complete
                else " [WARNING: %d cells hit the 500 cap, shrink --cell]" % result.capped_cells,
            ),
        )
        for record in result:
            yield record["title"]


def cmd_collect(args):
    api = MediaWiki(args.api_url, user_agent=args.user_agent, min_interval=args.min_interval)
    added = skipped = 0
    with Store(args.db) as store:
        titles = _collect_titles(args, api)
        if not args.force:
            titles = (t for t in titles if not store.was_visited(t))
        selected = list(itertools.islice(titles, args.limit))
        _log(args, "fetching %d pages" % len(selected))
        for record in fetch_pages(api, selected, with_wikitext=not args.no_wikitext):
            is_new = store.upsert_page(record)
            store.mark_visited(record["title"], source="collect")
            added += 1
            skipped += 0 if is_new else 1
            if added % 50 == 0:
                store.conn.commit()
                _log(args, "  %d pages stored" % added)
        store.conn.commit()
        _log(args, "done: %d stored (%d updated), %d total in db" % (added, skipped, store.count()))


def cmd_photos(args):
    commons = MediaWiki(
        args.commons_url, user_agent=args.user_agent, min_interval=args.min_interval
    )
    with Store(args.db) as store:
        pending = store.pending_image_files(limit=args.limit)
        _log(args, "resolving %d images on Commons" % len(pending))
        resolved = 0
        for record in fetch_imageinfo(commons, pending):
            store.upsert_photo(record)
            resolved += 1
        store.conn.commit()
        _log(args, "stored %d image records" % resolved)


def cmd_normalize(args):
    with Store(args.db) as store:
        if args.rebuild:
            existing = (
                store.conn.execute("SELECT COUNT(*) FROM place_links").fetchone()[0]
                if store.conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='place_links'"
                ).fetchone()
                else 0
            )
            if existing:
                _log(
                    args,
                    "WARNING: --rebuild drops %d Google links; re-import or re-match after"
                    % existing,
                )
            rebuild_schema(store.conn)
        else:
            ensure_schema(store.conn)
        summary = normalize(store.conn, dedupe=not args.no_dedupe)
        _log(
            args,
            "places=%(places)d photos=%(photos)d skipped=%(skipped)d "
            "duplicates=%(duplicates)d" % summary,
        )


def cmd_google_match(args):
    if not args.api_key and not args.dry_run:
        sys.exit("no API key: pass --api-key or set GOOGLE_MAPS_API_KEY")
    # dry-run makes no requests, so a placeholder key is enough
    client = PlacesClient(args.api_key or "dry-run")
    with Store(args.db) as store:
        ensure_schema(store.conn)
        summary = match_places(
            store.conn,
            client,
            limit=args.limit,
            threshold=args.threshold,
            radius_m=args.radius,
            store_fields=args.store_fields,
            dry_run=args.dry_run,
            log=lambda m: _log(args, m),
        )
        _log(args, "matched=%(matched)d rejected=%(rejected)d requests=%(requests)d" % summary)


def cmd_export(args):
    with Store(args.db) as store:
        if args.format == "google":
            _export_google(store.conn, args.out)
            if args.verify:
                _verify_or_fail(args.out)
        elif args.format == "links":
            payload = export_links(store.conn, include_unlinked=args.include_unlinked)
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            _log(
                args,
                "wrote %d linked and %d unlinked places to %s"
                % (len(payload["linked"]), len(payload.get("unlinked", [])), args.out),
            )
        elif args.format == "photo-index":
            rows = store.conn.execute("SELECT * FROM place_photos ORDER BY id").fetchall()
            index = photo_index([dict(r) for r in rows])
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(index, handle, indent=2)
            _log(args, "wrote %d photo references to %s" % (len(index), args.out))
        else:
            (store.export_jsonl if args.format == "jsonl" else store.export_csv)(args.out)
            _log(args, "wrote %d pages to %s" % (store.count(), args.out))


def _verify_or_fail(payload_path, index_path=None):
    """Run Google's parser over what was just written; exit 1 if it objects."""
    if index_path and not os.path.exists(index_path):
        index_path = None
    try:
        result = verify_files(payload_path, index_path)
    except MissingDependency as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    print(format_report(result), file=sys.stderr)
    if result["problems"]:
        raise SystemExit(1)


def _export_google(conn, out):
    """Write a payload that a Places API (New) client can parse unchanged."""
    places = []
    for row in conn.execute("SELECT * FROM places ORDER BY name"):
        photos = conn.execute(
            "SELECT * FROM place_photos WHERE place_id=? ORDER BY position, id",
            (row["id"],),
        ).fetchall()
        places.append(place_to_google(dict(row), [dict(p) for p in photos]))
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(places_response(places), handle, ensure_ascii=False, indent=2)
    print("wrote %d places to %s" % (len(places), out), file=sys.stderr)


def cmd_near(args):
    with Store(args.db) as store:
        for row in store.near(args.lat, args.lon, args.radius_km)[: args.limit]:
            print("%7.3f km  %-45s %s" % (row["distance_km"], row["title"][:45], row["url"]))


def _read_link_rows(path):
    """Read links from CSV or JSON; returns a list of dicts."""
    if not path:
        raise SystemExit("--file is required for link import")
    with open(path, encoding="utf-8") as handle:
        if path.lower().endswith(".json"):
            data = json.load(handle)
            return data["links"] if isinstance(data, dict) and "links" in data else data
        return list(csv.DictReader(handle))


def cmd_link(args):
    with Store(args.db) as store:
        ensure_schema(store.conn)
        if args.action == "import":
            rows = _read_link_rows(args.file)
            summary = import_links(store.conn, rows, method=args.method, dry_run=args.dry_run)
            _log(
                args,
                "links: added=%(added)d skipped=%(skipped)d errors=%(errors)d"
                % {
                    "added": summary["added"],
                    "skipped": summary["skipped"],
                    "errors": len(summary["errors"]),
                },
            )
            for number, message in summary["errors"][:10]:
                print("  row %s: %s" % (number, message), file=sys.stderr)
            return 1 if summary["errors"] else 0

        if args.action == "export":
            payload = export_links(store.conn, include_unlinked=args.include_unlinked)
            out = args.out or "links.json"
            with open(out, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            _log(
                args,
                "wrote %d linked, %d unlinked -> %s"
                % (len(payload["linked"]), len(payload.get("unlinked", [])), out),
            )
            return 0

        if args.action == "check":
            problems = check_integrity(store.conn)
            for severity, message in problems:
                print("%-5s %s" % (severity.upper(), message))
            print("OK" if not problems else "%d problem(s)" % len(problems))
            return 1 if any(severity == "error" for severity, _ in problems) else 0

        if args.action == "remove":
            if not args.place or not args.google_id:
                raise SystemExit("--place and --google-id are required")
            remove_link(store.conn, args.place, validate_google_id(args.google_id))
            store.conn.commit()
            _log(args, "removed %s -> %s" % (args.place, args.google_id))
            return 0

        if args.action == "promote":
            if not args.place or not args.google_id:
                raise SystemExit("--place and --google-id are required")
            set_primary(store.conn, args.place, validate_google_id(args.google_id))
            store.conn.commit()
            _log(args, "promoted %s -> %s" % (args.place, args.google_id))
            return 0

        report = link_report(store.conn)
        for key in (
            "places",
            "places_linked",
            "links",
            "primary_links",
            "cache_in_sync",
            "photos",
            "photos_linked",
        ):
            print("%-14s %s" % (key, report[key]))
        return 0


def cmd_bulk(args):
    with Store(args.db) as store:
        ensure_schema(store.conn)
        if args.action == "fetch":
            from .bulk import ensure_wd_schema
            from .wikidata import heritage_query

            ensure_wd_schema(store.conn)
            if args.dry_run:
                print(heritage_query(limit=args.page_size, offset=0, country=args.country))
                return 0
            client = SparqlClient(endpoint=args.endpoint, user_agent=args.user_agent)
            if args.all_countries:
                result = bulk_stage_countries(
                    store.conn,
                    client,
                    page_size=args.page_size,
                    limit=args.limit,
                    log=lambda m: _log(args, m),
                )
            else:
                result = bulk_stage(
                    store.conn,
                    client,
                    country=args.country,
                    page_size=args.page_size,
                    limit=args.limit,
                    log=lambda m: _log(args, m),
                )
            _log(args, "staged %(rows)d rows in %(requests)d requests" % result)
            return 0

        if args.action == "enrich":
            commons = MediaWiki(
                COMMONS_API, user_agent=args.user_agent, min_interval=args.min_interval
            )
            result = bulk_enrich(store.conn, commons, limit=args.limit, log=lambda m: _log(args, m))
            _log(args, "enriched %(places)d places, %(photos)d photos" % result)
            return 0

        report = bulk_status(store.conn)
        for key in ("staged", "pending", "enriched", "failed", "places", "photos"):
            print("%-10s %s" % (key, report[key]))
        return 0


def cmd_gaps(args):
    with Store(args.db) as store:
        gaps = collect_gaps(store.conn, limit=args.limit)
        if args.format == "json":
            text = render_json(gaps)
        else:
            text = render_markdown(gaps, source=os.path.basename(args.db))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(text)
            _log(args, "wrote %s" % args.out)
        else:
            print(text)
        total = sum(section["count"] for section in gaps.values())
        _log(
            args,
            "gaps: %d across %d sections" % (total, sum(1 for s in gaps.values() if s["count"])),
        )
        return 0


def cmd_publish(args):
    manifest = publish_bundle(
        args.db, args.out, name=args.name, title=args.title, version=args.version
    )
    counts = manifest["counts"]
    print("bundle: %s" % args.out)
    print(
        "  places %d  photos %d  links %d" % (counts["places"], counts["photos"], counts["links"])
    )
    for resource in manifest["resources"]:
        print(
            "  %-16s %8d rows  %s"
            % (resource["path"], resource["row_count"], resource["hash"][:19] + "...")
        )
    return 0


def cmd_verify(args):
    try:
        result = verify_files(args.file, args.photo_index)
    except MissingDependency as exc:
        sys.exit(str(exc))
    if result["problems"] or not args.quiet_ok:
        print(format_report(result))
    return 1 if result["problems"] else 0


def cmd_stats(args):
    with Store(args.db) as store:
        stats = store.stats()
        print("pages        %d" % stats["pages"])
        print("with coords  %d" % (stats["geo"] or 0))
        print("with image   %d" % (stats["with_image"] or 0))
        print("with infobox %d" % (stats["with_infobox"] or 0))
        print("photos       %d" % (stats["photos"] or 0))


def main(argv=None):
    args = _build_parser().parse_args(argv)
    handlers = {
        "collect": cmd_collect,
        "photos": cmd_photos,
        "normalize": cmd_normalize,
        "google-match": cmd_google_match,
        "export": cmd_export,
        "near": cmd_near,
        "bulk": cmd_bulk,
        "link": cmd_link,
        "gaps": cmd_gaps,
        "publish": cmd_publish,
        "verify": cmd_verify,
        "stats": cmd_stats,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
