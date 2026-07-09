"""
Retry pass for blocked/timeout/connection-failure domains.

Reads output_orgs.csv, groups failures by bucket, samples N from each,
clears their caches (so we re-fetch fresh), runs the standard pipeline,
and writes results to separate retry output files.

Usage:
  python -m src.retry                       # 20 from each bucket (test)
  python -m src.retry --sample 50           # 50 from each bucket
  python -m src.retry --all                 # every retry candidate
  python -m src.retry --bucket blocked      # one bucket only
  python -m src.retry --skip-dns            # omit dns_failure bucket (default)
  python -m src.retry --include-dns         # include dns_failure (usually pointless)
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
    get_run_cost,
    locations_to_rows,
    process_row,
    reset_run_cost,
)
from src.schema import SiteProfile

# ── column definitions (mirrors main.py) ──────────────────────────────────────

_LOCATION_COLUMNS = [
    "domain", "location_name", "address_street", "address_city",
    "address_state", "address_zip", "phone", "source_url", "snippet",
    "confidence", "validation_status",
]

_NON_EVIDENCE_FIELDS = {"locations", "locations_capped", "locations_capped_reason"}


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


# ── bucket loading ─────────────────────────────────────────────────────────────

def _load_buckets(orgs_path: str) -> dict[str, list[str]]:
    """Read output CSV and group domains by failure type."""
    buckets: dict[str, list[str]] = {
        "blocked": [],
        "timeout": [],
        "connection_failure": [],
        "dns_failure": [],
    }
    with open(orgs_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            domain = row.get("domain", "").strip()
            status = row.get("fetch_status", "").strip()
            error  = row.get("error", "").strip().lower()
            if not domain:
                continue
            if status == "timeout":
                buckets["timeout"].append(domain)
            elif status == "blocked":
                if "dns" in error:
                    buckets["dns_failure"].append(domain)
                elif "connection_failure" in error:
                    buckets["connection_failure"].append(domain)
                else:
                    buckets["blocked"].append(domain)
    return buckets


# ── cache clearing ─────────────────────────────────────────────────────────────

def _clear_domain_cache(domain: str) -> bool:
    """Remove the cached homepage for a domain so we fetch fresh."""
    safe = re.sub(r"[^\w.-]", "_", domain)
    cache_file = os.path.join(CACHE_DIR, f"{safe}.html")
    if os.path.exists(cache_file):
        os.remove(cache_file)
        return True
    return False


# ── main async run ─────────────────────────────────────────────────────────────

async def run(
    domains: list[str],
    orgs_path: str,
    locs_path: str,
    concurrency: int,
    max_cost: float,
):
    logger = logging.getLogger(__name__)
    total = len(domains)
    org_cols = _org_columns()
    _ensure_header(orgs_path, org_cols)
    _ensure_header(locs_path, _LOCATION_COLUMNS)

    semaphore = asyncio.Semaphore(concurrency)
    reset_run_cost()

    completed = 0
    tiers: dict[str, int] = collections.defaultdict(int)
    error_count = 0
    start_time = time.time()
    lock = asyncio.Lock()

    async def run_one(domain: str):
        nonlocal completed, error_count

        if get_run_cost() >= max_cost:
            logger.error(f"Cost cap ${max_cost:.2f} reached — stopping.")
            return

        async with semaphore:
            t0 = time.time()
            org_row, loc_rows = await process_row(domain, max_cost_usd=max_cost)
            latency = time.time() - t0

        with open(orgs_path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=org_cols, extrasaction="ignore").writerow(org_row)

        if loc_rows:
            with open(locs_path, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=_LOCATION_COLUMNS, extrasaction="ignore").writerows(loc_rows)

        tier  = org_row.get("fetch_status", "unknown")
        error = org_row.get("error", "")
        elapsed = time.time() - start_time

        print(
            f"  {domain}  {tier}  proc={latency:.1f}s  elapsed={elapsed:.1f}s"
            + (f"  [{error}]" if error else ""),
            file=sys.stderr,
        )

        async with lock:
            completed += 1
            tiers[tier] += 1
            if error:
                error_count += 1
            if completed % 10 == 0 or completed == total:
                rate = completed / max(elapsed, 0.001)
                eta  = (total - completed) / rate / 60 if rate > 0 else 0
                print(
                    f"{completed:>4}/{total}"
                    f"  rate={rate:.2f}/s  ETA={eta:.1f}min"
                    f"  cost=${get_run_cost():.2f}",
                    file=sys.stderr,
                )

    await asyncio.gather(*[run_one(d) for d in domains])
    elapsed = time.time() - start_time
    print(
        f"\nDone. {completed}/{total} processed in {elapsed/60:.1f}min."
        f"  Cost: ${get_run_cost():.4f}",
        file=sys.stderr,
    )


def main():
    parser = argparse.ArgumentParser(description="Retry pass for blocked/timeout domains")
    parser.add_argument("--orgs-input",  default="data/output_orgs.csv",
                        help="Source CSV to read failures from")
    parser.add_argument("--orgs-output", default="data/retry_orgs.csv",
                        help="Output CSV for retry results")
    parser.add_argument("--locs-output", default="data/retry_locations.csv",
                        help="Output CSV for retry locations")
    parser.add_argument("--sample",      type=int, default=20,
                        help="Domains per bucket (ignored with --all)")
    parser.add_argument("--all",         action="store_true",
                        help="Retry every candidate, not just a sample")
    parser.add_argument("--bucket",      choices=["blocked","timeout","connection_failure","dns_failure"],
                        help="Restrict to one bucket")
    parser.add_argument("--include-dns", action="store_true",
                        help="Include dns_failure bucket (usually unrecoverable)")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--max-cost",    type=float, default=50.0)
    parser.add_argument("--seed",        type=int, default=42,
                        help="Random seed for sample selection")
    parser.add_argument("--verbose",     action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    import random
    random.seed(args.seed)

    buckets = _load_buckets(args.orgs_input)

    # Which buckets to run
    if args.bucket:
        active = {args.bucket: buckets[args.bucket]}
    else:
        active = {k: v for k, v in buckets.items()
                  if k != "dns_failure" or args.include_dns}

    # Print summary
    print("\nRetry candidate summary:", file=sys.stderr)
    for name, doms in active.items():
        n = len(doms) if args.all else min(args.sample, len(doms))
        print(f"  {name:<22} {len(doms):>5} total  →  {n} selected", file=sys.stderr)

    # Build final domain list
    domains: list[str] = []
    for name, doms in active.items():
        if args.all:
            selected = list(doms)
        else:
            selected = random.sample(doms, min(args.sample, len(doms)))
        domains.extend(selected)

    if not domains:
        print("No retry candidates found.", file=sys.stderr)
        return

    # Clear caches so we re-fetch fresh (not hitting old blocked/empty pages)
    cleared = sum(_clear_domain_cache(d) for d in domains)
    print(f"\nCleared {cleared} cached homepage(s). Starting retry on {len(domains)} domains...\n",
          file=sys.stderr)

    asyncio.run(run(domains, args.orgs_output, args.locs_output, args.concurrency, args.max_cost))


if __name__ == "__main__":
    main()
