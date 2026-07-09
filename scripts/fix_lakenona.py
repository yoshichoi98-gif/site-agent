"""Trim flcancer.com Lake Nona dual-suite street to a single suite so it geocodes clean.
'6400 SANGER RD STE A-2400 & A-2000' -> '6400 SANGER RD STE A-2400'. Re-geocode, update, re-sync."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
NEW_STREET = "6400 SANGER RD STE A-2400"
C_STREET, C_VS = 3, 11


def main():
    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET_ID).worksheet("locations")
    sheet = ws.get_all_values()
    cells = []
    for i, row in enumerate(sheet[1:], start=2):
        if row[0].strip().lower() == "flcancer.com" and row[1].strip() == "Lake Nona":
            g = vg.google_status(f"{NEW_STREET}, {row[3]}, {row[4]} {row[5]}")
            vs = "passed" if g == "exists" else "needs_review"
            cells += [gspread.cell.Cell(i, C_STREET, NEW_STREET), gspread.cell.Cell(i, C_VS, vs)]
            print(f"  row {i} Lake Nona -> '{NEW_STREET}' | geocode={g} -> {vs}")
            break
    ws.update_cells(cells, value_input_option="RAW")
    fresh = ws.get_all_values()
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    print("re-synced local CSV")


if __name__ == "__main__":
    main()
