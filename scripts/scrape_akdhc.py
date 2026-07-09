"""Scrape every akdhc.com /locations/<x>/ detail page, extract the address, canonicalize +
geocode-verify, dedupe within domain. Stages to data/akdhc_parsed.csv (does not touch canonical)."""
import csv, re, importlib.util
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
sn = importlib.util.module_from_spec(importlib.util.spec_from_file_location("sn", "scripts/street_norm.py"))
importlib.util.spec_from_file_location("sn", "scripts/street_norm.py").loader.exec_module(sn)
fl = importlib.util.module_from_spec(importlib.util.spec_from_file_location("fl", "scripts/firecrawl_locations.py"))
importlib.util.spec_from_file_location("fl", "scripts/firecrawl_locations.py").loader.exec_module(fl)
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)

app = fl.Firecrawl(api_key=fl.API_KEY, timeout=fl.REQUEST_TIMEOUT_S)
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source"]


def link_set():
    doc = app.scrape("https://www.akdhc.com/locations/", formats=["links"], only_main_content=False, wait_for=8000)
    links = getattr(doc, "links", None) or []
    return sorted(set(l for l in links
                      if re.search(r"/locations?/[a-z0-9-]+", l, re.I) and not l.rstrip("/").endswith("/locations")))


def scrape_one(url):
    locs = fl.scrape_page(app, url, fl.ESCALATE_WAIT_MS)
    slug = urlparse(url).path.rstrip("/").split("/")[-1].replace("-", " ").title()
    out = []
    for l in locs:
        out.append({"name": l.get("location_name") or slug, "street": l.get("address_street") or "",
                    "city": l.get("address_city") or "", "state": l.get("address_state") or "",
                    "zip": l.get("address_zip") or "", "phone": l.get("phone") or "", "url": url})
    return out


def main():
    links = link_set()
    print(f"{len(links)} location links")
    raw = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for fut in as_completed({ex.submit(scrape_one, u): u for u in links}):
            raw.extend(fut.result())
    print(f"extracted {len(raw)} raw location rows")

    # canonicalize + normalize + verify
    rows = []
    for r in raw:
        if not str(r["street"]).strip():
            continue
        street = sn.canonical_display(re.sub(r"^\D*(?=\d)", "", r["street"]))
        zc = re.sub(r"\D", "", r["zip"])[:5]
        state = (r["state"] or "").strip().upper()[:2]
        g = vg.google_status(f"{street}, {r['city']}, {state} {zc}")
        rows.append({"domain": "akdhc.com", "location_name": r["name"], "address_street": street,
                     "address_city": r["city"], "address_state": state, "address_zip": zc,
                     "phone": r["phone"], "source_url": r["url"], "snippet": "", "confidence": "high",
                     "validation_status": "passed" if g == "exists" else "needs_review", "source": "firecrawl"})

    # within-domain dedup (keep suite distinct)
    def key(r): return (sn.norm_street(r["address_street"]), re.sub(r"[^a-z0-9]", "", r["address_city"].lower()), r["address_state"])
    def comp(r): return sum(1 for k in ("phone", "address_zip", "address_street", "address_city") if (r.get(k) or "").strip())
    groups = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r)
    deduped = [max(g, key=comp) for g in groups.values()]

    with open("data/akdhc_parsed.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(deduped)
    nr = sum(1 for r in deduped if r["validation_status"] != "passed")
    print(f"-> {len(deduped)} unique locations ({nr} needs_review) staged to data/akdhc_parsed.csv")
    for r in deduped:
        print(f"   {r['validation_status']:12} {r['address_city']:16} | {r['address_street']} {r['address_zip']}")


if __name__ == "__main__":
    main()
