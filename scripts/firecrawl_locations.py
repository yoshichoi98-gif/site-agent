"""
scripts/firecrawl_locations.py

Extract every physical location from clinical-research-site domains using Firecrawl,
following the validated map -> scrape -> completeness-check -> escalate workflow.

Why this shape (learned the hard way on rcaresearch.com):
  1. The "obvious" location hub page often returns ZERO addresses — they live on
     per-state / per-location subpages. So we MAP first and read the `links` to find
     where the data actually is, instead of guessing one URL.
  2. Firecrawl's extractor will sometimes FABRICATE placeholder addresses
     ("123 Research Way", "(305) 555-1234") when a JS page hasn't rendered. Two defenses:
       - the prompt forbids placeholders explicitly, and
       - any page that returns 0 locations is re-scraped with a longer `wait_for`.
  3. map() is called with NO search filter (a keyword search silently over-filters and drops
     location pages), and its link cap auto-escalates when results saturate so large networks
     aren't truncated. We pick a HUB page (parent of many location subpages) and scrape it first,
     then stop the subpage tail once a run of empties shows the hub already had everything.

Output: append-only to data/output_locations_firecrawl.csv (same columns as output_locations.csv).
Optionally also pushes rows to a Google Sheets tab (see --sheet / SHEET_TAB).

Run:
    .venv/bin/python -m scripts.firecrawl_locations --domains rcaresearch.com --verbose
    .venv/bin/python -m scripts.firecrawl_locations --input data/add_rcaresearch_input.csv
    .venv/bin/python -m scripts.firecrawl_locations --domains a.com,b.com --sheet <url-or-id>
"""
import argparse
import csv
import logging
import os
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from firecrawl import Firecrawl

load_dotenv("/Users/yoshichoi/site-agent/.env")
logger = logging.getLogger("firecrawl_locations")

API_KEY = os.environ["FIRECRAWL_API_KEY"]
OUT_PATH = "data/output_locations_firecrawl.csv"
SERVICE_ACCOUNT_PATH = "credentials/google_service_account.json"
SHEET_TAB = "locations_firecrawl"  # worksheet/tab name inside the target spreadsheet

# CSV columns — must match data/output_locations.csv exactly so the two are interchangeable.
FIELDNAMES = [
    "domain", "location_name", "address_street", "address_city", "address_state",
    "address_zip", "phone", "source_url", "snippet", "confidence",
    "validation_status", "source",
]

# Tuning
FIRST_PASS_WAIT_MS = 6000     # most JS location lists settle within ~6s
ESCALATE_WAIT_MS = 12000      # retry budget for pages that came back empty
MAP_LIMIT = 500               # initial map breadth (one cheap call)
MAP_LIMIT_MAX = 10000         # escalate the cap up to here when the map saturates (big networks)
EMPTY_TAIL_STOP = 3           # stop scraping the subpage tail after this many empties in a row
REQUEST_TIMEOUT_S = 90        # per-request HTTP timeout (seconds). MUST exceed a legit 12s-wait
                              # scrape + render (~30-60s). Without it the SDK hangs forever when a
                              # socket dies (e.g. wifi switch) instead of failing into our backoff.

# Which mapped URLs are worth scraping for addresses. We always add the homepage + /contact.
# NOTE the trailing `s?` on the group: it MUST match plurals like "/locations", "/offices",
# "/our-locations" — these are the single most common location-page URLs. (An earlier version
# only pluralized "site", so "/locations" silently failed to match and was never scraped:
# 1sturology.com → 1 instead of 14.)
LOCATION_HINT = re.compile(
    r"(location|office|clinic|center|centre|contact|find-a|where|visit|direction|site)s?\b",
    re.I,
)
# Pages that are almost never address-bearing — skip to save credits. Also pluralized so
# "/careers", "/providers", "/doctors", "/jobs" are skipped, not scraped for nothing.
SKIP_HINT = re.compile(
    r"(privacy|terms|career|job|blog|news|leadership|team|provider|doctor|staff|"
    r"login|patient-portal|sitemap|cookie|accessibility)s?\b",
    re.I,
)

# ── Extraction schema + prompt ────────────────────────────────────────────────

class Location(BaseModel):
    location_name:  Optional[str] = Field(None, description="Office/site label, e.g. 'Austin - Main Office'. Null if unlabeled.")
    address_street: Optional[str] = Field(None, description="Street address including suite/unit")
    address_city:   Optional[str] = Field(None, description="City")
    address_state:  Optional[str] = Field(None, description="2-letter US state abbreviation")
    address_zip:    Optional[str] = Field(None, description="5-digit ZIP")
    phone:          Optional[str] = Field(None, description="Phone for this specific location")


class Locations(BaseModel):
    locations: list[Location] = Field(default_factory=list)


PROMPT = """\
Extract every physical office/clinic location whose address LITERALLY appears in this page's content.

CRITICAL RULES:
1. A STREET ADDRESS IS REQUIRED. Look hard for the full street address (building number + street
   name, e.g. "170 Dr. Arla Way, Suite 101") for every location — it is almost always present on
   the page, sometimes in a footer, an expandable/table view, or next to a map. Put ONLY the real
   street in address_street. If you truly cannot find a street for a location, leave address_street
   empty — do NOT substitute the city, region, landmark, or building name to fill it.
2. NEVER invent, guess, or use placeholder/example data. Do not output sample addresses such as
   "123 Research Way" or phone numbers like "(555) 555-1234". If no real address is present,
   return an empty list.
3. ONE entry per UNIQUE physical street address. Do not create separate entries per doctor or
   service at the same address. If a page lists 5 doctors at one office, that is ONE location.
4. EXCLUDE partner practices, affiliates, and referral networks. Only locations operated by this org.
5. Expand any "Show More" / paginated / map-marker content and include all of those addresses.
"""

SCHEMA = Locations.model_json_schema()


def json_format() -> dict:
    return {"type": "json", "prompt": PROMPT, "schema": SCHEMA}


# ── Helpers ───────────────────────────────────────────────────────────────────

def has_street(loc: dict) -> bool:
    """True only for a REAL street address — one with a building number. Guards against the
    model stuffing a city/landmark ("Jeffersonville, IN", "Dupont Square") into the street
    field to satisfy the street-required rule. ~99% of clinic addresses carry a number."""
    return bool(re.search(r"\d", str(loc.get("address_street", "") or "")))


def looks_like_placeholder(loc: dict) -> bool:
    """Heuristic guard against the fabricated-address failure mode."""
    blob = " ".join(str(loc.get(k, "")) for k in ("address_street", "phone", "location_name")).lower()
    if re.search(r"\b555[-).\s]?\d{4}\b", blob):
        return True
    if re.search(r"\b123 (research|study|main|example)\b", blob):
        return True
    if "location a" in blob or "location b" in blob or "example" in blob:
        return True
    return False


def _link_url(link) -> str:
    """A mapped/harvested link may be a plain URL string, an SDK object with .url, or a dict."""
    if isinstance(link, str):
        return link
    if hasattr(link, "url"):
        return link.url
    if isinstance(link, dict):
        return link.get("url", "")
    return ""


def candidate_pages(domain: str, map_links: list) -> list[tuple[str, str]]:
    """Ordered (kind, url) pages worth scraping. Always the homepage and /contact.

    Crucially: when several mapped subpages share a parent path (e.g. 20× /locations/<clinic>),
    that parent (/locations) is almost certainly a HUB that lists every address on one page.
    map() frequently omits the bare index URL itself, so we synthesize it and scrape it FIRST —
    this is what was missing on bostonivf.com, where every individual /locations/<x> subpage
    rendered its address via JS and came back empty. kind ∈ {hub, home, contact, page}.

    `map_links` may mix SDK link objects (from map) and plain URL strings (harvested from the
    homepage), so that pages map() misses but the homepage links to still become candidates.
    """
    base = f"https://{domain}".rstrip("/")

    loc_urls: list[str] = []
    parent_kids: dict[str, set] = defaultdict(set)
    for link in map_links:
        url = _link_url(link)
        if not url:
            continue
        parts = urlparse(url)
        path = parts.path
        if SKIP_HINT.search(path):
            continue
        if LOCATION_HINT.search(path):
            loc_urls.append(url)
            segs = [s for s in path.rstrip("/").split("/") if s]
            if len(segs) >= 2:  # has a parent dir worth treating as a hub
                parent = f"{parts.scheme}://{parts.netloc}/" + "/".join(segs[:-1])
                parent_kids[parent].add(path)

    ordered: list[tuple[str, str]] = []
    seen = set()

    def add(kind: str, u: str):
        u = u.split("?")[0].split("#")[0].rstrip("/")  # drop query/fragment; dedupe page-level
        if u and u not in seen:
            seen.add(u)
            ordered.append((kind, u))

    # Hubs first, most-children first (likeliest to carry the complete list on one page).
    for parent, kids in sorted(parent_kids.items(), key=lambda kv: -len(kv[1])):
        if len(kids) >= 2:
            add("hub", parent)
    add("home", base)
    add("contact", f"{base}/contact")
    for url in loc_urls:
        add("page", url)
    return ordered


# Serializes the append-only CSV write so concurrent worker threads never interleave rows.
_write_lock = threading.Lock()

_RATE_LIMIT_MARKERS = ("429", "rate limit", "ratelimit", "too many requests", "rate_limit")


def _call_with_backoff(fn, *args, _what="firecrawl call", _max_tries=5, **kwargs):
    """Call a Firecrawl SDK method, retrying on rate-limit (429) / transient errors with
    exponential backoff. Lets concurrent runs ride out the plan's concurrency ceiling
    instead of dropping a domain's rows the moment we hit a 429."""
    last = None
    for attempt in range(1, _max_tries + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # SDK raises plain exceptions; inspect the message
            last = e
            is_rate = any(m in str(e).lower() for m in _RATE_LIMIT_MARKERS)
            if attempt == _max_tries:
                break
            wait = 5.0 * attempt if is_rate else 3.0
            logger.warning(f"  {_what} failed (attempt {attempt}/{_max_tries}, "
                           f"{'rate-limited' if is_rate else 'transient'}): {e} — retrying in {wait:.0f}s")
            time.sleep(wait)
    raise last


# road-type / unit / directional words that aren't distinctive enough to anchor a street name
_NONDISTINCTIVE = {
    "suite", "ste", "unit", "floor", "apt", "bldg", "building", "north", "south", "east", "west",
    "street", "st", "avenue", "ave", "road", "rd", "drive", "dr", "lane", "ln", "court", "ct",
    "place", "pl", "boulevard", "blvd", "highway", "hwy", "route", "rt", "rte", "circle", "cir",
    "terrace", "ter", "parkway", "pkwy", "way", "trail", "square", "plaza",
}


def street_on_page(street: str, page_text: str) -> bool:
    """Anti-hallucination guard: confirm the extracted street actually appears on the page.

    The model fabricates plausible addresses that AREN'T on the page — both one-offs (epilepsygroup's
    fake "170 Dr. Arla Way") and whole SERIES (universitygi: "2025 West River", "2025 Warren",
    "2025 Smithfield"… — it reused the year "2025" as the number for every made-up street). The old
    guard checked the number and a street word INDEPENDENTLY, so a fake passed whenever the year and
    some real place-name both happened to appear somewhere on the page.

    Fix: require the street NUMBER and its first DISTINCTIVE name word (not a road-type/directional)
    to appear ADJACENT on the page (within ~50 chars). A real "2025 West River" is contiguous; a fake
    "2025 Warren Avenue" is not (2025 and Warren live in different places on the page). Lenient when
    there's nothing reliable to anchor on (no leading number, or only road-type words) — keep the row."""
    pt = re.sub(r"[^a-z0-9]+", " ", page_text.lower())
    m = re.match(r"\s*(\d+)", street)
    if not m:
        return True  # no leading building number to verify — don't drop
    num = m.group(1)
    words = re.findall(r"[a-z]{3,}", street.lower())
    distinctive = [w for w in words if w not in _NONDISTINCTIVE] or [w for w in words if w not in ("suite", "ste", "unit", "floor")]
    if not distinctive:
        return num in pt.split()  # nothing distinctive — fall back to number-as-token
    w = distinctive[0]
    return re.search(rf"\b{re.escape(num)}\b[^0-9]{{0,50}}\b{re.escape(w)}\b", pt) is not None


def scrape_page(app: Firecrawl, url: str, wait_ms: int) -> list[dict]:
    """Scrape one URL with the JSON schema; return list of location dicts (may be empty).
    Also pulls the page markdown (same call, no extra credit) to verify each extracted street
    is really on the page — drops fabricated addresses."""
    doc = _call_with_backoff(app.scrape, url, formats=[json_format(), "markdown"],
                             only_main_content=True, wait_for=wait_ms, _what=f"scrape {url}")
    data = getattr(doc, "json", None) or {}
    page_text = getattr(doc, "markdown", "") or ""
    locs = data.get("locations", []) if isinstance(data, dict) else []
    out = []
    for loc in locs:
        loc = loc if isinstance(loc, dict) else (loc.model_dump() if hasattr(loc, "model_dump") else dict(loc))
        if looks_like_placeholder(loc):
            logger.warning(f"  dropped placeholder-looking row from {url}: {loc.get('address_street')!r}")
            continue
        street = str(loc.get("address_street", "") or "")
        if street and page_text and not street_on_page(street, page_text):
            logger.warning(f"  dropped off-page (likely hallucinated) row from {url}: {street!r}")
            continue
        loc["source_url"] = url
        out.append(loc)
    return out


# Common US road-type / directional abbreviations → canonical form, so that
# "St"/"Street", "Rd"/"Road", "Blvd"/"Boulevard" etc. share a first-word signature.
_ROAD_ABBR = {
    "st": "street", "str": "street", "rd": "road", "ave": "avenue", "av": "avenue",
    "blvd": "boulevard", "ln": "lane", "dr": "drive", "rt": "route", "rte": "route",
    "hwy": "highway", "sq": "square", "pkwy": "parkway", "ct": "court", "pl": "place",
    "ter": "terrace", "cir": "circle", "n": "north", "s": "south", "e": "east", "w": "west",
}


def _street_signature(street: str) -> tuple[str, str]:
    """(street_number, normalized_first_word). The number keeps distinct addresses on
    the same street apart (473 vs 477 Lakehurst); the first word collapses St/Street,
    Rd/Road, etc. spelling variants of the SAME building."""
    s = street.strip().lower()
    if not s:
        return ("", "")
    # Strip a leading building NAME: "Village Square at Howell, 59 Kent Rd" → "59 Kent Rd".
    # Only when the text BEFORE the first comma is a name (has letters, doesn't start with a
    # street number); otherwise a trailing ", 2nd Floor" / ", Suite 5" would clobber the street.
    if "," in s:
        head, rest = s.split(",", 1)
        if not re.match(r"\s*\d", head) and re.search(r"[a-z]", head) and re.match(r"\s*\d", rest):
            s = rest
    m = re.match(r"\s*(\d+)", s)
    num = m.group(1) if m else ""
    tail = s[m.end():] if m else s
    word = ""
    for tok in re.findall(r"[a-z]+", tail):
        word = _ROAD_ABBR.get(tok, tok)
        break
    return (num, word)


def _city_key(city: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(city).lower())


def dedupe(locs: list[dict]) -> list[dict]:
    """Collapse rows that point at the same physical office.

    Keyed on (zip, street-number, normalized-first-street-word) so that:
      (a) a street-less row (e.g. homepage city/zip only) that duplicates a real
          street-bearing row in the same zip/city is dropped, and
      (b) near-dups with different street SPELLINGS ("St" vs "Street") collapse —
    while genuinely distinct offices in one zip (473 vs 477 Lakehurst) stay separate.
    Validated offline against the 105-row allieddigestivehealth run (→ 86 unique);
    see scripts/validate_dedupe.py.
    """
    zips_with_street, cities_with_street = set(), set()
    for loc in locs:
        if str(loc.get("address_street", "")).strip():
            z = str(loc.get("address_zip", "")).strip()
            c = _city_key(loc.get("address_city", ""))
            if z:
                zips_with_street.add(z)
            if c:
                cities_with_street.add(c)

    seen = set()
    out = []
    for loc in locs:
        street = str(loc.get("address_street", "")).strip()
        z = str(loc.get("address_zip", "")).strip()
        c = _city_key(loc.get("address_city", ""))

        if not street:
            if (z and z in zips_with_street) or (c and c in cities_with_street):
                logger.info(f"  dropped street-less row {loc.get('address_city')!r} {z} "
                            f"(covered by a street-bearing row)")
                continue
            if not z and not c:  # no address at all — skip
                continue
            key = ("__nostreet__", z, c)
        else:
            num, word = _street_signature(street)
            geo = z if z else c
            key = (geo, num, word)

        if key in seen:
            continue
        seen.add(key)
        out.append(loc)
    return out


def map_site(app: Firecrawl, base: str, domain: str) -> list:
    """Map the whole site, escalating the link cap when the result saturates so big
    multi-location networks aren't silently truncated. map() is ONE cheap call, so when we
    get back exactly the cap we asked for (a strong sign there's more), we re-map at a higher
    cap and keep going until results stop saturating or we hit MAP_LIMIT_MAX.

    NO search filter: a multi-keyword `search=` makes Firecrawl's map semantically over-filter
    and silently drop location pages (3sync.com → 4 links with a search string vs 28 without).
    We map broadly and filter locally with LOCATION_HINT/SKIP_HINT — far more reliable for recall.
    """
    limit = MAP_LIMIT
    while True:
        mp = _call_with_backoff(app.map, base, limit=limit, _what=f"map {domain} (cap={limit})")
        links = mp.links if hasattr(mp, "links") else []
        if len(links) < limit or limit >= MAP_LIMIT_MAX:
            return links
        new_limit = min(limit * 4, MAP_LIMIT_MAX)
        logger.info(f"[{domain}] map returned {len(links)} = cap {limit} (likely truncated) "
                    f"→ re-mapping at {new_limit}")
        limit = new_limit


def harvest_home_links(app: Firecrawl, base: str, domain: str) -> list[str]:
    """Return the links the HOMEPAGE actually points to. map() relies on sitemap/crawl and can
    miss pages that are plainly linked from the homepage nav — epilepsygroup.com's offices page
    (`/epilepsy-treatment-offices3-8/offices.htm`, 10 addresses) was absent from all 93 mapped
    links but present in the homepage's links. We union these into discovery so we err toward
    finding every locations page, not fewer."""
    try:
        doc = _call_with_backoff(app.scrape, base, formats=["links"], only_main_content=False,
                                 wait_for=FIRST_PASS_WAIT_MS, _what=f"home-links {domain}")
        return list(getattr(doc, "links", None) or [])
    except Exception as e:
        logger.warning(f"[{domain}] homepage link harvest failed: {e}")
        return []


def process_domain(app: Firecrawl, domain: str) -> list[dict]:
    """Full workflow for one domain. Returns deduped location rows ready for CSV."""
    t0 = time.time()
    base = f"https://{domain}"
    logger.info(f"[{domain}] mapping…")
    try:
        links = map_site(app, base, domain)
    except Exception as e:
        logger.error(f"[{domain}] map failed: {e} — falling back to homepage+/contact only")
        links = []

    # Union the homepage's own links into discovery — catches location pages map() missed
    # (we'd rather over-discover than miss any). candidate_pages handles the mixed link types.
    home_links = harvest_home_links(app, base, domain)
    all_links = list(links) + home_links

    pages = candidate_pages(domain, all_links)
    logger.info(f"[{domain}] {len(links)} mapped + {len(home_links)} homepage links, "
                f"{len(pages)} candidate pages")

    def _missing_street(ls: list[dict]) -> bool:
        return any(not has_street(loc) for loc in ls)

    def _score(ls: list[dict]) -> tuple:  # prefer the pass with more REAL-street rows, then more rows
        return (sum(1 for loc in ls if has_street(loc)), len(ls))

    all_locs: list[dict] = []
    empty_streak = 0
    hub_had_locations = False
    for kind, url in pages:
        # Early-stop the individual-subpage tail ONLY when a HUB page already returned a list.
        # In that case the per-clinic subpages are redundant detail pages (bostonivf's hub had
        # all 22; every subpage rendered empty), so a run of empties means "nothing left to add".
        # We gate strictly on hub_had_locations: if NO hub produced results, the subpages are the
        # ONLY source of addresses, so we scrape every one — never risk skipping real data that
        # sits past a few empties. We also don't use the heuristic expected-count (unreliable).
        if kind == "page" and hub_had_locations and empty_streak >= EMPTY_TAIL_STOP:
            logger.info(f"  [{domain}] {empty_streak} empty subpages in a row after a hub gave "
                        f"{len(dedupe(all_locs))} → skipping the redundant subpage tail")
            break
        try:
            locs = scrape_page(app, url, FIRST_PASS_WAIT_MS)
            # Escalate (longer wait) when the page is EMPTY, or when it returned locations that
            # are MISSING a street — the street is almost always on the page, so a miss usually
            # means it hadn't finished rendering. Keep whichever pass recovered more streets.
            path = urlparse(url).path
            if (not locs and LOCATION_HINT.search(path)) or _missing_street(locs):
                reason = "empty" if not locs else "missing street(s)"
                logger.info(f"  [{url}] {reason} on first pass → retry with wait_for={ESCALATE_WAIT_MS}ms")
                retry = scrape_page(app, url, ESCALATE_WAIT_MS)
                if _score(retry) >= _score(locs):
                    locs = retry
            if locs:
                logger.info(f"  [{url}] {len(locs)} location(s)")
                empty_streak = 0
                if kind == "hub":
                    hub_had_locations = True
            elif kind == "page":
                empty_streak += 1
            all_locs.extend(locs)
        except Exception as e:
            logger.error(f"  [{url}] scrape failed: {e}")
            if kind == "page":
                empty_streak += 1

    deduped = dedupe(all_locs)
    # A real street address (with a building number) is REQUIRED — a name/city-only row, or one
    # where the model stuffed a city into the street field, isn't usable. Drop them (logged, never
    # silent) as the reliable backstop to the prompt's street-required rule + the retry above.
    with_street = [loc for loc in deduped if has_street(loc)]
    if len(with_street) < len(deduped):
        logger.info(f"  [{domain}] dropped {len(deduped) - len(with_street)} row(s) without a real street address")
    deduped = with_street
    dur = time.time() - t0
    # No expected-count comparison (unreliable). We only flag the unambiguous failure: zero.
    note = f"  ⚠ NO LOCATIONS FOUND — review {domain}" if not deduped else ""
    logger.info(f"[{domain}] done: {len(deduped)} locations in {dur:.0f}s{note}")

    rows = []
    for loc in deduped:
        rows.append({
            "domain": domain,
            "location_name": loc.get("location_name") or "",
            "address_street": loc.get("address_street") or "",
            "address_city": loc.get("address_city") or "",
            "address_state": loc.get("address_state") or "",
            "address_zip": loc.get("address_zip") or "",
            "phone": loc.get("phone") or "",
            "source_url": loc.get("source_url") or "",
            # snippet / confidence / validation_status intentionally left blank — kept only so the
            # columns line up 1:1 with output_locations.csv. (Yoshi doesn't use these three.)
            "snippet": "",
            "confidence": "",
            "validation_status": "",
            "source": "firecrawl",
        })
    return rows


# ── I/O ───────────────────────────────────────────────────────────────────────

def already_processed() -> set[str]:
    """Idempotent reruns: skip domains already in the output CSV."""
    if not os.path.exists(OUT_PATH):
        return set()
    with open(OUT_PATH, newline="", encoding="utf-8") as f:
        return {r["domain"] for r in csv.DictReader(f) if r.get("domain")}


def append_rows(rows: list[dict]) -> None:
    """Append-only write; create header if file is new. Lock-guarded so concurrent
    worker threads never interleave each other's rows mid-write."""
    if not rows:
        return
    with _write_lock:
        new_file = not os.path.exists(OUT_PATH)
        with open(OUT_PATH, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
            if new_file:
                w.writeheader()
            w.writerows(rows)


def load_domains(args) -> list[str]:
    if args.domains:
        return [d.strip() for d in args.domains.split(",") if d.strip()]
    domains = []
    with open(args.input, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        col = "domain" if "domain" in (reader.fieldnames or []) else (reader.fieldnames or [None])[0]
        for r in reader:
            d = (r.get(col) or "").strip()
            if d:
                domains.append(d)
    return domains


def push_to_sheet(sheet_ref: str) -> None:
    """Push the full output CSV to a Google Sheets tab named SHEET_TAB.

    Requires the spreadsheet to be shared (Editor) with the service account email in
    credentials/google_service_account.json. sheet_ref may be a full URL or a bare key.
    """
    import gspread  # imported lazily so the core CSV path has no hard dependency

    gc = gspread.service_account(filename=SERVICE_ACCOUNT_PATH)
    sh = gc.open_by_url(sheet_ref) if sheet_ref.startswith("http") else gc.open_by_key(sheet_ref)

    with open(OUT_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        logger.warning("nothing in output CSV to push")
        return

    try:
        ws = sh.worksheet(SHEET_TAB)
        ws.clear()
        logger.info(f"cleared existing tab '{SHEET_TAB}'")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=SHEET_TAB, rows=max(len(rows) + 10, 100), cols=len(FIELDNAMES))
        logger.info(f"created tab '{SHEET_TAB}'")

    ws.update(rows, value_input_option="RAW")
    logger.info(f"pushed {len(rows) - 1} data rows to tab '{SHEET_TAB}' in {sh.title}")


def main():
    ap = argparse.ArgumentParser(description="Extract locations via Firecrawl (map→scrape→check→escalate).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--domains", help="Comma-separated domains, e.g. 'rcaresearch.com,foo.com'")
    src.add_argument("--input", help="CSV file with a 'domain' column")
    ap.add_argument("--limit", type=int, default=None, help="Max domains to process this run")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="Domains processed in parallel (default 1=sequential; Firecrawl Standard ~8 is safe)")
    ap.add_argument("--sheet", default=None, help="Google Sheet URL or key to push results to")
    ap.add_argument("--no-resume", action="store_true", help="Reprocess domains already in the CSV")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    domains = load_domains(args)
    done = set() if args.no_resume else already_processed()
    todo = [d for d in domains if d not in done]
    if done:
        logger.info(f"resuming: {len(done)} already done, {len(todo)} to go")
    if args.limit:
        todo = todo[: args.limit]

    app = Firecrawl(api_key=API_KEY, timeout=REQUEST_TIMEOUT_S)
    n = len(todo)
    grand_total = 0

    def work(domain: str) -> int:
        rows = process_domain(app, domain)
        append_rows(rows)  # lock-guarded, per-domain, so a crash never loses prior work
        return len(rows)

    if args.concurrency > 1 and n > 1:
        logger.info(f"processing {n} domains with concurrency={args.concurrency}")
        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            futures = {ex.submit(work, d): d for d in todo}
            for done_n, fut in enumerate(as_completed(futures), 1):
                d = futures[fut]
                try:
                    cnt = fut.result()
                    grand_total += cnt
                    logger.info(f"=== done ({done_n}/{n}) {d}: {cnt} locations ===")
                except Exception as e:
                    logger.error(f"=== ({done_n}/{n}) {d} FAILED: {e}")
    else:
        for i, domain in enumerate(todo, 1):
            logger.info(f"=== ({i}/{n}) {domain} ===")
            grand_total += work(domain)

    logger.info(f"FINISHED: {grand_total} locations across {n} domains → {OUT_PATH}")

    if args.sheet:
        push_to_sheet(args.sheet)


if __name__ == "__main__":
    main()
