"""
Run pre-enrichment + hybrid pipeline on the bottom 25 companies
(lowest session count) from test_companies.json.

Usage: python3 run_bottom_tier.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from run_hybrid_pipeline import run_pipeline

with open("test_companies.json") as f:
    tc = json.load(f)

sorted_tc = sorted(tc, key=lambda x: x["total_sessions"], reverse=True)
bottom25  = sorted_tc[25:]

print(f"Running pipeline on {len(bottom25)} bottom-tier companies:")
for c in bottom25:
    print(f"  {c['domain']:<35} sessions={c['total_sessions']}")
print()


async def main():
    import aiohttp
    async with aiohttp.ClientSession() as session:
        results = await run_pipeline(bottom25, session)

    out = {
        "run_at": datetime.utcnow().isoformat(),
        "tier": "bottom_25",
        "company_count": len(results),
        "results": results,
    }
    os.makedirs("results", exist_ok=True)
    path = f"results/bottom_tier_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.json"
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nResults saved to {path}")
    return path


asyncio.run(main())
