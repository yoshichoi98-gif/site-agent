"""
Smoke test runner. Runs the pipeline on data/smoke_test_domains.csv.
Usage: python scripts/smoke_test.py [--limit N] [--concurrency N] [--max-cost X] [--verbose]

Idempotent: skips already-processed domains in data/smoke_output.csv.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import asyncio
import csv
import logging
import time

from src.pipeline import get_run_cost, process_row, reset_run_cost
from src.schema import SiteProfile

INPUT_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "smoke_test_domains.csv")
OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "smoke_output.csv")
MAX_COST = 5.0   # smoke test cap
MAX_DOMAINS = 20


def _csv_columns() -> list[str]:
    base = ["domain", "category", "latency_s", "fetch_status", "error"]
    for field_name in SiteProfile.model_fields:
        base += [
            f"{field_name}__value",
            f"{field_name}__confidence",
            f"{field_name}__source_url",
            f"{field_name}__snippet",
        ]
    return base


def _load_input() -> list[dict]:
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_processed() -> set[str]:
    if not os.path.exists(OUTPUT_CSV):
        return set()
    with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
        return {row["domain"] for row in csv.DictReader(f) if row.get("domain")}


async def run(limit: int, concurrency: int, max_cost: float):
    logger = logging.getLogger(__name__)
    rows = _load_input()[:limit]
    processed = _load_processed()
    todo = [r for r in rows if r["domain"] not in processed]

    if not todo:
        logger.info("All domains already processed.")
        return

    logger.info(f"Running {len(todo)} domains (concurrency={concurrency}, cost cap=${max_cost})")

    columns = _csv_columns()
    write_header = not os.path.exists(OUTPUT_CSV)
    if write_header:
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=columns).writeheader()

    semaphore = asyncio.Semaphore(concurrency)
    reset_run_cost()
    results_summary = []

    async def run_one(input_row: dict):
        domain = input_row["domain"]
        if get_run_cost() >= max_cost:
            logger.error(f"Cost cap ${max_cost} reached — skipping {domain}")
            return

        async with semaphore:
            t0 = time.time()
            row = await process_row(domain, max_cost_usd=max_cost)
            row["category"] = input_row.get("category", "")

        with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
            writer.writerow(row)

        fields_found = sum(
            1 for fn in SiteProfile.model_fields
            if row.get(f"{fn}__confidence", "not_found") not in ("not_found", "")
            and fn != "trials_status"  # ct.gov field counted separately
        )
        results_summary.append({
            "domain": domain,
            "fetch_status": row.get("fetch_status", "?"),
            "fields_found": fields_found,
            "latency_s": row.get("latency_s", 0),
            "error": row.get("error", ""),
        })
        logger.info(
            f"[{domain}] done — fetch={row.get('fetch_status')} "
            f"fields={fields_found}/7 latency={row.get('latency_s')}s "
            f"cost=${get_run_cost():.3f}"
        )

    await asyncio.gather(*[run_one(r) for r in todo])

    # Print summary table to stderr
    logger.info("\n=== SMOKE TEST SUMMARY ===")
    logger.info(f"{'domain':<35} {'fetch':<12} {'fields':>6} {'latency':>8} {'error'}")
    logger.info("-" * 80)
    for r in results_summary:
        logger.info(
            f"{r['domain']:<35} {r['fetch_status']:<12} {r['fields_found']:>5}/7 "
            f"{float(r['latency_s'] or 0):>7.1f}s  {r['error'][:40]}"
        )
    logger.info(f"\nEstimated total cost: ${get_run_cost():.3f}")
    logger.info(f"Output: {OUTPUT_CSV}")


def main():
    parser = argparse.ArgumentParser(description="Smoke test runner")
    parser.add_argument("--limit", type=int, default=MAX_DOMAINS)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--max-cost", type=float, default=MAX_COST)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    asyncio.run(run(args.limit, args.concurrency, args.max_cost))


if __name__ == "__main__":
    main()
