"""
Compute per-domain login activity broken into time windows:
  - Last 30 days   (from last data point: 2026-02-27 to 2026-03-27)
  - Last 6 months  (2025-09-27 to 2026-03-27)
  - Last 12 months (2025-03-27 to 2026-03-27)

Source: emolecules_data_by_email.qdatetime = last login date per user.
Metric: count of distinct users active in each window (based on last login).

Outputs: results/usage_windows.json  — domain → {users_30d, users_6mo, users_12mo}
"""

import json, urllib.request, urllib.parse
from datetime import datetime, timezone
from collections import defaultdict

URL = "https://vvqwhfzuuvgpzyjzjnoa.supabase.co"
KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZ2cXdoZnp1"
    "dXZncHp5anpqbm9hIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NDkwMjcxMCwiZXhwIjoyMDkwNDc4NzEwfQ"
    ".qU95gMA0xGyIcLDNwms6JU3uGW7X1MPeAFqATXKCdqQ"
)

# Last data point in the dataset
DATA_CUTOFF = datetime(2026, 3, 27, tzinfo=timezone.utc)
CUT_30D  = datetime(2026, 2, 25, tzinfo=timezone.utc)
CUT_6MO  = datetime(2025, 9, 27, tzinfo=timezone.utc)
CUT_12MO = datetime(2025, 3, 27, tzinfo=timezone.utc)


def get_all(path, params, page_size=1000):
    rows = []
    offset = 0
    while True:
        p = {**params, "limit": page_size, "offset": offset}
        qs = urllib.parse.urlencode(p)
        req = urllib.request.Request(
            f"{URL}/rest/v1/{path}?{qs}",
            headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            batch = json.loads(r.read())
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return rows


def main():
    # Load our 489 scored domains
    with open("results/hybrid_489_rerun_20260422_1511.json") as f:
        scored = json.load(f)["results"]
    our_domains = {r["domain"].strip() for r in scored}

    print("Fetching all email activity rows...")
    all_rows = get_all(
        "emolecules_data_by_email",
        {"select": "domain,qdatetime,session_count", "order": "domain"},
    )
    print(f"  {len(all_rows)} rows fetched")

    # Group by domain, filter to our 489
    domain_users: dict[str, list[datetime]] = defaultdict(list)
    for row in all_rows:
        d = (row.get("domain") or "").strip()
        if d not in our_domains:
            continue
        dt_str = row.get("qdatetime") or ""
        if not dt_str:
            continue
        try:
            dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
            domain_users[d].append(dt)
        except Exception:
            pass

    print(f"  Domains with activity in our 489: {len(domain_users)}")

    # Compute window counts
    output = {}
    for domain in our_domains:
        dates = domain_users.get(domain, [])
        output[domain] = {
            "users_30d":  sum(1 for dt in dates if dt >= CUT_30D),
            "users_6mo":  sum(1 for dt in dates if dt >= CUT_6MO),
            "users_12mo": sum(1 for dt in dates if dt >= CUT_12MO),
        }

    with open("results/usage_windows.json", "w") as f:
        json.dump(output, f, indent=2)

    # Summary
    has_30d  = sum(1 for v in output.values() if v["users_30d"] > 0)
    has_6mo  = sum(1 for v in output.values() if v["users_6mo"] > 0)
    has_12mo = sum(1 for v in output.values() if v["users_12mo"] > 0)
    print(f"\nUsage window coverage:")
    print(f"  Active in last 30 days:   {has_30d}/{len(our_domains)}")
    print(f"  Active in last 6 months:  {has_6mo}/{len(our_domains)}")
    print(f"  Active in last 12 months: {has_12mo}/{len(our_domains)}")
    print(f"\nSaved → results/usage_windows.json")


if __name__ == "__main__":
    main()
