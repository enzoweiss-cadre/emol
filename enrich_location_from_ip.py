"""
Geolocate company locations using actual user IP addresses from Supabase.
Uses ip-api.com free batch endpoint (no key, 45 req/min, 100 IPs/batch).

Outputs: results/ip_location_results.json  — domain → {country, city, geo_tier}
"""

import json
import time
import urllib.request
import urllib.parse
from collections import Counter, defaultdict

SUPABASE_URL = "https://vvqwhfzuuvgpzyjzjnoa.supabase.co"
SUPABASE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ2cXdoZnp1"
    "dXZncHp5anpqbm9hIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NDkwMjcxMCwiZXhwIjoyMDkwNDc4NzEwfQ"
    ".qU95gMA0xGyIcLDNwms6JU3uGW7X1MPeAFqATXKCdqQ"
)

EU_COUNTRIES = {
    "Germany", "France", "Switzerland", "Sweden", "Denmark", "Netherlands",
    "Belgium", "Spain", "Italy", "Austria", "Norway", "Finland", "Poland",
    "Czech Republic", "Hungary", "Ireland", "Portugal", "Greece", "Romania",
    "United Kingdom", "Russia", "Ukraine", "Croatia", "Slovakia", "Slovenia",
    "Estonia", "Latvia", "Lithuania", "Bulgaria", "Serbia",
}


def country_to_tier(country: str) -> str:
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


def supabase_get(path: str, params: dict) -> list:
    qs = urllib.parse.urlencode(params)
    url = f"{SUPABASE_URL}/rest/v1/{path}?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def batch_geolocate(ips: list[str]) -> dict[str, dict]:
    """Call ip-api.com batch endpoint. Returns ip → {country, city, regionName}."""
    if not ips:
        return {}
    payload = json.dumps([
        {"query": ip, "fields": "query,country,city,regionName,status"}
        for ip in ips
    ]).encode()
    req = urllib.request.Request(
        "http://ip-api.com/batch?fields=query,country,city,regionName,status",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            results = json.loads(resp.read())
        return {
            r["query"]: {
                "country": r.get("country", ""),
                "city": r.get("city", ""),
                "region": r.get("regionName", ""),
            }
            for r in results
            if r.get("status") == "success"
        }
    except Exception as e:
        print(f"  ip-api error: {e}")
        return {}


def main():
    # Load the 489 scored domains
    with open("results/hybrid_489_rerun_20260422_1511.json") as f:
        scored = json.load(f)["results"]
    all_domains = {r["domain"] for r in scored}

    # Load existing pre-enrichment location signals
    with open("results/pre_enrichment_results.json") as f:
        pre_raw = json.load(f)["results"]
    PRE = {r["domain"]: r for r in pre_raw}

    TLD_COUNTRY = {
        "cn": "China", "de": "Germany", "fr": "France", "jp": "Japan",
        "co.uk": "United Kingdom", "uk": "United Kingdom", "in": "India",
        "ch": "Switzerland", "kr": "South Korea", "co.kr": "South Korea",
        "se": "Sweden", "dk": "Denmark", "nl": "Netherlands", "be": "Belgium",
        "es": "Spain", "it": "Italy", "au": "Australia", "ca": "Canada",
        "il": "Israel", "sg": "Singapore", "tw": "Taiwan", "br": "Brazil",
        "ru": "Russia", "at": "Austria", "no": "Norway", "fi": "Finland",
        "pl": "Poland", "cz": "Czech Republic", "hu": "Hungary",
        "ie": "Ireland", "pt": "Portugal", "gr": "Greece", "ro": "Romania",
    }

    def has_existing_location(domain):
        p = PRE.get(domain, {})
        if p.get("sirene_found") or p.get("zefix_found") or p.get("opendart_registry") == "registered":
            return True
        return any(domain.endswith("." + t) for t in TLD_COUNTRY)

    # Only need IP geo for domains without a confident location already
    needs_geo = [d for d in all_domains if not has_existing_location(d)]
    print(f"Domains needing IP geolocation: {len(needs_geo)}")

    # Fetch IPs from Supabase emolecules_data_by_email, batched by domain
    print("Fetching IPs from Supabase...")
    domain_ips: dict[str, list[str]] = defaultdict(list)

    # Fetch all email rows for our domains in chunks
    # Use 'in' filter — Supabase PostgREST supports domain=in.(a,b,c)
    chunk_size = 50
    for i in range(0, len(needs_geo), chunk_size):
        chunk = needs_geo[i:i + chunk_size]
        domain_list = ",".join(f'"{d.strip()}"' for d in chunk)
        try:
            rows = supabase_get(
                "emolecules_data_by_email",
                {
                    "select": "domain,ipaddress,session_count",
                    "domain": f"in.({domain_list})",
                    "limit": 1000,
                }
            )
            for row in rows:
                d = (row.get("domain") or "").strip()
                ip = (row.get("ipaddress") or "").strip()
                if d and ip and d in all_domains:
                    domain_ips[d].append((ip, row.get("session_count") or 1))
        except Exception as e:
            print(f"  Supabase chunk error: {e}")
        time.sleep(0.1)

    print(f"Got IP data for {len(domain_ips)} domains")

    # For each domain, pick the IP with the most sessions
    domain_best_ip: dict[str, str] = {}
    for domain, ip_sessions in domain_ips.items():
        # Weight by session count — most active user's IP
        counter: Counter = Counter()
        for ip, sessions in ip_sessions:
            counter[ip] += sessions
        domain_best_ip[domain] = counter.most_common(1)[0][0]

    # Geolocate in batches of 100
    all_ips = list(set(domain_best_ip.values()))
    print(f"Geolocating {len(all_ips)} unique IPs...")
    ip_geo: dict[str, dict] = {}

    for i in range(0, len(all_ips), 100):
        batch = all_ips[i:i + 100]
        result = batch_geolocate(batch)
        ip_geo.update(result)
        print(f"  {min(i+100, len(all_ips))}/{len(all_ips)} IPs geolocated")
        if i + 100 < len(all_ips):
            time.sleep(1.5)  # stay under 45 req/min

    # Build domain → location mapping
    output: dict[str, dict] = {}
    for domain, ip in domain_best_ip.items():
        geo = ip_geo.get(ip, {})
        country = geo.get("country", "")
        city = geo.get("city", "")
        output[domain] = {
            "country":  country,
            "city":     city,
            "geo_tier": country_to_tier(country),
            "source":   "ip_geolocation",
            "ip_used":  ip,
        }

    # Summary
    from collections import Counter as C
    tier_counts = C(v["geo_tier"] for v in output.values())
    print("\nIP geolocation results:")
    for tier, count in sorted(tier_counts.items(), key=lambda x: -x[1]):
        print(f"  {tier:10}: {count}")
    print(f"  No IP data: {len(needs_geo) - len(output)}")

    with open("results/ip_location_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved → results/ip_location_results.json")


if __name__ == "__main__":
    main()
