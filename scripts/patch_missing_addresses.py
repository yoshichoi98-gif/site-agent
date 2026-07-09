"""
scripts/patch_missing_addresses.py

For location rows missing street or zip, fetch their source_url and extract
addresses directly from the enhanced HTML parser — NO LLM call needed.

The html_extract module already pulls addresses from:
  - data-label attributes  (e.g. universityradiology.com map widgets)
  - data-street/zip attrs  (e.g. houstoneye.com)
  - Google Maps iframe/link URLs
  - JSON-LD structured data
  - schema.org microdata
  - Script tag JSON variables

We parse those structured output blocks back into address components with
regex, then match to existing rows by city name and patch missing fields.

Usage:
    python -m scripts.patch_missing_addresses [--concurrency N] [--verbose] [--dry-run]
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
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

DATA      = os.path.join(os.path.dirname(__file__), "..", "data")
LOCS_PATH = os.path.join(DATA, "output_locations.csv")
REPORT    = os.path.join(DATA, "patch_missing_addresses_report.md")

URL_CONCURRENCY = 30

# US state abbreviations for parsing
_US_STATES = {
    'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA',
    'KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ',
    'NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT',
    'VA','WA','WV','WI','WY','DC','PR','GU','VI',
}

_ZIP_RE   = re.compile(r'\b(\d{5})(?:-\d{4})?\b')
_STATE_RE = re.compile(r'\b([A-Z]{2})\b')
_PHONE_RE = re.compile(r'tel:\S+')


def _normalize(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _parse_address_line(line: str) -> dict:
    """
    Parse a free-form address string into components.
    Handles formats like:
      "123 Main St | Austin, TX 78701"
      "123 Main St, Austin, TX 78701"
      "Location Name | 123 Main St | Austin, TX 78701"
      "Name — 123 Main St, City, ST 12345"
    Returns dict with street, city, state, zip (any may be empty string).
    """
    # Strip leading name segment if separated by | or —
    line = line.strip()

    # Remove phone numbers
    line = _PHONE_RE.sub('', line)

    # Normalize separators to comma
    line = re.sub(r'\s*\|\s*', ', ', line)
    line = re.sub(r'\s*—\s*', ', ', line)
    line = re.sub(r',\s*,', ',', line)
    line = line.strip(', ')

    result = {'street': '', 'city': '', 'state': '', 'zip': ''}

    # Extract ZIP
    zm = _ZIP_RE.search(line)
    if zm:
        result['zip'] = zm.group(1)
        # Remove zip from line for further parsing
        line = line[:zm.start()].strip(', ')

    # Extract state (2-letter abbreviation before the zip, after a comma/space)
    # Look for state at end of remaining line
    sm = re.search(r',?\s*\b([A-Z]{2})\s*$', line)
    if sm and sm.group(1) in _US_STATES:
        result['state'] = sm.group(1)
        line = line[:sm.start()].strip(', ')

    # Split remaining into parts
    parts = [p.strip() for p in line.split(',') if p.strip()]

    if not parts:
        return result

    # Heuristic: if first part looks like a street (has digits), it's the street
    # Otherwise it may be a location name — skip it
    if len(parts) >= 2:
        if re.search(r'\d', parts[0]):
            # First part is street, second is city
            result['street'] = parts[0]
            result['city'] = parts[1]
        else:
            # First part is name, second is street, third is city
            if len(parts) >= 3 and re.search(r'\d', parts[1]):
                result['street'] = parts[1]
                result['city'] = parts[2]
            elif re.search(r'\d', parts[1]):
                result['street'] = parts[1]
            else:
                # Just take last part as city
                result['city'] = parts[-1]
                if len(parts) >= 2 and re.search(r'\d', parts[-2]):
                    result['street'] = parts[-2]
    elif len(parts) == 1:
        if re.search(r'\d', parts[0]):
            result['street'] = parts[0]
        else:
            result['city'] = parts[0]

    return result


def _extract_addresses_from_html(html: str, url: str) -> list[dict]:
    """
    Run the enhanced HTML extractors and parse addresses from their output.
    Returns list of dicts with street/city/state/zip keys.
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

    def _add_parsed(line: str):
        parsed = _parse_address_line(line)
        # Only keep if we got something useful
        if parsed['street'] or parsed['zip']:
            key = (parsed['street'].lower(), parsed['city'].lower(), parsed['zip'])
            if key not in seen:
                seen.add(key)
                addresses.append(parsed)

    # DATA_ATTRS — most reliable for map widgets
    data_block = _extract_data_attr_addresses(soup)
    for line in data_block.split('\n'):
        line = line.strip().lstrip('  ')
        if line and _ZIP_RE.search(line):
            _add_parsed(line)

    # MICRODATA
    micro_block = _extract_microdata_addresses(soup)
    for line in micro_block.split('\n'):
        line = line.strip().lstrip('  ')
        if line and (_ZIP_RE.search(line) or re.search(r'\d{3,}', line)):
            _add_parsed(line)

    # GOOGLE_MAPS — iframe and link URLs
    gmaps_block = _extract_gmaps_addresses(soup)
    for line in gmaps_block.split('\n'):
        line = line.strip().lstrip('  ')
        if line and not line.startswith('GOOGLE') and _ZIP_RE.search(line):
            _add_parsed(line)

    # JSON-LD structured data
    jsonld_block = _extract_json_ld(soup)
    for line in jsonld_block.split('\n'):
        line = line.strip().lstrip('  ')
        if line.startswith('address:') and _ZIP_RE.search(line):
            _add_parsed(line.replace('address:', '').strip())

    # SCRIPT_DATA — JS variables
    script_block = _extract_script_address_data(soup)
    for line in script_block.split('\n'):
        line = line.strip().lstrip('  ')
        if line and _ZIP_RE.search(line):
            _add_parsed(line)

    return addresses


def _best_match(candidates: list[dict], existing_row: dict) -> dict | None:
    """
    Match a candidate address to an existing incomplete row by city name.
    """
    target_city = _normalize(existing_row.get('address_city', ''))
    target_name = _normalize(existing_row.get('location_name', ''))

    if not candidates:
        return None

    # If only one candidate and row has no city, just use it
    if len(candidates) == 1 and not target_city:
        return candidates[0]

    # Match by city
    if target_city:
        city_matches = [c for c in candidates if _normalize(c.get('city', '')) == target_city]
        if len(city_matches) == 1:
            return city_matches[0]
        # Multiple city matches — prefer one with street
        with_street = [c for c in city_matches if c.get('street')]
        if len(with_street) == 1:
            return with_street[0]
        if city_matches:
            return city_matches[0]

    return None


async def fetch_html(url: str, sem: asyncio.Semaphore) -> str:
    from src.fetch import fetch_url
    async with sem:
        try:
            result = await fetch_url(url)
            if result.html and not result.blocked:
                return result.html
        except Exception as e:
            logger.debug(f"fetch {url}: {e}")
    return ""


async def main(concurrency: int, verbose: bool, dry_run: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    # ── Load location rows ────────────────────────────────────────────────────
    with open(LOCS_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames[:]
        all_rows = list(reader)

    logger.info(f"Loaded {len(all_rows)} rows")

    # ── Find incomplete rows grouped by source_url ────────────────────────────
    url_to_rows: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    for i, row in enumerate(all_rows):
        s = (row.get('address_street') or '').strip()
        z = (row.get('address_zip') or '').strip()
        if not s or not z:
            src = (row.get('source_url') or '').strip()
            if src:
                url_to_rows[src].append((i, row))

    total_urls = len(url_to_rows)
    total_incomplete = sum(len(v) for v in url_to_rows.values())
    logger.info(f"Incomplete rows: {total_incomplete} across {total_urls} unique URLs")

    # ── Fetch all URLs concurrently ───────────────────────────────────────────
    sem = asyncio.Semaphore(concurrency)
    completed = 0
    patched = 0
    t0 = time.time()

    async def process_url(url: str):
        nonlocal completed, patched
        html = await fetch_html(url, sem)
        completed += 1

        if completed % 100 == 0 or completed == total_urls:
            elapsed = time.time() - t0
            rate = completed / elapsed
            eta = (total_urls - completed) / rate if rate else 0
            logger.info(f"{completed}/{total_urls} URLs | patched={patched} | ETA={eta/60:.1f}min")

        if not html:
            return

        candidates = _extract_addresses_from_html(html, url)
        if not candidates:
            return

        for row_idx, row in url_to_rows[url]:
            match = _best_match(candidates, row)
            if not match:
                # If only one candidate and row has no city yet, just take it
                if len(candidates) == 1:
                    match = candidates[0]
                else:
                    continue

            changed = False
            if not all_rows[row_idx].get('address_street','').strip() and match.get('street'):
                all_rows[row_idx]['address_street'] = match['street']
                changed = True
            if not all_rows[row_idx].get('address_zip','').strip() and match.get('zip'):
                all_rows[row_idx]['address_zip'] = match['zip']
                changed = True
            if not all_rows[row_idx].get('address_city','').strip() and match.get('city'):
                all_rows[row_idx]['address_city'] = match['city']
                changed = True
            if not all_rows[row_idx].get('address_state','').strip() and match.get('state'):
                all_rows[row_idx]['address_state'] = match['state']
                changed = True
            if changed:
                patched += 1

    await asyncio.gather(*[process_url(u) for u in url_to_rows.keys()])

    logger.info(f"Done. Patched {patched}/{total_incomplete} rows")

    # ── Write updated CSV ─────────────────────────────────────────────────────
    if not dry_run:
        with open(LOCS_PATH, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore',
                                    quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            writer.writerows(all_rows)
        logger.info(f"Written {len(all_rows)} rows to {LOCS_PATH}")
    else:
        logger.info("DRY RUN — nothing written")

    # ── Report ────────────────────────────────────────────────────────────────
    report = f"""# Patch Missing Addresses Report

Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

| | Count |
|---|---|
| Incomplete rows targeted | {total_incomplete} |
| Unique source URLs fetched | {total_urls} |
| Rows patched | {patched} |
| Rows not matched | {total_incomplete - patched} |
| Patch rate | {patched/total_incomplete*100:.1f}% |
"""
    with open(REPORT, 'w') as f:
        f.write(report)
    print(report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--concurrency', type=int, default=URL_CONCURRENCY)
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    asyncio.run(main(args.concurrency, args.verbose, args.dry_run))
