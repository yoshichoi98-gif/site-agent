"""
scripts/add_location_audit_columns.py

Adds three location-audit columns to downloads/output_orgs_copy.csv:
  - extracted_location_count  (int)
  - location_count_status     (MATCH | UNDER | OVER | UNPARSEABLE | CAPPED | NOT_APPLICABLE)
  - location_count_gap        (int, only for UNDER/OVER; blank otherwise)

Reads locations from downloads/output_locations_copy.csv.
Writes back to downloads/output_orgs_copy.csv (overwrites).

Safety guarantee: verifies every original field is string-equal before writing.
Raises if anything differs so the file is never silently corrupted.
"""
import csv
import os
import sys
from collections import Counter, defaultdict

ORGS_PATH = os.path.join(os.path.dirname(__file__), "..", "downloads", "output_orgs_copy.csv")
LOCS_PATH = os.path.join(os.path.dirname(__file__), "..", "downloads", "output_locations_copy.csv")

# Subcategories that trigger location enumeration — must match pipeline.py exactly.
RESEARCH_TARGET_SUBCATEGORIES = {
    "dedicated_research_site",
    "dedicated_research_site_network",
    "site_management_organization",
    "specialty_practice_with_research",
    "oncology_practice_with_research",
}

NEW_COLUMNS = ["extracted_location_count", "location_count_status", "location_count_gap"]


def _parse_claimed(raw: str) -> tuple[int | None, bool]:
    """
    Parse location_count__value into (claimed_int, has_plus).
    Returns (None, False) if the value is unparseable.
    Accepts: "5" → (5, False), "20+" → (20, True), " 3 " → (3, False).
    Rejects: "", "  ", "unknown", "not_found", etc.
    """
    s = raw.strip()
    if not s:
        return None, False
    has_plus = s.endswith("+")
    if has_plus:
        s = s[:-1].strip()
    try:
        return int(s), has_plus
    except ValueError:
        return None, False


def _compute_status(row: dict, extracted: int) -> tuple[str, str]:
    """
    Returns (status, gap_str) following the priority order in the spec.
    gap_str is a stringified int for UNDER/OVER, blank otherwise.
    """
    subcategory = (row.get("org_subcategory__value") or "").strip().lower()

    # 1. NOT_APPLICABLE
    if subcategory not in RESEARCH_TARGET_SUBCATEGORIES:
        return "NOT_APPLICABLE", ""

    # 2. CAPPED
    capped_raw = (row.get("locations_capped") or "").strip()
    if capped_raw in ("True", "true", "1", "yes"):
        return "CAPPED", ""

    # 3. UNPARSEABLE
    raw_count = row.get("location_count__value") or ""
    claimed, has_plus = _parse_claimed(raw_count)
    if claimed is None:
        return "UNPARSEABLE", ""

    # 4/5/6/7. Compare extracted vs claimed
    gap = extracted - claimed  # positive = over, negative = under

    # MATCH: exact match, OR has_plus and extracted >= claimed
    if extracted == claimed or (has_plus and extracted >= claimed):
        return "MATCH", ""

    # UNDER: extracted < claimed
    if extracted < claimed:
        return "UNDER", str(claimed - extracted)

    # OVER: extracted > claimed
    return "OVER", str(extracted - claimed)


def main():
    # ── 1. Load location counts per domain ──────────────────────────────────
    loc_counts: dict[str, int] = defaultdict(int)
    with open(LOCS_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            domain = (row.get("domain") or "").strip()
            if domain:
                loc_counts[domain] += 1

    # ── 2. Read orgs CSV (preserve everything) ───────────────────────────────
    with open(ORGS_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        original_fieldnames = reader.fieldnames or []
        input_rows = list(reader)

    if not input_rows:
        print("ERROR: orgs CSV is empty or header-only.", file=sys.stderr)
        sys.exit(1)

    # Guard: new columns must not already exist (would corrupt the integrity check)
    for col in NEW_COLUMNS:
        if col in original_fieldnames:
            print(f"ERROR: column '{col}' already exists — remove it first.", file=sys.stderr)
            sys.exit(1)

    new_fieldnames = original_fieldnames + NEW_COLUMNS

    # ── 3. Build output rows + integrity check ───────────────────────────────
    output_rows = []
    status_counter: Counter = Counter()
    under_rows = []  # for top-10 report

    for input_row in input_rows:
        domain = (input_row.get("domain") or "").strip()
        extracted = loc_counts.get(domain, 0)

        status, gap_str = _compute_status(input_row, extracted)
        status_counter[status] += 1

        if status == "UNDER":
            under_rows.append({
                "domain": domain,
                "subcategory": (input_row.get("org_subcategory__value") or "").strip(),
                "claimed": input_row.get("location_count__value", "").strip(),
                "extracted": extracted,
                "gap": int(gap_str),
            })

        output_row = dict(input_row)  # copy all original fields
        output_row["extracted_location_count"] = extracted
        output_row["location_count_status"] = status
        output_row["location_count_gap"] = gap_str

        # ── Integrity check: every original field must be string-equal ────────
        for field in original_fieldnames:
            original_val = input_row.get(field, "")
            output_val = output_row.get(field, "")
            if original_val != output_val:
                raise RuntimeError(
                    f"Integrity check failed for domain={domain!r}, field={field!r}: "
                    f"input={original_val!r} vs output={output_val!r}"
                )

        output_rows.append(output_row)

    # ── 4. Column-count sanity check ─────────────────────────────────────────
    expected_new_col_count = len(original_fieldnames) + 3
    actual_new_col_count = len(new_fieldnames)
    if actual_new_col_count != expected_new_col_count:
        raise RuntimeError(
            f"Column count mismatch: expected {expected_new_col_count}, got {actual_new_col_count}"
        )
    if len(output_rows) != len(input_rows):
        raise RuntimeError(
            f"Row count mismatch: input {len(input_rows)}, output {len(output_rows)}"
        )

    # ── 5. Write back ─────────────────────────────────────────────────────────
    with open(ORGS_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=new_fieldnames,
            extrasaction="ignore",
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        writer.writerows(output_rows)

    # ── 6. Summary report ────────────────────────────────────────────────────
    print("\n── Location audit summary ──────────────────────────────")
    for status in ["MATCH", "UNDER", "OVER", "UNPARSEABLE", "CAPPED", "NOT_APPLICABLE"]:
        print(f"  {status:<16} {status_counter[status]:>6}")
    print(f"  {'TOTAL':<16} {sum(status_counter.values()):>6}")

    print("\n── Top 10 UNDER rows (biggest gaps) ────────────────────")
    under_rows.sort(key=lambda r: r["gap"], reverse=True)
    if under_rows:
        print(f"  {'domain':<40} {'subcategory':<35} {'claimed':>7} {'extracted':>9} {'gap':>5}")
        print(f"  {'-'*40} {'-'*35} {'-'*7} {'-'*9} {'-'*5}")
        for r in under_rows[:10]:
            print(
                f"  {r['domain']:<40} {r['subcategory']:<35} "
                f"{r['claimed']:>7} {r['extracted']:>9} {r['gap']:>5}"
            )
    else:
        print("  (none)")

    print(f"\nWrote {len(output_rows)} rows → {ORGS_PATH}")


if __name__ == "__main__":
    main()
