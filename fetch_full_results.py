"""
Fetch all scored results from Supabase icp_hybrid_results and save locally.
"""
import json, urllib.request, urllib.parse
from datetime import datetime

SUPABASE_URL = "https://vvqwhfzuuvgpzyjzjnoa.supabase.co"
SUPABASE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ2cXdoZnp1"
    "dXZncHp5anpqbm9hIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NDkwMjcxMCwiZXhwIjoyMDkwNDc4NzEwfQ"
    ".qU95gMA0xGyIcLDNwms6JU3uGW7X1MPeAFqATXKCdqQ"
)

def fetch_all(table, select="*", order="total_sessions.desc"):
    rows = []
    page_size = 1000
    offset = 0
    while True:
        params = {"select": select, "limit": page_size, "offset": offset}
        if order:
            params["order"] = order
        qs = urllib.parse.urlencode(params)
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/{table}?{qs}",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            batch = json.loads(r.read())
        rows.extend(batch)
        print(f"  {table}: fetched {len(rows)}...")
        if len(batch) < page_size:
            break
        offset += page_size
    return rows

print("Fetching scored results...")
results = fetch_all("icp_hybrid_results", order="final_icp_score.desc")
print(f"  Total: {len(results)}")

print("Fetching usage data...")
usage = fetch_all("emolecules_data_by_company", select="domain,user_count,total_sessions,last_active", order="total_sessions.desc")
usage_by_domain = {r["domain"]: r for r in usage}

# Merge usage into results
for r in results:
    u = usage_by_domain.get(r.get("domain", ""), {})
    r["source_user_count"]     = u.get("user_count")
    r["source_total_sessions"] = u.get("total_sessions")
    r["source_last_active"]    = u.get("last_active")

output = {
    "run_at": datetime.now().isoformat(),
    "total_companies": len(results),
    "results": results,
}

out_path = "results/full_run_may18.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2)

print(f"Saved → {out_path}")
