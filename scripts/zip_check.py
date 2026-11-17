"""Check zip <-> city/state consistency using the offline `zipcodes` DB.
Flag values (blank = matches, or no zip to check):
  state_mismatch : row's state is not the zip's state (high confidence)
  city_mismatch  : state ok but row city isn't the zip's city/acceptable-cities (fuzzier)
  zip_invalid    : zip not in the US zip database
"""
import csv, re, zipcodes


def norm(s):
    s = re.sub(r"[^a-z0-9]", "", (s or "").lower())
    return s


def expand_city(s):
    # normalize common abbreviations so "Ft"/"Fort", "St"/"Saint" don't false-flag
    w = (s or "").lower()
    w = re.sub(r"\bft\b", "fort", w)
    w = re.sub(r"\bst\b", "saint", w)
    w = re.sub(r"\bmt\b", "mount", w)
    return norm(w)


def flag(zc, city, state):
    z = re.sub(r"\D", "", zc or "")[:5]
    if len(z) != 5:
        return ""                      # nothing to check
    recs = zipcodes.matching(z)
    if not recs:
        return "zip_invalid"
    states = {r["state"] for r in recs}
    if (state or "").strip() and state.strip().upper() not in states:
        return "state_mismatch"          # only when state is PRESENT and wrong
    if (city or "").strip():
        allowed = set()
        for r in recs:
            allowed.add(expand_city(r["city"]))
            for c in r.get("acceptable_cities", []):
                allowed.add(expand_city(c))
        if expand_city(city) not in allowed:
            return "city_mismatch"
    return ""


def main():
    rows = list(csv.DictReader(open("data/output_locations.csv")))
    from collections import Counter
    cnt = Counter()
    examples = {"state_mismatch": [], "city_mismatch": [], "zip_invalid": []}
    for r in rows:
        f = flag(r.get("address_zip"), r.get("address_city"), r.get("address_state"))
        cnt[f or "ok/blank"] += 1
        if f and len(examples[f]) < 8:
            examples[f].append(f"{r['domain']} | {r.get('address_street')} | {r.get('address_city')} {r.get('address_state')} {r.get('address_zip')}")
    total = sum(cnt.values())
    print("rows:", total)
    for k, n in cnt.most_common():
        print(f"  {k:16} {n}")
    for k in ("state_mismatch", "city_mismatch", "zip_invalid"):
        print(f"\n=== {k} examples ===")
        for e in examples[k]:
            print("   " + e)


if __name__ == "__main__":
    main()
