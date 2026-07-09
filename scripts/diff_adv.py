import csv
# all 152 location names from the doc
DOC = ["Abingdon","Afton","Albany","Alexandria","Alpena","Annapolis","Ashburn - Maragh","Aurora","Beaver",
"Bloomfield Hills","Boca Raton","Bokeelia","Boynton Beach","Brandon","Cape Coral","Cape Coral - Florida Skin Center",
"Cara Mia Medical Day Spa","Casselberry","Castle Rock","Cheboygan","Clearwater","Clermont","Cockeysville","Columbia",
"Dacula","DeBary","Deland - N Woodland Blvd","Deland - W Plymouth Ave","Denver - Central Park","Denver - Harvard Ave",
"Denver - Ogden St","Denver - Poplar St","Denver - S Madison St","Dubois","East Greenwich","Englewood","Fairfax",
"Flourtown","Fort Collins - Centre Ave","Fort Collins - Poudre River Dr","Fort Collins - Timberline","Fort Mill",
"Fort Mill - Arden","Fort Morgan","Fort Myers - College Pkwy","Fort Myers - Metropolis \"A\"","Fort Myers - Metropolis \"B\"",
"Fort Washington - MD","Fort Washington - PA","Gaylord","Gilbert","Greeley","Greenville - Greenville Dermatology",
"Greenville - Halton Village","Greenville - SkinTrust","Hazle Township","Heathrow","Henderson","Jackson - Veronica Ln",
"Jacksonville - Chimney Lakes","Jacksonville - Philips Hwy","Jacksonville - San Marco","Julington Creek - St. Johns",
"Kalamazoo - Portage","Kalkaska","La Plata","Lake Faith","Lakeland","Lansing","Largo","Las Vegas - Summerlin",
"Lawrenceville","Lehigh Acres","Livonia","Loveland","Macomb","Marbleton","Mason","Montgomery","National Harbor",
"New Port Richey","New Smyrna Beach","North Gilbert","North Scottsdale - E Bell Rd","North Wales","Ocala","Olney",
"Orange Park","Orlando - Baldwin Park","Orlando - Hunters Creek","Orlando - Lake Nona","Orlando - Metrowest",
"Orlando - South Downtown","Orlando - Waterford Lakes","Ormond Beach","Oviedo","Palm Coast - Office Park Dr",
"Palm Coast - Pine Cone Dr","Palm Harbor","Parker","Pembroke Pines","Petoskey","Phoenix","Pikesville","Pinedale",
"Pittsburgh","Plant City","Ponte Vedra","Port Charlotte","Port Orange","Port St. Lucie","Punta Gorda - Coastal",
"Punta Gorda - Florida Skin Center","Riverview","Rockville - Greater Washington","Rockville - Maragh",
"Scottsdale - N Miller Rd","Sebastian","Shelby Township","Spartanburg","Spring Hill - Commercial Way",
"Spring Hill - Spring Hill Dr","St Pete - Carillon","St. Augustine","St. Cloud","St. Petersburg - 38th Ave N",
"Sterling","Tampa - University Point Pl","Tampa - W Deleon St","Tavares","The Villages - Colony",
"The Villages - Spanish Springs","The Villages - The Center for Advanced Healthcare","Towson","Traverse City",
"Venice","Vero Beach - Terrace","Warren","Warrenton - Maragh","Wesley Chapel","West Columbia","West Mifflin",
"Westminster - Federal Blvd (Ste 205)","Westminster - Federal Blvd (Ste 210)","Weston","Wheat Ridge",
"White Oak - McKeesport","Windermere - Winter Garden","Winter Park","Winter Park Aesthetic Center","Wyandotte","Zephyrhills"]

cur = {(r.get("location_name") or "").strip() for r in csv.DictReader(open("data/output_locations.csv"))
       if r["domain"].strip().lower() == "advancedderm.com"}
docset = set(DOC)
print("doc names:", len(DOC), "| current names:", len(cur))
print("\nIN DOC, NOT IN CURRENT (missing -> to add):")
for n in DOC:
    if n not in cur:
        print("   " + n)
print("\nIN CURRENT, NOT IN DOC (extra):")
for n in sorted(cur - docset):
    print("   " + repr(n))
