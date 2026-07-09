"""Extract DelRicht Research's own sites from /contact-us/. Each site is a <p> block:
'DelRicht Research @ {Site}<br><a te:phone>phone</a> | <a maps-link>{full address}</a>'.
Parse those (ignoring the partner-referral list), run the address strings through the v10 extractor
for clean street/city/state/zip, geocode-verify + zip_check, add to sam_new_targets_locations."""
import os, sys, re, csv, importlib.util
sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv()
from bs4 import BeautifulSoup
from firecrawl import Firecrawl
from src.location_extract import extract_locations
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

DOMAIN = "delrichtresearch.com"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]


def main():
    fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"], timeout=90)
    h = fc.scrape("https://delrichtresearch.com/contact-us/", formats=["rawHtml"])
    html = getattr(h, "raw_html", None) or getattr(h, "rawHtml", "") or ""
    # Page embeds the location markup as a unicode-escaped blob (< etc.) — unescape so we get real tags.
    for a, b in [("\\u003C", "<"), ("\\u003c", "<"), ("\\u003E", ">"), ("\\u003e", ">"),
                 ("\\u0026", "&"), ("\\u0027", "'"), ("\\u0022", '"'), ('\\"', '"'), ("\\/", "/"),
                 ("\\u2028", " "), ("\\u2029", " ")]:
        html = html.replace(a, b)

    blocks = []
    for ch in re.split(r"DelRicht Research @", html)[1:]:
        seg = ch[:700]
        nm = re.match(r"\s*([^<|\n]{2,60}?)\s*(?:<|\|)", seg)
        name = ("DelRicht Research @ " + nm.group(1).strip()) if nm else "DelRicht Research"
        ph = re.search(r"\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}", seg)
        phone = ph.group(0) if ph else ""
        am = re.search(r"(?:goo\.gl|maps\.app|maps\.google)[^>]*>\s*([^<]+?)\s*</a>", seg)
        if am:
            addr = am.group(1).strip()
        else:
            a2 = re.search(r"(\d{2,6}[^<>|]{3,70}?\s+[A-Z]{2}\s+\d{5})", seg)
            addr = a2.group(1).strip() if a2 else ""
        if addr and re.search(r"[A-Z]{2}\s+\d{5}", addr):
            blocks.append((name, phone, addr))
    seen = set(); blocks = [b for b in blocks if not (b[2] in seen or seen.add(b[2]))]
    print(f"DelRicht site blocks: {len(blocks)}", file=sys.stderr)

    # parse addresses cleanly via the extractor (synthetic one-per-line page)
    synth = "<html><body>" + "".join(f"<p>{n} — {a} — Phone: {ph}</p>" for n, ph, a in blocks) + "</body></html>"
    res, _ = extract_locations(DOMAIN, "", {"https://delrichtresearch.com/contact-us/": synth})

    rows = []
    for l in res.locations:
        st = l.address_state or ""
        rows.append({"domain": DOMAIN, "location_name": l.location_name or "",
            "address_street": l.address_street or "", "address_city": l.address_city or "",
            "address_state": st, "address_zip": l.address_zip or "", "phone": l.phone or "",
            "source_url": "https://delrichtresearch.com/contact-us/", "snippet": "",
            "confidence": l.confidence or "high",
            "validation_status": "passed" if vg.google_status(f"{l.address_street}, {l.address_city}, {st} {l.address_zip}") == "exists" else "needs_review",
            "source": "manual", "zip_check": zc.flag(l.address_zip or "", l.address_city or "", st)})
    with open("data/delricht_locations.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    print(f"parsed {len(rows)} locations | full street: {sum(1 for r in rows if r['address_street'].strip())} | "
          f"needs_review: {sum(1 for r in rows if r['validation_status']!='passed')} | "
          f"zip flags: {sum(1 for r in rows if r['zip_check'])}", file=sys.stderr)
    for r in rows:
        print(f"  {r['location_name'][:30]:30} | {r['address_street'][:30]:30} | {r['address_city']}, {r['address_state']} {r['address_zip']}", file=sys.stderr)


if __name__ == "__main__":
    main()
