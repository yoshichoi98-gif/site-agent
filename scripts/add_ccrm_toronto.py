"""Append the Hannam Fertility - Toronto (Canada) row to ccrmivf.com so the domain has all 41.
Province normalized Ontario->ON (matching the 2-letter state column); zip kept verbatim (M4W 3R2).
US-only zip_check is N/A -> blank. Geocode-verify. Append + re-sync."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "ccrmivf.com"
SRC_URL = "https://www.ccrmivf.com/locations"

NAME = "Hannam Fertility - Toronto"
STREET = "160 Bloor St. East, 15th Floor"
CITY, STATE, ZIPC, PHONE = "Toronto", "ON", "M4W 3R2", "(416) 595-1521"


def main():
    g = vg.google_status(f"{STREET}, {CITY}, {STATE} {ZIPC}")
    vs = "passed" if g == "exists" else "needs_review"
    row = [DOMAIN, NAME, STREET, CITY, STATE, ZIPC, PHONE, SRC_URL, "", "high", vs, "manual", ""]
    print(f"  {NAME} | {STREET} | {CITY}, {STATE} {ZIPC} | geocode={g} -> {vs}")

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET_ID).worksheet("locations")
    ws.append_row(row, value_input_option="RAW")

    fresh = ws.get_all_values()
    n = sum(1 for r in fresh if r and r[0].strip().lower() == DOMAIN)
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    print(f"appended; ccrmivf.com now has {n} rows | sheet {len(fresh)-1} data rows; local re-synced")


if __name__ == "__main__":
    main()
