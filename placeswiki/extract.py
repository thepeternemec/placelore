"""Turn Wikipedia wikitext into structured records.

No regex-only shortcuts for nested templates: ``{{Infobox ...}}`` values often
contain ``{{convert|3|km}}`` or ``[[File:...|thumb|caption]]``, so brace and
bracket depth is tracked explicitly.
"""

from __future__ import annotations

import re

REF_RE = re.compile(r"<ref[^>/]*?/>|<ref[^>]*>.*?</ref>", re.S | re.I)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TAG_RE = re.compile(r"<[^>]+>")
LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
EXTLINK_RE = re.compile(r"\[https?://[^\]]*\]")
TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
COORD_RE = re.compile(r"\{\{\s*coord\s*\|([^}]*)\}\}", re.I)


def strip_markup(text):
    """Reduce wikitext to readable plain text."""
    if not text:
        return ""
    text = COMMENT_RE.sub("", text)
    text = REF_RE.sub("", text)
    text = EXTLINK_RE.sub("", text)
    text = re.sub(r"\{\{\s*convert\s*\|([^|}]*)\|([^|}]*)[^}]*\}\}", r"\1 \2", text, flags=re.I)
    text = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", text, flags=re.I)
    text = LINK_RE.sub(r"\1", text)
    text = re.sub(r"''+", "", text)
    text = TAG_RE.sub("", text)
    # collapse leftover templates such as {{citation needed}}
    for _ in range(5):
        text = TEMPLATE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_top_level(body, separator="|"):
    """Split on ``separator`` while ignoring it inside {{ }} and [[ ]]."""
    parts, depth_curly, depth_square, start = [], 0, 0, 0
    for index, char in enumerate(body):
        if char == "{":
            depth_curly += 1
        elif char == "}":
            depth_curly -= 1
        elif char == "[":
            depth_square += 1
        elif char == "]":
            depth_square -= 1
        elif char == separator and depth_curly == 0 and depth_square == 0:
            parts.append(body[start:index])
            start = index + 1
    parts.append(body[start:])
    return parts


def parse_infobox(wikitext):
    """Return ``{param: value}`` for the first Infobox, values plain-texted."""
    if not wikitext:
        return {}
    match = re.search(r"\{\{\s*Infobox", wikitext, re.I)
    if not match:
        return {}
    start = match.start()
    depth = 0
    for index in range(start, len(wikitext) - 1):
        pair = wikitext[index : index + 2]
        if pair == "{{":
            depth += 1
        elif pair == "}}":
            depth -= 1
            if depth == 0:
                body = wikitext[start + 2 : index]
                break
    else:
        return {}

    fields = {}
    for chunk in _split_top_level(body)[1:]:
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        key = key.strip().lower()
        cleaned = strip_markup(value.strip())
        if key and cleaned:
            fields[key] = cleaned
    return fields


def parse_coordinate_template(wikitext):
    """Fallback parser for ``{{coord|46|3|N|14|30|E}}`` markup.

    Preferred path is the API's ``prop=coordinates``. This exists because some
    pages carry coordinates only in prose or in an unusual template.
    Numbers are grouped per hemisphere token: a ``N`` closes the latitude
    group, an ``E``/``W`` closes the longitude group.
    """
    match = COORD_RE.search(wikitext or "")
    if not match:
        return None
    values = {"lat": None, "lon": None}
    pending = []
    for token in (t.strip() for t in match.group(1).split("|")):
        if re.fullmatch(r"-?\d+(?:\.\d+)?", token):
            pending.append(float(token))
            continue
        hemisphere = token.upper()
        if hemisphere not in ("N", "S", "E", "W") or not pending:
            continue
        degrees = pending[0]
        minutes = pending[1] if len(pending) > 1 else 0.0
        seconds = pending[2] if len(pending) > 2 else 0.0
        value = degrees + minutes / 60.0 + seconds / 3600.0
        if hemisphere in ("S", "W"):
            value = -value
        values["lat" if hemisphere in ("N", "S") else "lon"] = value
        pending = []
    if values["lat"] is None and values["lon"] is None:
        return None
    return values


def summary(wikitext, chars=500):
    """First prose paragraph as plain text, capped to ``chars``.

    Paragraph splitting happens before markup stripping, because stripping
    collapses newlines and would merge the lead with the infobox.
    """
    if not wikitext:
        return ""
    skip_prefixes = ("{", "|", "[[File:", "[[Image:", "[[Category:", "==", "*", "#")
    for raw in re.split(r"\n\s*\n", wikitext):
        candidate = raw.strip()
        if not candidate or candidate.startswith(skip_prefixes):
            continue
        text = strip_markup(candidate)
        if len(text) > 40:
            return text[:chars].strip()
    return strip_markup(wikitext)[:chars].strip()
