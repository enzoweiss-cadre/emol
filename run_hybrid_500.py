"""
Hybrid Pipeline — 500 company pilot run.
Pulls the top 500 companies by session count, runs the full hybrid pipeline.
Results write to the same icp_hybrid_results table.

Usage: python3 run_hybrid_500.py
"""

import asyncio
import sys
import json
import os
from datetime import datetime
from run_hybrid_pipeline import (
    fetch_all_companies,
    run_pipeline,
    API_KEY,
    SUPABASE_URL,
    SUPABASE_KEY,
)


async def main():
    print("\n" + "="*65)
    print("HYBRID PIPELINE — 500 COMPANY PILOT")
    print("="*65 + "\n")

    print("Loading company list...")
    async with __import__("aiohttp").ClientSession() as session:
        companies = await fetch_all_companies(session, limit=500)

    print(f"\nReady to run on {len(companies)} companies.")

    try:
        answer = input("Proceed? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return

    if answer not in ("y", "yes"):
        print("Cancelled.")
        return

    async with __import__("aiohttp").ClientSession() as session:
        results = await run_pipeline(companies, session)

    high = sum(1 for r in results if r.get("qualification_status") == "HIGH FIT")
    medium = sum(1 for r in results if r.get("qualification_status") == "MEDIUM FIT")
    low = sum(1 for r in results if r.get("qualification_status") == "LOW FIT")
    no_fit = sum(1 for r in results if r.get("qualification_status") == "NO FIT")
    stage_b = sum(1 for r in results if r.get("stage_reached") == "B")
    total_calls = sum(r.get("api_calls_total", 0) for r in results)

    print(f"\n{'='*65}")
    print("PILOT COMPLETE — SUMMARY")
    print(f"{'='*65}")
    print(f"  Total scored:    {len(results)}")
    print(f"  HIGH FIT:        {high}")
    print(f"  MEDIUM FIT:      {medium}")
    print(f"  LOW FIT:         {low}")
    print(f"  NO FIT:          {no_fit}")
    print(f"  Went to Stage 3: {stage_b} ({stage_b/max(len(results),1)*100:.1f}%)")
    print(f"  Total API calls: {total_calls}")

    os.makedirs("results", exist_ok=True)
    path = "results/hybrid_500_results.json"
    with open(path, "w") as f:
        json.dump({
            "run_at": datetime.now().isoformat(),
            "total_companies": len(results),
            "stage_b_escalated": stage_b,
            "total_api_calls": total_calls,
            "summary": {"high_fit": high, "medium_fit": medium, "low_fit": low, "no_fit": no_fit},
            "results": results
        }, f, indent=2)
    print(f"\nSaved to Supabase (icp_hybrid_results) + {path}")


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: Set OPENROUTER_API_KEY in .env")
        sys.exit(1)
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_KEY in .env")
        sys.exit(1)
    asyncio.run(main())
