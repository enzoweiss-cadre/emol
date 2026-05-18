"""
Test B — Categorical Agents
Multiple Perplexity Sonar calls per company — one agent per ICP scoring category,
each focused ONLY on finding signals for that specific category.
Results written to Supabase table: icp_test_b_categorical

Usage: python3 test_b_categorical.py
  Requires .env with OPENROUTER_API_KEY, SUPABASE_URL, SUPABASE_KEY
"""

import json
import os
import time
import asyncio
import aiohttp
from datetime import datetime, timezone

# Load .env file
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    if val and not os.environ.get(key):
                        os.environ[key] = val

load_env()

API_KEY = os.environ.get("OPENROUTER_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
MODEL = "perplexity/sonar-pro"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
BATCH_SIZE = 3  # fewer concurrent companies since each spawns 5 calls
DELAY_BETWEEN_BATCHES = 3

# ─────────────────────────────────────────────────────────────
# Category-specific agent prompts
# Each agent looks for ONE thing only — deep and focused
# ─────────────────────────────────────────────────────────────

CATEGORY_PROMPTS = {
    "small_molecule": {
        "system": """You are a drug discovery research analyst. Your ONLY task is to determine if a company is involved in small molecule drug discovery.

Search for these specific signals:
- Active medicinal chemistry programs
- Computational chemistry (CADD) capabilities
- Hit-to-lead or lead optimization activities
- Virtual screening programs
- SMILES/compound libraries
- SAR (structure-activity relationship) studies
- Small molecule pipeline assets

Also check for DISQUALIFIERS — if the company is ONLY focused on:
- Biologics (antibodies, gene therapy, cell therapy, mRNA)
- Medical devices
- Diagnostics only
- Manufacturing only (no discovery)
- Pure software/platform without wet lab
- Clinical-trials-only CRO
- Academic without industry drug discovery partnerships

Return valid JSON:
{
  "score": <0-30>,
  "has_small_molecule_focus": <true|false>,
  "sm_active_med_chem": "<evidence string if found, e.g. '3 active programs targeting GPCRs and kinase inhibitors' — if not found, write 'No active med chem programs found'>",
  "sm_cadd_capabilities": "<evidence string if found, e.g. 'In-house CADD team using Schrodinger, 5 comp chem staff' — if not found, write 'No CADD capabilities found'>",
  "sm_hit_to_lead": "<evidence string if found, e.g. 'Lead optimization of compound series XYZ per ACS presentation' — if not found, write 'No hit-to-lead activity found'>",
  "sm_virtual_screening": "<evidence string if found, e.g. 'Virtual screening of 10M compound library per Nature paper' — if not found, write 'No virtual screening activity found'>",
  "sm_scoring_basis": "<which criterion determined the score: active_med_chem | cadd | hit_to_lead | virtual_screening | none>",
  "auto_disqualified": <true|false>,
  "disqualify_reason": "<reason if auto_disqualified is true — if false, write 'Not disqualified'>",
  "dq_is_biologics_only": "<evidence if triggered, e.g. 'Pipeline is 100% monoclonal antibodies' — if not triggered, write 'Not biologics-only'>",
  "dq_is_manufacturing_only": "<evidence if triggered — if not triggered, write 'Not manufacturing-only'>",
  "dq_is_medical_device": "<evidence if triggered — if not triggered, write 'Not a medical device company'>",
  "dq_is_diagnostics_only": "<evidence if triggered — if not triggered, write 'Not diagnostics-only'>",
  "dq_is_pure_software": "<evidence if triggered — if not triggered, write 'Not pure software'>",
  "dq_is_clinical_cro_only": "<evidence if triggered — if not triggered, write 'Not a clinical-only CRO'>",
  "dq_is_academic_no_industry": "<evidence if triggered — if not triggered, write 'Not academic without industry partnerships'>",
  "evidence": ["<specific facts found>"],
  "confidence": <1-10>
}""",
        "user": "Research {domain} (https://{domain}). Focus ONLY on whether this company does small molecule drug discovery. Check their pipeline, platform, publications, and research areas. Ignore company size, funding, team — just small molecule focus."
    },

    "stage_fit": {
        "system": """You are a biotech industry analyst. Your ONLY task is to determine a company's stage and size fit for a chemical supplier targeting drug discovery organizations.

Classify the company:
- Series A+ biotech with active R&D: 30 points
- Mid-tier pharma (500-5,000 employees): 30 points
- AI/computational drug discovery company: 25 points
- Early preclinical through Phase II: 20 points
- Phase III/commercial stage only: 10 points
- Pure manufacturing/clinical/regulatory: 0 points

Also determine company tier:
- Tier 0: Pre-Funding/Early Startup (<10 employees, pre-Series A)
- Tier 1: Series A (10-50 employees)
- Tier 2: Series B (50-150 employees)
- Tier 3: Series C/Growth (150-500 employees)
- Tier 4: Public/Late-Stage (500+ employees or publicly listed)

Company type: Therapeutics biotech, Platform biotech, Pharma, CRO/CDMO, Tool/Instrumentation, Academic, Other

Return valid JSON:
{
  "score": <0-30>,
  "stage_tier": <0-4>,
  "stage_label": "<Pre-Funding/Early Startup | Series A | Series B | Series C/Growth | Public/Late-Stage>",
  "estimated_headcount": "<e.g. 35-50 employees>",
  "company_type": "<type>",
  "sf_stage_type": "<series_a_biotech | mid_tier_pharma | ai_drug_discovery | early_preclinical | phase_3_commercial | manufacturing_clinical | other>",
  "sf_funding_stage": "<e.g. 'Series B' or 'Public' or 'Unknown'>",
  "sf_is_public": "<evidence string if public, e.g. 'Listed on NASDAQ as OLMA since 2020' — if private or unknown, write 'Not found in public listings — likely private'>",
  "sf_scoring_basis": "<which stage fit criterion determined the score>",
  "evidence": ["<specific facts found>"],
  "confidence": <1-10>
}""",
        "user": "Research {domain} (https://{domain}). Focus ONLY on company size, funding stage, employee count, and organizational maturity. Check LinkedIn headcount, Crunchbase, press releases, and their About page. Ignore their science — just size and stage."
    },

    "contact_quality": {
        "system": """You are a sales intelligence analyst. Your ONLY task is to determine if a company has chemistry decision-makers who would buy chemical compounds and services.

Look for evidence of these roles existing at the company:
- Head of Medicinal Chemistry / Chemistry Director: 25 points
- Head of Computational Chemistry / CADD: 25 points
- VP/Director of Drug Discovery: 20 points
- Principal/Senior Medicinal Chemist: 15 points
- Research Scientist in chemistry: 10 points
- Non-chemistry roles only (admin, clinical, manufacturing): 0 points

Score based on the HIGHEST decision-maker role you can find evidence of.

Return valid JSON:
{
  "score": <0-25>,
  "highest_role_found": "<role title or 'none found'>",
  "cq_has_chemistry_team": "<evidence string if found, e.g. '15+ chemists on LinkedIn including 3 senior med chem roles' — if not found, write 'No chemistry team evidence found on LinkedIn or website'>",
  "cq_team_size_estimate": "<e.g. '10-20 chemists' or 'unknown'>",
  "cq_scoring_basis": "<which role level determined the score: head_med_chem | head_cadd | vp_drug_discovery | senior_chemist | research_scientist | none>",
  "evidence": ["<specific facts found — names, titles, LinkedIn profiles>"],
  "confidence": <1-10>
}""",
        "user": "Research {domain} (https://{domain}). Focus ONLY on whether this company has chemistry decision-makers. Check LinkedIn for employees with medicinal chemistry, computational chemistry, or drug discovery titles. Check their team/leadership page. Ignore funding, pipeline, size — just chemistry leadership."
    },

    "strategic_indicators": {
        "system": """You are a business intelligence analyst. Your ONLY task is to identify growth signals at a company that indicate they are actively investing in drug discovery.

Score these signals (take the highest applicable, cap at 15):
- Recent Series A+ funding (last 18 months): 15 points
- Recent chemistry leadership hires (last 12 months): 10 points
- Published drug discovery research (last 24 months): 10 points
- Active pharma partnerships: 10 points
- Patent filings in small molecules: 5 points
- No growth indicators: 0 points

Return valid JSON:
{
  "score": <0-15>,
  "signals_found": ["<list of signals>"],
  "si_recent_funding": "<evidence string if found, e.g. '$65M Series B closed March 2025, led by OrbiMed' — if not found, write 'No recent funding found'>",
  "si_funding_amount": "<dollar amount and round if found, e.g. '$45M Series B' — if not found, write 'No funding amount found'>",
  "si_recent_chem_hires": "<evidence string if found, e.g. 'Hired Director of Med Chem from Pfizer in Jan 2025' — if not found, write 'No recent chemistry hires found'>",
  "si_recent_publications": "<evidence string if found, e.g. '4 SAR papers in J Med Chem 2024-2025' — if not found, write 'No recent drug discovery publications found'>",
  "si_pharma_partnerships": "<evidence string if found, e.g. 'Roche collaboration on oncology program announced Sep 2024' — if not found, write 'No pharma partnerships found'>",
  "si_patent_filings": "<evidence string if found, e.g. 'WO2024/123456 filed for novel kinase scaffold' — if not found, write 'No small molecule patents found'>",
  "si_scoring_basis": "<primary signal: recent_funding | chem_hires | publications | partnerships | patents | none>",
  "evidence": ["<specific facts found with dates>"],
  "confidence": <1-10>
}""",
        "user": "Research {domain} (https://{domain}). Focus ONLY on recent growth signals. Check for: funding rounds in the last 18 months, chemistry leadership hires in the last 12 months, drug discovery publications in the last 24 months, pharma partnerships, and small molecule patent filings. Ignore what the company does — just growth signals."
    },

    "service_match": {
        "system": """You are a chemical supply sales specialist for eMolecules. Your ONLY task is to determine which eMolecules services would be relevant to this company.

eMolecules services:
- Building Blocks: Chemical building blocks for medicinal chemistry synthesis. Relevant if the company does hands-on synthesis, SAR studies, or medicinal chemistry.
- Screening Compounds: Compound libraries for high-throughput screening. Relevant if the company does HTS, hit finding, or phenotypic screening.
- Virtual Libraries: Make-on-demand virtual compound collections for virtual screening. Relevant if the company does computational chemistry, CADD, or virtual screening.
- Compound Management: Storage, logistics, and management of compound collections. Relevant if the company has large compound libraries or multiple research sites.

Return valid JSON:
{
  "service_match": ["<matching services>"],
  "primary_service": "<most relevant single service>",
  "reasoning": "<1-2 sentences on why these services match>",
  "confidence": <1-10>
}""",
        "user": "Research {domain} (https://{domain}). Determine which eMolecules services (Building Blocks, Screening Compounds, Virtual Libraries, Compound Management) this company would need based on their research activities. Focus on their chemistry workflow."
    }
}


async def call_category_agent(
    session: aiohttp.ClientSession,
    domain: str,
    category: str,
    prompts: dict
) -> dict:
    """Call a single category-specific agent for a domain."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": prompts["user"].format(domain=domain)}
        ],
        "temperature": 0.1,
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://emolecules.com",
        "X-Title": "eMolecules ICP Scorer",
    }

    try:
        start = time.time()
        async with session.post(API_URL, json=payload, headers=headers) as resp:
            elapsed = time.time() - start
            if resp.status != 200:
                error_text = await resp.text()
                return {
                    "category": category,
                    "error": f"API error {resp.status}: {error_text}",
                    "elapsed_seconds": round(elapsed, 2)
                }
            data = await resp.json()

        content = data["choices"][0]["message"]["content"]
        citations = data.get("citations", [])

        # Parse JSON from response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        result = json.loads(content.strip())
        result["category"] = category
        result["citations"] = citations
        result["elapsed_seconds"] = round(elapsed, 2)
        return result

    except json.JSONDecodeError as e:
        return {
            "category": category,
            "error": f"JSON parse error: {str(e)}",
            "raw_content": content if 'content' in dir() else None,
            "elapsed_seconds": round(time.time() - start, 2)
        }
    except Exception as e:
        return {
            "category": category,
            "error": str(e),
            "elapsed_seconds": 0
        }


async def upsert_to_supabase(session: aiohttp.ClientSession, result: dict):
    """Upsert a single result to icp_test_b_categorical."""
    if "error" in result:
        return

    # Clean category details for JSONB storage (remove non-serializable stuff)
    def clean_detail(d):
        return {k: v for k, v in d.items() if k != "category"}

    cats = result.get("category_details", {})

    row = {
        "domain": result["domain"],
        "icp_score": result.get("icp_score"),
        "qualification_status": result.get("qualification_status"),
        # Category scores
        "small_molecule_score": result.get("small_molecule_score"),
        "stage_fit_score": result.get("stage_fit_score"),
        "contact_quality_score": result.get("contact_quality_score"),
        "strategic_score": result.get("strategic_score"),
        # Small molecule sub-signals
        "sm_active_med_chem": result.get("sm_active_med_chem"),
        "sm_cadd_capabilities": result.get("sm_cadd_capabilities"),
        "sm_hit_to_lead": result.get("sm_hit_to_lead"),
        "sm_virtual_screening": result.get("sm_virtual_screening"),
        "sm_scoring_basis": result.get("sm_scoring_basis"),
        # Stage fit sub-signals
        "sf_scoring_basis": result.get("sf_scoring_basis"),
        # Contact quality sub-signals
        "cq_highest_role": result.get("cq_highest_role"),
        "cq_has_chemistry_team": result.get("cq_has_chemistry_team"),
        "cq_team_size_estimate": result.get("cq_team_size_estimate"),
        "cq_scoring_basis": result.get("cq_scoring_basis"),
        # Strategic sub-signals
        "si_recent_funding": result.get("si_recent_funding"),
        "si_funding_amount": result.get("si_funding_amount"),
        "si_recent_chem_hires": result.get("si_recent_chem_hires"),
        "si_recent_publications": result.get("si_recent_publications"),
        "si_pharma_partnerships": result.get("si_pharma_partnerships"),
        "si_patent_filings": result.get("si_patent_filings"),
        "si_scoring_basis": result.get("si_scoring_basis"),
        # Disqualifier sub-signals
        "auto_disqualified": result.get("auto_disqualified", False),
        "disqualify_reason": result.get("disqualify_reason"),
        "dq_is_biologics_only": result.get("dq_is_biologics_only"),
        "dq_is_manufacturing_only": result.get("dq_is_manufacturing_only"),
        "dq_is_medical_device": result.get("dq_is_medical_device"),
        "dq_is_diagnostics_only": result.get("dq_is_diagnostics_only"),
        "dq_is_pure_software": result.get("dq_is_pure_software"),
        "dq_is_clinical_cro_only": result.get("dq_is_clinical_cro_only"),
        "dq_is_academic_no_industry": result.get("dq_is_academic_no_industry"),
        # Meta
        "company_type": result.get("company_type"),
        "stage_tier": result.get("stage_tier"),
        "stage_label": result.get("stage_label"),
        "estimated_headcount": result.get("estimated_headcount"),
        "service_match": result.get("service_match", []),
        "key_evidence": result.get("key_evidence", []),
        "detail_small_molecule": clean_detail(cats.get("small_molecule", {})),
        "detail_stage_fit": clean_detail(cats.get("stage_fit", {})),
        "detail_contact_quality": clean_detail(cats.get("contact_quality", {})),
        "detail_strategic": clean_detail(cats.get("strategic_indicators", {})),
        "detail_service_match": clean_detail(cats.get("service_match", {})),
        "total_elapsed_seconds": result.get("total_elapsed_seconds"),
        "api_calls": result.get("api_calls", 5),
        "source_user_count": result.get("source_user_count"),
        "source_total_sessions": result.get("source_total_sessions"),
        "source_last_active": result.get("source_last_active"),
        "scored_at": datetime.now(timezone.utc).isoformat()
    }

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

    url = f"{SUPABASE_URL}/rest/v1/icp_test_b_categorical"
    async with session.post(url, json=row, headers=headers) as resp:
        if resp.status not in (200, 201):
            text = await resp.text()
            print(f"    Supabase write error for {result['domain']}: {resp.status} — {text[:100]}")

    # Stamp icp_searched_at on the source company row
    stamp_headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    stamp_url = f"{SUPABASE_URL}/rest/v1/emolecules_data_by_company?domain=eq.{result['domain']}"
    async with session.patch(stamp_url, json={"icp_searched_at": datetime.now(timezone.utc).isoformat()}, headers=stamp_headers) as resp:
        if resp.status not in (200, 204):
            text = await resp.text()
            print(f"    Stamp error for {result['domain']}: {resp.status} — {text[:100]}")


async def score_company(session: aiohttp.ClientSession, domain: str) -> dict:
    """Score a single company using all category agents in parallel."""
    tasks = [
        call_category_agent(session, domain, cat, prompts)
        for cat, prompts in CATEGORY_PROMPTS.items()
    ]
    category_results = await asyncio.gather(*tasks)

    # Build category result map
    cats = {}
    for r in category_results:
        cats[r["category"]] = r

    # Aggregate scores
    sm = cats.get("small_molecule", {})
    sf = cats.get("stage_fit", {})
    cq = cats.get("contact_quality", {})
    si = cats.get("strategic_indicators", {})
    svc = cats.get("service_match", {})

    # Check for auto-disqualification from small_molecule agent
    auto_disqualified = sm.get("auto_disqualified", False)
    disqualify_reason = sm.get("disqualify_reason")

    if auto_disqualified:
        icp_score = 0
    else:
        icp_score = (
            sm.get("score", 0) +
            sf.get("score", 0) +
            cq.get("score", 0) +
            si.get("score", 0)
        )

    # Determine qualification status
    if auto_disqualified or icp_score < 40:
        qualification_status = "NO FIT"
    elif icp_score < 60:
        qualification_status = "LOW FIT"
    elif icp_score < 80:
        qualification_status = "MEDIUM FIT"
    else:
        qualification_status = "HIGH FIT"

    # Collect all evidence
    all_evidence = []
    for cat_result in category_results:
        all_evidence.extend(cat_result.get("evidence", []))

    total_elapsed = sum(r.get("elapsed_seconds", 0) for r in category_results)

    return {
        "domain": domain,
        "icp_score": min(icp_score, 100),
        "qualification_status": qualification_status,
        "small_molecule_score": sm.get("score", 0),
        "stage_fit_score": sf.get("score", 0),
        "contact_quality_score": cq.get("score", 0),
        "strategic_score": si.get("score", 0),
        # Small molecule sub-signals
        "sm_active_med_chem": sm.get("sm_active_med_chem"),
        "sm_cadd_capabilities": sm.get("sm_cadd_capabilities"),
        "sm_hit_to_lead": sm.get("sm_hit_to_lead"),
        "sm_virtual_screening": sm.get("sm_virtual_screening"),
        "sm_scoring_basis": sm.get("sm_scoring_basis"),
        # Stage fit sub-signals
        "sf_scoring_basis": sf.get("sf_scoring_basis"),
        # Contact quality sub-signals
        "cq_highest_role": cq.get("highest_role_found"),
        "cq_has_chemistry_team": cq.get("cq_has_chemistry_team", cq.get("chemistry_team_evidence")),
        "cq_team_size_estimate": cq.get("cq_team_size_estimate"),
        "cq_scoring_basis": cq.get("cq_scoring_basis"),
        # Strategic sub-signals
        "si_recent_funding": si.get("si_recent_funding"),
        "si_funding_amount": si.get("si_funding_amount"),
        "si_recent_chem_hires": si.get("si_recent_chem_hires"),
        "si_recent_publications": si.get("si_recent_publications"),
        "si_pharma_partnerships": si.get("si_pharma_partnerships"),
        "si_patent_filings": si.get("si_patent_filings"),
        "si_scoring_basis": si.get("si_scoring_basis"),
        # Disqualifier sub-signals
        "auto_disqualified": auto_disqualified,
        "disqualify_reason": disqualify_reason,
        "dq_is_biologics_only": sm.get("dq_is_biologics_only"),
        "dq_is_manufacturing_only": sm.get("dq_is_manufacturing_only"),
        "dq_is_medical_device": sm.get("dq_is_medical_device"),
        "dq_is_diagnostics_only": sm.get("dq_is_diagnostics_only"),
        "dq_is_pure_software": sm.get("dq_is_pure_software"),
        "dq_is_clinical_cro_only": sm.get("dq_is_clinical_cro_only"),
        "dq_is_academic_no_industry": sm.get("dq_is_academic_no_industry"),
        # Meta
        "company_type": sf.get("company_type"),
        "stage_tier": sf.get("stage_tier"),
        "stage_label": sf.get("stage_label"),
        "estimated_headcount": sf.get("estimated_headcount"),
        "service_match": svc.get("service_match", []),
        "key_evidence": all_evidence[:10],
        "category_details": {
            "small_molecule": sm,
            "stage_fit": sf,
            "contact_quality": cq,
            "strategic_indicators": si,
            "service_match": svc
        },
        "total_elapsed_seconds": round(total_elapsed, 2),
        "api_calls": len(category_results),
        "model": MODEL,
        "test": "B_categorical"
    }


BATCH_FILE = "current_test_batch.json"

async def fetch_test_companies(session: aiohttp.ClientSession) -> list:
    """Return the shared 50-company batch for this A/B test run.

    If current_test_batch.json already exists, both tests use the same list.
    If not, fetch 50 random companies from Supabase, save the file, and use that.
    Delete current_test_batch.json to start a fresh batch.
    """
    if os.path.exists(BATCH_FILE):
        with open(BATCH_FILE) as f:
            companies = json.load(f)
        print(f"  Using existing batch from {BATCH_FILE} ({len(companies)} companies)")
        return companies

    url = f"{SUPABASE_URL}/rest/v1/rpc/get_random_icp_companies"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    async with session.post(url, json={"n": 50}, headers=headers) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise Exception(f"Failed to fetch companies from Supabase: {resp.status} — {text[:200]}")
        companies = await resp.json()

    with open(BATCH_FILE, "w") as f:
        json.dump(companies, f, indent=2)
    print(f"  Saved new batch to {BATCH_FILE} ({len(companies)} companies)")
    return companies


async def run_test():
    """Run Test B on all 50 companies."""
    async with aiohttp.ClientSession() as session:
        print("Fetching top 50 companies from emolecules_data_by_company...")
        companies = await fetch_test_companies(session)

    source_by_domain = {c["domain"]: c for c in companies}
    domains = [c["domain"] for c in companies]
    results = []
    total = len(domains)
    total_api_calls = total * len(CATEGORY_PROMPTS)

    print(f"\n{'='*60}")
    print(f"TEST B — CATEGORICAL AGENTS")
    print(f"Model: {MODEL}")
    print(f"Companies: {total}")
    print(f"Categories per company: {len(CATEGORY_PROMPTS)}")
    print(f"Total API calls: {total_api_calls}")
    print(f"Writing to: Supabase → icp_test_b_categorical")
    print(f"{'='*60}\n")

    async with aiohttp.ClientSession() as session:
        for i in range(0, total, BATCH_SIZE):
            batch = domains[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

            print(f"Batch {batch_num}/{total_batches}: {', '.join(batch)}")

            tasks = [score_company(session, domain) for domain in batch]
            batch_results = await asyncio.gather(*tasks)

            for r in batch_results:
                # Inject source fields from emolecules_data_by_company
                src = source_by_domain.get(r["domain"], {})
                r["source_user_count"] = src.get("user_count")
                r["source_total_sessions"] = src.get("total_sessions")
                r["source_last_active"] = src.get("last_active")

                results.append(r)
                status = r.get("qualification_status", "ERROR")
                score = r.get("icp_score", "N/A")
                error = r.get("error")
                if error:
                    print(f"  {r['domain']}: ERROR — {error[:80]}")
                else:
                    sm = r.get("small_molecule_score", "?")
                    sf = r.get("stage_fit_score", "?")
                    cq = r.get("contact_quality_score", "?")
                    si = r.get("strategic_score", "?")
                    print(f"  {r['domain']}: {score}/100 ({status}) [SM:{sm} SF:{sf} CQ:{cq} SI:{si}] [{r['total_elapsed_seconds']}s]")
                    await upsert_to_supabase(session, r)

            if i + BATCH_SIZE < total:
                await asyncio.sleep(DELAY_BETWEEN_BATCHES)

    # Local backup
    output = {
        "test": "B_categorical",
        "model": MODEL,
        "run_at": datetime.now().isoformat(),
        "total_companies": total,
        "total_api_calls": total_api_calls,
        "categories": list(CATEGORY_PROMPTS.keys()),
        "results": results,
        "summary": {
            "high_fit": len([r for r in results if r.get("qualification_status") == "HIGH FIT"]),
            "medium_fit": len([r for r in results if r.get("qualification_status") == "MEDIUM FIT"]),
            "low_fit": len([r for r in results if r.get("qualification_status") == "LOW FIT"]),
            "no_fit": len([r for r in results if r.get("qualification_status") == "NO FIT"]),
            "errors": len([r for r in results if "error" in r]),
            "auto_disqualified": len([r for r in results if r.get("auto_disqualified") == True]),
            "avg_elapsed": round(sum(r.get("total_elapsed_seconds", 0) for r in results) / len(results), 2),
            "avg_score": round(sum(r.get("icp_score", 0) for r in results) / len(results), 1)
        }
    }

    os.makedirs("results", exist_ok=True)
    with open("results/test_b_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*60}")
    for k, v in output["summary"].items():
        print(f"  {k}: {v}")
    print(f"\nResults saved to Supabase (icp_test_b_categorical) + results/test_b_results.json")


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: Set OPENROUTER_API_KEY in .env file")
        exit(1)
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_KEY in .env file")
        exit(1)
    asyncio.run(run_test())
