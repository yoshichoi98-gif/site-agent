"""Parse data/rca_manual.txt -> rcaresearch.com location rows. Stages to data/rca_parsed.csv
(does NOT touch the canonical). Canonicalizes streets, geocode-verifies each."""
import csv, re, importlib.util
sn = importlib.util.module_from_spec(importlib.util.spec_from_file_location("sn", "scripts/street_norm.py"))
importlib.util.spec_from_file_location("sn", "scripts/street_norm.py").loader.exec_module(sn)
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)

NAME2AB = {"alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY"}
NOISE = {"location informationdirections", "directions", "rgf icon", "rgf logo", "rctx logo"}
CITY_RE = re.compile(r"^(.+?),\s*([A-Za-z][A-Za-z .]*?)\s+(\d{5})(?:-\d{4})?$")
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source"]


def clean_phone(p):
    d = re.sub(r"\D", "", p)
    return f"({d[0:3]}) {d[3:6]}-{d[6:10]}" if len(d) == 10 else p.strip()


def main():
    lines = [ln.strip() for ln in open("data/rca_manual.txt") if ln.strip()]
    lines = [ln for ln in lines if ln.lower() not in NOISE]

    records, pending = [], []
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = CITY_RE.match(ln)
        if m and pending:
            city, state_full, zc = m.group(1).strip(), m.group(2).strip().lower(), m.group(3)
            street = pending[-1]
            name = pending[0]
            phone = ""
            if i + 1 < len(lines) and lines[i + 1].lower().startswith("phone:"):
                phone = clean_phone(lines[i + 1].split(":", 1)[1])
                i += 1
            street = re.sub(r"^\D*(?=\d)", "", street)   # strip building-name prefix up to the number
            records.append({"name": name, "street": sn.canonical_display(street), "city": city,
                            "state": NAME2AB.get(state_full, state_full.upper()[:2]), "zip": zc, "phone": phone})
            pending = []
        else:
            pending.append(ln)
        i += 1

    print(f"parsed {len(records)} location blocks\n")
    out = []
    for r in records:
        g = vg.google_status(f"{r['street']}, {r['city']}, {r['state']} {r['zip']}")
        vs = "passed" if g == "exists" else "needs_review"
        out.append({"domain": "rcaresearch.com", "location_name": r["name"], "address_street": r["street"],
                    "address_city": r["city"], "address_state": r["state"], "address_zip": r["zip"],
                    "phone": r["phone"], "source_url": "https://rcaresearch.com", "snippet": "",
                    "confidence": "high", "validation_status": vs, "source": "manual"})
        flag = "" if g == "exists" else "  <-- REVIEW"
        print(f"  {vs:12} {r['street']}, {r['city']} {r['state']} {r['zip']} | {r['phone']}{flag}")

    with open("data/rca_parsed.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(out)
    from collections import Counter
    print(f"\nstates: {dict(Counter(r['address_state'] for r in out))}")
    print(f"staged {len(out)} rows -> data/rca_parsed.csv")


if __name__ == "__main__":
    main()
