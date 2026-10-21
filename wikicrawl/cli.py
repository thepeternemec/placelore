"""Command line interface.

wikicrawl collect --category "Category:Colosseum" --depth 1 --db rome.sqlite
wikicrawl collect --lat 41.8902 --lon 12.4922 --radius 400 --db rome.sqlite
wikicrawl export --db rome.sqlite --out rome.jsonl
wikicrawl near --db rome.sqlite --lat 41.89 --lon 12.49 --radius-km 1
"""

from __future__ import annotations

import argparse
import itertools
import sys

from . import __version__
from .api import DEFAULT_UA, MediaWiki
from .crawl import crawl_category, crawl_links, geosearch
from .images import COMMONS_API, fetch_imageinfo
from .pages import fetch_pages
from .store import Store


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
    export.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")

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


def cmd_export(args):
    with Store(args.db) as store:
        (store.export_jsonl if args.format == "jsonl" else store.export_csv)(args.out)
        _log(args, "wrote %d pages to %s" % (store.count(), args.out))


def cmd_near(args):
    with Store(args.db) as store:
        for row in store.near(args.lat, args.lon, args.radius_km)[: args.limit]:
            print("%7.3f km  %-45s %s" % (row["distance_km"], row["title"][:45], row["url"]))


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
        "export": cmd_export,
        "near": cmd_near,
        "stats": cmd_stats,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
