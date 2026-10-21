"""Rate-limited, retrying MediaWiki API client.

Stdlib only, so the crawler runs on a bare Python 3.9+ install.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_UA = "wikicrawl/0.1 (https://github.com/; contact: you@example.org) python-urllib"


class APIError(RuntimeError):
    """The API returned an error object or an unusable response."""


class MaxLagError(APIError):
    """The server asked us to back off (replication lag)."""


class MediaWiki:
    """A polite client for one MediaWiki API endpoint.

    Politeness is enforced in three places:

    * ``min_interval`` spaces requests out (default 5 req/s per client).
    * ``maxlag`` lets the server reject us when replicas lag, and we honour
      it by backing off instead of hammering.
    * ``max_retries`` uses ``Retry-After`` when the server sends it.
    """

    def __init__(
        self,
        api_url,
        user_agent=DEFAULT_UA,
        maxlag=5,
        min_interval=0.2,
        timeout=45,
        max_retries=5,
        sleeper=time.sleep,
    ):
        self.api_url = api_url
        self.user_agent = user_agent
        self.maxlag = maxlag
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleeper
        self._lock = threading.Lock()
        self._last_call = 0.0

    # -- transport -----------------------------------------------------

    def _throttle(self):
        with self._lock:
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                self._sleep(wait)
            self._last_call = time.monotonic()

    def _fetch(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def get(self, params=None, _attempt=0, **kwargs):
        """GET the API with retries; returns the decoded JSON object.

        Accepts either a parameter dict or keyword arguments, because both
        read better in different call sites: ``get({"titles": t})`` and
        ``get(action="query", list="geosearch")``.
        """
        query = dict(params or {})
        query.update(kwargs)
        query.setdefault("format", "json")
        query.setdefault("formatversion", "2")
        query.setdefault("maxlag", self.maxlag)
        url = self.api_url + "?" + urllib.parse.urlencode(query)

        self._throttle()
        try:
            payload = self._fetch(url)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and _attempt < self.max_retries:
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after else 2.0**_attempt
                self._sleep(min(delay, 60))
                return self.get(query, _attempt + 1)
            raise APIError("HTTP %s for %s" % (exc.code, self.api_url)) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if _attempt < self.max_retries:
                self._sleep(2.0**_attempt)
                return self.get(query, _attempt + 1)
            raise APIError("network failure for %s: %s" % (self.api_url, exc)) from exc

        error = payload.get("error")
        if error:
            code = error.get("code", "")
            if code == "maxlag" and _attempt < self.max_retries:
                self._sleep(min(float(error.get("lag", 5)) * 2, 30))
                return self.get(query, _attempt + 1)
            raise APIError("%s: %s" % (code, error.get("info", "")))
        return payload

    # -- higher level --------------------------------------------------

    def query(self, **params):
        """One ``action=query`` call, returning the ``query`` block."""
        params.setdefault("action", "query")
        return self.get(params).get("query", {})

    def paginate(self, **params):
        """Yield every item from a list module, following ``continue`` tokens.

        This is what makes category listings, link listings and search results
        complete rather than truncated at the first page.
        """
        params.setdefault("action", "query")
        pending = dict(params)
        while True:
            payload = self.get(pending)
            for block in payload.get("query", {}).values():
                if isinstance(block, list):
                    for item in block:
                        yield item
            cont = payload.get("continue")
            if not cont:
                return
            pending = dict(params)
            pending.update(cont)
