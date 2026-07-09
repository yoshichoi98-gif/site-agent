"""
# v1
Eval harness: runs the pipeline against data/golden.csv, scores each field,
writes data/eval_results.csv and EVAL_REPORT.md.

Usage:
    python -m evals.eval [--concurrency 5] [--max-domains 30] [--max-cost 5.0] [--verbose]

Constraints:
- Max 30 domains, max $5, concurrency=5, Sonnet 4.6
- Idempotent: skips domains already fully scored in data/eval_results.csv
- Per-domain errors do not stop the run
- Does NOT iterate prompts — shows report and stops
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

from src.pipeline import get_run_cost, process_row, reset_run_cost

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

GOLDEN_CSV = "data/golden.csv"
RESULTS_CSV = "data/eval_results.csv"
REPORT_MD = "EVAL_REPORT.md"

# Fields we score. Order matters for report layout.
SCORED_FIELDS = [
    "canonical_org_name",
    "hq_phone",
    "hq_address",
    "location_count",
    "research_url",
    "org_subcategory",
]

RESULTS_COLUMNS = [
    "domain",
    "field",
    "expected",
    "actual",
    "match",        # "exact" | "soft" | "null_match" | "miss" | "skip"
    "confidence",
    "snippet",
    "note",
]

MAX_DOMAINS = 30
MAX_COST_USD = 5.0
CONCURRENCY = 5

# --------------------------------------------------------------------------- #
# Comparison helpers
# --------------------------------------------------------------------------- #

def _norm_str(s: str) -> str:
    return (s or "").strip().lower()


def _digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _norm_phone(raw: str) -> str:
    """Strip to digits, strip leading country code '1' if 11 digits, return last 10."""
    d = _digits_only(raw)
    if len(d) == 11 and d.startswith("1"):
        d = d[1:]
    return d[-10:] if len(d) >= 10 else d


def _norm_url(raw: str) -> str:
    """Strip protocol, strip www., strip trailing slash, lowercase."""
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    parsed = urlparse(s)
    host = parsed.netloc
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    return host + path


def _url_domain(raw: str) -> str:
    """Return just the host (no www.) from a URL."""
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    parsed = urlparse(s)
    host = parsed.netloc
    if host.startswith("www."):
        host = host[4:]
    return host


def _numeric_tokens(s: str) -> list[str]:
    """Extract tokens that are digits or digits+plus (e.g. '90+', '100', '3')."""
    return re.findall(r"\d+\+?", s or "")


def compare_canonical_org_name(expected: str, actual: str) -> tuple[str, str]:
    """Case-insensitive substring match either direction."""
    e, a = _norm_str(expected), _norm_str(actual)
    if not e:
        return ("skip", "no expected value")
    if not a:
        return ("miss", "actual is empty")
    if e in a or a in e:
        return ("exact", "")
    return ("miss", f"'{e}' not in '{a}' and vice versa")


def compare_phone(expected: str, actual: str, null_counts_as_match: bool = False) -> tuple[str, str]:
    """Digits-only, strip leading 1 if 11 digits, compare last 10."""
    if not (expected or "").strip():
        if not (actual or "").strip() and null_counts_as_match:
            return ("null_match", "both empty")
        return ("skip", "no expected value")
    if not (actual or "").strip():
        return ("miss", "actual is empty")
    e_norm = _norm_phone(expected)
    a_norm = _norm_phone(actual)
    if e_norm and a_norm and e_norm == a_norm:
        return ("exact", "")
    return ("miss", f"expected digits '{e_norm}', got '{a_norm}'")


def compare_hq_address(expected: str, actual: str) -> tuple[str, str]:
    """
    Lenient: match if street number OR city OR state present in actual.
    We extract: leading digits (street number), words of length>=4 (city proxy),
    and 2-letter state codes.
    """
    if not (expected or "").strip():
        return ("skip", "no expected value")
    if not (actual or "").strip():
        return ("miss", "actual is empty")
    e = _norm_str(expected)
    a = _norm_str(actual)
    # Street number: leading digits in expected
    street_num_match = re.search(r"^\d+", e)
    if street_num_match and street_num_match.group() in a:
        return ("exact", f"street number '{street_num_match.group()}' matched")
    # City: first word of 4+ chars (crude but effective for US cities)
    city_match = re.search(r"\b([a-z]{4,})\b", e)
    if city_match and city_match.group(1) in a:
        return ("exact", f"city token '{city_match.group(1)}' matched")
    # State: 2-letter token
    state_match = re.search(r"\b([a-z]{2})\b", e)
    if state_match and state_match.group(1) in a:
        return ("soft", f"state token '{state_match.group(1)}' matched")
    return ("miss", f"no street/city/state from expected found in actual")


def compare_location_count(expected: str, actual: str) -> tuple[str, str]:
    """Extract numeric+plus tokens and do substring match."""
    if not (expected or "").strip():
        return ("skip", "no expected value")
    if not (actual or "").strip():
        return ("miss", "actual is empty")
    e_tokens = _numeric_tokens(expected)
    a_tokens = _numeric_tokens(actual)
    if not e_tokens:
        return ("skip", "expected has no numeric token")
    # Check if any expected token appears in actual tokens
    for tok in e_tokens:
        if tok in a_tokens:
            return ("exact", f"token '{tok}' matched")
    # Soft: compare base numbers (strip '+')
    e_nums = {re.sub(r"\+", "", t) for t in e_tokens}
    a_nums = {re.sub(r"\+", "", t) for t in a_tokens}
    if e_nums & a_nums:
        return ("soft", f"base number match without plus")
    return ("miss", f"expected tokens {e_tokens}, got {a_tokens}")


def compare_org_subcategory(expected: str, actual: str) -> tuple[str, str]:
    """Exact match after lowercase."""
    if not (expected or "").strip():
        return ("skip", "no expected value")
    if not (actual or "").strip():
        return ("miss", "actual is empty")
    if _norm_str(expected) == _norm_str(actual):
        return ("exact", "")
    return ("miss", f"expected '{_norm_str(expected)}', got '{_norm_str(actual)}'")


def compare_research_url(expected: str, actual: str) -> tuple[str, str]:
    """
    Normalize both (strip protocol, www., trailing slash, lowercase).
    Exact match preferred; same-domain-different-path = soft match.
    """
    if not (expected or "").strip():
        return ("skip", "no expected value")
    if not (actual or "").strip():
        return ("miss", "actual is empty")
    e_norm = _norm_url(expected)
    a_norm = _norm_url(actual)
    if e_norm == a_norm:
        return ("exact", "")
    if _url_domain(expected) == _url_domain(actual):
        return ("soft", f"same domain, different path: '{e_norm}' vs '{a_norm}'")
    return ("miss", f"'{e_norm}' vs '{a_norm}'")


# Map field name → comparator function
COMPARATORS = {
    "canonical_org_name": compare_canonical_org_name,
    "hq_phone": compare_phone,
    "hq_address": compare_hq_address,
    "location_count": compare_location_count,
    "research_url": compare_research_url,
    "org_subcategory": compare_org_subcategory,
}


# --------------------------------------------------------------------------- #
# Golden CSV loader
# --------------------------------------------------------------------------- #

def load_golden(path: str) -> list[dict]:
    """Load golden.csv, return list of row dicts."""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --------------------------------------------------------------------------- #
# Idempotency: load already-scored domains
# --------------------------------------------------------------------------- #

def load_scored_domains(results_path: str) -> set[str]:
    """
    A domain is 'fully scored' if it appears in results CSV with all SCORED_FIELDS present.
    Returns set of fully-scored domains to skip.
    """
    if not os.path.exists(results_path):
        return set()
    domain_fields: dict[str, set] = defaultdict(set)
    with open(results_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = row.get("domain", "").strip()
            field = row.get("field", "").strip()
            if d and field:
                domain_fields[d].add(field)
    required = set(SCORED_FIELDS)
    return {d for d, fields in domain_fields.items() if required.issubset(fields)}


def _ensure_results_header(path: str):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=RESULTS_COLUMNS).writeheader()


# --------------------------------------------------------------------------- #
# Scoring a single domain
# --------------------------------------------------------------------------- #

async def score_domain(golden_row: dict, semaphore: asyncio.Semaphore,
                        max_cost: float) -> list[dict] | None:
    """
    Run the pipeline on one domain, compare each field to golden values.
    Returns list of result dicts (one per field), or None on crash.
    """
    domain = golden_row["domain"].strip()
    async with semaphore:
        try:
            org_row, _loc_rows = await process_row(domain, max_cost_usd=max_cost)
        except Exception as e:
            logger.error(f"[{domain}] process_row crashed: {e}")
            return None

    results = []
    for field in SCORED_FIELDS:
        expected = golden_row.get(f"expected_{field}", "").strip()
        actual = org_row.get(f"{field}__value", "").strip()
        confidence = org_row.get(f"{field}__confidence", "")
        snippet = org_row.get(f"{field}__snippet", "")

        comparator = COMPARATORS[field]
        match, note = comparator(expected, actual)

        results.append({
            "domain": domain,
            "field": field,
            "expected": expected,
            "actual": actual,
            "match": match,
            "confidence": confidence,
            "snippet": snippet[:120] if snippet else "",
            "note": note,
        })

    return results


# --------------------------------------------------------------------------- #
# Report generation
# --------------------------------------------------------------------------- #

def build_report(results_path: str, crashed: list[str]) -> str:
    """Read results CSV, compute per-field accuracy + disagreements, return markdown."""
    rows = []
    with open(results_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Per-field stats
    field_stats: dict[str, dict] = {}
    for field in SCORED_FIELDS:
        field_rows = [r for r in rows if r["field"] == field]
        scoreable = [r for r in field_rows if r["match"] != "skip"]
        hits = [r for r in scoreable if r["match"] in ("exact", "soft", "null_match")]
        field_stats[field] = {
            "total": len(scoreable),
            "hits": len(hits),
            "misses": [r for r in scoreable if r["match"] == "miss"],
        }

    lines = ["# Eval Report\n"]
    lines.append(f"Generated from `{results_path}`. "
                 f"Domains scored: {len({r['domain'] for r in rows})}. "
                 f"Crashes: {len(crashed)}.\n")

    # Per-field accuracy table
    lines.append("## Per-Field Accuracy\n")
    lines.append("| Field | Scored | Hits | Accuracy |")
    lines.append("|---|---|---|---|")
    for field, st in field_stats.items():
        pct = f"{100 * st['hits'] / st['total']:.0f}%" if st["total"] else "n/a"
        lines.append(f"| {field} | {st['total']} | {st['hits']} | {pct} |")

    # Top 5 disagreements per field
    lines.append("\n## Top 5 Disagreements Per Field\n")
    for field, st in field_stats.items():
        misses = st["misses"][:5]
        if not misses:
            lines.append(f"### {field}\nNo misses. ✅\n")
            continue
        lines.append(f"### {field}\n")
        lines.append("| Domain | Expected | Actual | Note |")
        lines.append("|---|---|---|---|")
        for r in misses:
            e = (r["expected"] or "")[:60].replace("|", "/")
            a = (r["actual"] or "")[:60].replace("|", "/")
            n = (r["note"] or "")[:80].replace("|", "/")
            lines.append(f"| {r['domain']} | {e} | {a} | {n} |")
        lines.append("")

    # Per-domain summary
    lines.append("## Per-Domain Summary\n")
    lines.append("| Domain | Fields Hit | Fields Missed | Fields Skipped |")
    lines.append("|---|---|---|---|")
    domains = sorted({r["domain"] for r in rows})
    for domain in domains:
        dr = [r for r in rows if r["domain"] == domain]
        hits = sum(1 for r in dr if r["match"] in ("exact", "soft", "null_match"))
        misses = sum(1 for r in dr if r["match"] == "miss")
        skips = sum(1 for r in dr if r["match"] == "skip")
        lines.append(f"| {domain} | {hits} | {misses} | {skips} |")

    # Crashed domains
    if crashed:
        lines.append("\n## Crashed Domains\n")
        for d in crashed:
            lines.append(f"- {d}")
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

async def run(max_domains: int, max_cost: float, concurrency: int):
    logger.info(f"Loading golden CSV from {GOLDEN_CSV}")
    golden_rows = load_golden(GOLDEN_CSV)

    # Only rows with a domain
    golden_rows = [r for r in golden_rows if r.get("domain", "").strip()]
    logger.info(f"Golden rows with domain: {len(golden_rows)}")

    already_scored = load_scored_domains(RESULTS_CSV)
    logger.info(f"Already scored (idempotent skip): {len(already_scored)}")

    todo = [r for r in golden_rows if r["domain"].strip() not in already_scored]
    todo = todo[:max_domains]
    logger.info(f"To run: {len(todo)}")

    crashed: list[str] = []

    if not todo:
        logger.info("Nothing to do — all domains already scored.")
    else:
        _ensure_results_header(RESULTS_CSV)
        reset_run_cost()
        semaphore = asyncio.Semaphore(concurrency)

        tasks = [score_domain(row, semaphore, max_cost) for row in todo]
        results_batches = await asyncio.gather(*tasks, return_exceptions=False)

        with open(RESULTS_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=RESULTS_COLUMNS, extrasaction="ignore")
            for i, batch in enumerate(results_batches):
                domain = todo[i]["domain"].strip()
                if batch is None:
                    crashed.append(domain)
                    logger.warning(f"[{domain}] crashed — no rows written")
                else:
                    writer.writerows(batch)

        logger.info(f"Estimated cost: ${get_run_cost():.3f}")
        logger.info(f"Crashes: {crashed}")

    # Build report from full results CSV (including previously scored rows)
    if not os.path.exists(RESULTS_CSV):
        logger.warning("No results to report.")
        return

    # crashed = only domains that returned None from score_domain this run
    # (domains not yet run are simply absent from the report, not listed as crashed)
    report_md = build_report(RESULTS_CSV, crashed)
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write(report_md)
    logger.info(f"Report written to {REPORT_MD}")
    print(f"\n{'='*60}")
    print(report_md)
    print(f"{'='*60}\n")
    print(f"Full results: {RESULTS_CSV}")
    print(f"Report: {REPORT_MD}")


def main():
    parser = argparse.ArgumentParser(description="Eval harness for site-agent pipeline")
    parser.add_argument("--max-domains", type=int, default=MAX_DOMAINS)
    parser.add_argument("--max-cost", type=float, default=MAX_COST_USD)
    parser.add_argument("--concurrency", type=int, default=CONCURRENCY)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    asyncio.run(run(args.max_domains, args.max_cost, args.concurrency))


if __name__ == "__main__":
    main()
