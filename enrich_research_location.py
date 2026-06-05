"""
Ask Perplexity Sonar where each company's chemistry research is located.
Runs on all 489 scored companies, cross-checks and fills gaps in IP geo data.

Outputs: results/research_location_results.json — domain → {country, city, confidence, raw}
"""

import json, asyncio, re, os
from datetime import datetime, timezone

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SEM = asyncio.Semaphore(8)

EU_COUNTRIES = {
    "Germany", "France", "Switzerland", "Sweden", "Denmark", "Netherlands",
    "Belgium", "Spain", "Italy", "Austria", "Norway", "Finland", "Poland",
    "Czech Republic", "Hungary", "Ireland", "Portugal", "Greece", "Romania",
    "United Kingdom", "Russia", "Ukraine", "Croatia", "Slovakia", "Slovenia",
    "Estonia", "Latvia", "Lithuania", "Bulgaria", "Serbia",
}

COUNTRY_ALIASES = {
    "usa": "United States", "u.s.": "United States", "u.s.a.": "United States",
    "us": "United States", "united states of america": "United States",
    "uk": "United Kingdom", "great britain": "United Kingdom",
    "south korea": "South Korea", "republic of korea": "South Korea",
    "people's republic of china": "China", "prc": "China",
}

CITY_COUNTRY = {
    "boston": "United States", "cambridge": "United States",
    "san francisco": "United States", "san diego": "United States",
    "new york": "United States", "seattle": "United States",
    "chicago": "United States", "los angeles": "United States",
    "south san francisco": "United States", "gaithersburg": "United States",
    "bethesda": "United States", "research triangle": "United States",
    "durham": "United States", "raleigh": "United States",
    "princeton": "United States", "new haven": "United States",
    "london": "United Kingdom", "cambridge uk": "United Kingdom",
    "zurich": "Switzerland", "basel": "Switzerland", "zug": "Switzerland",
    "munich": "Germany", "berlin": "Germany", "frankfurt": "Germany",
    "heidelberg": "Germany", "hamburg": "Germany",
    "paris": "France", "lyon": "France", "strasbourg": "France",
    "tokyo": "Japan", "osaka": "Japan",
    "shanghai": "China", "beijing": "China", "shenzhen": "China",
    "guangzhou": "China", "suzhou": "China", "wuhan": "China",
    "bangalore": "India", "hyderabad": "India", "mumbai": "India",
    "pune": "India", "chennai": "India",
    "singapore": "Singapore", "toronto": "Canada", "montreal": "Canada",
    "tel aviv": "Israel", "rehovot": "Israel", "jerusalem": "Israel",
    "amsterdam": "Netherlands", "leiden": "Netherlands",
    "stockholm": "Sweden", "gothenburg": "Sweden",
    "copenhagen": "Denmark", "oslo": "Norway", "helsinki": "Finland",
    "madrid": "Spain", "barcelona": "Spain",
    "milan": "Italy", "rome": "Italy",
    "vienna": "Austria", "warsaw": "Poland",
    "seoul": "South Korea", "incheon": "South Korea",
    "taipei": "Taiwan", "sydney": "Australia", "melbourne": "Australia",
}

_CITY_RE = re.compile(
    r'\b(' + '|'.join(re.escape(c) for c in sorted(CITY_COUNTRY, key=len, reverse=True)) + r')\b',
    re.IGNORECASE
)
_STATE_RE = re.compile(
    r'\b(California|Massachusetts|New Jersey|Connecticut|Maryland|'
    r'North Carolina|Texas|Illinois|Washington|Pennsylvania|'
    r'Colorado|Georgia|Indiana|Ohio|Florida|Virginia|New York)\b',
    re.IGNORECASE
)

def domain_to_name(domain: str) -> str:
    name = domain.split(".")[0]
    name = re.sub(r'[-_]', ' ', name)
    return name.title()

def parse_country(text: str) -> tuple[str, str]:
    """Returns (country, city) from Sonar answer text."""
    lower = text.lower()

    # Direct country mentions
    for alias, country in COUNTRY_ALIASES.items():
        if alias in lower:
            return country, ""

    # City → country
    m = _CITY_RE.search(text)
    if m:
        city = m.group(1)
        country = CITY_COUNTRY.get(city.lower(), "")
        return country, city.title()

    # US state mention
    if _STATE_RE.search(text):
        return "United States", ""

    # Country name directly in text
    for country in ["United States", "United Kingdom", "Germany", "France",
                    "Switzerland", "China", "India", "Japan", "South Korea",
                    "Israel", "Canada", "Australia", "Sweden", "Netherlands",
                    "Denmark", "Belgium", "Spain", "Italy", "Singapore"]:
        if country.lower() in lower:
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

async def query_research_location(domain: str, company_name: str, client) -> dict:
    prompt = (
        f"Where does {company_name} ({domain}) do its primary chemistry or drug discovery research? "
        f"Where are most of its chemists or medicinal chemists physically located? "
        f"Answer in one sentence with city and country only. "
        f"If unknown, say 'unknown'."
    )
    try:
        async with SEM:
            resp = await client.chat.completions.create(
                model="perplexity/sonar",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
            )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r'\[\d+\]', '', raw).replace("**", "").strip()
        country, city = parse_country(raw)
        return {
            "country":    country,
            "city":       city,
            "geo_tier":   country_to_tier(country),
            "raw":        raw,
            "source":     "sonar",
        }
    except Exception as e:
        return {"country": "", "city": "", "geo_tier": "Unknown", "raw": str(e), "source": "sonar_error"}


async def main():
    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )

    with open("results/full_run_may18.json") as f:
        scored = json.load(f)["results"]

    print(f"Running Sonar research-location queries for {len(scored)} companies...")

    tasks = []
    for r in scored:
        domain = r["domain"]
        name = domain_to_name(domain)
        tasks.append((domain, query_research_location(domain, name, client)))

    output = {}
    done = 0
    batch_size = 20
    domain_list = [(d, coro) for d, coro in tasks]

    for i in range(0, len(domain_list), batch_size):
        batch = domain_list[i:i + batch_size]
        results = await asyncio.gather(*[coro for _, coro in batch])
        for (domain, _), result in zip(batch, results):
            output[domain] = result
            done += 1
        print(f"  {done}/{len(scored)} done")

    # Summary
    from collections import Counter
    tier_counts = Counter(v["geo_tier"] for v in output.values())
    resolved = sum(1 for v in output.values() if v["country"])
    print(f"\nSonar research location results ({resolved}/{len(scored)} resolved):")
    for tier, count in sorted(tier_counts.items(), key=lambda x: -x[1]):
        print(f"  {tier:10}: {count}")

    with open("results/research_location_results.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved → results/research_location_results.json")


if __name__ == "__main__":
    asyncio.run(main())
