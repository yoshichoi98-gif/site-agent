"""Extract each Rainier Research site's address from its sell-sheet PDF (text-layer footer),
which Firecrawl's markdown garbles. Downloads each PDF, pypdf-extracts, regexes the footer
address + name + phone. Geocode-verifies. Stages to data/rainier_parsed.csv (no push)."""
import csv, re, io, urllib.request, importlib.util
from pypdf import PdfReader
sn = importlib.util.module_from_spec(importlib.util.spec_from_file_location("sn", "scripts/street_norm.py"))
importlib.util.spec_from_file_location("sn", "scripts/street_norm.py").loader.exec_module(sn)
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

PDFS = {
 "RCRC": "https://static1.squarespace.com/static/68eebc5c2000bf72493af0e4/t/690cb8ef03e2576c9bfeafc6/1762441455592/SellSheetRCRC_2025-09-25.pdf",
 "SCRC": "https://static1.squarespace.com/static/68eebc5c2000bf72493af0e4/t/690cb90c1e1c0f25677558ea/1762441484125/SellSheetSCRC_2025-09-30.pdf",
 "WCRC": "https://static1.squarespace.com/static/68eebc5c2000bf72493af0e4/t/690cb9412e9e336e2ce89754/1762441537218/SellSheetWCRC_2025-09-25.pdf",
 "SVRC": "https://static1.squarespace.com/static/68eebc5c2000bf72493af0e4/t/690cb9f3733c4f4353ec6219/1762441715917/SellSheetSVRC_2025-09-25.pdf",
 "PRRC": "https://static1.squarespace.com/static/68eebc5c2000bf72493af0e4/t/690cba7a80a5d307ba1fbffc/1762441850823/SellSheetPRRC_2025-09-25.pdf",
 "NCRC": "https://static1.squarespace.com/static/68eebc5c2000bf72493af0e4/t/690cbb2b3fab4d0347007d18/1762442027883/SellSheetNCRC_2025-09-25.pdf",
 "DSA":  "https://static1.squarespace.com/static/68eebc5c2000bf72493af0e4/t/690cbecb7445892ad2078c3b/1762442955519/SellSheetDSA_2025-09-25.pdf",
 "Altoona": "https://static1.squarespace.com/static/68eebc5c2000bf72493af0e4/t/690cc767c51bb2184586fc0a/1762445159422/SellSheetAltoona_2025-09-25.pdf",
 "SRC":  "https://static1.squarespace.com/static/68eebc5c2000bf72493af0e4/t/695bf8526061c948f762ee68/1767635026119/SellSheetSRC_2026-01-05.pdf",
}
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]
ADDR_RE = re.compile(r"(\d+ [A-Za-z0-9 .'#&/-]+?,\s*(?:Suite|Ste|Unit|#)?[^,]*?,?\s*[A-Za-z .]+,\s*([A-Z]{2})\s+(\d{5}))")
PHONE_RE = re.compile(r"(\d{3}[.\-)\s]\s?\d{3}[.\-]\d{4})")
NAME_RE = re.compile(r"([A-Z][A-Za-z0-9 .,'&/-]{4,60}?)\s*\((?:RCRC|SCRC|WCRC|SVRC|PRRC|NCRC|DSA|SRC)\)")


def main():
    rows = []
    for code, url in PDFS.items():
        urllib.request.urlretrieve(url, "/tmp/r_%s.pdf" % code)
        txt = "\n".join((p.extract_text() or "") for p in PdfReader("/tmp/r_%s.pdf" % code).pages)
        txt1 = re.sub(r"\s+", " ", txt)
        m = ADDR_RE.search(txt1)
        nm = NAME_RE.search(txt1)
        name = nm.group(1).strip() if nm else code
        if not m:
            print("  %-8s NO ADDRESS FOUND in text" % code)
            continue
        full = m.group(1).strip()
        # split full into street / city / state / zip
        parts = [p.strip() for p in full.split(",")]
        zc_ = parts[-1].split()[-1]
        state = m.group(2)
        city = parts[-2] if len(parts) >= 2 else ""
        street = ", ".join(parts[:-2])
        # phone: nearest phone before the address
        ph = ""
        pm = list(PHONE_RE.finditer(txt1[:m.start()]))
        if pm:
            ph = re.sub(r"[.\s]", "-", pm[-1].group(1)).replace("--", "-")
        canon = sn.canonical_display(street)
        g = vg.google_status(canon + ", " + city + ", " + state + " " + zc_)
        r = {"domain": "rainier-research.com", "location_name": name, "address_street": canon,
             "address_city": city, "address_state": state, "address_zip": zc_, "phone": ph,
             "source_url": url, "snippet": "", "confidence": "high",
             "validation_status": "passed" if g == "exists" else "needs_review", "source": "manual"}
        r["zip_check"] = zc.flag(zc_, city, state)
        rows.append(r)
        print("  %-8s [%s] %s | %s, %s %s %s | %s" % (code, g, name, canon, city, state, zc_, ph))
    with open("data/rainier_parsed.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    print("staged %d -> data/rainier_parsed.csv" % len(rows))


if __name__ == "__main__":
    main()
