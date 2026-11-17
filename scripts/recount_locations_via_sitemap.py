"""
scripts/recount_locations_via_sitemap.py

For every UNDER or OVER row in output_org_value_match.csv, re-enumerates
locations from scratch using the site's sitemap as the URL source.

Reads:  data/output_org_value_match.csv   (must have location_count_status column)
Reads:  data/output_locations.csv         (existing extracted locations)
Writes: data/output_locations_recount.csv (new location rows, source="sitemap_recount")
Writes: data/output_org_value_match.csv   (adds 3 new columns in-place)
Writes: data/recount_report.md

Usage:
    python -m scripts.recount_locations_via_sitemap [--concurrency N] [--limit N]
"""
import argparse
import asyncio
import csv
import logging
import os
import re
import sys
import time
from collections import defaultdict
from urllib.parse import urljoin, urlparse

import httpx

# ── Paths ────────────────────────────────────────────────────────────────────
DATA = os.path.join(os.path.dirname(__file__), "..", "data")
ORGS_PATH   = os.path.join(DATA, "output_org_value_match.csv")
LOCS_PATH   = os.path.join(DATA, "output_locations.csv")
OUT_LOCS    = os.path.join(DATA, "output_locations_recount.csv")
REPORT_PATH = os.path.join(DATA, "recount_report.md")

# ── Constants ────────────────────────────────────────────────────────────────
MAX_URLS_PER_DOMAIN   = 30
FETCH_CONCURRENCY     = 10   # concurrent URL fetches
SITEMAP_TIMEOUT       = 15   # seconds per sitemap HTTP request

# URL path segments that strongly suggest a location/office page
_LOCATION_PATH_SIGNALS = [
    "/location", "/office", "/clinic", "/branch", "/find-",
    "/our-", "/visit", "/center", "/centre", "/site",
]

# Leaf-page excludes — skip these even if no location signal found
_EXCLUDE_PATH_SIGNALS = [
    "/tag/", "/category/", "/author/", "/feed/", "/wp-admin/",
    "/page/", "/search/", "/?", "/wp-content/", "/wp-includes/",
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".css", ".js",
]

# US state names + 2-letter abbreviations (lowercase)
_US_STATES = {
    "alabama","alaska","arizona","arkansas","california","colorado","connecticut",
    "delaware","florida","georgia","hawaii","idaho","illinois","indiana","iowa",
    "kansas","kentucky","louisiana","maine","maryland","massachusetts","michigan",
    "minnesota","mississippi","missouri","montana","nebraska","nevada",
    "new-hampshire","new-jersey","new-mexico","new-york","north-carolina",
    "north-dakota","ohio","oklahoma","oregon","pennsylvania","rhode-island",
    "south-carolina","south-dakota","tennessee","texas","utah","vermont",
    "virginia","washington","west-virginia","wisconsin","wyoming",
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in",
    "ia","ks","ky","la","me","md","ma","mi","mn","ms","mo","mt","ne","nv",
    "nh","nj","nm","ny","nc","nd","oh","ok","or","pa","ri","sc","sd","tn",
    "tx","ut","vt","va","wa","wv","wi","wy",
}

NEW_COLS = ["sitemap_recount_status", "sitemap_recount_count", "sitemap_used"]
LOC_COLS = [
    "domain","location_name","address_street","address_city",
    "address_state","address_zip","phone","source_url","snippet",
    "confidence","validation_status","source",
]

logger = logging.getLogger(__name__)


# ── Sitemap discovery ────────────────────────────────────────────────────────

async def _fetch_text(client: httpx.AsyncClient, url: str) -> str | None:
    """Fetch URL and return text, or None on error."""
    try:
        r = await client.get(url, timeout=SITEMAP_TIMEOUT, follow_redirects=True)
        if r.status_code == 200 and r.text.strip():
            return r.text
    except Exception:
        pass
    return None


async def discover_sitemap_urls(domain: str) -> tuple[list[str], str]:
    """
    Returns (list_of_page_urls, sitemap_url_used).
    sitemap_url_used is blank if none found.

    Uses ultimate-sitemap-parser to handle sitemap indices, gzipped sitemaps, etc.
    Falls back to manual robots.txt parse if usp fails.
    """
    from usp.tree import sitemap_tree_for_homepage

    base = f"https://{domain}"
    candidates = [
        f"{base}/sitemap.xml",
        f"{base}/sitemap_index.xml",
        f"{base}/wp-sitemap.xml",
        f"{base}/sitemap-index.xml",
        f"{base}/sitemap.xml.gz",
    ]

    # Check robots.txt for Sitemap: directive
    async with httpx.AsyncClient(
        timeout=SITEMAP_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; SitemapBot/1.0)"},
        follow_redirects=True,
    ) as client:
        robots = await _fetch_text(client, f"{base}/robots.txt")
        if robots:
            for line in robots.splitlines():
                if line.lower().startswith("sitemap:"):
                    sm_url = line.split(":", 1)[1].strip()
                    if sm_url not in candidates:
                        candidates.insert(0, sm_url)

    # Try each candidate with usp
    for sm_url in candidates:
        try:
            # usp is sync — run in executor to avoid blocking event loop
            loop = asyncio.get_event_loop()
            tree = await loop.run_in_executor(None, sitemap_tree_for_homepage, f"https://{domain}")
            urls = [page.url for page in tree.all_pages() if page.url]
            if urls:
                return urls, sm_url
        except Exception as e:
            logger.debug(f"[{domain}] usp failed for {sm_url}: {e}")
            continue

    return [], ""


# ── URL filtering ────────────────────────────────────────────────────────────

def _path_segments(url: str) -> list[str]:
    try:
        return urlparse(url).path.lower().split("/")
    except Exception:
        return []


def _is_excluded(url: str) -> bool:
    lower = url.lower()
    return any(sig in lower for sig in _EXCLUDE_PATH_SIGNALS)


def _has_location_signal(url: str) -> bool:
    lower = url.lower()
    # Direct path signal
    if any(sig in lower for sig in _LOCATION_PATH_SIGNALS):
        return True
    # State name or abbreviation in path
    parts = _path_segments(url)
    if any(p in _US_STATES for p in parts):
        return True
    return False


def filter_location_urls(all_urls: list[str], domain: str) -> list[str]:
    """
    Filter sitemap URLs to location-relevant ones.
    If none match, fall back to all non-excluded leaf pages.
    Caps at MAX_URLS_PER_DOMAIN.
    """
    base_domain = domain.lower().lstrip("www.")

    # Only consider URLs from this domain (sitemap indices can include external)
    own = [u for u in all_urls if base_domain in urlparse(u).netloc.lower()]
    if not own:
        own = all_urls  # cross-domain sitemap, take everything

    not_excluded = [u for u in own if not _is_excluded(u)]

    with_signal = [u for u in not_excluded if _has_location_signal(u)]

    if with_signal:
        return with_signal[:MAX_URLS_PER_DOMAIN]

    # Fallback: all leaf pages (have a meaningful path, not just homepage)
    leaves = [u for u in not_excluded if len(urlparse(u).path.strip("/").split("/")) >= 1
              and urlparse(u).path.strip("/")]
    return leaves[:MAX_URLS_PER_DOMAIN]


# ── Fetch + extract ──────────────────────────────────────────────────────────

async def fetch_urls_for_domain(urls: list[str], domain: str) -> dict[str, str]:
    """Fetch all URLs with bounded concurrency. Returns {url: html}."""
    from src.fetch import fetch_url

    sem = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def _one(url):
        async with sem:
            try:
                result = await fetch_url(url)
                if result.html and not result.blocked:
                    return url, result.html
            except Exception as e:
                logger.debug(f"[{domain}] fetch_url {url}: {e}")
        return url, ""

    results = await asyncio.gather(*[_one(u) for u in urls])
    return {url: html for url, html in results if html}


def run_location_extractor(domain: str, pages: dict[str, str]) -> tuple[list, object]:
    """
    Call extract_locations with an empty homepage + all sitemap-fetched pages.
    Returns (locations_list, usage).
    """
    from src.location_extract import extract_locations
    # Pass empty string as homepage_html — all content is in additional_pages
    result, usage = extract_locations(domain, homepage_html="", additional_pages=pages)
    return result.locations, usage


# ── Main ─────────────────────────────────────────────────────────────────────

async def process_domain(domain: str, existing_extracted: int) -> dict:
    """
    Full recount pipeline for one domain.
    Returns a result dict with keys: domain, status, recount, sitemap_used, locations
    """
    logger.info(f"[{domain}] starting sitemap recount")

    # Part 1: discover sitemap
    all_urls, sitemap_used = await discover_sitemap_urls(domain)

    if not all_urls:
        logger.info(f"[{domain}] no sitemap found")
        return {
            "domain": domain,
            "status": "NO_SITEMAP_NEEDS_MANUAL",
            "recount": None,
            "sitemap_used": "",
            "locations": [],
        }

    # Part 2: filter URLs
    filtered = filter_location_urls(all_urls, domain)
    logger.info(f"[{domain}] sitemap: {len(all_urls)} total URLs → {len(filtered)} location URLs")

    if not filtered:
        logger.info(f"[{domain}] no location URLs after filtering")
        return {
            "domain": domain,
            "status": "NO_SITEMAP_NEEDS_MANUAL",
            "recount": None,
            "sitemap_used": sitemap_used,
            "locations": [],
        }

    # Part 3: fetch + extract
    pages = await fetch_urls_for_domain(filtered, domain)
    logger.info(f"[{domain}] fetched {len(pages)}/{len(filtered)} URLs successfully")

    if not pages:
        return {
            "domain": domain,
            "status": "NO_SITEMAP_NEEDS_MANUAL",
            "recount": None,
            "sitemap_used": sitemap_used,
            "locations": [],
        }

    try:
        locations, _ = run_location_extractor(domain, pages)
    except Exception as e:
        logger.error(f"[{domain}] extractor failed: {e}")
        locations = []

    status = "RECOUNTED" if locations else "RECOUNTED_NO_LOCATIONS_FOUND"
    logger.info(f"[{domain}] recount={len(locations)} (was extracted={existing_extracted}) status={status}")

    return {
        "domain": domain,
        "status": status,
        "recount": len(locations),
        "sitemap_used": sitemap_used,
        "locations": locations,
    }


def locations_to_rows(domain: str, locations: list) -> list[dict]:
    rows = []
    for loc in locations:
        rows.append({
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
            "source": "sitemap_recount",
        })
    return rows


async def main(concurrency: int, limit: int | None):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    # ── Load orgs file ───────────────────────────────────────────────────────
    with open(ORGS_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        orgs_fieldnames = reader.fieldnames[:]
        orgs_rows = list(reader)

    # If recount columns already exist (e.g. from a prior partial run), strip them
    # so we rebuild cleanly from scratch.
    orgs_fieldnames = [c for c in orgs_fieldnames if c not in NEW_COLS]
    for row in orgs_rows:
        for col in NEW_COLS:
            row.pop(col, None)

    # ── Load existing extracted counts ───────────────────────────────────────
    existing_counts: dict[str, int] = defaultdict(int)
    with open(LOCS_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = (row.get("domain") or "").strip()
            if d:
                existing_counts[d] += 1

    # ── Identify UNDER/OVER targets ──────────────────────────────────────────
    targets = [
        r for r in orgs_rows
        if r.get("location_count_status") in ("UNDER", "OVER")
    ]
    if limit:
        targets = targets[:limit]

    print(f"UNDER/OVER rows to recount: {len(targets)}", file=sys.stderr)

    # ── Process with bounded concurrency ─────────────────────────────────────
    sem = asyncio.Semaphore(concurrency)
    results: dict[str, dict] = {}

    async def _run_one(org_row):
        domain = org_row["domain"]
        extracted = existing_counts.get(domain, 0)
        async with sem:
            result = await process_domain(domain, extracted)
        results[domain] = result

    await asyncio.gather(*[_run_one(r) for r in targets])

    # ── Write output_locations_recount.csv ───────────────────────────────────
    all_loc_rows = []
    for res in results.values():
        all_loc_rows.extend(locations_to_rows(res["domain"], res["locations"]))

    with open(OUT_LOCS, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOC_COLS,
                                extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(all_loc_rows)

    # ── Patch output_org_value_match.csv with 3 new columns ─────────────────
    new_fieldnames = orgs_fieldnames + NEW_COLS
    patched_rows = []
    for org_row in orgs_rows:
        domain = org_row["domain"]
        out = dict(org_row)
        if domain in results:
            res = results[domain]
            out["sitemap_recount_status"] = res["status"]
            out["sitemap_recount_count"]  = "" if res["recount"] is None else str(res["recount"])
            out["sitemap_used"]           = res["sitemap_used"]
        else:
            out["sitemap_recount_status"] = ""
            out["sitemap_recount_count"]  = ""
            out["sitemap_used"]           = ""
        patched_rows.append(out)

    with open(ORGS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=new_fieldnames,
                                extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(patched_rows)

    # ── Build report ─────────────────────────────────────────────────────────
    recounted     = [r for r in results.values() if r["status"] == "RECOUNTED"]
    no_locs       = [r for r in results.values() if r["status"] == "RECOUNTED_NO_LOCATIONS_FOUND"]
    no_sitemap    = [r for r in results.values() if r["status"] == "NO_SITEMAP_NEEDS_MANUAL"]

    # Compare recount vs previous extracted
    same, gained, lost = [], [], []
    changes = []
    for res in recounted:
        d = res["domain"]
        prev = existing_counts.get(d, 0)
        new  = res["recount"]
        delta = new - prev
        changes.append({"domain": d, "prev": prev, "new": new, "delta": delta})
        if delta == 0:   same.append(d)
        elif delta > 0:  gained.append(d)
        else:            lost.append(d)

    top20 = sorted(changes, key=lambda x: abs(x["delta"]), reverse=True)[:20]

    lines = [
        "# Sitemap Recount Report",
        "",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "## Summary",
        "",
        f"| | Count |",
        f"|---|---|",
        f"| UNDER/OVER rows targeted | {len(targets)} |",
        f"| Successfully recounted (RECOUNTED) | {len(recounted)} |",
        f"| Recounted but 0 locations found | {len(no_locs)} |",
        f"| No sitemap — needs manual review | {len(no_sitemap)} |",
        f"| New location rows written | {len(all_loc_rows)} |",
        "",
        "## Recount vs Previous Extracted (RECOUNTED rows only)",
        "",
        f"| | Count |",
        f"|---|---|",
        f"| Same count (recount == extracted) | {len(same)} |",
        f"| We missed locations (recount > extracted) | {len(gained)} |",
        f"| We over-extracted (recount < extracted) | {len(lost)} |",
        "",
        "## Top 20 Biggest Changes (by absolute delta)",
        "",
        f"| domain | prev_extracted | recount | delta |",
        f"|---|---|---|---|",
    ]
    for c in top20:
        sign = "+" if c["delta"] >= 0 else ""
        lines.append(f"| {c['domain']} | {c['prev']} | {c['new']} | {sign}{c['delta']} |")

    lines += [
        "",
        "## Domains needing manual review (no sitemap)",
        "",
    ]
    for d in sorted(d for r in no_sitemap for d in [r["domain"]]):
        lines.append(f"- {d}")

    report = "\n".join(lines) + "\n"
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)

    # ── Print report ─────────────────────────────────────────────────────────
    print(report)
    print(f"Wrote locations → {OUT_LOCS}", file=sys.stderr)
    print(f"Patched orgs   → {ORGS_PATH}", file=sys.stderr)
    print(f"Report         → {REPORT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=5,
                        help="Max concurrent domain recount jobs (default: 5)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only process first N UNDER/OVER rows (for testing)")
    args = parser.parse_args()
    asyncio.run(main(args.concurrency, args.limit))
