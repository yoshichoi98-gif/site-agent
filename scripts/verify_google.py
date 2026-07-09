"""Hybrid existence check, stage 2: run the Census NO-MATCH addresses through Google Geocoding.
Reads data/location_verification.csv (Census results), Google-geocodes the No_Match rows, and
writes data/location_verification_final.csv with a combined verdict.

Verdict per row:
  verified  = Census Match/Tie, OR Google OK with partial_match=False
  suspect   = Google OK but partial_match=True (fell back), or ZERO_RESULTS  -> address likely not real
  no_address= row had no street to check
  error     = Google kept erroring (transient) — inconclusive
"""
import os, csv, time, requests
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv("/Users/yoshichoi/site-agent/.env")
KEY = os.environ["GOOGLE_PLACES_API_KEY"]
IN = "data/location_verification.csv"
OUT = "data/location_verification_final.csv"


def google_status(addr):
    """Return 'exists' | 'suspect' | 'error'. Retries transient REQUEST_DENIED/OVER_QUERY_LIMIT."""
    for attempt in range(4):
        try:
            r = requests.get("https://maps.googleapis.com/maps/api/geocode/json",
                             params={"address": addr, "key": KEY}, timeout=25).json()
        except Exception:
            time.sleep(2 * (attempt + 1)); continue
        st = r.get("status")
        if st == "OK":
            res = r["results"][0]
            return "suspect" if res.get("partial_match") else "exists"
        if st == "ZERO_RESULTS":
            return "suspect"
        if st in ("OVER_QUERY_LIMIT", "REQUEST_DENIED", "UNKNOWN_ERROR"):
            time.sleep(2 * (attempt + 1)); continue
        return "error"
    return "error"


def main():
    rows = list(csv.DictReader(open(IN)))
    nomatch = [r for r in rows if r["verify"] == "No_Match"]
    # unique address strings among the no-match rows
    def addr_of(r):
        return f"{r['address_street']}, {r['address_city']}, {r['address_state']} {r['address_zip']}".strip()
    uniq = {}
    for r in nomatch:
        uniq.setdefault(addr_of(r), None)
    print(f"Census no-match rows: {len(nomatch)} | unique addresses to Google-check: {len(uniq)}")

    addrs = list(uniq)
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(google_status, a): a for a in addrs}
        done = 0
        for fut in as_completed(futs):
            uniq[futs[fut]] = fut.result()
            done += 1
            if done % 200 == 0:
                print(f"  ...{done}/{len(addrs)}")

    cnt = Counter()
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["domain", "address_street", "address_city", "address_state", "address_zip", "census", "google", "final"])
        for r in rows:
            cen = r["verify"]
            if cen in ("Match", "Tie"):
                g, final = "", "verified"
            elif cen == "no_street":
                g, final = "", "no_address"
            else:  # No_Match -> use google
                g = uniq.get(addr_of(r), "error")
                final = {"exists": "verified", "suspect": "suspect", "error": "error"}[g]
            cnt[final] += 1
            w.writerow([r["domain"], r["address_street"], r["address_city"], r["address_state"], r["address_zip"], cen, g, final])

    total = sum(cnt.values())
    print(f"\n=== FINAL combined verdict ({total} rows) ===")
    for k, c in cnt.most_common():
        print(f"  {k:10} {c:6}  ({100*c/total:.1f}%)")
    print(f"  report: {OUT}")


if __name__ == "__main__":
    main()
