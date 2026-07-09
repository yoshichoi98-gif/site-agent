"""Parse careaccess.com's locations from data/careaccess_raw.txt and REPLACE all existing
careaccess.com rows in the sheet. 24 states. Blocks delimited by a leading US-state-name line;
each block = State / Branch / street / [suite...] / 'City, ST, zip' / [specialty]. Streets kept
VERBATIM. Doc has NO phones -> phone blank. Geocode-verify + zip_check. Pull-fresh -> replace -> push."""
import csv, re, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "careaccess.com"
SRC_URL = "https://www.careaccess.com/locations"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]
STATES = {"Arizona", "California", "Colorado", "Florida", "Georgia", "Illinois", "Indiana",
          "Louisiana", "Maryland", "Massachusetts", "Michigan", "Missouri", "New Jersey",
          "New York", "North Carolina", "Ohio", "Pennsylvania", "Rhode Island", "South Carolina",
          "South Dakota", "Tennessee", "Texas", "Utah", "Virginia"}
CITY_RE = re.compile(r"^(.*),\s*([A-Z]{2}),\s*(\d{5})$")


def parse_blocks():
    lines = [l.strip() for l in open("data/careaccess_raw.txt") if l.strip()]
    # group into blocks: each starts at a STATES line
    blocks, cur = [], []
    for l in lines:
        if l in STATES:
            if cur:
                blocks.append(cur)
            cur = [l]
        else:
            cur.append(l)
    if cur:
        blocks.append(cur)

    out = []
    for b in blocks:
        # b[0]=state name, b[1]=branch label, then street/suite..., cityline, [specialty]
        branch = b[1]
        ci = next(i for i, l in enumerate(b) if CITY_RE.match(l))
        m = CITY_RE.match(b[ci])
        city, state, zipc = m.group(1).strip(), m.group(2), m.group(3)
        street = ", ".join(b[2:ci])
        name = re.sub(r",\s*[A-Z]{2}$", "", branch).strip()   # "Sacramento, CA" -> "Sacramento"
        out.append((name, street, city, state, zipc))
    return out


def main():
    parsed = parse_blocks()
    print(f"parsed {len(parsed)} blocks\n")
    new_rows = []
    for name, street, city, state, zipc in parsed:
        g = vg.google_status(f"{street}, {city}, {state} {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, state)
        new_rows.append([DOMAIN, name, street, city, state, zipc, "", SRC_URL, "",
                         "high", vs, "manual", zf])
        tag = "" if vs == "passed" else " <REVIEW>"
        zt = f" zip:{zf}" if zf else ""
        print(f"  {name[:24]:24} | {street[:34]:34} | {city}, {state} {zipc}{tag}{zt}")

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
    print(f"pushed {len(final)-1} data rows to sheet")

    fresh = ws.get_all_values()
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    print(f"re-synced local CSV ({len(fresh)-1} rows)")
    nr = sum(1 for r in new_rows if r[10] != "passed")
    flg = sum(1 for r in new_rows if r[12])
    print(f"\ncareaccess: {len(new_rows)} rows | needs_review: {nr} | zip_check flags: {flg}")
    for r in new_rows:
        if r[10] != "passed" or r[12]:
            print(f"   - {r[1]} | {r[2]}, {r[3]} {r[4]} {r[5]} | vs={r[10]} zip={r[12]}")


if __name__ == "__main__":
    main()
