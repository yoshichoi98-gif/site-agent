"""Append 3 NY locations for a1clinical.com (A1 Clinical) — domain had 0 locations extracted
(HQ address was not_found). Streets kept VERBATIM (no normalization) per Yoshi's pref. zip_check
computed offline; geocode-verify -> validation_status; 22-col schema. Append (no clobber) + re-sync.
Phone left blank: only phone on file is the Houston (832) HQ number, wrong for these NY offices."""
import csv, importlib.util, gspread
from scripts import zip_check as zc

vg_spec = importlib.util.spec_from_file_location("vg", "scripts/verify_google.py")
vg = importlib.util.module_from_spec(vg_spec)
vg_spec.loader.exec_module(vg)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "a1clinical.com"
SRC_URL = "https://a1clinical.com"
ORG = "A1 Clinical"
SUBCAT = "dedicated_research_site"

# (location_name, street VERBATIM, city, state, zip)
LOCS = [
    ("", "2094 Merrick Ave",      "Merrick",         "NY", "11566"),
    ("", "92-04 Springfield Blvd", "Queens Village",  "NY", "11428"),
    ("", "116-05 Myrtle Ave",     "Richmond Hill",   "NY", "11418"),
]

# 22-col schema:
# domain, location_name, address_street, address_city, address_state, address_zip, phone,
# source_url, snippet, confidence, validation_status, source, zip_check, org_subcategory,
# usps_street, usps_city, usps_state, usps_zip, usps_dpv, suite_changed, canonical_org_name, gmaps_verified


def main():
    rows = []
    for name, street, city, state, zipc in LOCS:
        g = vg.google_status(f"{street}, {city}, {state} {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        zflag = zc.flag(zipc, city, state)
        row = [DOMAIN, name, street, city, state, zipc, "", SRC_URL, "", "high", vs, "manual",
               zflag, SUBCAT, "", "", "", "", "", "", ORG, ""]
        rows.append(row)
        print(f"  {street} | {city}, {state} {zipc} | geocode={g} -> {vs} | zip_check={zflag or 'ok'}")

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET_ID).worksheet("locations")
    ws.append_rows(rows, value_input_option="RAW")

    fresh = ws.get_all_values()
    n = sum(1 for r in fresh if r and r[0].strip().lower() == DOMAIN)
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    print(f"\nappended {len(rows)}; {DOMAIN} now has {n} rows | sheet {len(fresh)-1} data rows; local re-synced")


if __name__ == "__main__":
    main()
