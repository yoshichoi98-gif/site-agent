"""Update adcacardiology.com's 6 non-Aurora rows with real addresses from the Manual Locations doc.
Leaves Aurora alone. Pulls live sheet first (source of truth), targeted cell updates only, re-syncs local."""
import csv, importlib.util, gspread
sn = importlib.util.module_from_spec(importlib.util.spec_from_file_location("sn", "scripts/street_norm.py"))
importlib.util.spec_from_file_location("sn", "scripts/street_norm.py").loader.exec_module(sn)
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
# city -> (raw street, zip) from the doc
DOC = {
    "castle rock":      ("755 S Perry St Suite 200", "80104"),
    "centennial":       ("14100 East Arapahoe Road Suite 130", "80112"),
    "englewood":        ("499 E. Hampden Ave Suite 200", "80113"),
    "greenwood village":("8200 E. Belleview Suite 200C", "80111"),
    "lakewood":         ("3333 S. Wadsworth Blvd, Building D D-217", "80227"),
    "lone tree":        ("10103 RidgeGate Parkway Suite 103", "80124"),
}
# 1-based columns
C_STREET, C_ZIP, C_VS, C_SRC = 3, 6, 11, 12


def main():
    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET_ID).worksheet("locations")
    sheet = ws.get_all_values()
    hdr = sheet[0]

    cells = []
    for i, row in enumerate(sheet[1:], start=2):  # sheet row number
        if row[0].strip().lower() != "adcacardiology.com":
            continue
        city = row[3].strip().lower()
        if city == "aurora" or city not in DOC:
            print(f"  row {i}: {row[3]} -> LEFT ALONE ({row[2]})")
            continue
        raw, zc = DOC[city]
        street = sn.canonical_display(raw)
        g = vg.google_status(f"{street}, {row[3]}, CO {zc}")
        vs = "passed" if g == "exists" else "needs_review"
        cells += [gspread.cell.Cell(i, C_STREET, street), gspread.cell.Cell(i, C_ZIP, zc),
                  gspread.cell.Cell(i, C_VS, vs), gspread.cell.Cell(i, C_SRC, "manual")]
        print(f"  row {i}: {row[3]:18} {row[2]!r} ({row[5]}) -> {street!r} ({zc}) [{vs}]")

    if cells:
        ws.update_cells(cells, value_input_option="RAW")
        print(f"\nupdated {len(cells)} cells ({len(cells)//4} rows)")

    # re-sync local from the now-updated sheet
    fresh = ws.get_all_values()
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    print("re-synced local from sheet")


if __name__ == "__main__":
    main()
