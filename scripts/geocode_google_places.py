"""
scripts/geocode_google_places.py

For location rows with city+state but missing street and/or zip,
search Google Places Text Search API to find the full address.

Search query: "{location_name} {address_city} {address_state}"
Falls back to "{domain} {address_city} {address_state}" if no location_name.

Usage:
    python -m scripts.geocode_google_places [--dry-run] [--concurrency N] [--verbose]

Requires:
    GOOGLE_PLACES_API_KEY in .env

Cost estimate: ~$17 per 1,000 requests (Text Search basic tier)
"""
import argparse
import asyncio
import csv
import logging
import os
import re
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DATA      = os.path.join(os.path.dirname(__file__), "..", "data")
LOCS_PATH = os.path.join(DATA, "output_locations.csv")
REPORT    = os.path.join(DATA, "geocode_google_places_report.md")

CONCURRENCY  = 10   # Google allows higher, but stay polite
PRICE_PER_K  = 17.0 # USD per 1000 Text Search requests


# ── Address parsing ───────────────────────────────────────────────────────────

_ZIP_RE = re.compile(r'\b(\d{5})(?:-\d{4})?\b')
_US_STATES = {
    'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA',
    'KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ',
    'NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT',
    'VA','WA','WV','WI','WY','DC','PR','GU','VI',
}


def _parse_formatted_address(formatted: str) -> dict:
    """
    Parse Google's formatted_address like "123 Main St, Austin, TX 78701, USA"
    into street/city/state/zip components.
    """
    result = {'street': '', 'city': '', 'state': '', 'zip': ''}

    # Remove trailing country
    formatted = re.sub(r',?\s*(USA|United States)\s*$', '', formatted).strip()

    # Extract ZIP
    zm = _ZIP_RE.search(formatted)
    if zm:
        result['zip'] = zm.group(1)
        formatted = formatted[:zm.start()].strip(', ')

    # Extract state at end
    sm = re.search(r',?\s*\b([A-Z]{2})\s*$', formatted)
    if sm and sm.group(1) in _US_STATES:
        result['state'] = sm.group(1)
        formatted = formatted[:sm.start()].strip(', ')

    # Remaining: "Street, City" or "Street"
    parts = [p.strip() for p in formatted.split(',') if p.strip()]
    if len(parts) >= 2:
        result['street'] = parts[0]
        result['city'] = parts[1]
    elif len(parts) == 1:
        # Could be just city or just street
        if re.search(r'\d', parts[0]):
            result['street'] = parts[0]
        else:
            result['city'] = parts[0]

    return result


def _parse_address_components(components: list) -> dict:
    """
    Parse Google Places address_components array into street/city/state/zip.
    More reliable than parsing formatted_address.
    """
    result = {'street': '', 'city': '', 'state': '', 'zip': ''}

    street_number = ''
    route = ''

    for comp in components:
        types = comp.get('types', [])
        short = comp.get('short_name', '')
        long_ = comp.get('long_name', '')

        if 'street_number' in types:
            street_number = long_
        elif 'route' in types:
            route = long_
        elif 'locality' in types or 'sublocality_level_1' in types:
            if not result['city']:
                result['city'] = long_
        elif 'administrative_area_level_1' in types:
            result['state'] = short  # 2-letter abbr
        elif 'postal_code' in types:
            result['zip'] = long_

    if street_number and route:
        result['street'] = f"{street_number} {route}"
    elif route:
        result['street'] = route

    return result


# ── Google Places API ─────────────────────────────────────────────────────────

async def search_place(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    query: str,
    api_key: str,
) -> dict | None:
    """
    Call Google Places Text Search (old API) for a single query.
    Returns parsed address dict or None if not found.
    """
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": query,
        "type": "health",   # bias toward medical facilities
        "key": api_key,
    }

    async with sem:
        try:
            resp = await client.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.debug(f"Places API error for '{query}': {e}")
            return None

    if data.get('status') not in ('OK', 'ZERO_RESULTS'):
        logger.debug(f"Places API status={data.get('status')} for '{query}'")
        return None

    results = data.get('results', [])
    if not results:
        return None

    top = results[0]
    formatted = top.get('formatted_address', '')
    if not formatted:
        return None

    # Use formatted_address parsing (components not returned in textsearch by default)
    return _parse_formatted_address(formatted)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main(concurrency: int, verbose: bool, dry_run: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    api_key = os.environ.get('GOOGLE_PLACES_API_KEY', '')
    if not api_key:
        logger.error("GOOGLE_PLACES_API_KEY not set in .env — aborting")
        sys.exit(1)

    # Load rows
    with open(LOCS_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames[:]
        all_rows = list(reader)

    logger.info(f"Loaded {len(all_rows)} rows")

    # Find city+state-only rows (no street, no zip)
    target_indices = []
    for i, row in enumerate(all_rows):
        has_street = bool((row.get('address_street') or '').strip())
        has_zip    = bool((row.get('address_zip') or '').strip())
        has_city   = bool((row.get('address_city') or '').strip())
        has_state  = bool((row.get('address_state') or '').strip())
        # Only target rows with city+state but missing street or zip
        if not has_street and has_city and has_state:
            target_indices.append(i)

    total = len(target_indices)
    est_cost = total * PRICE_PER_K / 1000
    logger.info(f"Target rows: {total} | Est. cost: ${est_cost:.2f}")

    if dry_run:
        logger.info("DRY RUN — showing first 5 queries only")
        for idx in target_indices[:5]:
            row = all_rows[idx]
            name  = (row.get('location_name') or '').strip()
            city  = (row.get('address_city') or '').strip()
            state = (row.get('address_state') or '').strip()
            domain = row.get('domain', '')
            q = f"{name or domain} {city} {state}".strip()
            logger.info(f"  Would search: '{q}'")
        return

    # Run
    sem = asyncio.Semaphore(concurrency)
    patched = 0
    not_found = 0
    completed = 0
    t0 = time.time()

    async with httpx.AsyncClient() as client:
        async def process_row(idx: int):
            nonlocal patched, not_found, completed

            row = all_rows[idx]
            name   = (row.get('location_name') or '').strip()
            city   = (row.get('address_city') or '').strip()
            state  = (row.get('address_state') or '').strip()
            domain = row.get('domain', '')

            # Build search query — always include humanized domain as org context
            # e.g. "universitycardiology.com" → "universitycardiology"
            org_name = domain.rsplit('.', 1)[0].replace('-', ' ').replace('_', ' ')
            # Combine org name + location branch name (if any) for best match
            if name and name.lower() not in org_name.lower():
                search_name = f"{org_name} {name}"
            else:
                search_name = org_name
            query = f"{search_name} {city} {state}".strip()

            result = await search_place(client, sem, query, api_key)
            completed += 1

            if completed % 100 == 0 or completed == total:
                elapsed = time.time() - t0
                rate = completed / elapsed
                eta = (total - completed) / rate if rate else 0
                logger.info(
                    f"{completed}/{total} | patched={patched} | "
                    f"not_found={not_found} | ETA={eta/60:.1f}min"
                )

            if not result:
                not_found += 1
                return

            changed = False
            if not all_rows[idx].get('address_street','').strip() and result.get('street'):
                all_rows[idx]['address_street'] = result['street']
                changed = True
            if not all_rows[idx].get('address_zip','').strip() and result.get('zip'):
                all_rows[idx]['address_zip'] = result['zip']
                changed = True
            if not all_rows[idx].get('address_city','').strip() and result.get('city'):
                all_rows[idx]['address_city'] = result['city']
                changed = True
            if not all_rows[idx].get('address_state','').strip() and result.get('state'):
                all_rows[idx]['address_state'] = result['state']
                changed = True
            if changed:
                patched += 1
            else:
                not_found += 1

        await asyncio.gather(*[process_row(i) for i in target_indices])

    logger.info(f"Done. Patched {patched}/{total} | Not found/unchanged: {not_found}")

    # Write
    with open(LOCS_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore',
                                quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(all_rows)
    logger.info(f"Written {len(all_rows)} rows to {LOCS_PATH}")

    actual_cost = completed * PRICE_PER_K / 1000

    report = f"""# Google Places Geocoding Report

Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

| | Count |
|---|---|
| Target rows (city+state, no street) | {total} |
| Patched | {patched} |
| Not found / unchanged | {not_found} |
| Patch rate | {patched/total*100:.1f}% |
| Est. API cost | ${actual_cost:.2f} |
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
