"""
scripts/smart_location_recount.py

For every UNDER or OVER row in output_org_value_match.csv, re-enumerates
locations using a 3-tier discovery strategy:

  Tier 1 — Sitemap:       fetch /sitemap.xml (and index), get all URLs,
                          ask LLM which ones likely have location data,
                          fetch those pages, extract locations.

  Tier 2 — Homepage crawl: if no sitemap, fetch homepage, pull all <a href>
                          links, ask LLM which ones to fetch, same extraction.

  Tier 3 — Common paths:  if no links found, try /locations, /offices,
                          /find-a-location, etc. directly.

  Fallback — Flag:        if none of the above yields pages, mark as
                          NEEDS_MANUAL and move on.

Outputs:
  data/output_locations_smart_recount.csv   — new location rows
  data/output_org_value_match.csv           — 3 new columns added in-place
  data/smart_recount_report.md              — summary report

Usage:
    python -m scripts.smart_location_recount [--concurrency N] [--limit N] [--verbose]
"""
import argparse
import asyncio
import concurrent.futures
import csv
import logging
import os
import re
import sys
import time
from collections import defaultdict
from urllib.parse import urljoin, urlparse

import anthropic
import httpx
import instructor
from pydantic import BaseModel, Field

import src.llm_log as llm_log
from src.config import ANTHROPIC_API_KEY, MODEL
from src.location_extract import extract_locations
from src.pipeline import add_cost, get_run_cost, reset_run_cost

_MAX_COST_USD = float("inf")   # set from --max-cost in __main__

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────
DATA        = os.path.join(os.path.dirname(__file__), "..", "data")
ORGS_PATH   = os.path.join(DATA, "output_org_value_match.csv")
LOCS_PATH   = os.path.join(DATA, "output_locations.csv")
OUT_LOCS    = os.path.join(DATA, "output_locations_smart_recount.csv")
REPORT_PATH = os.path.join(DATA, "smart_recount_report.md")

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompts", "url_selector.txt")
with open(PROMPT_PATH) as f:
    _URL_SELECTOR_PROMPT = f.read()

# ── Config ───────────────────────────────────────────────────────────────────
MAX_SITEMAP_URLS      = 500    # max URLs to collect from sitemap before truncating
MAX_URLS_TO_LLM       = 500    # max URLs to send to LLM (context limit)
MAX_URLS_TO_FETCH     = 100    # max pages to fetch per domain — bumped from 20 to avoid missing locations
DOMAIN_CONCURRENCY    = 30     # concurrent domains — bumped from 15 (LLM-side only, no IP risk)

# Common location page paths to try when sitemap and crawl both fail
_COMMON_LOCATION_PATHS = [
    "/locations", "/our-locations", "/find-a-location", "/find-location",
    "/offices", "/our-offices", "/clinics", "/our-clinics",
    "/centers", "/our-centers", "/find-care", "/contact",
    "/about/locations", "/about-us/locations", "/visit-us",
    "/locations/all", "/locations/list",
]

NEW_COLS = ["smart_recount_status", "smart_recount_count", "smart_recount_source"]

LOC_COLS = [
    "domain", "location_name", "address_street", "address_city",
    "address_state", "address_zip", "phone", "source_url", "snippet",
    "confidence", "validation_status", "source",
]


# ── Pydantic schema for URL selector LLM call ────────────────────────────────

class URLSelection(BaseModel):
    selected_urls: list[str] = Field(
        description="URLs from the provided list most likely to contain physical location/address data. Max 20."
    )
    reasoning: str = Field(
        description="One sentence explaining which signals you used to select these URLs."
    )


# ── LLM: URL selector ────────────────────────────────────────────────────────

def _select_urls_via_llm(domain: str, urls: list[str]) -> list[str]:
    """
    Ask the LLM to pick which URLs from the list are most likely to have
    location/address data. Returns list of selected URLs (subset of input).
    """
    client = instructor.from_anthropic(anthropic.Anthropic(api_key=ANTHROPIC_API_KEY))

    # Truncate to MAX_URLS_TO_LLM — prioritise location-looking ones first
    # so the most relevant survive the cut if there are thousands.
    priority = [u for u in urls if any(
        sig in u.lower() for sig in [
            "location", "office", "clinic", "center", "centre",
            "find", "contact", "about", "visit", "address",
        ]
    )]
    rest = [u for u in urls if u not in set(priority)]
    trimmed = (priority + rest)[:MAX_URLS_TO_LLM]

    url_list = "\n".join(trimmed)
    # NOTE: use .replace (not .format) — the prompt contains literal braces like "{slug}"
    # in example URL patterns that .format() would choke on (KeyError: 'slug').
    prompt = (_URL_SELECTOR_PROMPT
              .replace("{domain}", domain)
              .replace("{count}", str(len(trimmed)))
              .replace("{url_list}", url_list))

    t0 = time.time()
    try:
        result, completion = client.chat.completions.create_with_completion(
            model=MODEL,
            max_tokens=4096,  # bumped from 1024 — sites with 100+ location URLs overflowed → max_tokens crash
            messages=[{"role": "user", "content": prompt}],
            response_model=URLSelection,
        )
    except Exception as e:
        # FAIL-SOFT: never let one domain's selector abort the whole run. Fall back to the
        # heuristic location-looking URLs (the priority list) capped at the fetch budget.
        fallback = (priority or trimmed)[:MAX_URLS_TO_FETCH]
        logger.warning(f"[{domain}] url_selector failed ({type(e).__name__}) — heuristic fallback ({len(fallback)} urls)")
        return fallback
    duration = time.time() - t0
    usage = completion.usage
    add_cost(usage.input_tokens, usage.output_tokens)
    llm_log.write({
        "name": "url_selector",
        "model": MODEL,
        "timestamp": time.time(),
        "duration_s": round(duration, 2),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "domain": domain,
        "urls_in": len(trimmed),
        "urls_selected": len(result.selected_urls),
    })

    # Validate — only return URLs that were actually in our input list
    input_set = set(trimmed)
    valid = [u for u in result.selected_urls if u in input_set]
    logger.info(
        f"[{domain}] url_selector: {len(trimmed)} in → {len(result.selected_urls)} selected "
        f"({len(valid)} valid) | {usage.input_tokens}in/{usage.output_tokens}out | {result.reasoning}"
    )
    return valid[:MAX_URLS_TO_FETCH]


# ── Sitemap discovery via ultimate-sitemap-parser ────────────────────────────
#
# usp handles everything: robots.txt parsing, sitemap index recursion,
# gzipped sitemaps, all XML formats (Google News, plain text, RSS, Atom).
# We run it in a thread executor so it doesn't block the async event loop,
# and wrap it in a 60s timeout to avoid hanging on massive sitemaps.

# Sub-sitemap names to skip — these are content feeds, not location pages.
# usp's recurse_list_callback lets us prune the recursion tree early so we
# never fetch blog/news sub-sitemaps that could have 100K+ URLs.
_SKIP_SITEMAP_PATTERNS = ["blog", "news", "post", "author", "category", "tag", "archive"]
_KEEP_SITEMAP_PATTERNS = ["location", "office", "clinic", "branch", "page", "main", "store"]

USP_TIMEOUT_SECONDS = 15  # lowered from 30 — broken sitemaps wasted 30s each


def _usp_filter_callback(urls: list[str], recursion_level: int, parent_urls: set) -> list[str]:
    """
    Called by usp before recursing into each child sitemap.
    Prunes sub-sitemaps that are clearly content feeds (blog, news, etc.)
    so we don't waste time on 50K post URLs.
    Keep anything that looks location-related or is ambiguous.
    """
    filtered = []
    for url in urls:
        lower = url.lower()
        # Explicit keep signals override skip signals
        if any(p in lower for p in _KEEP_SITEMAP_PATTERNS):
            filtered.append(url)
        elif any(p in lower for p in _SKIP_SITEMAP_PATTERNS):
            logger.debug(f"usp: skipping sub-sitemap {url}")
        else:
            filtered.append(url)  # keep ambiguous ones
    return filtered


def _run_usp(homepage_url: str) -> list[str]:
    """
    Synchronous usp call — runs in a thread executor.
    Returns list of page URLs, capped at MAX_SITEMAP_URLS.
    """
    from usp.tree import sitemap_tree_for_homepage
    tree = sitemap_tree_for_homepage(
        homepage_url,
        recurse_list_callback=_usp_filter_callback,
    )
    urls = []
    for page in tree.all_pages():
        if page.url:
            urls.append(page.url)
        if len(urls) >= MAX_SITEMAP_URLS:
            break
    return urls


# Resolve the host that actually serves content (apex vs www). Many clinical sites' TLS cert is
# valid only for www, so strict-SSL requests to the apex fail even though browsers work fine.
_BASE_CACHE: dict[str, str] = {}
_BASE_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
# Module-level executor for usp so an asyncio.wait_for timeout actually frees the coroutine.
# (A per-call `with ThreadPoolExecutor()` blocks on shutdown waiting for the orphaned usp thread —
# that's why broken-sitemap domains hung the whole batch for minutes.)
_USP_EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=80)


async def _working_base(domain: str) -> str:
    """Return https://<host> that actually responds (apex, else www) — handles apex-cert mismatch."""
    if domain in _BASE_CACHE:
        return _BASE_CACHE[domain]
    base = f"https://{domain}"
    for cand in (f"https://{domain}", f"https://www.{domain}"):
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True, headers=_BASE_UA) as c:
                r = await c.head(cand)
            base = f"https://{urlparse(str(r.url)).netloc}" or cand
            break
        except Exception:
            continue
    _BASE_CACHE[domain] = base
    return base


async def discover_all_sitemap_urls(domain: str) -> tuple[list[str], str]:
    """
    Discover all sitemap URLs for a domain using usp, against the working host (apex/www).
    Hard-timeboxed via a module executor so broken sitemaps bail and fall through to other tiers.
    Returns (page_urls, sitemap_source_label).
    """
    homepage_url = await _working_base(domain)
    loop = asyncio.get_event_loop()

    try:
        urls = await asyncio.wait_for(
            loop.run_in_executor(_USP_EXEC, _run_usp, homepage_url),
            timeout=USP_TIMEOUT_SECONDS,
        )
        if urls:
            logger.info(f"[{domain}] usp: {len(urls)} URLs collected")
            return urls, f"{homepage_url}/sitemap (via usp)"
        else:
            logger.info(f"[{domain}] usp: no sitemap found")
            return [], ""
    except asyncio.TimeoutError:
        logger.warning(f"[{domain}] usp timed out after {USP_TIMEOUT_SECONDS}s")
        return [], ""
    except Exception as e:
        logger.warning(f"[{domain}] usp failed: {e}")
        return [], ""


# ── Homepage crawl fallback ───────────────────────────────────────────────────

async def crawl_homepage_links(domain: str) -> list[str]:
    """
    Fetch the homepage and extract all internal <a href> links.
    Returns list of absolute URLs on the same domain.
    """
    base = await _working_base(domain)
    # Discovery via Firecrawl too (not just local fetch) so hard-blocked sites still yield links.
    loop = asyncio.get_event_loop()
    html = await loop.run_in_executor(_FC_EXEC, _fc_scrape_html, base)
    if not html:
        return []

    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        absolute = urljoin(base, href)
        # Only keep same-domain links
        if urlparse(absolute).netloc.replace("www.", "") == domain.replace("www.", ""):
            links.add(absolute)

    logger.info(f"[{domain}] homepage crawl: {len(links)} internal links found")
    return list(links)


# ── Common paths fallback ─────────────────────────────────────────────────────

async def try_common_paths(domain: str) -> list[str]:
    """
    Try common location page paths directly. Returns paths that return 200 OK.
    """
    base = await _working_base(domain)
    found = []
    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 Chrome/124"},
    ) as client:
        for path in _COMMON_LOCATION_PATHS:
            try:
                r = await client.head(f"{base}{path}")
                if r.status_code == 200:
                    found.append(f"{base}{path}")
                    logger.info(f"[{domain}] common path found: {path}")
            except Exception:
                pass
    return found


# ── Pattern B: subpage link extraction ───────────────────────────────────────
#
# Many sites have a "listing page" (e.g. /locations) that shows city names
# but the actual address is on a per-location subpage (/locations/austin-tx).
# We detect listing pages and follow those subpage links within the page budget.

_LOCATION_SUBPAGE_RE = re.compile(
    r"/(location|office|clinic|center|branch|site|practice|provider)"
    r"s?/[a-z0-9][a-z0-9\-]+",
    re.IGNORECASE,
)


def _extract_location_subpage_links(page_url: str, html: str, domain: str) -> list[str]:
    """
    From a fetched page, find links that look like individual location subpages.
    E.g. /locations/austin-tx, /offices/beverly-hills — depth-2 paths under
    a location-category parent.

    Returns absolute URLs on the same domain, deduplicated.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    candidates: set[str] = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        # Same domain only
        if parsed.netloc.replace("www.", "") != domain.replace("www.", ""):
            continue
        # Must match the location subpage path pattern
        if _LOCATION_SUBPAGE_RE.search(parsed.path):
            candidates.add(absolute)
    return list(candidates)


# ── Firecrawl fetcher (default — strong anti-bot/JS rendering) ────────────────
FIRECRAWL_CONCURRENCY = 40   # Firecrawl Standard plan allows 50 concurrent — stay under with headroom
_FC_CLIENT = None
_FC_SEM = None
# DEDICATED thread pool for blocking Firecrawl scrapes — must be >= FIRECRAWL_CONCURRENCY,
# else the default executor (~cpu+4 threads) saturates and the run deadlocks.
_FC_EXEC = concurrent.futures.ThreadPoolExecutor(max_workers=FIRECRAWL_CONCURRENCY + 8)


def _firecrawl():
    global _FC_CLIENT
    if _FC_CLIENT is None:
        from firecrawl import Firecrawl
        _FC_CLIENT = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"], timeout=60)
    return _FC_CLIENT


def _fc_scrape_html(url: str) -> str:
    """Sync Firecrawl scrape → raw HTML (run in an executor). Empty string on failure."""
    try:
        r = _firecrawl().scrape(url, formats=["rawHtml"], wait_for=2500)
        return getattr(r, "raw_html", None) or getattr(r, "rawHtml", "") or ""
    except Exception:
        return ""


def _fc_sem() -> asyncio.Semaphore:
    global _FC_SEM
    if _FC_SEM is None:
        _FC_SEM = asyncio.Semaphore(FIRECRAWL_CONCURRENCY)
    return _FC_SEM


# ── Fetch pages + extract ─────────────────────────────────────────────────────

async def fetch_and_extract(domain: str, urls: list[str]) -> tuple[list, int]:
    """
    Fetch each URL and run the location extractor on the combined content.

    Pattern B: after fetching the initial URL set, scan each page for links
    to individual location subpages (e.g. /locations/austin-tx). If found,
    fetch up to MAX_URLS_TO_FETCH total pages (using remaining budget).

    Returns (locations, pages_fetched).
    """
    # Firecrawl is the default fetcher (strong anti-bot + JS rendering).
    async def _fetch_one(url):
        async with _fc_sem():
            loop = asyncio.get_event_loop()
            html = await loop.run_in_executor(_FC_EXEC, _fc_scrape_html, url)
            if html:
                return url, html
            logger.debug(f"[{domain}] firecrawl empty: {url}")
            return url, ""

    # ── Round 1: fetch the LLM-selected URLs ─────────────────────────────────
    round1 = await asyncio.gather(*[_fetch_one(u) for u in urls])
    pages: dict[str, str] = {url: html for url, html in round1 if html}
    logger.info(f"[{domain}] fetched {len(pages)}/{len(urls)} pages (round 1)")

    # ── Pattern B: follow location subpage links ──────────────────────────────
    # Scan every successfully-fetched page for links to individual location
    # subpages. Collect candidates not already fetched, then fetch the remaining
    # budget (up to MAX_URLS_TO_FETCH total pages).
    remaining_budget = MAX_URLS_TO_FETCH - len(pages)
    if remaining_budget > 0:
        subpage_candidates: list[str] = []
        for page_url, html in pages.items():
            links = _extract_location_subpage_links(page_url, html, domain)
            subpage_candidates.extend(links)

        # Deduplicate, exclude already fetched
        already_fetched = set(pages.keys())
        new_urls = list(dict.fromkeys(
            u for u in subpage_candidates if u not in already_fetched
        ))[:remaining_budget]

        if new_urls:
            logger.info(f"[{domain}] Pattern B: following {len(new_urls)} location subpage links")
            round2 = await asyncio.gather(*[_fetch_one(u) for u in new_urls])
            for url, html in round2:
                if html:
                    pages[url] = html
            logger.info(f"[{domain}] total pages after subpage follow: {len(pages)}")

    if not pages:
        return [], 0

    try:
        loc_result, usage = extract_locations(domain, homepage_html="", additional_pages=pages)
        add_cost(usage.input_tokens, usage.output_tokens)
        return loc_result.locations, len(pages)
    except Exception as e:
        logger.error(f"[{domain}] location extractor failed: {e}")
        return [], len(pages)


# ── Per-domain orchestration ──────────────────────────────────────────────────

async def process_domain(domain: str) -> dict:
    """
    Full smart recount for one domain.
    Returns result dict with keys: domain, status, count, source, locations.
    """
    logger.info(f"[{domain}] starting smart recount")

    if get_run_cost() >= _MAX_COST_USD:
        logger.warning(f"[{domain}] cost cap ${_MAX_COST_USD:.0f} reached — skipping")
        return {"domain": domain, "status": "SKIPPED_COST_CAP", "count": None,
                "source": "none", "sitemap_used": "", "locations": []}

    # ── Tier 1: Sitemap ───────────────────────────────────────────────────────
    sitemap_urls, sitemap_used = await discover_all_sitemap_urls(domain)

    if sitemap_urls:
        selected = _select_urls_via_llm(domain, sitemap_urls)
        if selected:
            locations, pages_fetched = await fetch_and_extract(domain, selected)
            status = "RECOUNTED" if locations else "RECOUNTED_NO_LOCATIONS_FOUND"
            return {
                "domain": domain, "status": status,
                "count": len(locations), "source": "sitemap",
                "sitemap_used": sitemap_used, "locations": locations,
            }

    # ── Tier 2: Homepage crawl ────────────────────────────────────────────────
    logger.info(f"[{domain}] no sitemap — trying homepage crawl")
    homepage_links = await crawl_homepage_links(domain)

    if homepage_links:
        selected = _select_urls_via_llm(domain, homepage_links)
        if selected:
            locations, pages_fetched = await fetch_and_extract(domain, selected)
            status = "RECOUNTED" if locations else "RECOUNTED_NO_LOCATIONS_FOUND"
            return {
                "domain": domain, "status": status,
                "count": len(locations), "source": "homepage_crawl",
                "sitemap_used": "", "locations": locations,
            }

    # ── Tier 3: Common paths ──────────────────────────────────────────────────
    logger.info(f"[{domain}] no homepage links — trying common paths")
    common_urls = await try_common_paths(domain)

    if common_urls:
        locations, pages_fetched = await fetch_and_extract(domain, common_urls)
        status = "RECOUNTED" if locations else "RECOUNTED_NO_LOCATIONS_FOUND"
        return {
            "domain": domain, "status": status,
            "count": len(locations), "source": "common_paths",
            "sitemap_used": "", "locations": locations,
        }

    # ── Fallback ──────────────────────────────────────────────────────────────
    logger.info(f"[{domain}] all tiers exhausted — flagging for manual review")
    return {
        "domain": domain, "status": "NEEDS_MANUAL",
        "count": None, "source": "none",
        "sitemap_used": "", "locations": [],
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def locations_to_rows(domain: str, locations: list) -> list[dict]:
    return [{
        "domain": domain,
        "location_name": loc.location_name or "",
        "address_street": loc.address_street or "",
        "address_city": loc.address_city or "",
        "address_state": loc.address_state or "",
        "address_zip": loc.address_zip or "",
        "phone": loc.phone or "",
        "source_url": loc.source_url,
        "snippet": loc.snippet,
        "confidence": loc.confidence,
        "validation_status": loc.validation_status,
        "source": "smart_recount",
    } for loc in locations]


async def main(concurrency: int, limit: int | None, verbose: bool,
               domains_file: str | None = None, out_locs: str = OUT_LOCS,
               report_path: str = REPORT_PATH):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    reset_run_cost()

    # ── Load orgs ─────────────────────────────────────────────────────────────
    with open(ORGS_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        orgs_fieldnames = reader.fieldnames[:]
        orgs_rows = list(reader)

    # Strip existing smart_recount columns if present (clean rerun)
    orgs_fieldnames = [c for c in orgs_fieldnames if c not in NEW_COLS]
    for row in orgs_rows:
        for col in NEW_COLS:
            row.pop(col, None)

    # ── Load existing extracted counts ────────────────────────────────────────
    existing_counts: dict[str, int] = defaultdict(int)
    with open(LOCS_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = (row.get("domain") or "").strip()
            if d:
                existing_counts[d] += 1

    # ── Identify targets ──────────────────────────────────────────────────────
    if domains_file:
        # Use explicit domain list (e.g. from a retry run). Domains not already in
        # ORGS_PATH are synthesized so brand-new domains (e.g. resolved final_urls) still run.
        with open(domains_file, newline="", encoding="utf-8") as f:
            domain_set = {r["domain"].strip() for r in csv.DictReader(f) if r.get("domain", "").strip()}
        by_dom = {r["domain"]: r for r in orgs_rows}
        targets = [by_dom.get(d, {"domain": d}) for d in sorted(domain_set)]
    else:
        targets = [r for r in orgs_rows if r.get("location_count_status") in ("UNDER", "OVER")]

    if limit:
        targets = targets[:limit]

    print(f"Targeting {len(targets)} domains with concurrency={concurrency}", file=sys.stderr)

    # ── Process (crash-safe incremental writes + resume) ───────────────────────
    already = set()
    if os.path.exists(out_locs):
        with open(out_locs, newline="") as f:
            already = {r["domain"] for r in csv.DictReader(f)}
    if already:
        before = len(targets); targets = [t for t in targets if t["domain"] not in already]
        print(f"resume: {len(already)} domains already in {out_locs}; skipping {before-len(targets)}, {len(targets)} to run", file=sys.stderr)

    sem = asyncio.Semaphore(concurrency)
    results: dict[str, dict] = {}
    _new = not os.path.exists(out_locs)
    _fout = open(out_locs, "a", newline="", encoding="utf-8")
    _lw = csv.DictWriter(_fout, fieldnames=LOC_COLS, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
    if _new:
        _lw.writeheader(); _fout.flush()
    _wlock = asyncio.Lock()

    async def _run(org_row):
        domain = org_row["domain"]
        async with sem:
            try:
                res = await process_domain(domain)
            except Exception as e:
                logger.error(f"[{domain}] process_domain crashed ({type(e).__name__}: {e}) — skipping")
                res = {"domain": domain, "status": "ERROR", "count": None, "source": "none", "sitemap_used": "", "locations": []}
            results[domain] = res
            rows = locations_to_rows(res["domain"], res["locations"])
            if rows:
                async with _wlock:
                    _lw.writerows(rows); _fout.flush()

    await asyncio.gather(*[_run(r) for r in targets], return_exceptions=True)
    _fout.close()

    # ── Patch orgs CSV ────────────────────────────────────────────────────────
    new_fieldnames = orgs_fieldnames + NEW_COLS
    patched = []
    for row in orgs_rows:
        out = dict(row)
        domain = row["domain"]
        if domain in results:
            res = results[domain]
            out["smart_recount_status"] = res["status"]
            out["smart_recount_count"]  = "" if res["count"] is None else str(res["count"])
            out["smart_recount_source"] = res["source"]
        else:
            out["smart_recount_status"] = ""
            out["smart_recount_count"]  = ""
            out["smart_recount_source"] = ""
        patched.append(out)

    with open(ORGS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(patched)

    # ── Report ────────────────────────────────────────────────────────────────
    recounted   = [r for r in results.values() if r["status"] == "RECOUNTED"]
    no_locs     = [r for r in results.values() if r["status"] == "RECOUNTED_NO_LOCATIONS_FOUND"]
    manual      = [r for r in results.values() if r["status"] == "NEEDS_MANUAL"]
    by_source   = defaultdict(int)
    for r in recounted + no_locs:
        by_source[r["source"]] += 1

    # Compare recount vs previous extracted
    changes = []
    for res in recounted:
        d = res["domain"]
        prev = existing_counts.get(d, 0)
        new  = res["count"]
        changes.append({"domain": d, "prev": prev, "new": new, "delta": new - prev, "source": res["source"]})

    top20 = sorted(changes, key=lambda x: abs(x["delta"]), reverse=True)[:20]

    lines = [
        "# Smart Location Recount Report",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "## Summary",
        "",
        f"| | Count |",
        f"|---|---|",
        f"| UNDER/OVER domains targeted | {len(targets)} |",
        f"| Successfully recounted | {len(recounted)} |",
        f"| Recounted — 0 locations found | {len(no_locs)} |",
        f"| Needs manual review | {len(manual)} |",
        f"| New location rows written | {len(all_loc_rows)} |",
        "",
        "## Discovery source breakdown",
        "",
        f"| Source | Count |",
        f"|---|---|",
    ]
    for src in ["sitemap", "homepage_crawl", "common_paths"]:
        lines.append(f"| {src} | {by_source[src]} |")

    lines += [
        "",
        "## Recount vs previous extracted",
        "",
        f"| | Count |",
        f"|---|---|",
        f"| Same (delta = 0) | {sum(1 for c in changes if c['delta']==0)} |",
        f"| We missed locations (recount > prev) | {sum(1 for c in changes if c['delta']>0)} |",
        f"| We over-extracted (recount < prev) | {sum(1 for c in changes if c['delta']<0)} |",
        "",
        "## Top 20 biggest changes",
        "",
        "| domain | prev | recount | delta | source |",
        "|---|---|---|---|---|",
    ]
    for c in top20:
        sign = "+" if c["delta"] >= 0 else ""
        lines.append(f"| {c['domain']} | {c['prev']} | {c['new']} | {sign}{c['delta']} | {c['source']} |")

    lines += ["", "## Domains needing manual review", ""]
    for r in sorted(manual, key=lambda x: x["domain"]):
        lines.append(f"- {r['domain']}")

    report = "\n".join(lines) + "\n"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    print(f"\nLocations → {out_locs}", file=sys.stderr)
    print(f"Orgs      → {ORGS_PATH}", file=sys.stderr)
    print(f"Report    → {report_path}", file=sys.stderr)
    print(f"LLM cost  → ${get_run_cost():.2f}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=DOMAIN_CONCURRENCY)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--domains-file", default=None,
                        help="CSV with 'domain' column — use instead of UNDER/OVER filter")
    parser.add_argument("--out-locs", default=OUT_LOCS,
                        help="Output path for location rows")
    parser.add_argument("--report", default=REPORT_PATH,
                        help="Output path for report")
    parser.add_argument("--max-cost", type=float, default=float("inf"),
                        help="LLM cost cap (USD). Domains skip once the running total crosses this.")
    args = parser.parse_args()
    _MAX_COST_USD = args.max_cost
    asyncio.run(main(args.concurrency, args.limit, args.verbose,
                     domains_file=args.domains_file,
                     out_locs=args.out_locs,
                     report_path=args.report))
