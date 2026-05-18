"""
Reparse existing research_location_results.json with a fixed parser.
No new Sonar queries — just re-classifies the raw text already collected.
"""

import json, re

EU_COUNTRIES = {
    "Germany", "France", "Switzerland", "Sweden", "Denmark", "Netherlands",
    "Belgium", "Spain", "Italy", "Austria", "Norway", "Finland", "Poland",
    "Czech Republic", "Hungary", "Ireland", "Portugal", "Greece", "Romania",
    "United Kingdom", "Russia", "Ukraine", "Croatia", "Slovakia", "Slovenia",
    "Estonia", "Latvia", "Lithuania", "Bulgaria", "Serbia",
}

# City → country (longest first to avoid partial matches)
CITY_COUNTRY = {
    "south san francisco": "United States",
    "research triangle": "United States",
    "new haven": "United States",
    "new york": "United States",
    "san francisco": "United States",
    "san diego": "United States",
    "los angeles": "United States",
    "tel aviv": "Israel",
    "cambridge": "United States",
    "boston": "United States",
    "seattle": "United States",
    "chicago": "United States",
    "houston": "United States",
    "raleigh": "United States",
    "durham": "United States",
    "princeton": "United States",
    "gaithersburg": "United States",
    "bethesda": "United States",
    "indianapolis": "United States",
    "cambridge uk": "United Kingdom",
    "london": "United Kingdom",
    "zurich": "Switzerland",
    "basel": "Switzerland",
    "zug": "Switzerland",
    "munich": "Germany",
    "berlin": "Germany",
    "frankfurt": "Germany",
    "heidelberg": "Germany",
    "hamburg": "Germany",
    "paris": "France",
    "lyon": "France",
    "strasbourg": "France",
    "tokyo": "Japan",
    "osaka": "Japan",
    "shanghai": "China",
    "beijing": "China",
    "shenzhen": "China",
    "guangzhou": "China",
    "suzhou": "China",
    "wuhan": "China",
    "nanjing": "China",
    "wuxi": "China",
    "bangalore": "India",
    "hyderabad": "India",
    "mumbai": "India",
    "pune": "India",
    "chennai": "India",
    "singapore": "Singapore",
    "toronto": "Canada",
    "montreal": "Canada",
    "mississauga": "Canada",
    "rehovot": "Israel",
    "jerusalem": "Israel",
    "amsterdam": "Netherlands",
    "leiden": "Netherlands",
    "stockholm": "Sweden",
    "gothenburg": "Sweden",
    "copenhagen": "Denmark",
    "oslo": "Norway",
    "helsinki": "Finland",
    "madrid": "Spain",
    "barcelona": "Spain",
    "milan": "Italy",
    "rome": "Italy",
    "vienna": "Austria",
    "warsaw": "Poland",
    "seoul": "South Korea",
    "incheon": "South Korea",
    "taipei": "Taiwan",
    "sydney": "Australia",
    "melbourne": "Australia",
    "foster city": "United States",
}

# Named countries to detect directly (word-boundary safe)
COUNTRY_NAMES = [
    "United States", "United Kingdom", "Germany", "France", "Switzerland",
    "China", "India", "Japan", "South Korea", "Israel", "Canada", "Australia",
    "Sweden", "Netherlands", "Denmark", "Belgium", "Spain", "Italy",
    "Singapore", "Taiwan", "Poland", "Austria", "Norway", "Finland",
    "Czech Republic", "Hungary", "Ireland", "Russia", "Brazil",
]

_CITY_RE = re.compile(
    r'\b(' + '|'.join(re.escape(c) for c in sorted(CITY_COUNTRY, key=len, reverse=True)) + r')\b',
    re.IGNORECASE
)
_STATE_RE = re.compile(
    r'\b(California|Massachusetts|New Jersey|Connecticut|Maryland|'
    r'North Carolina|Texas|Illinois|Washington|Pennsylvania|'
    r'Colorado|Georgia|Indiana|Ohio|Florida|Virginia|New York|'
    r'New Brunswick|Wisconsin|Michigan|Missouri|Tennessee|Minnesota)\b',
    re.IGNORECASE
)
_COUNTRY_RE = {
    c: re.compile(r'\b' + re.escape(c) + r'\b', re.IGNORECASE)
    for c in COUNTRY_NAMES
}
# Also catch "USA" and "U.S." with word boundaries
_USA_RE   = re.compile(r'\bUSA\b|\bU\.S\.A\.\b|\bU\.S\.\b')
_UK_RE    = re.compile(r'\bU\.K\.\b|\bUK\b')
_INDIA_RE = re.compile(r'\bIndia\b', re.IGNORECASE)


def parse_country(text: str) -> tuple[str, str]:
    """Returns (country, city). Fixed: uses word-boundary checks only."""
    if not text or text.strip().lower() in ("unknown.", "unknown", "n/a"):
        return "", ""

    # City match first (most specific)
    m = _CITY_RE.search(text)
    if m:
        city = m.group(1)
        return CITY_COUNTRY[city.lower()], city.title()

    # US state
    if _STATE_RE.search(text):
        return "United States", ""

    # USA abbreviations
    if _USA_RE.search(text):
        return "United States", ""

    # UK abbreviation
    if _UK_RE.search(text):
        return "United Kingdom", ""

    # India explicit
    if _INDIA_RE.search(text):
        return "India", ""

    # Full country names (word boundary)
    for country in COUNTRY_NAMES:
        if _COUNTRY_RE[country].search(text):
            return country, ""

    return "", ""


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


def main():
    with open("results/research_location_results.json") as f:
        data = json.load(f)

    fixed = 0
    for domain, v in data.items():
        raw = v.get("raw", "")
        old_country = v.get("country", "")
        old_tier    = v.get("geo_tier", "")

        new_country, new_city = parse_country(raw)
        new_tier = country_to_tier(new_country)

        if new_country != old_country or new_tier != old_tier:
            fixed += 1
            v["country"] = new_country
            v["city"]    = new_city
            v["geo_tier"] = new_tier

    from collections import Counter
    tier_counts = Counter(v["geo_tier"] for v in data.values())
    resolved = sum(1 for v in data.values() if v.get("country"))
    print(f"Fixed {fixed} classifications")
    print(f"Resolved: {resolved}/{len(data)}")
    for tier, count in sorted(tier_counts.items(), key=lambda x: -x[1]):
        print(f"  {tier:10}: {count}")

    with open("results/research_location_results.json", "w") as f:
        json.dump(data, f, indent=2)
    print("\nSaved → results/research_location_results.json")


if __name__ == "__main__":
    main()
