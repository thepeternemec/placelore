#!/usr/bin/env python3
"""Use wikicrawl as a library: no CLI, no database required.

    python3 examples/programmatic.py

Prints the five closest geocoded articles around the Colosseum, with the
Commons licence of each lead image.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from wikicrawl import MediaWiki, Store, fetch_pages, geosearch
from wikicrawl.images import fetch_imageinfo

WIKIPEDIA = "https://en.wikipedia.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"
UA = "wikicrawl-example/0.1 (https://github.com/; example@example.org)"


def main():
    wikipedia = MediaWiki(WIKIPEDIA, user_agent=UA)
    commons = MediaWiki(COMMONS, user_agent=UA)

    # 1. pages near a point, de-duplicated across grid cells
    nearby = geosearch(wikipedia, lat=41.8902, lon=12.4922, radius=300, cell=100)
    print(f"{len(nearby)} articles in {nearby.cells} cells; complete={nearby.complete}")
    titles = [hit["title"] for hit in nearby][:5]

    # 2. structured page records
    pages = fetch_pages(wikipedia, titles, with_wikitext=True)
    for page in pages:
        print(f"  {page['title']:<35} {page['lat']}, {page['lon']}")

    # 3. Commons image metadata, keyed by file name
    files = [page["image"] for page in pages if page["image"]]
    photos = {photo["file"]: photo for photo in fetch_imageinfo(commons, files)}
    for photo in photos.values():
        print(f"  {photo['file'][:40]:<42} {photo['license']}")

    # 4. or persist everything
    with Store(":memory:") as store:
        for page in pages:
            store.upsert_page(page)
        print("stored:", store.stats())


if __name__ == "__main__":
    main()
