"""
Score the same 25 companies from retest_20260420_2104.json using the updated
pipeline (with sig_web_context + 8000-char site cap).
"""
import asyncio, json, os, re, sys
from datetime import datetime

import aiohttp

sys.path.insert(0, os.path.dirname(__file__))
from run_hybrid_pipeline import run_pipeline

RETEST_SOURCE = "results/retest_20260420_2104.json"

FIELDS = [
    "sf_is_public", "sf_funding_stage", "sf_employee_range",
    "sm_active_med_chem", "sm_cadd_capabilities", "sm_hit_to_lead", "sm_virtual_screening",
    "cq_highest_role", "cq_has_chemistry_team", "cq_team_size_estimate",
    "si_recent_funding", "si_funding_amount", "si_recent_chem_hires",
    "si_recent_publications", "si_pharma_partnerships", "si_patent_filings",
]

UNKNOWN_PATTERNS = [
    re.compile(r'^\s*$'),
    re.compile(r'^unknown\b'),
    re.compile(r'^n/?a$'),
    re.compile(r'^-+$'),
    re.compile(r'cannot be determined'),
    re.compile(r'cannot (confirm|verify)'),
    re.compile(r'could not (determine|find|confirm|verify)'),
    re.compile(r'insufficient (information|data|evidence)'),
    re.compile(r'^not (determined|available|verified)'),
    re.compile(r'unable to (determine|find|verify)'),
    re.compile(r'lookup failed'),
    re.compile(r'treat as unknown'),
    re.compile(r'not checked'),
]

APRIL1_BASELINES = {
    "sm_active_med_chem":   15, "sm_cadd_capabilities":  15,
    "sm_hit_to_lead":       15, "sm_virtual_screening":  15,
    "sf_funding_stage":     63, "sf_employee_range":     63,
    "sf_is_public":         63, "sf_recent_offering":    63,
    "cq_highest_role":      21, "cq_has_chemistry_team": 21,
    "cq_team_size_estimate":21,
    "si_recent_funding":    13, "si_funding_amount":     13,
    "si_recent_chem_hires": 13, "si_recent_publications":13,
    "si_pharma_partnerships":13, "si_patent_filings":    13,
}

CATEGORY_FIELDS = {
    "Small Molecule":        ["sm_active_med_chem","sm_cadd_capabilities","sm_hit_to_lead","sm_virtual_screening"],
    "Stage Fit":             ["sf_is_public","sf_funding_stage","sf_employee_range"],
    "Contact Quality":       ["cq_highest_role","cq_has_chemistry_team","cq_team_size_estimate"],
    "Strategic Intelligence":["si_recent_funding","si_funding_amount","si_recent_chem_hires",
                               "si_recent_publications","si_pharma_partnerships","si_patent_filings"],
}


def is_real_fill(value) -> bool:
    if value in (None, "", "null"):
        return False
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    v = str(value).strip().lower()
    return bool(v) and not any(p.search(v) for p in UNKNOWN_PATTERNS)


def print_fill_rates(results: list):
    total = len(results)
    print(f"\n{'='*65}")
    print(f"FILL RATES — POST-ENRICHMENT RUN ({total} companies)")
    print(f"{'='*65}")

    for cat, fields in CATEGORY_FIELDS.items():
        cat_filled = sum(1 for r in results for f in fields if is_real_fill(r.get(f)))
        cat_total  = total * len(fields)
        cat_pct    = round(cat_filled / cat_total * 100) if cat_total else 0
        # rough baseline for this category
        sample_field = fields[0]
        baseline = APRIL1_BASELINES.get(sample_field, "?")
        delta = f"+{cat_pct - baseline}%" if isinstance(baseline, int) else ""
        print(f"\n  {cat} (baseline ~{baseline}% → now {cat_pct}% {delta})")
        for field in fields:
            filled = sum(1 for r in results if is_real_fill(r.get(field)))
            pct = round(filled / total * 100)
            b = APRIL1_BASELINES.get(field)
            d = f"  (was {b}%)" if b is not None else ""
            print(f"    {field:<35} {filled:>3}/{total:<3} {pct:>4}%{d}")

    all_filled = sum(1 for r in results for f in FIELDS if is_real_fill(r.get(f)))
    all_total  = total * len(FIELDS)
    overall    = round(all_filled / all_total * 100) if all_total else 0
    print(f"\n  OVERALL: {overall}%  (April 1 baseline: 27.6%)")
    print("="*65)


async def main():
    with open(RETEST_SOURCE) as f:
        raw = json.load(f)

    companies = [
        {"domain": r["domain"],
         "user_count": r.get("source_user_count", 1),
         "total_sessions": r.get("source_total_sessions", 1)}
        for r in raw["results"]
        if r.get("domain")
    ]
    print(f"\nScoring {len(companies)} companies from {RETEST_SOURCE}")
    print(f"Domains: {[c['domain'] for c in companies]}\n")

    async with aiohttp.ClientSession() as session:
        results = await run_pipeline(companies, session)

    print_fill_rates(results)

    out = {
        "run_at":        datetime.utcnow().isoformat(),
        "company_count": len(results),
        "source":        RETEST_SOURCE,
        "results":       results,
    }
    path = f"results/retest_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.json"
    os.makedirs("results", exist_ok=True)
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved to {path}")


asyncio.run(main())
