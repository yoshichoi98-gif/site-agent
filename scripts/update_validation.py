"""Promote the 11 verified-real needs_review rows to 'passed' — targeted cell updates only.
Then sync the validation_status column of the local output_locations.csv from the sheet so they match.
"""
import csv, gspread

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
PULL = "data/locations_sheet_pull.csv"
LOCAL = "data/output_locations.csv"


def key(r):
    return ((r.get("domain") or "").strip().lower(), (r.get("address_street") or "").strip().lower(),
            (r.get("address_city") or "").strip().lower(), (r.get("address_state") or "").strip().upper(),
            (r.get("address_zip") or "").strip())


def main():
    pull = list(csv.DictReader(open(PULL)))
    hdr = list(pull[0].keys())
    vs_col = hdr.index("validation_status") + 1   # 1-based column

    # the 11: needs_review WITH a street
    targets = [(i, r) for i, r in enumerate(pull)
               if (r.get("validation_status") or "").strip() == "needs_review" and (r.get("address_street") or "").strip()]
    print(f"promoting {len(targets)} needs_review->passed")

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET_ID).worksheet("locations")
    cells = []
    for i, r in targets:
        sheet_row = i + 2   # +1 header, +1 for 1-based
        cells.append(gspread.cell.Cell(sheet_row, vs_col, "passed"))
        r["validation_status"] = "passed"   # update the in-memory pull too
        print(f"   row {sheet_row}: {r['domain']} | {r['address_street']}")
    if cells:
        ws.update_cells(cells, value_input_option="RAW")
        print(f"updated {len(cells)} cells in the sheet")

    # rewrite the pull (now reflects the 11 change)
    with open(PULL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=hdr); w.writeheader(); w.writerows(pull)

    # sync local validation_status from the sheet pull (captures user's manual passes + these 11)
    status_by_key = {key(r): (r.get("validation_status") or "").strip() for r in pull}
    local = list(csv.DictReader(open(LOCAL)))
    lhdr = list(local[0].keys())
    synced = 0
    for r in local:
        k = key(r)
        if k in status_by_key and (r.get("validation_status") or "").strip() != status_by_key[k]:
            r["validation_status"] = status_by_key[k]; synced += 1
    with open(LOCAL, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=lhdr); w.writeheader(); w.writerows(local)
    print(f"synced {synced} validation_status values into local {LOCAL}")
    from collections import Counter
    print("local validation_status now:", dict(Counter((r.get('validation_status') or '').strip() for r in local)))


if __name__ == "__main__":
    main()
