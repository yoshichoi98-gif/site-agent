"""Merge the Firecrawl location re-extractions into the canonical output_locations.csv.

Two stages:
  1. RE-DEDUPE the Firecrawl rows per-domain with a tightened key — (state, city, street-number,
     street-name-word) — anchored on city+state instead of zip. Zip is too often missing/inconsistent
     across a site's pages, which left the same physical office as 2-3 rows (e.g. ascendvision.com's
     "1611 State Road 60" appeared with zip '', '33859', '33853'). City+state+number+street-name is
     stable and still keeps genuinely distinct addresses (473 vs 477 Lakehurst) apart. When collapsing
     a group we keep the most-complete row (prefer one that has a zip).
  2. PER-DOMAIN REPLACE into the canonical file: for every domain Firecrawl covered, drop its old
     canonical rows and substitute the (deduped) Firecrawl rows. Domains Firecrawl didn't touch are
     left exactly as-is (keep-old-rows policy for the still-empty flagged domains).

Writes to output_locations_merged.csv and prints verification stats. Does NOT overwrite the canonical
file (a timestamped backup already exists; swap in only after review).

Run:  .venv/bin/python scripts/merge_locations.py
"""
import csv
import importlib.util
import re

CANON = "data/output_locations.csv"
FIRECRAWL = "data/output_locations_firecrawl.csv"
OUT = "data/output_locations_merged.csv"

# reuse the validated street signature (number + abbrev-normalized first word) from the extractor
_spec = importlib.util.spec_from_file_location("fl", "scripts/firecrawl_locations.py")
_fl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fl)
_street_signature = _fl._street_signature


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def dedupe_key(r: dict) -> tuple:
    """(state, city, street-number, street-name-word) — city/state anchored, zip-agnostic."""
    num, word = _street_signature(str(r.get("address_street", "") or ""))
    return (_norm(r.get("address_state")), _norm(r.get("address_city")), num, word)


def _completeness(r: dict) -> int:
    """Prefer the most-filled row when collapsing a dup group (so we keep the one with a zip)."""
    return sum(1 for k in ("address_zip", "address_street", "phone", "address_city") if str(r.get(k, "")).strip())


def redupe_firecrawl(rows: list[dict]) -> tuple[list[dict], int]:
    """Collapse cross-page dups within each domain. Returns (rows, num_collapsed)."""
    by_key: dict[tuple, dict] = {}
    order: list[tuple] = []
    for r in rows:
        k = (r["domain"].strip().lower(),) + dedupe_key(r)
        if k not in by_key:
            by_key[k] = r
            order.append(k)
        elif _completeness(r) > _completeness(by_key[k]):
            by_key[k] = r  # keep the more complete row
    deduped = [by_key[k] for k in order]
    return deduped, len(rows) - len(deduped)


def main():
    canon = list(csv.DictReader(open(CANON)))
    fields = canon[0].keys() if canon else None
    fc = list(csv.DictReader(open(FIRECRAWL)))
    if fields is None:
        fields = fc[0].keys()

    fc_deduped, collapsed = redupe_firecrawl(fc)
    fc_domains = {r["domain"].strip().lower() for r in fc_deduped if r.get("domain")}

    kept_canon = [r for r in canon if (r.get("domain") or "").strip().lower() not in fc_domains]
    replaced_domains = {(r.get("domain") or "").strip().lower() for r in canon} & fc_domains
    new_domains = fc_domains - {(r.get("domain") or "").strip().lower() for r in canon}

    merged = kept_canon + fc_deduped
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(fields), extrasaction="ignore")
        w.writeheader()
        w.writerows(merged)

    # ── verification ─────────────────────────────────────────────────────────
    print("=== Firecrawl re-dedupe ===")
    print(f"  firecrawl rows: {len(fc)} -> {len(fc_deduped)}  (collapsed {collapsed} cross-page dups)")
    print(f"  firecrawl domains: {len(fc_domains)}")
    print("=== Per-domain replace into canonical ===")
    print(f"  canonical rows: {len(canon)} | domains: {len({(r.get('domain') or '').strip().lower() for r in canon})}")
    print(f"  domains replaced (old rows dropped): {len(replaced_domains)}")
    print(f"  brand-new domains added: {len(new_domains)}")
    print(f"  canonical rows kept (untouched domains): {len(kept_canon)}")
    print("=== Merged result ===")
    print(f"  total rows: {len(merged)}")
    print(f"  total domains: {len({(r.get('domain') or '').strip().lower() for r in merged})}")
    print(f"  wrote {OUT}")
    # spot-check: any domain still holding BOTH old + firecrawl source? (should be none)
    src_by_dom = {}
    for r in merged:
        d = (r.get("domain") or "").strip().lower()
        src_by_dom.setdefault(d, set()).add((r.get("source") or "").strip())
    mixed = [d for d in fc_domains if len(src_by_dom.get(d, set()) - {"firecrawl"}) > 0]
    print(f"  sanity: replaced domains still carrying non-firecrawl rows: {len(mixed)} (expect 0)")


if __name__ == "__main__":
    main()
