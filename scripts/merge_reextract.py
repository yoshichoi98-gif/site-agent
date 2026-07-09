"""
scripts/merge_reextract.py

Merges reextract pipeline output into the main output CSVs.

For output_orgs.csv:
  - Rows whose domain appears in reextract_orgs.csv are replaced in-place
    (original row order preserved; reextract row replaces the old one).
  - Rows not in reextract are kept unchanged.

For output_locations.csv:
  - All rows for domains in the reextract set are dropped.
  - Rows from reextract_locations.csv are appended at the end.

Backups must already exist before running this script.
"""
import csv
import os
import sys

DATA = os.path.join(os.path.dirname(__file__), "..", "data")

ORGS_PATH       = os.path.join(DATA, "output_orgs.csv")
LOCS_PATH       = os.path.join(DATA, "output_locations.csv")
REEXTRACT_ORGS  = os.path.join(DATA, "reextract_orgs.csv")
REEXTRACT_LOCS  = os.path.join(DATA, "reextract_locations.csv")


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames[:]
        rows = list(reader)
    return fieldnames, rows


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames,
                                extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(rows)


def main():
    # ── Load all four files ──────────────────────────────────────────────────
    orgs_fields,  orgs_rows  = load_csv(ORGS_PATH)
    locs_fields,  locs_rows  = load_csv(LOCS_PATH)
    re_orgs_fields, re_orgs_rows = load_csv(REEXTRACT_ORGS)
    re_locs_fields, re_locs_rows = load_csv(REEXTRACT_LOCS)

    # ── Sanity: columns must match ───────────────────────────────────────────
    if orgs_fields != re_orgs_fields:
        only_new = set(re_orgs_fields) - set(orgs_fields)
        only_old = set(orgs_fields) - set(re_orgs_fields)
        sys.exit(f"ERROR: orgs column mismatch.\n  Only in reextract: {only_new}\n  Only in output: {only_old}")

    if locs_fields != re_locs_fields:
        sys.exit(f"ERROR: locations column mismatch.\n  Only in reextract: {set(re_locs_fields)-set(locs_fields)}\n  Only in output: {set(locs_fields)-set(re_locs_fields)}")

    # ── Build reextract lookup: domain → row ─────────────────────────────────
    reextract_orgs_map = {r["domain"]: r for r in re_orgs_rows}
    reextract_domains  = set(reextract_orgs_map.keys())

    print(f"Reextract domains: {len(reextract_domains)}")
    print(f"Output orgs before: {len(orgs_rows)} rows")
    print(f"Output locs before: {len(locs_rows)} rows")

    # ── Merge orgs: replace in-place ─────────────────────────────────────────
    replaced = 0
    not_found_in_output = []
    merged_orgs = []

    for row in orgs_rows:
        domain = row["domain"]
        if domain in reextract_orgs_map:
            merged_orgs.append(reextract_orgs_map[domain])
            replaced += 1
        else:
            merged_orgs.append(row)

    # Domains in reextract but not in original output (new domains) → append
    existing_domains = {r["domain"] for r in orgs_rows}
    new_domains = [d for d in reextract_orgs_map if d not in existing_domains]
    for d in new_domains:
        merged_orgs.append(reextract_orgs_map[d])
        not_found_in_output.append(d)

    # ── Merge locations: drop old, append new ────────────────────────────────
    kept_locs   = [r for r in locs_rows  if r["domain"] not in reextract_domains]
    dropped_locs = len(locs_rows) - len(kept_locs)
    merged_locs = kept_locs + re_locs_rows

    # ── Write ────────────────────────────────────────────────────────────────
    write_csv(ORGS_PATH, orgs_fields, merged_orgs)
    write_csv(LOCS_PATH, locs_fields, merged_locs)

    # ── Summary ──────────────────────────────────────────────────────────────
    print(f"\n── Orgs ────────────────────────────────────────────")
    print(f"  Replaced (in-place):  {replaced}")
    print(f"  Appended (new):       {len(not_found_in_output)}")
    print(f"  Unchanged:            {len(orgs_rows) - replaced}")
    print(f"  Output rows after:    {len(merged_orgs)}")

    print(f"\n── Locations ───────────────────────────────────────")
    print(f"  Dropped (old):        {dropped_locs}")
    print(f"  Appended (reextract): {len(re_locs_rows)}")
    print(f"  Kept (unchanged):     {len(kept_locs)}")
    print(f"  Output rows after:    {len(merged_locs)}")

    if not_found_in_output:
        print(f"\n  Note: {len(not_found_in_output)} reextract domains were not in original output (appended as new):")
        for d in not_found_in_output[:10]:
            print(f"    {d}")
        if len(not_found_in_output) > 10:
            print(f"    ... and {len(not_found_in_output) - 10} more")

    print(f"\nDone. Backups: output_orgs_pre_merge_backup.csv / output_locations_pre_merge_backup.csv")


if __name__ == "__main__":
    main()
