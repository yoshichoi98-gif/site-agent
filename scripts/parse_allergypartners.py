"""Parse allergypartners.com from the badly-formatted doc text (saved to data/allergypartners_raw.txt).
Structure per block (after dropping ',' and blank-cell noise lines), delimited by 'View Website':
  City, ST, street, [suite...], City(repeat), ST, zip, phone
Diffs against current data by address; prints doc records + which are missing. Stages, no push."""
import csv, re, importlib.util
sn = importlib.util.module_from_spec(importlib.util.spec_from_file_location("sn", "scripts/street_norm.py"))
importlib.util.spec_from_file_location("sn", "scripts/street_norm.py").loader.exec_module(sn)

RAW = open("data/allergypartners_raw.txt").read()


def tokens(block):
    out = []
    for ln in block.split("\n"):
        s = ln.strip()
        if s and s != "," and not re.fullmatch(r"[\s,]*", s):
            out.append(s)
    return out


def parse():
    recs = []
    for block in RAW.split("View Website"):
        t = tokens(block)
        if len(t) < 6:
            continue
        city, state = t[0], t[1]
        # second occurrence of the city marks the start of the city/state/zip/phone tail
        j = next((k for k in range(2, len(t)) if t[k] == city), None)
        if j is None or j + 2 >= len(t):
            continue
        street_parts = t[2:j]
        street = street_parts[0]
        suite = " ".join(street_parts[1:]).strip(", ")
        full = street + (", " + suite if suite else "")
        zc = re.sub(r"\D", "", t[j + 2])[:5]
        phone = t[j + 3] if j + 3 < len(t) else ""
        recs.append({"name": city, "street": sn.canonical_display(re.sub(r"^\D*(?=\d)", "", full)),
                     "city": city, "state": state.upper(), "zip": zc, "phone": phone})
    return recs


def addr_key(street, city, state):
    m = sn.norm_street(street)
    return (m, re.sub(r"[^a-z0-9]", "", city.lower()), state.upper())


def main():
    recs = parse()
    print("parsed", len(recs), "doc records")
    cur = [r for r in csv.DictReader(open("data/output_locations.csv")) if r["domain"].strip().lower() == "allergypartners.com"]
    have = {addr_key(r["address_street"], r["address_city"], r["address_state"]) for r in cur}
    missing = [r for r in recs if addr_key(r["street"], r["city"], r["state"]) not in have]
    print("current rows:", len(cur), "| doc:", len(recs), "| MISSING from data:", len(missing))
    for r in missing:
        print("   " + r["street"] + ", " + r["city"] + " " + r["state"] + " " + r["zip"] + " | " + r["phone"])
    # also doc dup check
    from collections import Counter
    kc = Counter(addr_key(r["street"], r["city"], r["state"]) for r in recs)
    dups = [k for k, n in kc.items() if n > 1]
    print("intra-doc duplicate address keys:", len(dups))


if __name__ == "__main__":
    main()
