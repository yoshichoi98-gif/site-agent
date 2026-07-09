"""
scripts/expand_multi_location_rows.py

For rows that have a location_name but no city, where the source page
has multiple locations for that same practice name — expand into one row
per location instead of keeping one ambiguous row.

How it works:
1. Find rows with location_name but missing city (and missing street)
2. Group by source_url
3. Fetch each source_url with Playwright (JS-rendered)
4. Run named-block extraction to get (practice_name -> [address, ...]) map
5. For each ambiguous row whose location_name matches a practice with N locations:
   - If N == 1: just patch the row in place
   - If N > 1: delete the original row, insert N new rows (one per location)

Usage:
    python -m scripts.expand_multi_location_rows [--dry-run] [--verbose]
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
REPORT    = os.path.join(DATA, "expand_multi_location_report.md")

CONCURRENCY = 5

_ZIP_RE    = re.compile(r'\b(\d{5})(?:-\d{4})?\b')
_US_STATES = {'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA',
              'KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ',
              'NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT',
              'VA','WA','WV','WI','WY','DC','PR','GU','VI'}
_PHONE_RE  = re.compile(r'tel:\S+')


def _normalize(s: str) -> str:
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def _parse_address_line(line: str) -> dict:
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


def _extract_named_addresses(html: str) -> dict[str, list[dict]]:
    """
    Extract a map of {practice_name: [address_dict, ...]} from rendered HTML.

    Looks for heading elements followed by address content (either zip-containing
    text or Google Maps daddr links). Each heading becomes a practice name key.
    """
    from bs4 import BeautifulSoup, Tag

    soup = BeautifulSoup(html, 'html.parser')
    named = defaultdict(list)  # name -> [parsed_address, ...]
    seen  = set()

    def _add(name: str, line: str):
        parsed = _parse_address_line(line)
        if not (parsed['street'] or parsed['zip']):
            return
        key = (parsed['street'].lower(), parsed['city'].lower(), parsed['zip'])
        if key in seen:
            return
        seen.add(key)
        named[name].append(parsed)

    for heading in soup.find_all(['h1', 'h2', 'h3', 'h4']):
        name_text = heading.get_text(separator=' ', strip=True).strip()
        if not name_text or len(name_text) > 100:
            continue

        sibling = heading.next_sibling
        steps = 0
        while sibling and steps < 8:
            if isinstance(sibling, Tag):
                # Plain text with zip
                text = sibling.get_text(separator=' ', strip=True)
                if _ZIP_RE.search(text):
                    _add(name_text, text)
                # Google Maps daddr links
                for a in sibling.find_all('a', href=True):
                    href = a['href']
                    if 'daddr=' in href or 'maps.google' in href:
                        addr_text = a.get_text(separator=', ', strip=True)
                        if _ZIP_RE.search(addr_text):
                            _add(name_text, addr_text)
                # Stop if we hit another heading
                if sibling.name in ('h1', 'h2', 'h3', 'h4'):
                    break
            sibling = sibling.next_sibling
            steps += 1

    return dict(named)


async def fetch_html(url: str, browser, sem: asyncio.Semaphore) -> str:
    async with sem:
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await page.wait_for_timeout(2000)
            return await page.content()
        except Exception as e:
            logger.debug(f"fetch {url}: {e}")
            return ''
        finally:
            await page.close()


async def main(dry_run: bool, verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s',
        stream=sys.stderr,
    )

    # Load rows
    with open(LOCS_PATH, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames[:]
        all_rows = list(reader)

    logger.info(f'Loaded {len(all_rows)} rows')

    # Find ambiguous rows: have location_name, missing city AND street
    ambiguous_indices = []
    for i, row in enumerate(all_rows):
        has_name   = bool((row.get('location_name') or '').strip())
        has_city   = bool((row.get('address_city') or '').strip())
        has_street = bool((row.get('address_street') or '').strip())
        has_url    = bool((row.get('source_url') or '').strip())
        if has_name and not has_city and not has_street and has_url:
            ambiguous_indices.append(i)

    # Group by source_url
    url_to_indices: dict[str, list[int]] = defaultdict(list)
    for i in ambiguous_indices:
        url_to_indices[all_rows[i]['source_url']].append(i)

    logger.info(f'Ambiguous rows: {len(ambiguous_indices)} across {len(url_to_indices)} URLs')

    if dry_run:
        logger.info('DRY RUN — showing first 5 URLs')
        for url, indices in list(url_to_indices.items())[:5]:
            names = [all_rows[i].get('location_name','') for i in indices]
            logger.info(f'  {url}')
            for n in names:
                logger.info(f'    → "{n}"')
        return

    # Fetch all URLs
    sem = asyncio.Semaphore(CONCURRENCY)
    url_to_named: dict[str, dict[str, list[dict]]] = {}
    completed = 0
    t0 = time.time()

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        async def process_url(url: str):
            nonlocal completed
            html = await fetch_html(url, browser, sem)
            completed += 1
            if completed % 20 == 0 or completed == len(url_to_indices):
                logger.info(f'{completed}/{len(url_to_indices)} URLs fetched')
            if html:
                url_to_named[url] = _extract_named_addresses(html)

        await asyncio.gather(*[process_url(u) for u in url_to_indices])
        await browser.close()

    # Build expanded rows
    # rows_to_delete: set of indices to remove
    # rows_to_insert: list of (after_index, new_row) to insert after processing
    rows_to_delete = set()
    rows_to_insert = []  # (insert_after_index, [new_rows])

    expanded_count = 0
    patched_count  = 0
    skipped_count  = 0

    for url, indices in url_to_indices.items():
        named = url_to_named.get(url, {})
        if not named:
            skipped_count += len(indices)
            continue

        for idx in indices:
            row = all_rows[idx]
            loc_name   = (row.get('location_name') or '').strip()
            norm_name  = _normalize(loc_name)

            # Find which practice name in the page best matches this row's location_name
            best_key = None
            best_score = 0
            for page_name in named:
                norm_page = _normalize(page_name)
                # Simple containment match
                if norm_name in norm_page or norm_page in norm_name:
                    score = len(set(norm_name) & set(norm_page))
                    if score > best_score:
                        best_score = score
                        best_key = page_name

            if not best_key:
                skipped_count += 1
                logger.debug(f'No match for "{loc_name}" on {url}')
                continue

            locations = named[best_key]

            if len(locations) == 1:
                # Patch in place
                addr = locations[0]
                changed = False
                for field, key in [('address_street','street'),('address_zip','zip'),
                                    ('address_city','city'),('address_state','state')]:
                    if not all_rows[idx].get(field,'').strip() and addr.get(key):
                        all_rows[idx][field] = addr[key]
                        changed = True
                if changed:
                    patched_count += 1
            else:
                # Expand: delete original, insert N rows
                rows_to_delete.add(idx)
                new_rows = []
                for addr in locations:
                    new_row = dict(row)  # copy all fields
                    new_row['address_street'] = addr.get('street', '')
                    new_row['address_city']   = addr.get('city', '')
                    new_row['address_state']  = addr.get('state', '')
                    new_row['address_zip']    = addr.get('zip', '')
                    new_rows.append(new_row)
                rows_to_insert.append((idx, new_rows))
                expanded_count += len(locations)
                logger.debug(
                    f'Expanding "{loc_name}" → {len(locations)} rows '
                    f'({", ".join(a.get("city","?") for a in locations)})'
                )

    # Apply deletions and insertions
    # Process in reverse index order to preserve positions
    final_rows = []
    insert_map = {idx: new_rows for idx, new_rows in rows_to_insert}

    for i, row in enumerate(all_rows):
        if i in rows_to_delete:
            # Insert expanded rows in place
            final_rows.extend(insert_map[i])
        else:
            final_rows.append(row)

    logger.info(
        f'Results: {patched_count} patched in place | '
        f'{len(rows_to_delete)} rows expanded → {expanded_count} new rows | '
        f'{skipped_count} skipped'
    )
    logger.info(f'Row count: {len(all_rows)} → {len(final_rows)}')

    # Write
    with open(LOCS_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore',
                                quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(final_rows)
    logger.info(f'Written {len(final_rows)} rows to {LOCS_PATH}')

    report = f"""# Expand Multi-Location Rows Report

Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}

| | Count |
|---|---|
| Ambiguous rows targeted | {len(ambiguous_indices)} |
| Patched in place (1 location) | {patched_count} |
| Rows expanded (2+ locations) | {len(rows_to_delete)} → {expanded_count} rows |
| Skipped (no match found) | {skipped_count} |
| Final row count | {len(final_rows)} |
"""
    with open(REPORT, 'w') as f:
        f.write(report)
    print(report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    asyncio.run(main(args.dry_run, args.verbose))
