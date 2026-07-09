"""
Re-categorize every org with the two-dimension scheme (business_type + research_involvement +
specialties), reading CACHED HTML only — no re-crawling. See prompts/classify.txt and src/classify.py.

Reads data/output_orgs.csv for the domain list (+ research_url hint), loads the cached homepage
(and the cached research-page when available), runs the focused classifier, and appends one row
per domain to data/classify_orgs.csv. Append-only + idempotent: re-runs skip domains already in
the output, so a capped/interrupted run resumes cleanly.

Usage:
  python -m scripts.classify_business --limit 60 --verbose          # sample run
  python -m scripts.classify_business --domains-file data/sample.txt # specific domains
  python -m scripts.classify_business                               # full run (cost-capped)
  python -m scripts.classify_business --max-cost 5                  # tighter cap
"""
import argparse
import asyncio
import csv
import logging
import os
import sys
import time

from src.classify import classify
from src.config import CACHE_DIR, MAX_COST_USD_PER_RUN
from src.fetch import _cache_key_for_domain, _cache_key_for_url
from src.pipeline import add_cost, get_run_cost, reset_run_cost

logger = logging.getLogger(__name__)

OUT_COLUMNS = [
    "domain", "business_type", "business_type_confidence", "business_type_snippet",
    "specialties", "research_involvement", "research_involvement_confidence",
    "research_involvement_snippet", "error",
]


def _read_cache(path: str) -> str | None:
    if path and os.path.exists(path):
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    return None


def _load_domains(orgs_path: str) -> list[tuple[str, str]]:
    """Return [(domain, research_url)] deduped (last row wins)."""
    seen: dict[str, str] = {}
    with open(orgs_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = (row.get("domain") or "").strip()
            if d:
                seen[d] = (row.get("research_url__value") or "").strip()
    return list(seen.items())


def _already_done(out_path: str) -> set[str]:
    if not os.path.exists(out_path):
        return set()
    with open(out_path, newline="", encoding="utf-8") as f:
        return {r["domain"] for r in csv.DictReader(f) if r.get("domain")}


def _classify_one(domain: str, research_url: str) -> dict:
    homepage = _read_cache(_cache_key_for_domain(domain))
    if not homepage:
        return {"domain": domain, "error": "no_cache"}

    additional: dict[str, str] = {}
    if research_url:
        rp = _read_cache(_cache_key_for_url(research_url))
        if rp:
            additional[research_url] = rp

    try:
        result, usage = classify(domain, homepage, additional)
    except Exception as e:
        logger.error(f"[{domain}] classifier failed: {e}")
        return {"domain": domain, "error": f"classify_error: {type(e).__name__}"}

    add_cost(usage.input_tokens, usage.output_tokens)
    return {
        "domain": domain,
        "business_type": result.business_type,
        "business_type_confidence": result.business_type_confidence,
        "business_type_snippet": result.business_type_snippet,
        "specialties": "; ".join(result.specialties),
        "research_involvement": result.research_involvement,
        "research_involvement_confidence": result.research_involvement_confidence,
        "research_involvement_snippet": result.research_involvement_snippet,
        "error": "",
    }


async def run(targets: list[tuple[str, str]], out_path: str, concurrency: int, max_cost: float):
    if not os.path.exists(out_path):
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=OUT_COLUMNS).writeheader()

    total = len(targets)
    sem = asyncio.Semaphore(concurrency)
    reset_run_cost()
    completed = no_cache = errors = 0
    start = time.time()
    lock = asyncio.Lock()
    loop = asyncio.get_event_loop()

    async def run_one(domain: str, research_url: str):
        nonlocal completed, no_cache, errors
        if get_run_cost() >= max_cost:
            return
        async with sem:
            row = await loop.run_in_executor(None, lambda: _classify_one(domain, research_url))
        with open(out_path, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=OUT_COLUMNS, extrasaction="ignore").writerow(row)
        async with lock:
            completed += 1
            if row.get("error") == "no_cache":
                no_cache += 1
            elif row.get("error"):
                errors += 1
            if completed % 25 == 0 or completed == total:
                rate = completed / max(time.time() - start, 0.001)
                eta = (total - completed) / rate / 60 if rate else 0
                print(f"{completed}/{total} rate={rate:.1f}/s ETA={eta:.1f}min "
                      f"no_cache={no_cache} errors={errors} cost=${get_run_cost():.2f}",
                      file=sys.stderr)

    await asyncio.gather(*[run_one(d, r) for d, r in targets])
    print(f"\nDone. {completed}/{total} | no_cache={no_cache} errors={errors} "
          f"cost=${get_run_cost():.4f}", file=sys.stderr)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--orgs-input", default="data/output_orgs.csv")
    p.add_argument("--output", default="data/classify_orgs.csv")
    p.add_argument("--domains-file", default=None, help="newline-delimited domains to classify (overrides full list)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--max-cost", type=float, default=200.0)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr,
    )

    research_by_domain = dict(_load_domains(args.orgs_input))
    if args.domains_file:
        with open(args.domains_file) as f:
            wanted = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        targets = [(d, research_by_domain.get(d, "")) for d in wanted]
    else:
        targets = list(research_by_domain.items())

    done = _already_done(args.output)
    targets = [(d, r) for d, r in targets if d not in done]
    if args.limit:
        targets = targets[:args.limit]

    print(f"To classify: {len(targets)} (skipping {len(done)} already done)", file=sys.stderr)
    if not targets:
        return
    asyncio.run(run(targets, args.output, args.concurrency, args.max_cost))


if __name__ == "__main__":
    main()
