"""Push mnoncology.com's 21 locations (from the Manual Locations doc) to the sheet, REPLACING
existing rows. Streets VERBATIM. Mostly MN + 1 WI (Hudson). Geocode-verify + zip_check.
Pull-fresh -> replace -> push -> re-sync."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "mnoncology.com"
SRC_URL = "https://www.mnoncology.com/locations"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]

# (name, street, city, state, zip, phone)
LOCS = [
    ("Administrative and Corporate Office", "2550 University Avenue West, Suite 110-N", "Saint Paul", "MN", "55114", "651-602-5335"),
    ("Bloomington Clinic", "7760 France Ave South, Suite 1000", "Bloomington", "MN", "55435", "(952) 746-6767"),
    ("Burnsville Clinic", "675 E Nicollet Blvd, Suite 100", "Burnsville", "MN", "55337", "(952) 892-7190"),
    ("Chaska - Minnesota Oncology & Ridgeview Cancer & Infusion Center", "110105 Pioneer Trail, Suite 302", "Chaska", "MN", "55318", "(952) 361-5800"),
    ("Colon & Rectal Surgery - Burnsville Clinic", "675 E Nicollet Blvd, Suite 135", "Burnsville", "MN", "55337", "(651) 312-1700"),
    ("Colon & Rectal Surgery - Coon Rapids Clinic", "11850 Blackfoot Street N.W., Suite 270", "Coon Rapids", "MN", "55433", "(651) 312-1717"),
    ("Colon & Rectal Surgery - Edina Clinic", "6363 France Ave. S. Suite 400", "Edina", "MN", "55435", "(651) 312-1700"),
    ("Colon & Rectal Surgery - Maplewood Clinic", "2945 Hazelwood St. Suite 340", "Maplewood", "MN", "55109", "(651) 312-1620"),
    ("Coon Rapids Clinic", "11850 Blackfoot St NW, Suite 100", "Coon Rapids", "MN", "55433", "(763) 712-2100"),
    ("Duluth Clinic", "4316 Rice Lake Road, Suite 101", "Duluth", "MN", "55811", "(218) 524-3600"),
    ("Edina Clinic", "6545 France Avenue, Suite 210", "Edina", "MN", "55435", "(952) 928-2900"),
    ("Hudson Clinic", "2651 Hillcrest Drive, Suite 105", "Hudson", "WI", "54016", "(715) 280-9151"),
    ("Maple Grove Clinic", "10150 Niagara Lane N, Suite 100", "Maple Grove", "MN", "55369", "(763) 297-9700"),
    ("Maplewood Cancer Center", "1580 Beam Avenue", "Maplewood", "MN", "55109", "(651) 779-7978"),
    ("Minneapolis Clinic", "910 E 26th St, Suite 200", "Minneapolis", "MN", "55404", "(612) 884-6300"),
    ("Pelvic Floor Center Edina", "6363 France Ave. S. Suite 400", "Edina", "MN", "55435", "(651) 225-7800"),
    ("Pelvic Floor Center Maplewood", "2945 Hazelwood, Suite 340", "Maplewood", "MN", "55109", "(651) 312-1600"),
    ("Plymouth Clinic", "2805 Campus Drive, Suite 105", "Plymouth", "MN", "55441", "(763) 519-7440"),
    ("St. Paul Cancer Center *HDR ONLY*", "310 Smith Ave N, Suite 100", "Saint Paul", "MN", "55102", "(651) 251-5500"),
    ("Waconia - Minnesota Oncology & Ridgeview Cancer & Infusion Center", "560 Maple Street South, Suite 100", "Waconia", "MN", "55387", "(952) 442-6006"),
    ("Woodbury Clinic", "6025 Lake Rd, Suite 110", "Woodbury", "MN", "55125", "(651) 735-7414"),
]


def main():
    print(f"{len(LOCS)} locations\n")
    new_rows = []
    for name, street, city, state, zipc, phone in LOCS:
        g = vg.google_status(f"{street}, {city}, {state} {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, state)
        new_rows.append([DOMAIN, name, street, city, state, zipc, phone, SRC_URL, "",
                         "high", vs, "manual", zf])
        if vs != "passed" or zf:
            print(f"  FLAG {name[:48]:48} | {street}, {city} {state} {zipc} | vs={vs} zip={zf}")

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
    print(f"mnoncology: {len(new_rows)} rows | needs_review: {nr} | zip_check flags: {flg}")


if __name__ == "__main__":
    main()
