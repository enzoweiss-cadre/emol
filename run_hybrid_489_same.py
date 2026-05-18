"""
Hybrid Pipeline — re-run on the EXACT 489 domains from results/hybrid_pipeline_results.json
(the April 1 baseline). Apples-to-apples comparison for enrichment + new APIs.

Usage: python3 run_hybrid_489_same.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime

import aiohttp

from run_hybrid_pipeline import (
    run_pipeline,
    API_KEY,
    SUPABASE_URL,
    SUPABASE_KEY,
)

PRIOR_RUN_PATH = "results/hybrid_pipeline_results.json"


async def fetch_metadata_for_domains(session: aiohttp.ClientSession, domains: list) -> list:
    """Fetch user_count/total_sessions/last_active for an explicit domain list."""
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    out_by_domain = {}
    chunk = 100
    for i in range(0, len(domains), chunk):
        slice_ = domains[i:i + chunk]
        in_clause = ",".join(f'"{d}"' for d in slice_)
        url = (
            f"{SUPABASE_URL}/rest/v1/emolecules_data_by_company"
            f"?select=domain,user_count,total_sessions,last_active"
            f"&domain=in.({in_clause})"
        )
        async with session.get(url, headers=headers) as resp:
            rows = await resp.json() if resp.status == 200 else []
        for r in rows:
            out_by_domain[r["domain"]] = r

    ordered = []
    for d in domains:
        row = out_by_domain.get(d)
        if row:
            ordered.append(row)
        else:
            ordered.append({"domain": d, "user_count": None, "total_sessions": None, "last_active": None})
    return ordered


async def main():
    print("\n" + "=" * 65)
    print("HYBRID PIPELINE — RE-RUN ON SAME 489 DOMAINS (apples-to-apples)")
    print("=" * 65 + "\n")

    with open(PRIOR_RUN_PATH) as f:
        prior = json.load(f)
    domains = [r["domain"] for r in prior["results"]]
    print(f"Loaded {len(domains)} domains from {PRIOR_RUN_PATH}")

    async with aiohttp.ClientSession() as session:
        companies = await fetch_metadata_for_domains(session, domains)

    hit = sum(1 for c in companies if c["total_sessions"] is not None)
    print(f"Metadata found for {hit}/{len(companies)} (missing will pass through with None)")

    if "--yes" not in sys.argv:
        try:
            answer = input("Proceed? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("Aborted.")
            return
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return

    async with aiohttp.ClientSession() as session:
        results = await run_pipeline(companies, session)

    high = sum(1 for r in results if r.get("qualification_status") == "HIGH FIT")
    medium = sum(1 for r in results if r.get("qualification_status") == "MEDIUM FIT")
    low = sum(1 for r in results if r.get("qualification_status") == "LOW FIT")
    no_fit = sum(1 for r in results if r.get("qualification_status") == "NO FIT")
    stage_b = sum(1 for r in results if r.get("stage_reached") == "B")
    total_calls = sum(r.get("api_calls_total", 0) for r in results)

    print(f"\n{'='*65}")
    print("RE-RUN COMPLETE — SUMMARY")
    print(f"{'='*65}")
    print(f"  Total scored:    {len(results)}")
    print(f"  HIGH FIT:        {high}")
    print(f"  MEDIUM FIT:      {medium}")
    print(f"  LOW FIT:         {low}")
    print(f"  NO FIT:          {no_fit}")
    print(f"  Went to Stage 3: {stage_b} ({stage_b/max(len(results),1)*100:.1f}%)")
    print(f"  Total API calls: {total_calls}")

    os.makedirs("results", exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = f"results/hybrid_489_rerun_{stamp}.json"
    with open(path, "w") as f:
        json.dump({
            "run_at": datetime.now().isoformat(),
            "baseline_source": PRIOR_RUN_PATH,
            "total_companies": len(results),
            "stage_b_escalated": stage_b,
            "total_api_calls": total_calls,
            "summary": {"high_fit": high, "medium_fit": medium, "low_fit": low, "no_fit": no_fit},
            "results": results,
        }, f, indent=2)
    print(f"\nSaved to Supabase (icp_hybrid_results) + {path}")


if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit("Missing OPENROUTER_API_KEY in .env")
    asyncio.run(main())
