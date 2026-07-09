import importlib.util, re, csv
fl = importlib.util.module_from_spec(importlib.util.spec_from_file_location("fl", "scripts/firecrawl_locations.py"))
importlib.util.spec_from_file_location("fl", "scripts/firecrawl_locations.py").loader.exec_module(fl)
sn = importlib.util.module_from_spec(importlib.util.spec_from_file_location("sn", "scripts/street_norm.py"))
importlib.util.spec_from_file_location("sn", "scripts/street_norm.py").loader.exec_module(sn)
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)

app = fl.Firecrawl(api_key=fl.API_KEY, timeout=fl.REQUEST_TIMEOUT_S)
urls = ["https://www.akdhc.com/locations/avondale-office/",
        "https://www.akdhc.com/locations/deer-valley-office/",
        "https://www.akdhc.com/locations/westgate-surgery-center/"]
rec = []
for u in urls:
    slug = u.rstrip("/").split("/")[-1]
    doc = app.scrape(u, formats=[fl.json_format()], only_main_content=True, wait_for=fl.ESCALATE_WAIT_MS)  # RAW (no on-page guard)
    data = getattr(doc, "json", None) or {}
    for l in (data.get("locations") or []):
        l = l if isinstance(l, dict) else l.model_dump()
        st = sn.canonical_display(l.get("address_street") or "")
        city = l.get("address_city") or ""
        state = (l.get("address_state") or "").upper()[:2]
        z = re.sub(r"\D", "", l.get("address_zip") or "")[:5]
        g = vg.google_status(st + ", " + city + ", " + state + " " + z)
        print("  " + slug + " -> " + st + ", " + city + " " + state + " " + z + " | google=" + g)
        if g == "exists":
            rec.append({"domain": "akdhc.com", "location_name": l.get("location_name") or slug.replace("-", " ").title(),
                        "address_street": st, "address_city": city, "address_state": state, "address_zip": z,
                        "phone": l.get("phone") or "", "source_url": u, "snippet": "", "confidence": "high",
                        "validation_status": "passed", "source": "firecrawl"})

staged = list(csv.DictReader(open("data/akdhc_parsed.csv")))
hdr = list(staged[0].keys())
def key(r): return (sn.norm_street(r["address_street"]), re.sub(r"[^a-z0-9]", "", r["address_city"].lower()), r["address_state"])
have = {key(r) for r in staged}
added = [r for r in rec if key(r) not in have]
allrows = staged + added
with open("data/akdhc_parsed.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=hdr); w.writeheader(); w.writerows(allrows)
print("recovered " + str(len(added)) + " new; akdhc total now " + str(len(allrows)))
