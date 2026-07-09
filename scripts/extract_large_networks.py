"""
scripts/extract_large_networks.py

For large research networks (dedicated_research_site_network with many locations),
the standard smart_location_recount hits two limits:
  - LLM URL selector caps at 20 pages
  - Location extractor prompt caps at 100 locations

This script bypasses those limits:
  1. Fetches ALL URLs from the sitemap (no cap)
  2. Filters to location-pattern pages using regex (no LLM selector)
  3. Fetches all matching pages in batches of BATCH_SIZE
  4. Runs the location extractor on each batch
  5. Aggregates + deduplicates results across batches
  6. Writes to a separate output CSV

Usage:
    python -m scripts.extract_large_networks [--verbose]
"""
import asyncio
import concurrent.futures
import csv
import logging
import os
import re
import sys
import time
from collections import defaultdict
from urllib.parse import urlparse

from src.config import ANTHROPIC_API_KEY, MODEL
from src.location_extract import extract_locations
from src.pipeline import add_cost

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA     = os.path.join(os.path.dirname(__file__), "..", "data")
OUT_LOCS = os.path.join(DATA, "output_locations_large_networks.csv")
REPORT   = os.path.join(DATA, "large_networks_report.md")

LOC_COLS = [
    "domain", "location_name", "address_street", "address_city",
    "address_state", "address_zip", "phone", "source_url", "snippet",
    "confidence", "validation_status", "source",
]

# ── Target domains ─────────────────────────────────────────────────────────────
# dedicated_research_site_network with 40+ claimed locations
TARGET_DOMAINS = [
    "retinaconsultantsofamerica.com",
    "synexus.com",
    "trialmed.com",
    "careaccess.com",
    "scri.com",
    "rayusradiology.com",
    "centerforvein.com",
    "velocityclinical.com",
    "accellacare.com",
    "btcsites.com",
    "gulfsouthclinicaltrials.org",
]

# ── Config ────────────────────────────────────────────────────────────────────
USP_TIMEOUT_SECONDS = 90        # longer for large sitemaps
MAX_SITEMAP_URLS    = 5000      # no practical cap — we want everything
BATCH_SIZE          = 15        # pages per extractor call
PAGE_CONCURRENCY    = 8         # concurrent page fetches
DOMAIN_CONCURRENCY  = 3         # concurrent domains (these are heavy)

# Regex: URL paths that likely contain individual location pages
# Matches /locations/city-name, /sites/name, /clinics/name, etc.
_LOCATION_PATH_RE = re.compile(
    r"/(location|office|clinic|site|center|centre|branch|practice|store|facility)"
    r"s?/[a-z0-9][a-z0-9\-_%]+",
    re.IGNORECASE,
)

# Also always include these generic pages as seeds
_SEED_PATHS = ["/locations", "/offices", "/clinics", "/sites", "/find-a-location",
               "/our-locations", "/contact", "/about"]


# ── Sitemap discovery ─────────────────────────────────────────────────────────

def _usp_skip_callback(urls, recursion_level, parent_urls):
    """Skip obvious content-feed sub-sitemaps."""
    skip = ["blog", "news", "post", "author", "category", "tag", "archive"]
    return [u for u in urls if not any(p in u.lower() for p in skip)]


def _run_usp(homepage_url: str) -> list[str]:
    from usp.tree import sitemap_tree_for_homepage
    tree = sitemap_tree_for_homepage(homepage_url, recurse_list_callback=_usp_skip_callback)
    urls = []
    for page in tree.all_pages():
        if page.url:
            urls.append(page.url)
        if len(urls) >= MAX_SITEMAP_URLS:
            break
    return urls


async def get_all_sitemap_urls(domain: str) -> list[str]:
    loop = asyncio.get_event_loop()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            urls = await asyncio.wait_for(
                loop.run_in_executor(pool, _run_usp, f"https://{domain}"),
                timeout=USP_TIMEOUT_SECONDS,
            )
        logger.info(f"[{domain}] usp: {len(urls)} total sitemap URLs")
        return urls
    except asyncio.TimeoutError:
        logger.warning(f"[{domain}] usp timed out after {USP_TIMEOUT_SECONDS}s")
        return []
    except Exception as e:
        logger.warning(f"[{domain}] usp failed: {e}")
        return []


# ── URL filtering ─────────────────────────────────────────────────────────────

def filter_location_urls(domain: str, all_urls: list[str]) -> list[str]:
    """
    From all sitemap URLs, keep only those that look like individual location pages.
    Also adds seed paths that may not appear in the sitemap.
    """
    base = f"https://{domain}"
    location_urls = []
    seen = set()

    for url in all_urls:
        parsed = urlparse(url)
        if _LOCATION_PATH_RE.search(parsed.path):
            if url not in seen:
                seen.add(url)
                location_urls.append(url)

    # Add seed paths if not already present
    for path in _SEED_PATHS:
        url = f"{base}{path}"
        if url not in seen:
            seen.add(url)
            location_urls.append(url)

    logger.info(f"[{domain}] {len(location_urls)} location-pattern URLs to fetch")
    return location_urls


# ── Page fetching ─────────────────────────────────────────────────────────────

async def fetch_pages(domain: str, urls: list[str]) -> dict[str, str]:
    """Fetch all URLs concurrently, return {url: html}."""
    from src.fetch import fetch_url

    sem = asyncio.Semaphore(PAGE_CONCURRENCY)

    async def _fetch_one(url):
        async with sem:
            try:
                result = await fetch_url(url)
                if result.html and not result.blocked:
                    return url, result.html
            except Exception as e:
                logger.debug(f"[{domain}] fetch {url}: {e}")
            return url, ""

    results = await asyncio.gather(*[_fetch_one(u) for u in urls])
    pages = {url: html for url, html in results if html}
    logger.info(f"[{domain}] fetched {len(pages)}/{len(urls)} pages")
    return pages


# ── Batched extraction ────────────────────────────────────────────────────────

def _dedup_locations(locations: list) -> list:
    """Deduplicate across batches by (street, city, zip)."""
    seen = set()
    deduped = []
    for loc in locations:
        key = (
            (loc.address_street or "").strip().lower(),
            (loc.address_city or "").strip().lower(),
            (loc.address_zip or "").strip(),
        )
        if key == ("", "", ""):
            # No address at all — keep but don't dedup
            deduped.append(loc)
            continue
        if key not in seen:
            seen.add(key)
            deduped.append(loc)
    return deduped


async def extract_all_batched(domain: str, pages: dict[str, str]) -> list:
    """
    Run the location extractor on pages in batches of BATCH_SIZE.
    Aggregate and deduplicate results across all batches.
    """
    page_items = list(pages.items())
    all_locations = []
    n_batches = (len(page_items) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(page_items), BATCH_SIZE):
        batch = dict(page_items[i:i + BATCH_SIZE])
        batch_num = i // BATCH_SIZE + 1
        logger.info(f"[{domain}] batch {batch_num}/{n_batches}: {len(batch)} pages")

        try:
            # Run in thread executor — extract_locations is sync
            loop = asyncio.get_event_loop()
            result, usage = await loop.run_in_executor(
                None,
                lambda b=batch: extract_locations(domain, homepage_html="", additional_pages=b)
            )
            add_cost(usage.input_tokens, usage.output_tokens)
            logger.info(
                f"[{domain}] batch {batch_num}: {len(result.locations)} locations "
                f"({usage.input_tokens}in/{usage.output_tokens}out tokens)"
            )
            all_locations.extend(result.locations)
        except Exception as e:
            logger.error(f"[{domain}] batch {batch_num} failed: {e}")

    deduped = _dedup_locations(all_locations)
    logger.info(f"[{domain}] total: {len(all_locations)} raw → {len(deduped)} after dedup")
    return deduped


# ── Per-domain orchestration ──────────────────────────────────────────────────

async def process_domain(domain: str) -> dict:
    logger.info(f"[{domain}] starting large-network extraction")

    # Step 1: Get all sitemap URLs
    all_urls = await get_all_sitemap_urls(domain)

    # Step 2: Filter to location-pattern URLs
    location_urls = filter_location_urls(domain, all_urls)

    if not location_urls:
        logger.warning(f"[{domain}] no location URLs found")
        return {"domain": domain, "locations": [], "pages_fetched": 0, "status": "no_urls"}

    # Step 3: Fetch all pages
    pages = await fetch_pages(domain, location_urls)

    if not pages:
        return {"domain": domain, "locations": [], "pages_fetched": 0, "status": "fetch_failed"}

    # Step 4: Extract in batches
    locations = await extract_all_batched(domain, pages)

    return {
        "domain": domain,
        "locations": locations,
        "pages_fetched": len(pages),
        "status": "done",
    }


# ── Row conversion ────────────────────────────────────────────────────────────

def locations_to_rows(domain: str, locations: list) -> list[dict]:
    return [{
        "domain": domain,
        "location_name":  loc.location_name or "",
        "address_street": loc.address_street or "",
        "address_city":   loc.address_city or "",
        "address_state":  loc.address_state or "",
        "address_zip":    loc.address_zip or "",
        "phone":          loc.phone or "",
        "source_url":     loc.source_url,
        "snippet":        loc.snippet,
        "confidence":     loc.confidence,
        "validation_status": loc.validation_status,
        "source":         "large_network_extract",
    } for loc in locations]


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    sem = asyncio.Semaphore(DOMAIN_CONCURRENCY)
    results = {}

    async def _run(domain):
        async with sem:
            results[domain] = await process_domain(domain)

    await asyncio.gather(*[_run(d) for d in TARGET_DOMAINS])

    # Write locations
    all_rows = []
    for res in results.values():
        all_rows.extend(locations_to_rows(res["domain"], res["locations"]))

    with open(OUT_LOCS, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOC_COLS, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(all_rows)

    # Report
    lines = [
        "# Large Network Extraction Report",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "| domain | pages_fetched | locations | status |",
        "|---|---|---|---|",
    ]
    for domain in TARGET_DOMAINS:
        res = results.get(domain, {})
        lines.append(
            f"| {domain} | {res.get('pages_fetched',0)} "
            f"| {len(res.get('locations',[]))} | {res.get('status','not_run')} |"
        )
    lines += ["", f"**Total location rows: {len(all_rows)}**"]

    report = "\n".join(lines) + "\n"
    with open(REPORT, "w") as f:
        f.write(report)

    print(report)
    print(f"\nLocations → {OUT_LOCS}", file=sys.stderr)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.verbose))
