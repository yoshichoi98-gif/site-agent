"""Append a single Wichita location to elevateclinical.com. Geocode-verify + zip_check, append + re-sync."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "elevateclinical.com"
SRC_URL = "https://www.elevateclinical.com/locations"
NAME, STREET, CITY, STATE, ZIPC, PHONE = "Wichita", "1035 N Emporia Ave", "Wichita", "KS", "67214", "(316) 320-0833"


def main():
    g = vg.google_status(f"{STREET}, {CITY}, {STATE} {ZIPC}")
    vs = "passed" if g == "exists" else "needs_review"
    zf = zc.flag(ZIPC, CITY, STATE)
    row = [DOMAIN, NAME, STREET, CITY, STATE, ZIPC, PHONE, SRC_URL, "", "high", vs, "manual", zf]
    print(f"  {NAME} | {STREET}, {CITY} {STATE} {ZIPC} | geocode={g} -> {vs} | zip_check='{zf}'")

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET_ID).worksheet("locations")
    ws.append_row(row, value_input_option="RAW")

    fresh = ws.get_all_values()
    n = sum(1 for r in fresh if r and r[0].strip().lower() == DOMAIN)
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    print(f"appended; elevateclinical.com now has {n} rows; local re-synced ({len(fresh)-1} data rows)")


if __name__ == "__main__":
    main()
