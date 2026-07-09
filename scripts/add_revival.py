"""Parse the user-provided Revival Research Institute locations, canonicalize, geocode-verify,
and REPLACE revivalresearch.org's 8 blank-street stub rows in output_locations.csv with these."""
import csv, importlib.util
sn = importlib.util.module_from_spec(importlib.util.spec_from_file_location("sn", "scripts/street_norm.py"))
importlib.util.spec_from_file_location("sn", "scripts/street_norm.py").loader.exec_module(sn)
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)

DOMAIN = "revivalresearch.org"
PATH = "data/output_locations.csv"

# (street, city, state, zip) — 13 unique, deduped from the pasted list
RAW = [
    ("1002 Williamsburg Way", "Evans", "GA", "30809"),
    ("2130 Point Blvd., Suite #200", "Elgin", "IL", "60123"),
    ("6512 Schaefer Rd.", "Dearborn", "MI", "48126"),
    ("1565 W. Big Beaver Rd., Suite #F", "Troy", "MI", "48084"),
    ("23999 Northwestern Hwy.", "Southfield", "MI", "48075"),
    ("43303 Schoenherr Rd.", "Sterling Heights", "MI", "48313"),
    ("25150 Ford Rd., Suite #120", "Dearborn Heights", "MI", "48127"),
    ("4004 Pioneer Woods Drive", "Lincoln", "NE", "68506"),
    ("160 Macgregor Pines Drive, Suite #100", "Cary", "NC", "27511"),
    ("1400 N Coit Road, Suite #2002", "McKinney", "TX", "75071"),
    ("10260 N Central Expressway, Suite #100N", "Dallas", "TX", "75231"),
    ("3300 Colorado Blvd.", "Denton", "TX", "76210"),
    ("1700 N Travis St", "Sherman", "TX", "75092"),
]

FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source"]


def main():
    new = []
    for street, city, state, z in RAW:
        canon = sn.canonical_display(street)
        addr = f"{canon}, {city}, {state} {z}"
        g = vg.google_status(addr)
        vs = "passed" if g == "exists" else "needs_review"
        new.append({"domain": DOMAIN, "location_name": city, "address_street": canon,
                    "address_city": city, "address_state": state, "address_zip": z,
                    "phone": "", "source_url": "https://revivalresearch.org", "snippet": "",
                    "confidence": "high", "validation_status": vs, "source": "manual"})
        print(f"  {g:8} {vs:12} {canon}, {city} {state} {z}")

    rows = list(csv.DictReader(open(PATH)))
    old = [r for r in rows if r["domain"].strip().lower() == DOMAIN]
    kept = [r for r in rows if r["domain"].strip().lower() != DOMAIN]
    out = kept + new
    with open(PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(out)
    print(f"\nremoved {len(old)} old stub rows, added {len(new)} parsed rows")
    print(f"output_locations.csv now: {len(out)} rows")


if __name__ == "__main__":
    main()
