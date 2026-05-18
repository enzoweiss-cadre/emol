"""Run pipeline on a single domain and append to an existing results file."""
import asyncio, json, os
from datetime import datetime
import aiohttp
from run_hybrid_pipeline import run_pipeline, API_KEY, SUPABASE_URL, SUPABASE_KEY

DOMAIN = "ibs.net.in"
TARGET_FILE = "results/hybrid_489_rerun_20260422_1511.json"

async def main():
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    async with aiohttp.ClientSession() as session:
        url = (f"{SUPABASE_URL}/rest/v1/emolecules_data_by_company"
               f"?select=domain,user_count,total_sessions,last_active&domain=eq.{DOMAIN}")
        async with session.get(url, headers=headers) as resp:
            rows = await resp.json() if resp.status == 200 else []

    company = rows[0] if rows else {"domain": DOMAIN, "user_count": None, "total_sessions": None, "last_active": None}
    print(f"Running pipeline on {DOMAIN}...")

    async with aiohttp.ClientSession() as session:
        results = await run_pipeline([company], session)

    if not results:
        print("No result returned.")
        return

    with open(TARGET_FILE) as f:
        data = json.load(f)

    data["results"].append(results[0])
    data["total_companies"] = len(data["results"])

    with open(TARGET_FILE, "w") as f:
        json.dump(data, f, indent=2)

    r = results[0]
    print(f"\nDone: {r['domain']} — {r.get('final_icp_score')}/100 ({r.get('qualification_status')}) [Stage {r.get('stage_reached')}]")
    print(f"Updated {TARGET_FILE} — now {data['total_companies']} companies")

if __name__ == "__main__":
    if not API_KEY:
        raise SystemExit("Missing OPENROUTER_API_KEY")
    asyncio.run(main())
