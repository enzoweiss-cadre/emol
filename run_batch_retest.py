"""
Re-run pipeline on a batch of domains from the April 1 results to measure
actual fill rates after pre-enrichment + prompt changes.

Usage: python3 run_batch_retest.py [--limit N]
"""

import asyncio
import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from run_hybrid_pipeline import run_pipeline

FIELDS = [
    "sf_is_public", "si_recent_publications", "si_recent_funding",
    "sm_active_med_chem", "sm_cadd_capabilities", "sm_hit_to_lead",
    "sm_virtual_screening", "si_patent_filings", "sf_funding_stage",
    "sf_employee_range",
]

PREV_RESULTS_PATH = "results/hybrid_pipeline_results.json"


def load_batch(limit: int) -> list:
    with open(PREV_RESULTS_PATH) as f:
        raw = json.load(f)
    companies = [
        {"domain": r["domain"], "user_count": r.get("source_user_count", 1),
         "total_sessions": r.get("source_total_sessions", 1)}
        for r in raw["results"][:limit]
    ]
    return companies


import re as _re

# A field is FILLED when the agent returned evidence — in either direction.
# "No med chem programs found on website" = filled (confirmed negative).
# "Unknown" / "could not determine" / "insufficient data" = NOT filled.
_UNKNOWN_PATTERNS = [
    _re.compile(r'^\s*$'),
    _re.compile(r'^unknown\b'),
    _re.compile(r'^n/?a$'),
    _re.compile(r'^-+$'),
    _re.compile(r'cannot be determined'),
    _re.compile(r'cannot (confirm|verify)'),
    _re.compile(r'could not (determine|find|confirm|verify)'),
    _re.compile(r'insufficient (information|data|evidence)'),
    _re.compile(r'^not (determined|available|verified)'),
    _re.compile(r'unable to (determine|find|verify)'),
    _re.compile(r'lookup failed'),
    _re.compile(r'treat as unknown'),
    _re.compile(r'not checked'),
]

def is_real_fill(value) -> bool:
    if value in (None, "", "null"):
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    v = str(value).strip().lower()
    if not v:
        return False
    return not any(p.search(v) for p in _UNKNOWN_PATTERNS)


def print_fill_rates(results: list, label: str):
    total = len(results)
    print(f"\n{'='*55}")
    print(f"FILL RATES — {label} ({total} companies)")
    print(f"{'='*55}")
    print(f"{'Field':<30} {'Filled':>8} {'%':>6}")
    print("-"*46)
    for field in FIELDS:
        filled = sum(1 for r in results if is_real_fill(r.get(field)))
        pct = round(filled / total * 100)
        print(f"{field:<30} {filled:>5}/{total:<3} {pct:>5}%")


async def main():
    limit = 25
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--limit" and i + 1 < len(sys.argv) - 1:
            limit = int(sys.argv[i + 2])

    print(f"\nLoading {limit} companies from April 1 run...")
    companies = load_batch(limit)
    print(f"Domains: {[c['domain'] for c in companies]}\n")

    print(f"Running pipeline on {len(companies)} companies...\n")
    import aiohttp
    async with aiohttp.ClientSession() as session:
        results = await run_pipeline(companies, session)

    print_fill_rates(results, "NEW RUN")

    # Save results
    out = {
        "run_at": datetime.utcnow().isoformat(),
        "company_count": len(results),
        "results": results,
    }
    os.makedirs("results", exist_ok=True)
    path = f"results/retest_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to {path}")


asyncio.run(main())
