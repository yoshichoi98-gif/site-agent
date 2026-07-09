"""Verify the rows the user touched during manual review:
  A) newly-PASSED  = 'passed' in the sheet but NOT previously passed locally (status flipped to
     passed, or address edited on a passed row).
  B) still NEEDS_REVIEW in the sheet.
Runs each through Google geocoding (existence only, no name match) and reports.
"""
import csv, importlib.util

vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)

SHEET = "data/locations_sheet_pull.csv"
LOCAL = "data/output_locations.csv"


def key(r):
    return ((r.get("domain") or "").strip().lower(), (r.get("address_street") or "").strip().lower(),
            (r.get("address_city") or "").strip().lower(), (r.get("address_state") or "").strip().upper(),
            (r.get("address_zip") or "").strip())


def addr(r):
    return f"{r['address_street']}, {r['address_city']}, {r['address_state']} {r['address_zip']}".strip()


def main():
    sheet = list(csv.DictReader(open(SHEET)))
    local = list(csv.DictReader(open(LOCAL)))
    local_passed = {key(r) for r in local if (r.get("validation_status") or "").strip() == "passed"}

    newly_passed, needs_review = [], []
    for r in sheet:
        st = (r.get("validation_status") or "").strip()
        if not (r.get("address_street") or "").strip():
            continue
        if st == "passed" and key(r) not in local_passed:
            newly_passed.append(r)
        elif st == "needs_review":
            needs_review.append(r)

    print(f"newly-passed (your manual passes / edits): {len(newly_passed)}")
    print(f"still needs_review: {len(needs_review)}")

    def run(rows, label):
        print(f"\n=== {label} ({len(rows)}) ===")
        exists = suspect = err = 0
        bad = []
        for r in rows:
            v = vg.google_status(addr(r))
            if v == "exists":
                exists += 1
            elif v == "suspect":
                suspect += 1
                bad.append(r)
            else:
                err += 1
        print(f"  verified-exists: {exists} | SUSPECT: {suspect} | error: {err}")
        for r in bad:
            print(f"     SUSPECT: {r['domain']:26} | {r['address_street']} | {r['address_city']} {r['address_state']} {r['address_zip']}")
        return bad

    run(newly_passed, "A) ROWS YOU PASSED — confirm they exist")
    run(needs_review, "B) STILL needs_review — which actually exist")


if __name__ == "__main__":
    main()
