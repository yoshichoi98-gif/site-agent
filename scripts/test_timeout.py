"""
Quick test: verify the 180s outer timeout fires correctly.

We mock fetch() to hang forever (simulating a wedged Playwright networkidle),
then confirm process_row() returns fetch_status="timeout" in ≤185s.

Run with: .venv/bin/python scripts/test_timeout.py
"""
import asyncio
import time
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Patch fetch to simulate a hang before importing pipeline
import unittest.mock as mock

async def _hanging_fetch(*args, **kwargs):
    """Simulates a domain that never responds — hangs indefinitely."""
    await asyncio.sleep(9999)

# Also patch fetch_url in case planner somehow runs
async def _hanging_fetch_url(*args, **kwargs):
    await asyncio.sleep(9999)

# Domains to test — known slow/wedged from the chunk1 run
DOMAINS = [
    "burnshousing.com",
    "aad.org",
    "21stcenturyneurology.com",
    "310clinicalresearch.com",
    "burncenters.com",
]

async def test_domain(domain: str):
    # Re-import pipeline fresh for each domain so cost state is clean
    from src.pipeline import process_row, reset_run_cost
    reset_run_cost()

    t0 = time.time()
    org_row, loc_rows = await process_row(domain, max_cost_usd=300.0)
    elapsed = time.time() - t0

    status = org_row.get("fetch_status", "??")
    error = org_row.get("error", "")
    ok = status == "timeout" and elapsed <= 185
    mark = "✅" if ok else "❌"
    print(f"{mark} {domain:40s}  status={status:12s}  elapsed={elapsed:.1f}s  error={error}")
    return ok

async def main():
    # Patch fetch and fetch_url to hang
    with mock.patch("src.pipeline.fetch", side_effect=_hanging_fetch), \
         mock.patch("src.pipeline.fetch_url", side_effect=_hanging_fetch_url):

        results = []
        for domain in DOMAINS:
            ok = await test_domain(domain)
            results.append(ok)

    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} passed")
    if passed < total:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
