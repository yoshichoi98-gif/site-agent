"""Drop 'PH503' from Rovia Doral's street ('3650 NW 82nd Ave, PH503' -> '3650 NW 82nd Ave'),
re-geocode, update street + validation_status. Targeted cell update, re-sync local."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "eastcoastresearch.net"
NEW_STREET = "3650 NW 82nd Ave"
C_STREET, C_VS = 3, 11


def main():
    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET_ID).worksheet("locations")
    sheet = ws.get_all_values()
    cells = []
    for i, row in enumerate(sheet[1:], start=2):
        if row[0].strip().lower() == DOMAIN and row[1].strip().startswith("Rovia Doral"):
            g = vg.google_status(f"{NEW_STREET}, {row[3]}, {row[4]} {row[5]}")
            vs = "passed" if g == "exists" else "needs_review"
            cells += [gspread.cell.Cell(i, C_STREET, NEW_STREET), gspread.cell.Cell(i, C_VS, vs)]
            print(f"  row {i} {row[1]} -> '{NEW_STREET}' | geocode={g} -> {vs}")
            break
    ws.update_cells(cells, value_input_option="RAW")
    fresh = ws.get_all_values()
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    print("re-synced local CSV")


if __name__ == "__main__":
    main()
