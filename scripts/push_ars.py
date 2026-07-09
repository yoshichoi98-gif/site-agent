"""Parse arshealthcare.com's locations from data/ars_raw.txt and REPLACE all existing
arshealthcare.com rows in the sheet. Multi-state (AL/SC/TN/GA). Streets kept VERBATIM
(no canonicalization). Geocode-verify + zip_check each. Pull-fresh -> replace -> push -> re-sync."""
import csv, re, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "arshealthcare.com"
SRC_URL = "https://www.arshealthcare.com/locations"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]
TAIL_RE = re.compile(r"([A-Z]{2})\s+(\d{5})$")


def parse_blocks():
    raw = open("data/ars_raw.txt").read()
    out = []
    for block in raw.split("Learn More"):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        name = lines[0]
        phone = ""
        addr_lines = []
        for l in lines[1:]:
            if l.upper().startswith("P:"):
                phone = re.sub(r"\s+", "", l.split(":", 1)[1].strip())
            else:
                addr_lines.append(l)
        addr = ", ".join(addr_lines)
        segs = [s.strip() for s in addr.split(",") if s.strip()]
        m = TAIL_RE.search(segs[-1])
        state, zipc = m.group(1), m.group(2)
        if len(segs) >= 3:
            city = segs[-2]
            street = ", ".join(segs[:-2])
        else:                                  # glued: "<street> <City>, ST zip"
            toks = segs[0].split()
            city = toks[-1]
            street = " ".join(toks[:-1])
        out.append((name, street, city, state, zipc, phone))
    return out


def main():
    parsed = parse_blocks()
    print(f"parsed {len(parsed)} blocks\n")
    new_rows = []
    for name, street, city, state, zipc, phone in parsed:
        g = vg.google_status(f"{street}, {city}, {state} {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, state)
        new_rows.append([DOMAIN, name, street, city, state, zipc, phone, SRC_URL, "",
                         "high", vs, "manual", zf])
        tag = "" if vs == "passed" else " <REVIEW>"
        zt = f" zip:{zf}" if zf else ""
        print(f"  {name[:46]:46} | {street[:34]:34} | {city}, {state} {zipc}{tag}{zt}")

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
    print(f"\nars: {len(new_rows)} rows | needs_review: {nr} | zip_check flags: {flg}")


if __name__ == "__main__":
    main()
