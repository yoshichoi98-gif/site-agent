"""Targeted fixes to 5 careaccess.com rows per Yoshi's review. Pull-fresh sheet, locate rows by
(domain, location_name), update specific cells only, recompute zip_check, re-sync local."""
import csv, importlib.util, gspread
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "careaccess.com"
# 1-based columns
C_STREET, C_CITY, C_ZIP, C_VS, C_ZC = 3, 4, 6, 11, 13


def main():
    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET_ID).worksheet("locations")
    sheet = ws.get_all_values()

    cells = []
    for i, row in enumerate(sheet[1:], start=2):
        if row[0].strip().lower() != DOMAIN:
            continue
        name = row[1].strip()
        if name == "Hoboken":
            cells += [gspread.cell.Cell(i, C_STREET, "10 Church Towers"),
                      gspread.cell.Cell(i, C_VS, "passed")]
            print(f"  row {i} Hoboken     -> street '10 Church Towers', passed")
        elif name == "Tampa":
            cells += [gspread.cell.Cell(i, C_STREET, "6328 Gunn Highway, Suite A"),
                      gspread.cell.Cell(i, C_VS, "passed")]
            print(f"  row {i} Tampa       -> street 'Suite A', passed")
        elif name == "Altamonte Springs":
            cells += [gspread.cell.Cell(i, C_VS, "passed")]
            print(f"  row {i} Altamonte   -> passed (kept as-is)")
        elif name == "Charlotte":
            zf = zc.flag(row[5], "Charlotte", "NC")
            cells += [gspread.cell.Cell(i, C_CITY, "Charlotte"),
                      gspread.cell.Cell(i, C_ZC, zf)]
            print(f"  row {i} Charlotte   -> city Pineville->Charlotte, zip_check '{zf}'")
        elif name == "Alexandria":
            zf = zc.flag(row[5], "Arlington", "VA")
            cells += [gspread.cell.Cell(i, C_CITY, "Arlington"),
                      gspread.cell.Cell(i, C_ZC, zf)]
            print(f"  row {i} Alexandria  -> city Alexandria->Arlington, zip_check '{zf}'")

    ws.update_cells(cells, value_input_option="RAW")
    print(f"\nupdated {len(cells)} cells")

    fresh = ws.get_all_values()
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    print(f"re-synced local CSV ({len(fresh)-1} rows)")


if __name__ == "__main__":
    main()
