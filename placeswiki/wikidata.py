"""Bulk place lists from Wikidata.

The worldwide set is defined by one query: items with a heritage designation
(``P1435``) and coordinates (``P625``). That is ~2.2 M rows, far too many for a
single response, so the list is fetched in pages — optionally per country, which
keeps ``OFFSET`` shallow and makes the crawl resumable at country granularity.

Two endpoints are supported:

* ``qlever`` (default) — fast, no rate limit worth speaking of, needs explicit
  ``PREFIX`` lines.
* ``wdqs`` — the canonical endpoint, currently rate-limited during incidents.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

ENDPOINTS = {
    "qlever": "https://qlever.dev/api/wikidata",
    "wdqs": "https://query.wikidata.org/sparql",
}

PREFIXES = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>
PREFIX geof: <http://www.opengis.net/def/function/geosparql/>"""

DEFAULT_UA = "placeswiki/0.3 (bulk; contact: you@example.org)"


class SparqlError(RuntimeError):
    """Endpoint returned an error or an unusable response."""


def heritage_query(limit=500, offset=0, country=None):
    """Items with a heritage designation and coordinates.

    ``country`` takes a Wikidata QID (e.g. ``Q215`` for Slovenia). ``None``
    means worldwide, which works but leaves ``OFFSET`` deep — prefer looping
    countries for a full build.
    """
    scope = "\n  ?item wdt:P17 wd:%s ." % country if country else ""
    return """%s
SELECT ?item ?label ?lat ?lon ?article ?image ?category ?heritage ?country WHERE {
  ?item wdt:P1435 ?heritage ; wdt:P625 ?c .%s
  BIND(geof:latitude(?c) AS ?lat)
  BIND(geof:longitude(?c) AS ?lon)
  OPTIONAL { ?item wdt:P18 ?image }
  OPTIONAL { ?item wdt:P373 ?category }
  OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }
  OPTIONAL { ?item rdfs:label ?label FILTER(lang(?label) = "en") }
  OPTIONAL { ?item wdt:P17 ?country }
}
ORDER BY ?item
LIMIT %d OFFSET %d""" % (PREFIXES, scope, int(limit), int(offset))


def countries_query():
    """Countries that contain heritage-listed, geocoded items, largest first."""
    return (
        """%s
SELECT ?country (COUNT(?item) AS ?n) WHERE {
  ?item wdt:P1435 ?h ; wdt:P625 ?c ; wdt:P17 ?country .
}
GROUP BY ?country
ORDER BY DESC(?n)"""
        % PREFIXES
    )


class SparqlClient:
    """Minimal SPARQL client with retry/backoff."""

    def __init__(
        self,
        endpoint="qlever",
        user_agent=DEFAULT_UA,
        timeout=120,
        max_retries=4,
        sleeper=time.sleep,
        send=None,
    ):
        if endpoint in ENDPOINTS:
            self.url = ENDPOINTS[endpoint]
        elif endpoint.startswith("http"):
            self.url = endpoint
        else:
            raise ValueError("unknown endpoint %r; use qlever, wdqs or a URL" % endpoint)
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleeper
        self._send = send
        self.requests = 0

    def _post(self, query):
        body = urllib.parse.urlencode({"query": query}).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/sparql-results+json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def query(self, text):
        """Run a SELECT and return a list of plain ``{var: value}`` dicts."""
        self.requests += 1
        attempt = 0
        while True:
            try:
                payload = (self._send or self._post)(text)
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    retry_after = exc.headers.get("Retry-After")
                    self._sleep(min(float(retry_after) if retry_after else 2.0**attempt, 60))
                    attempt += 1
                    continue
                raise SparqlError("HTTP %s from %s" % (exc.code, self.url)) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.max_retries:
                    self._sleep(2.0**attempt)
                    attempt += 1
                    continue
                raise SparqlError("network failure: %s" % exc) from exc

        bindings = payload.get("results", {}).get("bindings", [])
        return [{key: value.get("value") for key, value in row.items()} for row in bindings]


def qid(uri):
    """``http://www.wikidata.org/entity/Q42`` -> ``Q42``."""
    return (uri or "").rsplit("/", 1)[-1]


def enwiki_title(uri):
    """Wiki URL -> article title, undecorated."""
    if not uri:
        return ""
    tail = uri.split("/wiki/", 1)[-1]
    return urllib.parse.unquote(tail).replace("_", " ")


def commons_file(uri):
    """``Special:FilePath/Foo.jpg`` -> ``File:Foo.jpg``."""
    if not uri:
        return ""
    tail = urllib.parse.unquote(uri.split("Special:FilePath/", 1)[-1].split("?")[0])
    tail = tail.replace("_", " ")
    return tail if tail.lower().startswith("file:") else "File:" + tail


def parse_row(row):
    """Normalise one SPARQL binding into a staging record."""
    return {
        "qid": qid(row.get("item")),
        "label": row.get("label") or "",
        "lat": float(row["lat"]) if row.get("lat") else None,
        "lon": float(row["lon"]) if row.get("lon") else None,
        "enwiki_title": enwiki_title(row.get("article")),
        "image_file": commons_file(row.get("image")),
        "commons_category": row.get("category") or "",
        "heritage": row.get("heritage") or "",
        "country": qid(row.get("country")),
    }
