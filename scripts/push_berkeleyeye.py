"""Parse berkeleyeye.com's 29 locations from the Manual Locations doc and add them into
sam_new_targets_locations (replace any existing berkeleyeye rows). All TX. Geocode-verify + zip_check.
Streets verbatim. Updates the CSV + the sam_new_targets_locations sheet tab."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "berkeleyeye.com"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]
B = "https://www.berkeleyeye.com/locations/"
# (name, street, city, zip, phone, source_url)
LOCS = [
    ("Atascocita", "18545 W Lake Houston Pkwy", "Atascocita", "77346", "(281) 812-4000", B+"atascocita/"),
    ("Bay City", "6500 7th St Suite 200", "Bay City", "77414", "(979) 318-3204", B+"bay-city/"),
    ("Baytown", "1025 Birdsong Drive, Suite A", "Baytown", "77521", "(281) 422-2020", B+"baytown"),
    ("Brenham", "605 Medical Courts #203", "Brenham", "77833", "(979) 830-1444", B+"brenham/"),
    ("Caplan Surgery Center", "3100 Weslayan St #400", "Houston", "77027", "(713) 526-1600", "https://www.berkeleyeye.com/cataract-surgery/caplan-surgery-center/"),
    ("Champions", "5419 Farm to Market 1960 Rd W suite c", "Houston", "77069", "(281) 894-2020", B+"champions/"),
    ("Clear Lake", "18040 Saturn Ln", "Houston", "77058", "(281) 333-8600", B+"clear-lake/"),
    ("Cleveland", "901 E Houston St", "Cleveland", "77327", "(281) 659-2020", B+"cleveland/"),
    ("Corpus Christi", "5350 S Staples St #318", "Corpus Christi", "78411", "(361) 992-1060", B+"corpus-christi/"),
    ("Dayton", "306 N Main St suite a", "Dayton", "77535", "(936) 258-0020", B+"dayton/"),
    ("East Freeway", "12140 East Fwy", "Houston", "77029", "(832) 995-2613", B+"east-freeway/"),
    ("El Campo", "2012 West Loop", "El Campo", "77437", "(979) 543-6821", B+"el-campo/"),
    ("Fulshear", "28840 FM 1093 #130", "Fulshear", "77441", "(346) 595-2020", B+"fulshear"),
    ("Grand Oaks", "3929 Woodson's Reserve Pkwy", "Spring", "77386", "(346) 423-6443", B+"grand-oaks/"),
    ("Grand Oaks Surgery Center", "3929 Woodson's Reserve Pkwy", "Spring", "77386", "(346) 423-6443", B+"grand-oaks-surgery-center"),
    ("Greenway Plaza", "3100 Weslayan St Suite 400", "Houston", "77027", "(713) 526-1600", B+"weslayan/"),
    ("Harrisburg", "7438 Harrisburg Blvd", "Houston", "77011", "(713) 928-3375", B+"harrisburg/"),
    ("Huntsville", "2 Financial Plaza #801", "Huntsville", "77340", "(936) 295-2020", B+"huntsville/"),
    ("Katy", "21502 Merchants Way", "Katy", "77449", "(281) 579-6777", B+"katy/"),
    ("Katy Area Surgical Center", "21502 Merchants Way", "Katy", "77449", "(281) 579-6777", B+"katy-area-surgical-center/"),
    ("Kingwood", "22741 Professional Dr", "Kingwood", "77339", "(281) 319-4334", B+"kingwood/"),
    ("Lake Jackson", "117 Circle Way St", "Lake Jackson", "77566", "(979) 297-4042", B+"lake-jackson/"),
    ("Memorial", "8731 Katy Freeway, #300", "Houston", "77024", "(713) 827-8311", B+"memorial/"),
    ("Pearland", "1535 Cullen Blvd Suite 200", "Pearland", "77581", "(713) 436-1551", B+"pearland/"),
    ("Retina West", "1315 W Grand Pkwy S, Ste. 106", "Katy", "77494", "(346) 585-2020", B+"retina-west"),
    ("Sugar Land", "1435 Hwy 6 Suite 202", "Sugar Land", "77478", "(281) 478-9889", B+"sugar-land/"),
    ("The Woodlands", "143 Vision Park Blvd.", "The Woodlands", "77384", "(281) 363-3443", B+"woodlands/"),
    ("Tomball", "14030 Farm to Market 2920 ste e", "Tomball", "77377", "(281) 351-0744", B+"tomball/"),
    ("Wharton", "1602 N Fulton St", "Wharton", "77488", "(979) 532-0805", B+"wharton/"),
]


def main():
    new = []
    for name, street, city, zipc, phone, su in LOCS:
        g = vg.google_status(f"{street}, {city}, TX {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        new.append({"domain": DOMAIN, "location_name": name, "address_street": street, "address_city": city,
                    "address_state": "TX", "address_zip": zipc, "phone": phone, "source_url": su, "snippet": "",
                    "confidence": "high", "validation_status": vs, "source": "manual",
                    "zip_check": zc.flag(zipc, city, "TX")})
    nr = sum(1 for r in new if r["validation_status"] != "passed")
    flg = sum(1 for r in new if r["zip_check"])
    print(f"berkeleyeye: {len(new)} rows | needs_review: {nr} | zip_check flags: {flg}")

    # merge into sam_new_targets_locations (replace existing berkeleyeye rows)
    rows = [r for r in csv.DictReader(open("data/sam_new_targets_locations.csv")) if r["domain"].strip().lower() != DOMAIN]
    removed = sum(1 for _ in csv.DictReader(open("data/sam_new_targets_locations.csv")) if _["domain"].strip().lower() == DOMAIN)
    rows += new
    with open("data/sam_new_targets_locations.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET).worksheet("sam_new_targets_locations")
    body = [[r.get(c, "") for c in FIELDS] for r in rows]
    ws.clear(); ws.resize(rows=len(body) + 1, cols=len(FIELDS)); ws.update([FIELDS] + body, value_input_option="RAW")
    print(f"removed {removed} old berkeleyeye rows | sam_new_targets_locations now {len(rows)} rows")


if __name__ == "__main__":
    main()
