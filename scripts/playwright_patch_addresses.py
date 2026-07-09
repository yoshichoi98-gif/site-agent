"""
scripts/playwright_patch_addresses.py

Two-pass address repair using Playwright:

Pass 1 — Clear bad zips:
  Detects zips that are geographically impossible for their state
  (e.g., an AZ row with a Maryland zip) and blanks them out so
  Pass 2 can fill them in correctly.

Pass 2 — Playwright fetch + extract:
  For all rows missing street, or whose zip was just cleared,
  fetch the source_url with Playwright (full JS render), run the
  HTML address extractors, match by city/name, and patch fields.

Usage:
    python -m scripts.playwright_patch_addresses [--concurrency N] [--verbose] [--dry-run]
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

logger = logging.getLogger(__name__)

DATA      = os.path.join(os.path.dirname(__file__), "..", "data")
LOCS_PATH = os.path.join(DATA, "output_locations.csv")
REPORT    = os.path.join(DATA, "playwright_patch_report.md")

CONCURRENCY = 5   # Playwright is heavy — keep low

# ── Zip validation by first digit ────────────────────────────────────────────
# Each US state's zip codes start with a predictable first digit.
# Anything outside this set is almost certainly a misextracted street number.
STATE_ZIP_FIRST_DIGIT = {
    'CT': {0}, 'MA': {0}, 'ME': {0}, 'NH': {0}, 'NJ': {0}, 'RI': {0}, 'VT': {0},
    'DE': {1}, 'NY': {1}, 'PA': {1},
    'DC': {2}, 'MD': {2}, 'NC': {2}, 'SC': {2}, 'VA': {2}, 'WV': {2},
    'AL': {3}, 'FL': {3}, 'GA': {3}, 'MS': {3}, 'TN': {3},
    'IN': {4}, 'KY': {4}, 'MI': {4}, 'OH': {4},
    'IA': {5}, 'MN': {5}, 'MT': {5}, 'ND': {5}, 'SD': {5}, 'WI': {5},
    'IL': {6}, 'KS': {6}, 'MO': {6}, 'NE': {6},
    'AR': {7}, 'LA': {7}, 'OK': {7}, 'TX': {7},
    'AZ': {8}, 'CO': {8}, 'ID': {8}, 'NM': {8}, 'NV': {8}, 'UT': {8}, 'WY': {8},
    'AK': {9}, 'CA': {9}, 'GU': {9}, 'HI': {9}, 'OR': {9}, 'WA': {9},
}

_ZIP_RE   = re.compile(r'\b(\d{5})(?:-\d{4})?\b')
_PHONE_RE = re.compile(r'tel:\S+')
_US_STATES = set(STATE_ZIP_FIRST_DIGIT.keys())


def is_bad_zip(zip_val: str, state: str) -> bool:
    """True if this zip is geographically impossible for the state."""
    if not zip_val or not state or state not in STATE_ZIP_FIRST_DIGIT:
        return False
    if not re.match(r'^\d{5}$', zip_val):
        return False
    first_digit = int(zip_val[0])
    return first_digit not in STATE_ZIP_FIRST_DIGIT[state]


def _normalize(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _parse_address_line(line: str) -> dict:
    """Parse a free-form address string into street/city/state/zip."""
    line = line.strip()
    line = _PHONE_RE.sub('', line)
    line = re.sub(r'\s*\|\s*', ', ', line)
    line = re.sub(r'\s*[—–]\s*', ', ', line)
    line = re.sub(r',\s*,', ',', line)
    line = line.strip(', ')

    result = {'street': '', 'city': '', 'state': '', 'zip': ''}

    zm = _ZIP_RE.search(line)
    if zm:
        result['zip'] = zm.group(1)
        line = line[:zm.start()].strip(', ')

    sm = re.search(r',?\s*\b([A-Z]{2})\s*$', line)
    if sm and sm.group(1) in _US_STATES:
        result['state'] = sm.group(1)
        line = line[:sm.start()].strip(', ')

    parts = [p.strip() for p in line.split(',') if p.strip()]
    if len(parts) >= 2:
        if re.search(r'\d', parts[0]):
            result['street'] = parts[0]
            result['city']   = parts[1]
        else:
            if len(parts) >= 3 and re.search(r'\d', parts[1]):
                result['street'] = parts[1]
                result['city']   = parts[2]
            elif re.search(r'\d', parts[1]):
                result['street'] = parts[1]
            else:
                result['city'] = parts[-1]
                if len(parts) >= 2 and re.search(r'\d', parts[-2]):
                    result['street'] = parts[-2]
    elif len(parts) == 1:
        if re.search(r'\d', parts[0]):
            result['street'] = parts[0]
        else:
            result['city'] = parts[0]

    return result


def _extract_addresses_from_html(html: str) -> list[dict]:
    """
    Run all HTML address extractors and return parsed address dicts.
    Each dict has street/city/state/zip plus an optional 'near_name' key
    populated by the named-block extractor (heading text near the address).
    """
    from src.html_extract import (
        _extract_json_ld, _extract_gmaps_addresses,
        _extract_data_attr_addresses, _extract_microdata_addresses,
        _extract_script_address_data,
    )
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    addresses = []
    seen = set()

    def _add(line: str, near_name: str = ''):
        parsed = _parse_address_line(line)
        if parsed['street'] or parsed['zip']:
            key = (parsed['street'].lower(), parsed['city'].lower(), parsed['zip'])
            if key not in seen:
                seen.add(key)
                parsed['near_name'] = near_name
                addresses.append(parsed)

    # ── Structured extractors ─────────────────────────────────────────────────
    for block_fn, prefix_filter in [
        (_extract_data_attr_addresses,   None),
        (_extract_microdata_addresses,   None),
        (_extract_gmaps_addresses,       'GOOGLE'),
        (_extract_script_address_data,   None),
    ]:
        block = block_fn(soup)
        for line in block.split('\n'):
            line = line.strip().lstrip(' ')
            if not line:
                continue
            if prefix_filter and line.startswith(prefix_filter):
                continue
            if _ZIP_RE.search(line) or re.search(r'\d{3,}', line):
                _add(line)

    # JSON-LD
    for line in _extract_json_ld(soup).split('\n'):
        line = line.strip()
        if line.startswith('address:') and _ZIP_RE.search(line):
            _add(line.replace('address:', '').strip())

    # ── Named block extractor ─────────────────────────────────────────────────
    # Looks for heading elements (h1-h4) followed within 3 siblings by an
    # address-like block. Returns (heading_text, address) pairs so we can
    # match rows by location_name even when city is missing.
    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4']):
        name_text = heading.get_text(separator=' ', strip=True)
        if not name_text or len(name_text) > 80:
            continue
        # Look at the next few siblings for address content
        # Note: siblings may be NavigableString (plain text) or Tag objects
        sibling = heading.next_sibling
        steps = 0
        while sibling and steps < 5:
            from bs4 import Tag
            if isinstance(sibling, Tag):
                text = sibling.get_text(separator=' ', strip=True)
                if _ZIP_RE.search(text):
                    _add(text, near_name=name_text)
                # Also check links inside for daddr
                for a in sibling.find_all('a', href=True):
                    href = a['href']
                    if 'daddr=' in href or 'maps.google' in href:
                        addr_text = a.get_text(separator=', ', strip=True)
                        if _ZIP_RE.search(addr_text):
                            _add(addr_text, near_name=name_text)
            sibling = sibling.next_sibling
            steps += 1

    return addresses


def _best_match(candidates: list[dict], row: dict) -> dict | None:
    """
    Match candidate address to existing row.

    Priority order:
    1. City match (most reliable)
    2. location_name matches near_name from the named-block extractor
    3. Exactly one candidate and row has no city (last resort)

    Never apply a candidate whose city contradicts a known row city.
    """
    target_city = _normalize(row.get('address_city', ''))
    target_name = _normalize(row.get('location_name', ''))

    if not candidates:
        return None

    # 1. City match
    if target_city:
        city_matches = [c for c in candidates if _normalize(c.get('city', '')) == target_city]
        if not city_matches:
            return None
        with_street = [c for c in city_matches if c.get('street')]
        return with_street[0] if with_street else city_matches[0]

    # 2. Name match via near_name (handles pages like allieddigestivehealth)
    if target_name:
        name_matches = [
            c for c in candidates
            if c.get('near_name') and target_name in _normalize(c['near_name'])
        ]
        if len(name_matches) == 1:
            return name_matches[0]
        # Multiple name matches — prefer one with a street
        if name_matches:
            with_street = [c for c in name_matches if c.get('street')]
            return with_street[0] if with_street else name_matches[0]

    # 3. Single candidate, no city to contradict
    if len(candidates) == 1:
        return candidates[0]

    return None


# ── Playwright fetch ──────────────────────────────────────────────────────────

async def fetch_with_playwright(url: str, page) -> str:
    """Fetch a URL with Playwright and return rendered HTML."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)   # let JS settle
        return await page.content()
    except Exception as e:
        logger.debug(f"playwright fetch {url}: {e}")
        return ""


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(concurrency: int, verbose: bool, dry_run: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    # ── Load rows ─────────────────────────────────────────────────────────────
    with open(LOCS_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames[:]
        all_rows = list(reader)

    logger.info(f"Loaded {len(all_rows)} rows")

    # ── Pass 1: Clear bad zips ────────────────────────────────────────────────
    bad_zip_count = 0
    for row in all_rows:
        z = (row.get('address_zip') or '').strip()
        s = (row.get('address_state') or '').strip()
        if is_bad_zip(z, s):
            logger.debug(f"Clearing bad zip {z} for {row.get('domain')} ({s})")
            row['address_zip'] = ''
            bad_zip_count += 1

    logger.info(f"Pass 1: Cleared {bad_zip_count} bad zips")

    # ── Find target rows ──────────────────────────────────────────────────────
    url_to_rows: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for i, row in enumerate(all_rows):
        missing_street = not (row.get('address_street') or '').strip()
        missing_zip    = not (row.get('address_zip') or '').strip()
        if missing_street or missing_zip:
            src = (row.get('source_url') or '').strip()
            if src:
                url_to_rows[src].append((i, row))

    total_urls = len(url_to_rows)
    total_rows = sum(len(v) for v in url_to_rows.values())
    logger.info(f"Pass 2: {total_rows} target rows across {total_urls} unique URLs")

    if dry_run:
        logger.info("DRY RUN — not fetching or writing")
        for url in list(url_to_rows.keys())[:5]:
            logger.info(f"  Would fetch: {url} ({len(url_to_rows[url])} rows)")
        return

    # ── Pass 2: Playwright fetch + extract ────────────────────────────────────
    patched   = 0
    completed = 0
    t0 = time.time()

    from playwright.async_api import async_playwright

    sem = asyncio.Semaphore(concurrency)

    async def process_url(url: str, browser):
        nonlocal patched, completed

        async with sem:
            page = await browser.new_page()
            try:
                html = await fetch_with_playwright(url, page)
            finally:
                await page.close()

        completed += 1
        if completed % 25 == 0 or completed == total_urls:
            elapsed = time.time() - t0
            rate = completed / elapsed if elapsed else 1
            eta = (total_urls - completed) / rate
            logger.info(
                f"{completed}/{total_urls} URLs | patched={patched} | "
                f"ETA={eta/60:.1f}min"
            )

        if not html:
            return

        candidates = _extract_addresses_from_html(html)
        if not candidates:
            return

        for row_idx, row in url_to_rows[url]:
            match = _best_match(candidates, row)
            if not match:
                continue

            changed = False
            for field, key in [
                ('address_street', 'street'),
                ('address_zip',    'zip'),
                ('address_city',   'city'),
                ('address_state',  'state'),
            ]:
                if not all_rows[row_idx].get(field, '').strip() and match.get(key):
                    all_rows[row_idx][field] = match[key]
                    changed = True
            if changed:
                patched += 1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        await asyncio.gather(*[process_url(u, browser) for u in url_to_rows.keys()])
        await browser.close()

    logger.info(f"Done. Patched {patched}/{total_rows} rows")

    # ── Write ─────────────────────────────────────────────────────────────────
    with open(LOCS_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore',
                                quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(all_rows)
    logger.info(f"Written {len(all_rows)} rows to {LOCS_PATH}")

    # ── Report ────────────────────────────────────────────────────────────────
    report = f"""# Playwright Address Patch Report

Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

| | Count |
|---|---|
| Bad zips cleared (Pass 1) | {bad_zip_count} |
| Target rows (Pass 2) | {total_rows} |
| Unique URLs fetched | {total_urls} |
| Rows patched | {patched} |
| Patch rate | {patched/total_rows*100:.1f}% |
"""
    with open(REPORT, 'w') as f:
        f.write(report)
    print(report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--concurrency', type=int, default=CONCURRENCY)
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    asyncio.run(main(args.concurrency, args.verbose, args.dry_run))
