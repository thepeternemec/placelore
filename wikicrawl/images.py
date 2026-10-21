"""Resolve page lead images into downloadable URLs plus licence metadata.

Wikipedia's ``prop=pageimages`` gives a file name such as ``Colosseo.jpg``;
the actual upload URL and the attribution string live on Commons, so this
module queries ``commons.wikimedia.org`` in batches of 50 titles.
"""

from __future__ import annotations

from .pages import batched

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
BATCH = 50


def _as_file(title):
    if not title:
        return ""
    return title if title.lower().startswith("file:") else "File:" + title


def _field(meta, name):
    """Read one extmetadata value, tolerating missing keys."""
    return (meta.get(name) or {}).get("value", "")


def fetch_imageinfo(commons, file_titles, batch=BATCH):
    """Yield ``{file, url, width, height, license, artist, credit, description_url}``."""
    pending = sorted({_as_file(t) for t in file_titles if t})
    for chunk in batched(pending, batch):
        payload = commons.get(
            action="query",
            prop="imageinfo",
            titles="|".join(chunk),
            iiprop="url|size|mime|extmetadata",
            iiextmetadatafilter="LicenseShortName|License|Artist|Credit|ImageDescription",
        )
        for page in payload.get("query", {}).get("pages", []):
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {}) or {}
            if not info.get("url"):
                continue
            yield {
                "file": page.get("title", ""),
                "url": info.get("url", "").split("?")[0],
                "width": info.get("width"),
                "height": info.get("height"),
                "mime": info.get("mime", ""),
                "license": _field(meta, "LicenseShortName") or _field(meta, "License"),
                "artist": _field(meta, "Artist"),
                "credit": _field(meta, "Credit"),
                "description": _field(meta, "ImageDescription")[:300],
                "description_url": info.get("descriptionurl", ""),
            }
