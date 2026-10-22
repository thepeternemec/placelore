"""Crawl strategies: category trees, link graphs, and geographic grids.

All three are generators so a caller can stream results into a store without
holding a whole crawl in memory, and stop at any page budget.
"""

from __future__ import annotations

import math
from collections import deque

CATEGORY_NS = 14
MAX_RADIUS = 10000
MAX_RESULTS = 500


def _as_category(title):
    return title if title.lower().startswith("category:") else "Category:" + title


def category_members(api, title):
    """Yield ``(namespace, title)`` for a category's pages and subcategories."""
    for member in api.paginate(
        list="categorymembers",
        cmtitle=_as_category(title),
        cmlimit="max",
        cmtype="page|subcat",
    ):
        yield member.get("ns", 0), member.get("title", "")


def crawl_category(api, roots, depth=1, namespace=0):
    """Breadth-first walk of a category tree, yielding article titles.

    ``depth`` counts subcategory hops: 0 means pages directly in the root.
    Cycles are impossible to avoid on Wikipedia (categories are a graph), so
    visited titles are tracked.
    """
    queue = deque((_as_category(root), 0) for root in roots)
    seen = set()
    while queue:
        category, level = queue.popleft()
        if category in seen:
            continue
        seen.add(category)
        for member_ns, title in category_members(api, category):
            if member_ns == CATEGORY_NS:
                if level < depth:
                    queue.append((title, level + 1))
            elif member_ns == namespace and title not in seen:
                seen.add(title)
                yield title


def crawl_links(api, seeds, depth=2, namespace=0):
    """Breadth-first walk of internal links from seed articles."""
    queue = deque((seed, 0) for seed in seeds)
    seen = set(seeds)
    for seed in seeds:
        yield seed
    while queue:
        title, level = queue.popleft()
        if level >= depth:
            continue
        for link in api.paginate(
            prop="links",
            titles=title,
            plnamespace=namespace,
            pllimit="max",
        ):
            target = link.get("title", "")
            if target and target not in seen:
                seen.add(target)
                queue.append((target, level + 1))
                yield target


def grid_centers(lat, lon, radius, cell):
    """Cell centres covering a search circle.

    geosearch returns at most 500 rows and has no continuation token, so a
    single call silently truncates dense areas. Querying a grid of smaller
    cells is the only way to enumerate completely.
    """
    step = cell / 111320.0
    span = int(radius / cell) + 1
    lat_cos = max(0.01, abs(math.cos(math.radians(lat))))
    centers = []
    for row in range(-span, span + 1):
        for col in range(-span, span + 1):
            dy = row * step
            dx = col * step / lat_cos
            if (dy * 111320.0) ** 2 + (dx * 111320.0 * lat_cos) ** 2 <= radius**2:
                centers.append((round(lat + dy, 7), round(lon + dx, 7)))
    return centers


def geosearch(api, lat, lon, radius=500, cell=100, namespace=0):
    """Yield page records near a point, plus a ``capped`` flag per cell.

    Records carry ``distance_m`` and the cell centre that found them, which
    makes it possible to audit coverage afterwards.
    """
    if not 10 <= radius <= MAX_RADIUS:
        raise ValueError("radius must be 10..10000 metres (API limit)")
    centers = grid_centers(lat, lon, radius, cell)
    found = {}
    capped = 0
    for cell_lat, cell_lon in centers:
        payload = api.get(
            action="query",
            list="geosearch",
            gscoord="%s|%s" % (cell_lat, cell_lon),
            gsradius=int(cell * 0.75),
            gslimit=MAX_RESULTS,
            gsnamespace=namespace,
        )
        hits = payload.get("query", {}).get("geosearch", [])
        if len(hits) >= MAX_RESULTS:
            capped += 1
        for hit in hits:
            record = dict(hit)
            record["cell"] = (cell_lat, cell_lon)
            found.setdefault(hit.get("pageid"), record)
    return GeoResult(found.values(), capped_cells=capped, cells=len(centers), cell_size=cell)


class GeoResult(list):
    """Records near a point, with coverage diagnostics attached."""

    def __init__(self, records=(), capped_cells=0, cells=0, cell_size=0):
        super().__init__(records)
        self.capped_cells = capped_cells
        self.cells = cells
        self.cell_size = cell_size

    @property
    def complete(self):
        """False when some cell hit the 500-row cap, so results are truncated."""
        return self.capped_cells == 0
