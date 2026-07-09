"""Parse the Headlands Research network locations from the doc (names + addresses + phones),
canonicalize, geocode-verify US ones, flag international. STAGES to data/headlands_parsed.csv only —
does NOT push to the sheet/canonical."""
import csv, re, importlib.util
sn = importlib.util.module_from_spec(importlib.util.spec_from_file_location("sn", "scripts/street_norm.py"))
importlib.util.spec_from_file_location("sn", "scripts/street_norm.py").loader.exec_module(sn)
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)

# (name, raw_street, city, state/province, zip/postal, phone, country)
RAW = [
 ("Artemis Institute for Clinical Research", "11748 Magnolia Ave, Suite D", "Riverside", "CA", "92503", "951-374-1190", "US"),
 ("Artemis Institute for Clinical Research", "3870 Murphy Canyon Rd, Suite 200", "San Diego", "CA", "92123", "858-278-3647", "US"),
 ("Clinical Research Atlanta", "175 Country Club Drive, Suite 200B", "Stockbridge", "GA", "30281", "1-770-507-6867", "US"),
 ("Clinvest Research", "909 E Republic Rd, Building D 200", "Springfield", "MO", "65807", "417-883-7889", "US"),
 ("Clinical Research Professionals", "17998 Chesterfield Airport Rd., Suite 100", "Chesterfield", "MO", "63005", "636-220-1200", "US"),
 ("Headlands Research - AMCR Institute", "625 West Citracado Parkway, Suite 112", "Escondido", "CA", "92025", "877-567-2627", "US"),
 ("Headlands Research - Brownsville", "302 Lorenaly Dr., Suite D", "Brownsville", "TX", "78526", "956-303-2776", "US"),
 ("Headlands Research - Detroit", "29355 Northwestern Highway, Suite 200", "Southfield", "MI", "48034", "248-243-1870", "US"),
 ("Headlands Research - Eastern Massachusetts", "45 Resnik Rd #205", "Plymouth", "MA", "02360", "508-746-5060", "US"),
 ("Headlands Research El Paso", "1600 Medical Center Street, Suite 307", "El Paso", "TX", "79902", "951-374-1190", "US"),
 ("Headlands Research - Orlando", "100 W. Gore Street", "Orlando", "FL", "32806", "407-729-3677", "US"),
 ("Headlands Research - Scottsdale", "7425 E. Shea Blvd, Suite 103-104", "Scottsdale", "AZ", "85260", "480-927-3800", "US"),
 ("JEM Research Institute", "130 John F Kennedy Dr, Suite 203", "Lake Worth", "FL", "33462", "1-561-968-2933", "US"),
 ("Okanagan Clinical Trials", "204-1353 Ellis St.", "Kelowna", "BC", "V1Y 1Z9", "1-250-862-8141", "CANADA"),
 ("Richmond Clinical Trials", "Unit 115, 13575 Commerce Parkway (Building 6)", "Richmond", "BC", "V6V 2L1", "604-373-4954", "CANADA"),
 ("Peninsula Research Associates", "550 Deep Valley Drive, Suite 317", "Rolling Hills Estates", "CA", "90274", "310-265-1623", "US"),
 ("Headlands PharmaSite", "1314 Bedford Ave #205", "Pikesville", "MD", "21208", "410-602-1440", "US"),
 ("Summit Research Network", "2701 NW Vaughn St, Suite 350", "Portland", "OR", "97210", "503-228-2273", "US"),
 ("Toronto Memory Program", "1 Valleybrook Drive, Suite 400", "Toronto", "Ontario", "M3B 2S7", "416-386-9761", "CANADA"),
 ("Trial Management Associates", "1221 Floral Parkway, Suite 101", "Wilmington", "NC", "28403", "910-338-1555", "US"),
 ("Trial Management Associates", "945 82nd Parkway", "Myrtle Beach", "SC", "29572", "843-994-7655", "US"),
 ("Headlands Research Twin Cities", "Maplewood Professional Building, 1655 Beam Ave, Suite 210", "Maplewood", "MN", "55109", "", "US"),
 ("CMR Center", "120 Domenech Ave", "San Juan", "PR", "00918", "787-679-3324", "US"),
]
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source"]


def main():
    out = []
    for name, street, city, state, z, phone, country in RAW:
        clean = re.sub(r"^\D*(?=\d)", "", street)        # strip leading building-name to first number
        canon = sn.canonical_display(clean)
        if country == "US":
            g = vg.google_status(canon + ", " + city + ", " + state + " " + z)
            vs = "passed" if g == "exists" else "needs_review"
        else:
            g = "intl"
            vs = "international"
        out.append({"domain": "headlandsresearch.com", "location_name": name, "address_street": canon,
                    "address_city": city, "address_state": state, "address_zip": z, "phone": phone,
                    "source_url": "https://headlandsresearch.com", "snippet": "", "confidence": "high",
                    "validation_status": vs, "source": "manual"})
        print("  [" + g.ljust(8) + "] " + name[:38].ljust(38) + " | " + canon + ", " + city + " " + state + " " + z)
    with open("data/headlands_parsed.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(out)
    us = sum(1 for r in out if r["validation_status"] != "international")
    print("\nparsed " + str(len(out)) + " (US/PR: " + str(us) + ", Canada: " + str(len(out) - us) + ") -> data/headlands_parsed.csv (NOT pushed)")


if __name__ == "__main__":
    main()
