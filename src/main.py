"""
CLI entry point.
Usage: python -m src.main --input data/smoke_test_domains.csv
                          --orgs data/output_orgs.csv
                          --locations data/output_locations.csv
                          [--limit N] [--concurrency N] [--verbose]

Produces two append-only CSVs joined by `domain`:
  output_orgs.csv      — one row per domain (SiteProfile Evidence fields)
  output_locations.csv — one row per Location extracted
"""
import argparse
import asyncio
import collections
import csv
import logging
import os
import sys
import time

from src.config import MAX_COST_USD_PER_RUN, MAX_ROWS_PER_RUN
from src.pipeline import RESEARCH_TARGET_SUBCATEGORIES, get_run_cost, locations_to_rows, process_row, reset_run_cost
from src.schema import SiteProfile

_LOCATION_COLUMNS = [
    "domain", "location_name", "address_street", "address_city",
    "address_state", "address_zip", "phone", "source_url", "snippet", "confidence",
    "validation_status",
]

_NON_EVIDENCE_FIELDS = {"locations", "locations_capped", "locations_capped_reason"}


def _org_columns() -> list[str]:
    base = ["domain", "finished_at", "latency_s", "fetch_status", "content_quality", "error", "locations_capped", "locations_capped_reason"]
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


def _load_processed(orgs_path: str) -> set[str]:
    if not os.path.exists(orgs_path):
        return set()
    with open(orgs_path, newline="", encoding="utf-8") as f:
        return {row["domain"] for row in csv.DictReader(f) if row.get("domain")}


def _load_input(input_path: str) -> list[str]:
    with open(input_path, newline="", encoding="utf-8") as f:
        return [row["domain"].strip() for row in csv.DictReader(f) if row.get("domain", "").strip()]


def _ensure_header(path: str, columns: list[str]):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=columns).writeheader()


async def run(input_path: str, orgs_path: str, locs_path: str,
              limit: int, concurrency: int, max_cost: float):
    logger = logging.getLogger(__name__)
    domains = _load_input(input_path)
    processed = _load_processed(orgs_path)
    todo = [d for d in domains if d not in processed][:limit]

    logger.info(f"Input: {len(domains)} | Already done: {len(processed)} | To run: {len(todo)}")
    if not todo:
        logger.info("Nothing to do.")
        return

    total = len(todo)
    org_cols = _org_columns()
    _ensure_header(orgs_path, org_cols)
    _ensure_header(locs_path, _LOCATION_COLUMNS)

    semaphore = asyncio.Semaphore(concurrency)
    reset_run_cost()

    # Progress state
    completed = 0
    tiers: dict[str, int] = collections.defaultdict(int)
    enum_count = 0
    skip_count = 0
    error_count = 0
    recent_times: list[float] = []  # completion timestamps for rolling rate
    last_print_time = time.time()
    start_time = time.time()
    lock = asyncio.Lock()

    def _print_progress(last_domain: str, last_tier: str, last_latency: float):
        now = time.time()
        # Rolling rate over last 20 completions
        if len(recent_times) >= 2:
            window = recent_times[-min(20, len(recent_times)):]
            rate = (len(window) - 1) / max(window[-1] - window[0], 0.001)
        else:
            elapsed = now - start_time
            rate = completed / max(elapsed, 0.001)
        remaining = total - completed
        eta_min = (remaining / rate / 60) if rate > 0 else 0

        print(
            f"{completed:>4}/{total}"
            f"  rate={rate:.1f}/s"
            f"  ETA={eta_min:.1f}min"
            f"  cache={tiers['cache']}"
            f" httpx={tiers['httpx']}"
            f" curl={tiers['curl_cffi']}"
            f" pw={tiers['playwright']}"
            f" stealth={tiers['playwright_stealth']}"
            f" blocked={tiers['blocked']}"
            f" parked={tiers['parked']}"
            f"  enum={enum_count} skip={skip_count}"
            f"  errors={error_count}"
            f"  cost=${get_run_cost():.2f}"
            f"  last={last_domain}({last_tier},{last_latency:.1f}s)",
            file=sys.stderr,
        )

    async def run_one(domain: str):
        nonlocal completed, enum_count, skip_count, error_count, last_print_time

        if get_run_cost() >= max_cost:
            logger.error(f"Cost cap ${max_cost:.2f} reached — stopping.")
            return
        async with semaphore:
            t0 = time.time()
            org_row, loc_rows = await process_row(domain, max_cost_usd=max_cost)
            latency = time.time() - t0  # inside semaphore: no other coroutine can preempt here

        with open(orgs_path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=org_cols, extrasaction="ignore").writerow(org_row)

        if loc_rows:
            with open(locs_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=_LOCATION_COLUMNS, extrasaction="ignore")
                writer.writerows(loc_rows)
        tier = org_row.get("fetch_status", "unknown")
        error = org_row.get("error", "")
        if error:
            error_count += 1

        # Per-row line — latency = time inside semaphore (excludes queue wait)
        # elapsed = wall-clock time since run started (includes queue wait)
        elapsed = time.time() - start_time
        print(f"  {domain}  {tier}  proc={latency:.1f}s  elapsed={elapsed:.1f}s" + (f"  [{error}]" if error else ""),
              file=sys.stderr)

        subcategory = org_row.get("org_subcategory__value", "").lower()
        async with lock:
            completed += 1
            tiers[tier] += 1
            recent_times.append(time.time())
            if subcategory in RESEARCH_TARGET_SUBCATEGORIES:
                enum_count += 1
            else:
                skip_count += 1

            now = time.time()
            should_print = (completed % 5 == 0) or (now - last_print_time >= 30)
            if should_print:
                _print_progress(domain, tier, latency)
                last_print_time = now

    await asyncio.gather(*[run_one(d) for d in todo])

    # Final line always prints
    _print_progress("—", "—", 0)
    print(f"\nDone. Total cost: ${get_run_cost():.4f}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Site enrichment pipeline")
    parser.add_argument("--input", required=True)
    parser.add_argument("--orgs", default="data/output_orgs.csv")
    parser.add_argument("--locations", default="data/output_locations.csv")
    parser.add_argument("--limit", type=int, default=MAX_ROWS_PER_RUN)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--max-cost", type=float, default=MAX_COST_USD_PER_RUN)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    asyncio.run(run(args.input, args.orgs, args.locations, args.limit, args.concurrency, args.max_cost))


if __name__ == "__main__":
    main()
