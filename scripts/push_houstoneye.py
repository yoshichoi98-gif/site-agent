"""Push houstoneye.com's 17 locations (from the Manual Locations doc) to the sheet, REPLACING any
existing houstoneye.com rows. Streets VERBATIM (trailing comma artifact stripped). All TX.
Geocode-verify + zip_check. Pull-fresh -> replace -> push -> re-sync."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "houstoneye.com"
SRC_URL = "https://www.houstoneye.com/locations"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]

# (name, street, city, zip, phone) -- all TX
LOCS = [
    ("Houston Eye Associates-Conroe Eye Care Center", "333 N. Rivershire Drive, Suite 160", "Conroe", "77304", "(936) 441-2020"),
    ("Houston Eye Associates-East Eye Care Center", "5614 E. Sam Houston Pkwy N.", "Houston", "77015", "(713) 678-8288"),
    ("Houston Eye Associates-Gramercy Eye Care Center", "2855 Gramercy St", "Houston", "77025", "(713) 668-6828"),
    ("Houston Eye Associates-Memorial City Eye Care Center", "915 Gessner Rd, Suite 250", "Houston", "77024", "(713) 467-6474"),
    ("Houston Eye Associates-North Loop Eye Care Center", "1415 North Loop West, Suite 400", "Houston", "77008", "(713) 869-6400"),
    ("Houston Eye Associates-Tanglewood Eye Care Center", "590 Chimney Rock Rd", "Houston", "77056", "(713) 782-4406"),
    ("Houston Eye Associates-West Eye Care Center", "12121 Richmond Ave, Suite 110", "Houston", "77082", "(281) 493-1733"),
    ("Houston Eye Associates-Katy Eye Care Center", "1331 W Grand Parkway N, Suite 120", "Katy", "77493", "(281) 347-0176"),
    ("Houston Eye Associates-Kingwood Eye Care Center", "22659 Highway 59 North, Suite 100", "Kingwood", "77339", "(281) 348-3375"),
    ("Houston Eye Associates-League City Eye Care Center", "1100 Gulf Freeway, Suite 114", "League City", "77573", "(281) 332-3937"),
    ("Houston Eye Associates-Pasadena Eye Care Center", "5125 Fairmont Parkway", "Pasadena", "77505", "(713) 477-6929"),
    ("Houston Eye Associates-Pearland Eye Care Center", "10907 Memorial Hermann Dr., Suite 150", "Pearland", "77584", "(281) 582-9100"),
    ("Houston Eye Associates-Richmond Eye Care Center", "1601 Main St., Suite 408", "Richmond", "77469", "(281) 341-0405"),
    ("Houston Eye Associates-Spring-Klein Eye Care Center", "5211 FM 2920, Suite 102", "Spring", "77388", "(281) 444-1677"),
    ("Houston Eye Associates-Sugar Land Eye Care Center", "1447 Highway 6, Suite 110", "Sugar Land", "77478", "(281) 565-2020"),
    ("Houston Eye Associates-The Woodlands Eye Care Center", "1699 Research Forest Drive, Suite 150", "The Woodlands", "77380", "(281) 363-2155"),
    ("Houston Eye Associates-Tomball Eye Care Center", "455 School Street, Suite 47", "Tomball", "77375", "(281) 351-7483"),
]


def main():
    print(f"{len(LOCS)} locations\n")
    new_rows = []
    for name, street, city, zipc, phone in LOCS:
        g = vg.google_status(f"{street}, {city}, TX {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, "TX")
        new_rows.append([DOMAIN, name, street, city, "TX", zipc, phone, SRC_URL, "",
                         "high", vs, "manual", zf])
        tag = "" if vs == "passed" else " <REVIEW>"
        zt = f" zip:{zf}" if zf else ""
        print(f"  {name[24:54]:32} | {street[:36]:36} | {city} {zipc}{tag}{zt}")

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET_ID).worksheet("locations")
    sheet = ws.get_all_values()
    hdr, body = sheet[0], sheet[1:]
    kept = [r for r in body if r and r[0].strip().lower() != DOMAIN]
    removed = len(body) - len(kept)
    final = [hdr] + kept + new_rows
    print(f"\nremoved {removed} old {DOMAIN} rows, adding {len(new_rows)} new")

    ws.clear()
    ws.resize(rows=len(final), cols=len(hdr))
    ws.update(final, value_input_option="RAW")

    fresh = ws.get_all_values()
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    nr = sum(1 for r in new_rows if r[10] != "passed")
    flg = sum(1 for r in new_rows if r[12])
    print(f"pushed; sheet now {len(fresh)-1} data rows; local re-synced")
    print(f"houstoneye: {len(new_rows)} rows | needs_review: {nr} | zip_check flags: {flg}")


if __name__ == "__main__":
    main()
