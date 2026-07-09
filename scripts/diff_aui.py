import csv
DOC = ["Advanced Prostate Cancer Institute","Allen Ridge","Daytona Beach","Dunedin","Hope Regional Cancer Center",
"Inverness","IR Center of Daytona","IR Center of Oxford","IR Center of Pinellas","Largo","Lecanto","Leesburg",
"Naples","New Smyrna Beach","Ocala West","Orange City","Oxford Leesburg","Oxford Ocala","Palm Coast",
"Palm Harbor East Lake","Palm Harbor US 19","Panama City","Port Orange","Safety Harbor",
"SE Regional Prostate Cancer Treatment Center","St Augustine","St Petersburg 38th Avenue","St Petersburg Pasadena",
"Tallahassee","Tallahassee Crawfordville","Tampa Westchase","Trinity Duck Slough","Vero Beach",
"West Florida Radiation Therapy","Windsor Oaks"]
cur = {(r.get("location_name") or "").strip() for r in csv.DictReader(open("data/output_locations.csv"))
       if r["domain"].strip().lower() == "advancedurologyinstitute.com"}
print("doc:", len(DOC), "| current:", len(cur))
print("\nIN DOC, NOT IN CURRENT (missing):")
for n in DOC:
    if n not in cur: print("   " + n)
print("\nIN CURRENT, NOT IN DOC (extra/name-diff):")
for n in sorted(cur - set(DOC)): print("   " + repr(n))
