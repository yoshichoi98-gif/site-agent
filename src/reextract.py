"""
Re-extraction pass for domains that were fetched successfully but produced
empty evidence fields (caused by an API overload cascade mid-run).

Reads output_orgs.csv, finds rows with a successful fetch_status but blank
canonical_org_name, loads the cached HTML, and re-runs steps 2-5 of the
pipeline (planner → subpage fetch → extractor → location extractor).

Results are written to data/reextract_orgs.csv and data/reextract_locations.csv.
To merge back into the master CSV afterwards, use --merge.

Usage:
  python -m src.reextract                  # dry-run count
  python -m src.reextract --run            # process all 4558 domains
  python -m src.reextract --run --limit 50 # test on first 50
  python -m src.reextract --merge          # splice reextract results back into output_orgs.csv
"""
import argparse
import asyncio
import collections
import csv
import logging
import os
import re
import sys
import time

from src.config import CACHE_DIR, MAX_COST_USD_PER_RUN
from src.pipeline import (
    RESEARCH_TARGET_SUBCATEGORIES,
    _profile_to_org_row,
    add_cost,
    get_run_cost,
    locations_to_rows,
    reset_run_cost,
)
from src.extract import extract
from src.fetch import fetch_url
from src.planner import plan_crawl
from src.location_extract import extract_locations
from src.schema import Evidence, SiteProfile

import httpx

logger = logging.getLogger(__name__)

FETCH_SUCCESS = {'httpx', 'curl_cffi', 'playwright', 'playwright_stealth', 'cache'}

_NON_EVIDENCE_FIELDS = {"locations", "locations_capped", "locations_capped_reason"}

_LOCATION_COLUMNS = [
    "domain", "location_name", "address_street", "address_city",
    "address_state", "address_zip", "phone", "source_url", "snippet",
    "confidence", "validation_status",
]


def _org_columns() -> list[str]:
    base = [
        "domain", "finished_at", "latency_s", "fetch_status", "content_quality",
        "error", "locations_capped", "locations_capped_reason",
    ]
    for field_name in SiteProfile.model_fields:
        if field_name in _NON_EVIDENCE_FIELDS:
            continue
        base += [
            f"{field_name}__value",
            f"{field_name}__confidence",
            f"{field_name}__source_url",
            f"{field_name}__snippet",
        ]
    return base


def _ensure_header(path: str, columns: list[str]):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=columns).writeheader()


def _load_cache(domain: str) -> str | None:
    safe = re.sub(r"[^\w.-]", "_", domain)
    path = os.path.join(CACHE_DIR, f"{safe}.html")
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    return None


def _find_reextract_targets(orgs_path: str) -> list[tuple[str, str]]:
    """Return (domain, original_fetch_status) for rows needing re-extraction.

    Also tracks already-processed reextract domains so reruns are idempotent.
    """
    seen: dict[str, str] = {}  # domain → fetch_status (last occurrence wins)
    with open(orgs_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            domain = row.get("domain", "").strip()
            status = row.get("fetch_status", "").strip()
            org    = row.get("canonical_org_name__value", "").strip()
            if domain:
                seen[domain] = (status, org)

    targets = []
    for domain, (status, org) in seen.items():
        if status in FETCH_SUCCESS and not org:
            targets.append((domain, status))
    return targets


def _load_already_done(reextract_path: str) -> set[str]:
    if not os.path.exists(reextract_path):
        return set()
    with open(reextract_path, newline="", encoding="utf-8") as f:
        return {row["domain"] for row in csv.DictReader(f) if row.get("domain")}


async def _reextract_one(
    domain: str,
    original_status: str,
    max_cost_usd: float,
) -> tuple[dict, list[dict]]:
    """Re-run planner→fetch subpages→extract→locations using cached homepage HTML."""
    t0 = time.time()

    def _empty(error: str = "") -> tuple[dict, list]:
        profile = SiteProfile()
        return (_profile_to_org_row(domain, profile, time.time() - t0,
                                    original_status, error), [])

    if get_run_cost() >= max_cost_usd:
        return _empty("cost_cap_reached")

    homepage_html = _load_cache(domain)
    if not homepage_html:
        logger.warning(f"[{domain}] no cache found — skipping")
        return _empty("no_cache")

    loop = asyncio.get_event_loop()

    # Step 2: planner
    plan = None
    try:
        plan, plan_usage = await loop.run_in_executor(
            None, lambda: plan_crawl(homepage_html, domain)
        )
        add_cost(plan_usage.input_tokens, plan_usage.output_tokens)
    except Exception as e:
        logger.warning(f"[{domain}] planner failed: {e}")

    # Step 3: fetch subpages (hits cache when available, re-fetches otherwise)
    additional: dict[str, str] = {}
    if plan and plan.pages:
        results = await asyncio.gather(
            *[fetch_url(p.url) for p in plan.pages],
            return_exceptions=True,
        )
        for p, result in zip(plan.pages, results):
            if isinstance(result, Exception):
                logger.warning(f"[{domain}] subpage error {p.url}: {result}")
            elif result.blocked or not result.html:
                logger.info(f"[{domain}] subpage blocked: {p.url}")
            else:
                additional[p.url] = result.html

    # Step 4: extract
    profile = SiteProfile()
    try:
        profile, extract_usage = await loop.run_in_executor(
            None, lambda: extract(domain, homepage_html, additional)
        )
        add_cost(extract_usage.input_tokens, extract_usage.output_tokens)
    except Exception as e:
        logger.error(f"[{domain}] extractor failed: {e}")

    # Step 4b: validate research_url
    if profile.research_url.value:
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.head(profile.research_url.value)
            if resp.status_code in {404, 410, 451} or resp.status_code >= 500:
                profile.research_url = Evidence()
        except Exception:
            pass

    # Step 5: location extraction (conditional)
    profile.locations = []
    profile.locations_capped = False
    profile.locations_capped_reason = None

    subcategory = (profile.org_subcategory.value or "").lower()
    if subcategory in RESEARCH_TARGET_SUBCATEGORIES and get_run_cost() < max_cost_usd:
        try:
            loc_result, loc_usage = await loop.run_in_executor(
                None, lambda: extract_locations(domain, homepage_html, additional)
            )
            profile.locations = loc_result.locations
            profile.locations_capped = loc_result.capped
            profile.locations_capped_reason = loc_result.capped_reason
            add_cost(loc_usage.input_tokens, loc_usage.output_tokens)
        except Exception as e:
            logger.error(f"[{domain}] location extractor failed: {e}")

    latency = time.time() - t0
    org_row  = _profile_to_org_row(domain, profile, latency, original_status)
    loc_rows = locations_to_rows(domain, profile.locations)
    return org_row, loc_rows


async def run(
    targets: list[tuple[str, str]],
    orgs_out: str,
    locs_out: str,
    concurrency: int,
    max_cost: float,
):
    total = len(targets)
    org_cols = _org_columns()
    _ensure_header(orgs_out, org_cols)
    _ensure_header(locs_out, _LOCATION_COLUMNS)

    semaphore = asyncio.Semaphore(concurrency)
    reset_run_cost()

    completed = 0
    filled_count  = 0
    empty_count   = 0
    no_cache_count = 0
    enum_count    = 0
    skip_count    = 0
    error_count   = 0
    last_info     = ""
    start_time = time.time()
    lock = asyncio.Lock()

    async def run_one(domain: str, original_status: str):
        nonlocal completed, filled_count, empty_count, no_cache_count
        nonlocal enum_count, skip_count, error_count, last_info

        if get_run_cost() >= max_cost:
            logger.error(f"Cost cap ${max_cost:.2f} reached — stopping.")
            return

        async with semaphore:
            t0 = time.time()
            org_row, loc_rows = await _reextract_one(domain, original_status, max_cost)
            proc = time.time() - t0

        with open(orgs_out, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=org_cols, extrasaction="ignore").writerow(org_row)
        if loc_rows:
            with open(locs_out, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=_LOCATION_COLUMNS, extrasaction="ignore").writerows(loc_rows)

        org_name  = org_row.get("canonical_org_name__value", "")
        error     = org_row.get("error", "")
        elapsed   = time.time() - start_time

        async with lock:
            completed += 1
            if error == "no_cache":
                no_cache_count += 1
            elif error:
                error_count += 1
            elif org_name:
                filled_count += 1
            else:
                empty_count += 1

            if loc_rows:
                enum_count += 1
            else:
                skip_count += 1

            last_info = f"{domain}({original_status},{proc:.1f}s)"

            if completed % 25 == 0 or completed == total:
                rate = completed / max(elapsed, 0.001)
                eta  = (total - completed) / rate / 60 if rate > 0 else 0
                print(
                    f"{completed}/{total}  rate={rate:.1f}/s  ETA={eta:.1f}min"
                    f"  filled={filled_count} empty={empty_count} no_cache={no_cache_count}"
                    f"  enum={enum_count} skip={skip_count}  errors={error_count}"
                    f"  cost=${get_run_cost():.2f}  last={last_info}",
                    file=sys.stderr,
                )

    await asyncio.gather(*[run_one(d, s) for d, s in targets])
    elapsed = time.time() - start_time
    print(
        f"\nDone. {completed}/{total} in {elapsed/60:.1f}min."
        f"  Filled: {filled_count}  Empty: {empty_count}  Cost: ${get_run_cost():.4f}",
        file=sys.stderr,
    )


def _merge(orgs_master: str, reextract_path: str):
    """Replace empty-extraction rows in orgs_master with rows from reextract_path."""
    # Load reextract results keyed by domain
    reextracted: dict[str, dict] = {}
    with open(reextract_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row.get("domain", "").strip()
            if d:
                reextracted[d] = row

    # Read master, replace matching rows
    with open(orgs_master, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    replaced = 0
    seen_domains: set[str] = set()
    out_rows = []
    for row in rows:
        d = row.get("domain", "").strip()
        if d in reextracted and d not in seen_domains:
            new_row = reextracted[d]
            # Carry over fetch_status / content_quality from original if reextract kept them
            out_rows.append({k: new_row.get(k, row.get(k, "")) for k in fieldnames})
            replaced += 1
        else:
            out_rows.append(row)
        seen_domains.add(d)

    backup = orgs_master.replace(".csv", "_pre_reextract_backup.csv")
    import shutil
    shutil.copy2(orgs_master, backup)
    print(f"Backup saved to {backup}")

    with open(orgs_master, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Merged {replaced} rows into {orgs_master}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--orgs-input",  default="data/output_orgs.csv")
    parser.add_argument("--orgs-output", default="data/reextract_orgs.csv")
    parser.add_argument("--locs-output", default="data/reextract_locations.csv")
    parser.add_argument("--run",         action="store_true",
                        help="Actually process (default is dry-run count only)")
    parser.add_argument("--limit",       type=int, default=None,
                        help="Cap number of domains to process")
    parser.add_argument("--concurrency", type=int, default=15)
    parser.add_argument("--max-cost",    type=float, default=120.0)
    parser.add_argument("--merge",       action="store_true",
                        help="Merge reextract_orgs.csv back into output_orgs.csv")
    parser.add_argument("--verbose",     action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if args.merge:
        _merge(args.orgs_input, args.orgs_output)
        return

    targets = _find_reextract_targets(args.orgs_input)

    # Skip already done
    already_done = _load_already_done(args.orgs_output)
    targets = [(d, s) for d, s in targets if d not in already_done]

    if args.limit:
        targets = targets[:args.limit]

    print(f"Re-extraction targets: {len(targets)}", file=sys.stderr)
    if not args.run:
        print("(dry run — pass --run to execute)", file=sys.stderr)
        return

    asyncio.run(run(targets, args.orgs_output, args.locs_output, args.concurrency, args.max_cost))


if __name__ == "__main__":
    main()
