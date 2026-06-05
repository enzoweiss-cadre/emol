"""
Re-run Stage B only for companies where Stage B previously failed
(Stage A was MEDIUM/HIGH FIT but final score came back as 0).
"""
import json, asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def main():
    import aiohttp
    from run_hybrid_pipeline import (
        score_company_stage_b,
        merge_results,
        upsert_hybrid_result,
        fetch_all_enrichment,
        SUPABASE_URL, SUPABASE_KEY,
        BATCH_SIZE,
    )

    print("Loading failed companies...")
    with open("results/full_run_may18.json") as f:
        all_results = json.load(f)["results"]

    failed = [
        r for r in all_results
        if r.get("stage_reached") == "B"
        and (r.get("final_icp_score") or 0) == 0
        and r.get("stage_a_status") in ("MEDIUM FIT", "HIGH FIT")
    ]
    print(f"Companies to rerun: {len(failed)}")

    async with aiohttp.ClientSession() as session:
        print("Loading pre-enrichment data...")
        enrichment_map = await fetch_all_enrichment(session)
        print(f"  {len(enrichment_map)} enrichment records loaded")

        batch_size = 20
        for i in range(0, len(failed), batch_size):
            batch = failed[i:i + batch_size]
            tasks = []
            for r in batch:
                domain = r["domain"]
                enrichment = enrichment_map.get(domain, {})
                tasks.append(score_company_stage_b(session, domain, enrichment))

            stage_b_results = await asyncio.gather(*tasks, return_exceptions=True)

            for r, stage_b in zip(batch, stage_b_results):
                domain = r["domain"]
                if isinstance(stage_b, Exception):
                    print(f"  ERROR {domain}: {stage_b}")
                    continue
                merged = merge_results(r, stage_b, escalation_reason=r.get("escalation_reason"))
                await upsert_hybrid_result(session, merged)
                score = merged.get("final_icp_score", 0)
                status = merged.get("qualification_status", "?")
                print(f"  [{i + batch.index(r) + 1}/{len(failed)}] {domain}: {score}/100 ({status})")

    print("\nDone — re-fetch results and regenerate exports.")

if __name__ == "__main__":
    asyncio.run(main())
