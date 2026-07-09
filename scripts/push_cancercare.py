"""Push cancercarespecialists.org's locations from the Manual Locations doc (Centers & Clinics List).
23 unique = 20 Medical Oncology + 3 Radiation Oncology (2 radiation entries are exact dups of
medical-onc rows -> collapsed). Streets VERBATIM. All IL. Geocode-verify + zip_check.
Pull-fresh -> replace -> push -> re-sync."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "cancercarespecialists.org"
SRC_URL = "https://cancercarespecialists.org/centers-clinics/"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]

# (name, street, city, zip, phone) -- all IL
LOCS = [
    ("Cancer Care Center of Decatur", "210 W. McKinley Ave., Suite 1", "Decatur", "62526", "(217) 876-6600"),
    ("Cancer Care Center of O’Fallon", "321 Regency Park", "O’Fallon", "62269", "(618) 416-7970"),
    ("Centralia Oncology Clinic", "1052 M. L. King Drive, Suite 2", "Centralia", "62801", "(618) 436-5410"),
    ("Crossroads Cancer Center", "905 Medical Park Drive", "Effingham", "62401", "(217) 342-2066"),
    ("Cancer Care Specialists of Illinois – Sparta (Broadway Plaza Specialty Clinic)", "Suite 1 Broadway Plaza", "Sparta", "62286", "(618) 443-2177"),
    ("Carle Richland Memorial Hospital", "800 E. Locust St.", "Olney", "62450", "(618) 395-6079"),
    ("Clay County Hospital Medical Clinic", "929 Stacy Burk Drive", "Flora", "62839", "(618) 662-2191"),
    ("Fairfield Memorial Hospital – Medical Arts Complex", "213 N.W. 10th Street, Suite D", "Fairfield", "62837", "(618) 847-8296"),
    ("Sarah Bush Lincoln Fayette County Hospital", "650 West Taylor St.", "Vandalia", "62471", "(618) 283-5531"),
    ("HSHS Good Shepherd Hospital – Physicians Center", "207 S. Pine St., Suite F", "Shelbyville", "62565", "(217) 774-3886"),
    ("HSHS Holy Family Hospital", "200 Healthcare Drive, Suite 1501", "Greenville", "62246", "(618) 690-3411"),
    ("HSHS St. Joseph’s Hospital – Breese Specialty Clinic", "9515 Holy Cross Lane, Suite 6", "Breese", "62230", "(618) 526-8585"),
    ("HSHS St. Joseph’s Hospital Highland – Medical Office Building", "12860 Troxler Ave., Suite 135", "Highland", "62249", "(618) 651-2888"),
    ("HSHS St. Mary’s Cancer Care Center", "1990 E. Lake Shore Drive", "Decatur", "62521", "(217) 464-2900"),
    ("Kirby Medical Center", "#2 Sage Crossing Blvd, Suite A", "Monticello", "61856", "(217) 762-2115"),
    ("Memorial Hospital Oncology Clinic", "1900 State St.", "Chester", "62233", "(618) 826-4581"),
    ("Pana Community Hospital Medical Mall", "101 E. Ninth, Suite 1", "Pana", "62557", "(217) 562-2131"),
    ("Salem Township Hospital", "1201 Ricker Drive", "Salem", "62881", "(618) 740-0945"),
    ("Taylorville Memorial Hospital", "201 E. Pleasant", "Taylorville", "62568", "(217) 707-5555"),
    ("Warner Hospital & Health Services", "422 West White Street", "Clinton", "61727", "(217) 935-9571"),
    # Radiation Oncology (distinct from the medical-onc rows above)
    ("DMH Cancer Care Institute at Cancer Care Center of Decatur", "210 W. McKinley Ave., Suite 2", "Decatur", "62526", "(217) 876-4700"),
    ("HSHS St. Elizabeth’s Radiation Oncology Center at Cancer Care Center of O’Fallon", "321 Regency Park", "O’Fallon", "62269", "(618) 607-5545"),
    ("Sarah Bush Lincoln Regional Cancer Center – Radiation Oncology", "1001 Health Center Dr.", "Mattoon", "61938", "(217) 258-2250"),
]


def main():
    print(f"{len(LOCS)} locations\n")
    new_rows = []
    for name, street, city, zipc, phone in LOCS:
        g = vg.google_status(f"{street}, {city}, IL {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, "IL")
        new_rows.append([DOMAIN, name, street, city, "IL", zipc, phone, SRC_URL, "",
                         "high", vs, "manual", zf])
        if vs != "passed" or zf:
            print(f"  FLAG {name[:46]:46} | {street}, {city} {zipc} | vs={vs} zip={zf}")

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
    print(f"cancercare: {len(new_rows)} rows | needs_review: {nr} | zip_check flags: {flg}")


if __name__ == "__main__":
    main()
