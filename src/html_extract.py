"""
Robust HTML-to-text extraction for JS-heavy sites.
trafilatura alone fails on pages where content is mostly JS-rendered —
it may return <500 chars from a 700KB page. This module supplements it
with structured extraction of elements that survive JS rendering gaps:
title, headings, meta tags, contact links, footer text, and JSON-LD
structured data (addresses buried in Wix/Squarespace JSON-LD are
invisible to trafilatura but contain the ground-truth address).
"""
import json
import logging
import re
from urllib.parse import parse_qs, unquote, urlparse
from bs4 import BeautifulSoup
import trafilatura

logger = logging.getLogger(__name__)

_ZIP_RE = re.compile(r'\b\d{5}\b')
_PHONE_RE = re.compile(r'\(\d{3}\)\s?\d{3}-\d{4}|\d{3}[-.\s]\d{3}[-.\s]\d{4}')


def extract_page_sections(html: str, url: str) -> str:
    """
    Return structured text representation of a page, formatted for the extractor prompt.

    Sections:
      PAGE: <url>
      TITLE: ...
      HEADINGS:
        H1: ...
        H2: ...
        H3: ...
      META: ...
      CONTACT LINKS:
        tel:...
        mailto:...
      FOOTER:
        ...
      BODY:
        <trafilatura output>
    """
    soup = BeautifulSoup(html, "html.parser")
    parts = [f"PAGE: {url}"]

    # TITLE
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        parts.append(f"TITLE: {title_tag.get_text(strip=True)}")

    # HEADINGS
    headings = []
    for level in ("h1", "h2", "h3"):
        for tag in soup.find_all(level):
            text = tag.get_text(separator=" ", strip=True)
            if text:
                headings.append(f"  {level.upper()}: {text}")
    if headings:
        parts.append("HEADINGS:\n" + "\n".join(headings[:200]))  # bumped from 30 — large sites have many location headings

    # META — description + og:*
    meta_lines = []
    for tag in soup.find_all("meta"):
        name = tag.get("name", "") or tag.get("property", "")
        content = tag.get("content", "").strip()
        if not name or not content:
            continue
        name_lower = name.lower()
        if name_lower in ("description",) or name_lower.startswith("og:"):
            meta_lines.append(f"  {name}: {content}")
    if meta_lines:
        parts.append("META:\n" + "\n".join(meta_lines[:10]))

    # STRUCTURED DATA — JSON-LD schema.org blocks (addresses in Wix/Squarespace live here)
    structured = _extract_json_ld(soup)
    if structured:
        parts.append(f"STRUCTURED DATA:\n{structured}")

    # CONTACT LINKS — tel: and mailto:
    contact_links = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if href.startswith("tel:") or href.startswith("mailto:"):
            if href not in contact_links:
                contact_links.append(href)
    if contact_links:
        parts.append("CONTACT LINKS:\n" + "\n".join(f"  {l}" for l in contact_links[:20]))

    # FOOTER — look for <footer> tag or elements with footer-like classes
    footer_text = _extract_footer(soup)
    if footer_text:
        parts.append(f"FOOTER:\n{footer_text}")

    # BODY — trafilatura output (may be sparse on JS-heavy sites)
    body_text = trafilatura.extract(html) or ""
    if body_text:
        parts.append(f"BODY:\n{body_text[:20000]}")  # bumped from 3000 — was cutting off pages with 40+ locations

    # GOOGLE_MAPS_ADDRESS — addresses in Google Maps iframe src URLs AND <a href> direction links
    gmaps = _extract_gmaps_addresses(soup)
    if gmaps:
        parts.append(gmaps)

    # DATA_ATTRS — addresses stored in HTML data-* attributes (common in interactive map widgets).
    # e.g. data-label="Name<br/>123 Main St<br/>City, ST 12345" or data-zip="78701" data-street="..."
    data_attrs = _extract_data_attr_addresses(soup)
    if data_attrs:
        parts.append(f"DATA_ATTRS:\n{data_attrs}")

    # MICRODATA — schema.org microdata (itemprop="streetAddress" etc.)
    microdata = _extract_microdata_addresses(soup)
    if microdata:
        parts.append(f"MICRODATA:\n{microdata}")

    # SCRIPT_DATA — addresses buried in JS map widget variables (not captured by JSON-LD).
    # Many sites embed location data as JS arrays fed into Google Maps or Leaflet. trafilatura
    # strips <script> entirely, so we scan non-JSON-LD scripts for address key-value patterns.
    script_data = _extract_script_address_data(soup)
    if script_data:
        parts.append(f"SCRIPT_DATA:\n{script_data}")

    # RAW_TEXT fallback — trafilatura strips styled-widget content (e.g. WP CTA boxes).
    # Add raw soup text when BODY is missing zip codes or phones that are visible in the raw HTML.
    raw_text = _clean_whitespace(soup.get_text(separator=" ", strip=True))[:20000]  # bumped from 2000 to match BODY cap
    body_sparse = len(body_text) < 500
    body_missing_zip = not _ZIP_RE.search(body_text) and _ZIP_RE.search(raw_text)
    body_missing_phone = not _PHONE_RE.search(body_text) and _PHONE_RE.search(raw_text)
    if body_sparse or body_missing_zip or body_missing_phone:
        parts.append(f"RAW_TEXT:\n{raw_text}")
        logger.debug(f"[{url}] RAW_TEXT added (sparse={body_sparse}, zip={body_missing_zip}, phone={body_missing_phone})")

    return "\n\n".join(parts)


_JSON_LD_TYPES = {
    "organization", "localbusiness", "medicalorganization",
    "place", "researchorganization", "medicalclinic", "hospital",
}

_JSON_LD_ADDRESS_KEYS = (
    "streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry"
)


def _extract_json_ld(soup: BeautifulSoup) -> str:
    """
    Parse <script type="application/ld+json"> blocks and extract address, telephone,
    name, and location fields from relevant schema.org types.
    Returns a flat text block suitable for inclusion in the LLM prompt.
    """
    lines = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError) as e:
            logger.debug(f"JSON-LD parse error: {e}")
            continue

        # Handle both single objects and @graph arrays
        items = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            items = data["@graph"]

        for item in items:
            if not isinstance(item, dict):
                continue
            schema_type = str(item.get("@type", "")).lower()
            if not any(t in schema_type for t in _JSON_LD_TYPES):
                continue

            if item.get("name"):
                lines.append(f"  name: {item['name']}")
            if item.get("telephone"):
                lines.append(f"  telephone: {item['telephone']}")
            if item.get("url"):
                lines.append(f"  url: {item['url']}")

            addr = item.get("address", {})
            if isinstance(addr, dict):
                addr_parts = [addr.get(k, "") for k in _JSON_LD_ADDRESS_KEYS if addr.get(k)]
                if addr_parts:
                    lines.append(f"  address: {', '.join(addr_parts)}")

            # location can be a list of sub-locations
            for loc in (item.get("location") or []):
                if not isinstance(loc, dict):
                    continue
                loc_name = loc.get("name", "")
                loc_addr = loc.get("address", {})
                if isinstance(loc_addr, dict):
                    parts = [loc_addr.get(k, "") for k in _JSON_LD_ADDRESS_KEYS if loc_addr.get(k)]
                    if parts:
                        lines.append(f"  location: {loc_name + ' — ' if loc_name else ''}{', '.join(parts)}")

    return "\n".join(lines)


def _extract_gmaps_addresses(soup: BeautifulSoup) -> str:
    """
    Extract addresses encoded in Google Maps URLs — both iframe embeds and <a href> links.

    Iframe patterns: ?q=, /place/, !2s (pb= param)
    Link patterns: ?daddr=, ?destination=, /dir//<address>/ (directions links)
    """
    addrs = []
    seen = set()

    def _add(addr: str):
        addr = addr.strip()
        if addr and addr not in seen and len(addr) > 5:
            seen.add(addr)
            addrs.append(addr)

    # ── Iframe src URLs ───────────────────────────────────────────────────────
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        if "google.com/maps" not in src:
            continue
        parsed = urlparse(src)
        qs = parse_qs(parsed.query)
        if "q" in qs:
            _add(unquote(qs["q"][0]))
            continue
        m = re.search(r'/place/([^/@]+)', parsed.path)
        if m:
            _add(unquote(m.group(1).replace("+", " ")))
            continue
        m = re.search(r'!2s([^!]+)', src)
        if m:
            candidate = unquote(m.group(1))
            if re.search(r'\d', candidate) and len(candidate) < 200:
                _add(candidate)

    # ── <a href> direction links ──────────────────────────────────────────────
    # Pattern: https://maps.google.com/maps?...&daddr=123+Main+St,+Austin,+TX+78701,+USA
    # Also: https://www.google.com/maps/dir//address/@lat,lng
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "google.com/maps" not in href and "maps.google" not in href:
            continue
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        # daddr= or destination= param (directions to address)
        for param in ("daddr", "destination", "q"):
            if param in qs:
                val = unquote(qs[param][0]).replace("+", " ")
                # Filter out lat/lng-only values (no letters = coordinates)
                if re.search(r'[A-Za-z]', val) and _ZIP_RE.search(val):
                    _add(val)
                break
        else:
            # /dir//<address>/ path format
            m = re.search(r'/dir//([^/@]{10,200})/', parsed.path)
            if m:
                candidate = unquote(m.group(1).replace("+", " "))
                if _ZIP_RE.search(candidate):
                    _add(candidate)

    if not addrs:
        return ""
    if len(addrs) == 1:
        return f"GOOGLE_MAPS_ADDRESS:\n  {addrs[0]}"
    lines = "\n".join(f"  {a}" for a in addrs[:200])  # bumped from 30 — large map-based sites have 100+ markers
    return f"GOOGLE_MAPS_ADDRESSES ({len(addrs)} locations from map links/embeds):\n{lines}"


def _extract_data_attr_addresses(soup: BeautifulSoup) -> str:
    """
    Extract addresses from HTML data-* attributes — common in interactive map widgets.

    Pattern A — data-label with full address:
        <li data-label="Name<br/>123 Main St<br/>City, ST 12345" data-lat="..." data-lng="...">
        Addresses are HTML-encoded and line-separated by <br/> tags.

    Pattern B — individual data-* address components:
        <div data-street="123 Main" data-city="Austin" data-state="TX" data-zip="78701">
    """
    lines = []
    seen = set()

    for tag in soup.find_all(True):
        attrs = tag.attrs

        # Pattern A: data-label with <br/> separators and a ZIP
        label = attrs.get("data-label", "")
        if label and _ZIP_RE.search(label):
            # Decode HTML entities and replace <br/> with newlines
            clean = re.sub(r'<br\s*/?>', '\n', label, flags=re.IGNORECASE)
            clean = re.sub(r'<[^>]+>', '', clean)  # strip any remaining tags
            clean = _clean_whitespace(clean.replace('&amp;', '&').replace('&lt;', '<')
                                      .replace('&gt;', '>').replace('&#39;', "'")
                                      .replace('&quot;', '"'))
            if clean and clean not in seen:
                seen.add(clean)
                # Format as single line for LLM prompt
                single_line = ' | '.join(p.strip() for p in clean.split('\n') if p.strip())
                lines.append(f"  {single_line}")

        # Pattern B: individual data-street / data-address + data-zip on same element
        street = (attrs.get("data-street") or attrs.get("data-address") or
                  attrs.get("data-addr") or "")
        city   = attrs.get("data-city", "")
        state  = attrs.get("data-state", "")
        zipv   = (attrs.get("data-zip") or attrs.get("data-zipcode") or
                  attrs.get("data-postal") or "")

        if (street or city) and (zipv or state):
            parts = [p.strip() for p in [street, city, state, zipv] if p and p.strip()]
            key = ",".join(parts)
            if key not in seen:
                seen.add(key)
                lines.append(f"  {', '.join(parts)}")

        if len(lines) >= 200:
            break

    return "\n".join(lines[:200])  # bumped from 50 — data-attr maps can have 100+ markers


def _extract_microdata_addresses(soup: BeautifulSoup) -> str:
    """
    Extract schema.org microdata address fields (itemprop attributes).
    Handles both content= attribute and inner text.

    Looks for: streetAddress, postalCode, addressLocality, addressRegion, telephone
    Groups them by nearest itemscope ancestor.
    """
    ADDR_PROPS = {
        "streetaddress", "postalcode", "addresslocality",
        "addressregion", "addresscountry", "telephone", "name",
    }

    # Collect all itemprop elements with address-related properties
    entries: dict[int, dict] = {}  # keyed by itemscope ancestor id

    for tag in soup.find_all(itemprop=True):
        prop = tag.get("itemprop", "").lower()
        if prop not in ADDR_PROPS:
            continue
        value = (tag.get("content") or tag.get_text(separator=" ", strip=True))[:200]
        if not value:
            continue

        # Find nearest itemscope ancestor to group fields together
        group_id = id(tag)  # default: tag itself
        for ancestor in tag.parents:
            if ancestor.get("itemscope") is not None:
                group_id = id(ancestor)
                break

        if group_id not in entries:
            entries[group_id] = {}
        entries[group_id][prop] = value

    if not entries:
        return ""

    lines = []
    for group in entries.values():
        parts = []
        if group.get("name"):
            parts.append(group["name"])
        if group.get("streetaddress"):
            parts.append(group["streetaddress"])
        if group.get("addresslocality"):
            parts.append(group["addresslocality"])
        if group.get("addressregion"):
            parts.append(group["addressregion"])
        if group.get("postalcode"):
            parts.append(group["postalcode"])
        if group.get("telephone"):
            parts.append(f"tel:{group['telephone']}")
        if len(parts) >= 2:  # only emit if we have at least 2 fields
            lines.append(f"  {', '.join(parts)}")

    return "\n".join(lines[:200])  # bumped from 50 — schema.org microdata can mark 100+ branches


_SCRIPT_STREET_RE = re.compile(
    r'''["\']?(?:street1?|address1?|street_address|addr(?:ess)?)["\']?\s*[=:]\s*["\']([^"\'<>\n]{3,120})["\']''',
    re.IGNORECASE,
)
_SCRIPT_ZIP_RE = re.compile(
    r'''["\']?(?:zip\w*|postal(?:_?code)?)["\']?\s*[=:]\s*["\']?(\d{5}(?:-\d{4})?)["\']?''',
    re.IGNORECASE,
)
_SCRIPT_CITY_RE = re.compile(
    r'''["\']?city["\']?\s*[=:]\s*["\']([A-Za-z][^"\'<>\n]{1,60})["\']''',
    re.IGNORECASE,
)
_SCRIPT_STATE_RE = re.compile(
    r'''["\']?(?:state|province)["\']?\s*[=:]\s*["\']([A-Z]{2})["\']''',
)


def _extract_script_address_data(soup: BeautifulSoup) -> str:
    """
    Scan non-JSON-LD <script> tags for address data embedded in JS map widgets.

    Strategy A — JSON arrays: find [{ ... }] blocks, try json.loads, look for address keys.
    Strategy B — key-value regex: find street/zip patterns anywhere in script text.

    Returns a SCRIPT_DATA block with up to 20 location snippets.
    """
    lines: list[str] = []
    seen: set[str] = set()

    for script in soup.find_all("script"):
        # Skip JSON-LD — already handled by _extract_json_ld()
        if (script.get("type") or "").lower() == "application/ld+json":
            continue
        # Skip external scripts (src= attr — no inline text to parse)
        if script.get("src"):
            continue
        content = script.string or ""
        if not content or len(content) < 30:
            continue

        # ── Strategy A: find JSON array/object blobs with address keys ────────
        # Look for quoted keys that signal address data. If found, try to extract
        # the surrounding JSON object. This catches map widget data like:
        #   var locs = [{"name":"Office","street":"123 Main","zip":"78701"},...]
        if re.search(r'"(?:street|zip|postal|address\d?)', content, re.IGNORECASE):
            # Try to pull full JSON arrays from the script
            for match in re.finditer(r'\[\s*\{[^[\]]{20,5000}\}\s*\]', content, re.DOTALL):
                blob = match.group(0)
                try:
                    items = json.loads(blob)
                    if not isinstance(items, list):
                        continue
                    for item in items[:200]:  # bumped from 30 — JS arrays can have 100+ location objects
                        if not isinstance(item, dict):
                            continue

                        # Pattern: {"address": "full address string", "name": "...", "lat": ...}
                        # calderminstitute.com style — single combined address value
                        full_addr = _dict_get_ci(item, ["address"])
                        name = _dict_get_ci(item, ["name", "title"])
                        if full_addr and _ZIP_RE.search(full_addr) and len(full_addr) > 10:
                            entry = f"{name} — {full_addr}" if name else full_addr
                            if entry not in seen:
                                seen.add(entry)
                                lines.append(f"  {entry}")
                            continue

                        # Pattern: broken-out fields
                        street = _dict_get_ci(item, ["street", "street1", "street_1", "address1", "addr"])
                        city   = _dict_get_ci(item, ["city", "location-city"])
                        state  = _dict_get_ci(item, ["state"])
                        zipv   = _dict_get_ci(item, ["zip", "zipcode", "zip_code", "postal", "postalcode"])
                        if street and (zipv or city):
                            parts = [p for p in [street, city, state, zipv] if p]
                            key = ",".join(parts)
                            if key not in seen:
                                seen.add(key)
                                lines.append(f"  {', '.join(parts)}")
                except (json.JSONDecodeError, TypeError):
                    pass

        # ── Strategy B: regex key-value extraction ────────────────────────────
        # Fallback for non-JSON (JS object literals, template strings, etc.)
        streets = _SCRIPT_STREET_RE.findall(content)
        zips    = _SCRIPT_ZIP_RE.findall(content)
        cities  = _SCRIPT_CITY_RE.findall(content)
        states  = _SCRIPT_STATE_RE.findall(content)

        # Only bother if we found at least a street AND (zip or city) in this script
        if streets and (zips or cities):
            for street in streets[:200]:  # bumped from 20
                street = street.strip()
                if not street or len(street) < 5:
                    continue
                # Find first city/state/zip near this street value in the content
                city  = cities[0].strip() if cities else ""
                state = states[0].strip() if states else ""
                zipv  = zips[0].strip() if zips else ""
                parts = [p for p in [street, city, state, zipv] if p]
                key = ",".join(parts)
                if key not in seen:
                    seen.add(key)
                    lines.append(f"  {', '.join(parts)}")

        if len(lines) >= 200:
            break

    return "\n".join(lines[:200])  # bumped from 20 — JS variables can hold all locations


def _dict_get_ci(d: dict, keys: list[str]) -> str:
    """Case-insensitive key lookup across a list of candidate key names."""
    d_lower = {k.lower(): v for k, v in d.items()}
    for key in keys:
        val = d_lower.get(key.lower())
        if val and isinstance(val, str):
            return val.strip()
    return ""


def _extract_footer(soup: BeautifulSoup) -> str:
    """Extract text from <footer> or common footer class names."""
    # Try semantic <footer> first
    footer = soup.find("footer")
    if footer:
        text = footer.get_text(separator="\n", strip=True)
        return _clean_whitespace(text)[:1500]

    # Fall back to divs/sections with footer-like class or id.
    # Use r"\bfooter" (no trailing \b) so "footer_widget" matches — underscore is a
    # word char in Python regex, so \bfooter\b would silently skip underscore-named classes.
    # Collect all matching sections; a site may split its footer into several sibling divs
    # (e.g. one per office location) rather than one container.
    seen_ids: set[int] = set()
    parts: list[str] = []
    for tag in soup.find_all(["div", "section"], class_=True):
        classes = " ".join(tag.get("class", []))
        if not re.search(r"\bfooter", classes, re.IGNORECASE):
            continue
        # Skip if this tag is a descendant of one we already collected (avoid duplicate text)
        if any(id(ancestor) in seen_ids for ancestor in tag.parents):
            continue
        text = tag.get_text(separator="\n", strip=True)
        if len(text) > 20:
            seen_ids.add(id(tag))
            parts.append(text)

    if parts:
        combined = "\n\n".join(parts)
        return _clean_whitespace(combined)[:1500]

    return ""


def _clean_whitespace(text: str) -> str:
    """Collapse runs of whitespace/newlines."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()
