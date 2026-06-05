"""Regenerate the scores CSV with location and usage columns added."""
import json, csv, re
from collections import Counter

# ── Load data ──────────────────────────────────────────────────────────────────
with open("results/full_run_may18.json") as f:
    data = json.load(f)
results = data["results"]

with open("results/pre_enrichment_results.json") as f:
    PRE = {r["domain"]: r for r in json.load(f)["results"]}

with open("results/ip_location_results.json") as f:
    IP_GEO = json.load(f)

with open("results/usage_windows.json") as f:
    USAGE_WINDOWS = json.load(f)

with open("results/research_location_results.json") as f:
    RESEARCH_LOC = json.load(f)

# ── Location helpers ───────────────────────────────────────────────────────────
TLD_COUNTRY = {
    "cn":"China","de":"Germany","fr":"France","jp":"Japan",
    "co.uk":"United Kingdom","uk":"United Kingdom","in":"India",
    "ch":"Switzerland","kr":"South Korea","co.kr":"South Korea",
    "se":"Sweden","dk":"Denmark","nl":"Netherlands","be":"Belgium",
    "es":"Spain","it":"Italy","au":"Australia","ca":"Canada",
    "il":"Israel","sg":"Singapore","tw":"Taiwan","br":"Brazil",
    "ru":"Russia","at":"Austria","no":"Norway","fi":"Finland",
    "pl":"Poland","cz":"Czech Republic","hu":"Hungary",
    "ie":"Ireland","pt":"Portugal","gr":"Greece","ro":"Romania",
}
EU_COUNTRIES = {
    "Germany","France","Switzerland","Sweden","Denmark","Netherlands",
    "Belgium","Spain","Italy","Austria","Norway","Finland","Poland",
    "Czech Republic","Hungary","Ireland","Portugal","Greece","Romania",
    "United Kingdom","Russia","Ukraine","Croatia","Slovakia","Slovenia",
    "Estonia","Latvia","Lithuania","Bulgaria","Serbia",
}
CITY_COUNTRY = {
    "boston":"United States","cambridge":"United States",
    "san francisco":"United States","san diego":"United States",
    "new york":"United States","seattle":"United States",
    "chicago":"United States","los angeles":"United States",
    "houston":"United States","raleigh":"United States",
    "philadelphia":"United States","atlanta":"United States",
    "london":"United Kingdom","zurich":"Switzerland",
    "basel":"Switzerland","munich":"Germany","berlin":"Germany",
    "frankfurt":"Germany","hamburg":"Germany",
    "paris":"France","lyon":"France",
    "tokyo":"Japan","osaka":"Japan",
    "shanghai":"China","beijing":"China","shenzhen":"China",
    "guangzhou":"China","suzhou":"China","wuhan":"China",
    "bangalore":"India","hyderabad":"India","mumbai":"India",
    "pune":"India","chennai":"India",
    "singapore":"Singapore","toronto":"Canada",
    "tel aviv":"Israel","rehovot":"Israel",
    "amsterdam":"Netherlands","stockholm":"Sweden",
    "copenhagen":"Denmark","oslo":"Norway","helsinki":"Finland",
}
_CITY_RE = re.compile(r'\b(' + '|'.join(re.escape(c) for c in CITY_COUNTRY) + r')\b', re.IGNORECASE)
_STATE_RE = re.compile(r'\b(California|Massachusetts|New Jersey|Connecticut|Maryland|North Carolina|Texas|Illinois|Washington|Pennsylvania|Colorado|Georgia|Indiana|Ohio|Florida|Virginia)\b', re.IGNORECASE)

def infer_location(domain):
    p = PRE.get(domain, {})
    if p.get("sirene_found"):
        return "France", p.get("sirene_city", ""), "registry"
    if p.get("zefix_found"):
        return "Switzerland", "", "registry"
    if p.get("opendart_registry") == "registered":
        return "South Korea", "", "registry"
    for tld, country in TLD_COUNTRY.items():
        if domain.endswith("." + tld):
            return country, "", "tld"
    ip_data = IP_GEO.get(domain)
    if ip_data and ip_data.get("country"):
        return ip_data["country"], ip_data.get("city", ""), "ip_geo"
    text = " ".join(filter(None, [p.get("sig_web_context","") or "", p.get("site_summary_text","") or ""]))
    if text:
        m = _CITY_RE.search(text)
        if m:
            return CITY_COUNTRY[m.group(1).lower()], m.group(1).title(), "keyword"
        if _STATE_RE.search(text):
            return "United States", "", "keyword"
    return "", "", ""

def country_to_tier(country):
    if not country:
        return "Unknown"
    if country == "United States":
        return "US"
    if country in EU_COUNTRIES:
        return "EU"
    if country == "China":
        return "China"
    if country == "India":
        return "India"
    return "Other"

# ── Build rows ─────────────────────────────────────────────────────────────────
# Enforce qualification_status from final_icp_score
for r in results:
    score = r.get("final_icp_score") or 0
    if score >= 80:
        r["qualification_status"] = "HIGH FIT"
    elif score >= 60:
        r["qualification_status"] = "MEDIUM FIT"
    elif score >= 40:
        r["qualification_status"] = "LOW FIT"
    else:
        r["qualification_status"] = "NO FIT"

sorted_results = sorted(results, key=lambda r: r.get("final_icp_score") or 0, reverse=True)

NEW_FIELDS = ["geo_tier", "country", "city", "loc_source",
              "research_country", "research_city", "research_detail",
              "source_user_count", "source_total_sessions", "source_last_active",
              "users_30d", "users_6mo", "users_12mo"]

# Read existing CSV headers
with open("results/emolecules_scores_apr22.csv") as f:
    reader = csv.DictReader(f)
    existing_fields = reader.fieldnames

all_fields = existing_fields + NEW_FIELDS

out_path = "results/emolecules_scores_may18.csv"
with open(out_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
    writer.writeheader()
    for r in sorted_results:
        country, city, source = infer_location(r.get("domain", ""))
        r["geo_tier"]              = country_to_tier(country)
        r["country"]               = country
        r["city"]                  = city
        r["loc_source"]            = source
        r["source_user_count"]     = r.get("source_user_count", "")
        r["source_total_sessions"] = r.get("source_total_sessions", "")
        r["source_last_active"]    = (r.get("source_last_active") or "")[:10]
        rl = RESEARCH_LOC.get(r.get("domain", ""), {})
        r["research_country"] = rl.get("country", "")
        r["research_city"]    = rl.get("city", "")
        r["research_detail"]  = rl.get("raw", "")
        w = USAGE_WINDOWS.get(r.get("domain", ""), {})
        r["users_30d"]  = w.get("users_30d", "")
        r["users_6mo"]  = w.get("users_6mo", "")
        r["users_12mo"] = w.get("users_12mo", "")
        writer.writerow(r)

print(f"Saved → {out_path}  ({len(sorted_results)} rows)")
tier_counts = Counter(country_to_tier(infer_location(r.get("domain",""))[0]) for r in results)
for tier in ["US","EU","India","China","Other","Unknown"]:
    print(f"  {tier:10}: {tier_counts.get(tier,0)}")
