"""
Test A — Holistic Agent with Rabbit-Hole Sub-Agents
Initial broad research call per company. The agent scores everything AND
identifies specific rabbit holes — unanswered questions it wants a sub-agent
to investigate. Follow-up agents are dispatched with those exact questions,
then findings are merged back into the final score.

1 call for obvious companies, 2-5 for ambiguous ones.

Results written to Supabase table: icp_test_a_holistic

Usage: python3 test_a_holistic.py
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
BATCH_SIZE = 5
DELAY_BETWEEN_BATCHES = 2
MAX_RABBIT_HOLES = 3  # cap follow-ups per company to control cost

# ─────────────────────────────────────────────────────────────
# Stage 1: Initial broad research
# Scores everything + identifies specific rabbit holes to investigate
# ─────────────────────────────────────────────────────────────

INITIAL_SYSTEM_PROMPT = """You are an ICP qualification specialist for eMolecules, a chemical supplier serving drug discovery organizations. Your job is to evaluate companies to determine fit for eMolecules' services: Building Blocks, Screening Compounds, Virtual Libraries, and Compound Management.

Research the company thoroughly — check their website, pipeline, team, funding, and any available information.

SCORING FRAMEWORK (0-100 SCALE)

CORE REQUIREMENTS (60 points maximum)

Small Molecule Drug Discovery (30 points)
- Active medicinal chemistry programs: 30 points
- Computational chemistry/CADD capabilities: 25 points
- Hit-to-lead/lead optimization activities: 20 points
- Virtual screening programs: 15 points
- No drug discovery activities: 0 points

Company Stage Fit (30 points)
- Series A+ biotech with active R&D: 30 points
- Mid-tier pharma (500-5,000 employees): 30 points
- AI/computational drug discovery company: 25 points
- Early preclinical through Phase II: 20 points
- Phase III/commercial stage only: 10 points
- Pure manufacturing/clinical/regulatory: 0 points

CONTACT QUALITY (25 points maximum)
Decision Maker Authority (25 points):
- Head of Medicinal Chemistry / Chemistry Director: 25 points
- Head of Computational Chemistry / CADD: 25 points
- VP/Director of Drug Discovery: 20 points
- Principal/Senior Medicinal Chemist: 15 points
- Research Scientist in chemistry: 10 points
- Non-chemistry roles (admin, clinical, manufacturing): 0 points

STRATEGIC INDICATORS (15 points maximum)
Growth Signals (15 points)
- Recent Series A+ funding: 15 points
- Recent chemistry leadership hires: 10 points
- Published drug discovery research: 10 points
- Active pharma partnerships: 10 points
- Patent filings in small molecules: 5 points
- No growth indicators: 0 points

AUTOMATIC DISQUALIFIERS (Score = 0)
- Pure biologics companies (antibodies, gene therapy, cell therapy)
- Manufacturing-only operations
- Medical device companies
- Diagnostics-only companies
- Pure software/platform companies without wet lab validation
- Clinical research organizations (CROs) focused only on clinical trials
- Academic institutions without industry partnerships

IMPORTANT — RABBIT HOLES:
After scoring, identify any specific unanswered questions that would materially change the score if answered. These should be SPECIFIC and ACTIONABLE — not vague. Examples:
- "Their website mentions 'novel modalities' but doesn't specify — check if their drug candidate XYZ-001 is a small molecule or biologic"
- "They have a partnership with Pfizer announced in 2024 — determine if this is a small molecule collaboration"
- "Their LinkedIn shows 200+ employees but no funding data found — check Crunchbase for funding rounds"
- "Found a med chem job posting from 6 months ago — check if they actually hired a Head of Chemistry"

If you are confident in ALL scores (8+/10), return an empty rabbit_holes array.

Return your response as valid JSON with these exact keys:
{
  "icp_score": <0-100>,
  "qualification_status": "<HIGH FIT | MEDIUM FIT | LOW FIT | NO FIT>",

  "small_molecule_score": <0-30>,
  "small_molecule_confidence": <1-10>,
  "sm_active_med_chem": "<evidence string if found, e.g. '3 active programs targeting GPCRs and kinase inhibitors per pipeline page' — if not found, write 'No active med chem programs found on website or pipeline'>",
  "sm_cadd_capabilities": "<evidence string if found, e.g. 'In-house CADD team using Schrodinger, 5 comp chem staff on LinkedIn' — if not found, write 'No CADD capabilities found'>",
  "sm_hit_to_lead": "<evidence string if found, e.g. 'Lead optimization of compound series XYZ per 2024 ACS presentation' — if not found, write 'No hit-to-lead activity found'>",
  "sm_virtual_screening": "<evidence string if found, e.g. 'Virtual screening of 10M compound library mentioned in Nature 2024 paper' — if not found, write 'No virtual screening activity found'>",
  "sm_scoring_basis": "<which criterion determined the score: active_med_chem | cadd | hit_to_lead | virtual_screening | none>",

  "stage_fit_score": <0-30>,
  "stage_fit_confidence": <1-10>,
  "sf_stage_type": "<series_a_biotech | mid_tier_pharma | ai_drug_discovery | early_preclinical | phase_3_commercial | manufacturing_clinical | other>",
  "sf_employee_range": "<e.g. '50-150 employees'>",
  "sf_funding_stage": "<e.g. 'Series B' or 'Public' or 'Unknown'>",
  "sf_is_public": "<evidence string if public, e.g. 'Listed on NASDAQ as OLMA since 2020' — if private or unknown, write 'Not found in public listings — likely private'>",
  "sf_scoring_basis": "<which stage fit criterion determined the score>",

  "contact_quality_score": <0-25>,
  "contact_quality_confidence": <1-10>,
  "cq_highest_role": "<actual title and name if found, e.g. 'Dr. Jane Smith, VP Drug Discovery' — or 'none found'>",
  "cq_has_chemistry_team": "<evidence string if found, e.g. '15+ chemists on LinkedIn including 3 senior med chem roles' — if not found, write 'No chemistry team evidence found on LinkedIn or website'>",
  "cq_team_size_estimate": "<e.g. '10-20 chemists' or 'unknown'>",
  "cq_scoring_basis": "<which role level determined the score: head_med_chem | head_cadd | vp_drug_discovery | senior_chemist | research_scientist | none>",

  "strategic_score": <0-15>,
  "strategic_confidence": <1-10>,
  "si_recent_funding": "<evidence string if found, e.g. '$65M Series B closed March 2025, led by OrbiMed' — if not found, write 'No recent funding found in public records'>",
  "si_funding_amount": "<dollar amount and round if found, e.g. '$45M Series B' — if not found, write 'No funding amount found'>",
  "si_recent_chem_hires": "<evidence string if found, e.g. 'Hired Director of Med Chem from Pfizer in Jan 2025 per LinkedIn' — if not found, write 'No recent chemistry hires found'>",
  "si_recent_publications": "<evidence string if found, e.g. '4 SAR papers published in J Med Chem 2024-2025' — if not found, write 'No recent drug discovery publications found'>",
  "si_pharma_partnerships": "<evidence string if found, e.g. 'Collaboration with Roche on small molecule oncology program announced Sep 2024' — if not found, write 'No pharma partnerships found'>",
  "si_patent_filings": "<evidence string if found, e.g. 'WO2024/123456 filed for novel kinase inhibitor scaffold' — if not found, write 'No small molecule patents found'>",
  "si_scoring_basis": "<primary signal: recent_funding | chem_hires | publications | partnerships | patents | none>",

  "auto_disqualified": <true|false>,
  "disqualify_reason": "<reason if auto_disqualified is true — if false, write 'Not disqualified'>",
  "dq_is_biologics_only": "<evidence if triggered, e.g. 'Pipeline is 100% monoclonal antibodies, no small molecule programs' — if not triggered, write 'Not biologics-only'>",
  "dq_is_manufacturing_only": "<evidence if triggered — if not triggered, write 'Not manufacturing-only'>",
  "dq_is_medical_device": "<evidence if triggered — if not triggered, write 'Not a medical device company'>",
  "dq_is_diagnostics_only": "<evidence if triggered — if not triggered, write 'Not diagnostics-only'>",
  "dq_is_pure_software": "<evidence if triggered — if not triggered, write 'Not pure software'>",
  "dq_is_clinical_cro_only": "<evidence if triggered — if not triggered, write 'Not a clinical-only CRO'>",
  "dq_is_academic_no_industry": "<evidence if triggered — if not triggered, write 'Not academic without industry partnerships'>",

  "company_type": "<Therapeutics biotech | Platform biotech | Pharma | CRO/CDMO | Tool/Instrumentation | Academic | Other>",
  "service_match": ["<Building Blocks | Screening Compounds | Virtual Libraries | Compound Management>"],
  "reasoning": "<2-3 sentences explaining the score>",
  "key_evidence": ["<up to 5 specific facts you found>"],
  "rabbit_holes": [
    {
      "question": "<specific question to investigate>",
      "why_it_matters": "<which score category this could change and by how much>",
      "where_to_look": "<specific URL, database, or search query to try>",
      "affects_category": "<small_molecule | stage_fit | contact_quality | strategic | disqualifier>"
    }
  ]
}"""

# ─────────────────────────────────────────────────────────────
# Stage 2: Rabbit hole investigator
# Gets a specific question and goes deep on just that
# ─────────────────────────────────────────────────────────────

RABBIT_HOLE_SYSTEM = """You are a research investigator. You have been given a SPECIFIC question about a company that a previous analyst could not answer. Your job is to find the answer.

Be thorough — check the specific sources suggested, but also try related searches. If you can't find a definitive answer, say so clearly.

Return valid JSON:
{
  "question": "<the question you were asked>",
  "answer": "<your findings — be specific with facts, dates, names>",
  "answer_found": <true|false>,
  "confidence": <1-10>,
  "score_impact": {
    "category": "<which scoring category this affects>",
    "suggested_score_change": "<e.g. '+10 to small_molecule_score' or 'no change' or 'auto_disqualify'>",
    "reasoning": "<why this changes the score>"
  },
  "evidence": ["<specific facts with sources>"]
}"""


async def perplexity_call(session: aiohttp.ClientSession, system: str, user: str) -> tuple:
    """Make a single Perplexity API call. Returns (parsed_dict, citations, elapsed)."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://emolecules.com",
        "X-Title": "eMolecules ICP Scorer",
    }

    start = time.time()
    async with session.post(API_URL, json=payload, headers=headers) as resp:
        elapsed = time.time() - start
        if resp.status != 200:
            error_text = await resp.text()
            raise Exception(f"API error {resp.status}: {error_text[:200]}")
        data = await resp.json()

    content = data["choices"][0]["message"]["content"]
    citations = data.get("citations", [])

    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]

    return json.loads(content.strip()), citations, round(elapsed, 2)


def apply_rabbit_hole_findings(initial: dict, findings: list) -> dict:
    """Merge rabbit hole findings back into the initial assessment."""
    for finding in findings:
        if not finding.get("answer_found"):
            continue

        impact = finding.get("score_impact", {})
        category = impact.get("category", "")
        change = impact.get("suggested_score_change", "")

        # Parse score changes like "+10 to small_molecule_score"
        if "auto_disqualify" in change.lower():
            initial["auto_disqualified"] = True
            initial["disqualify_reason"] = impact.get("reasoning", "Identified via follow-up investigation")
        elif change and "no change" not in change.lower():
            # Try to extract numeric change
            try:
                # Handle formats like "+10", "-5", "+10 to small_molecule_score"
                num_str = change.split(" ")[0].replace("+", "")
                delta = int(num_str)

                score_key_map = {
                    "small_molecule": "small_molecule_score",
                    "stage_fit": "stage_fit_score",
                    "contact_quality": "contact_quality_score",
                    "strategic": "strategic_score"
                }

                if category in score_key_map:
                    key = score_key_map[category]
                    max_scores = {
                        "small_molecule_score": 30,
                        "stage_fit_score": 30,
                        "contact_quality_score": 25,
                        "strategic_score": 15
                    }
                    old = initial.get(key, 0)
                    new = max(0, min(old + delta, max_scores.get(key, 100)))
                    initial[key] = new
            except (ValueError, IndexError):
                pass  # couldn't parse, keep original score

        # Merge evidence
        existing = initial.get("key_evidence", [])
        new_evidence = finding.get("evidence", [])
        initial["key_evidence"] = (existing + new_evidence)[:10]

    # Recalculate total
    if initial.get("auto_disqualified"):
        initial["icp_score"] = 0
        initial["qualification_status"] = "NO FIT"
    else:
        recalc = (
            initial.get("small_molecule_score", 0) +
            initial.get("stage_fit_score", 0) +
            initial.get("contact_quality_score", 0) +
            initial.get("strategic_score", 0)
        )
        initial["icp_score"] = min(recalc, 100)
        if recalc >= 80:
            initial["qualification_status"] = "HIGH FIT"
        elif recalc >= 60:
            initial["qualification_status"] = "MEDIUM FIT"
        elif recalc >= 40:
            initial["qualification_status"] = "LOW FIT"
        else:
            initial["qualification_status"] = "NO FIT"

    return initial


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


async def score_company(session: aiohttp.ClientSession, domain: str) -> dict:
    """Score a company: initial broad call, then chase rabbit holes."""
    total_calls = 0
    total_elapsed = 0
    all_citations = []
    rabbit_hole_results = []

    # ── Stage 1: Initial broad research ──
    try:
        initial, citations, elapsed = await perplexity_call(
            session,
            INITIAL_SYSTEM_PROMPT,
            f"Research and score this company: {domain}\n\nVisit their website at https://{domain} and research them thoroughly. Check their pipeline, team, funding, publications, and any other relevant information. Then score them using the framework above."
        )
        total_calls += 1
        total_elapsed += elapsed
        all_citations.extend(citations)
    except Exception as e:
        return {"domain": domain, "error": str(e), "elapsed_seconds": 0}

    rabbit_holes = initial.get("rabbit_holes", [])

    # ── Stage 2: Chase rabbit holes (if any) ──
    if rabbit_holes:
        # Cap at MAX_RABBIT_HOLES to control cost
        holes_to_chase = rabbit_holes[:MAX_RABBIT_HOLES]

        rabbit_hole_coroutines = [
            perplexity_call(
                session,
                RABBIT_HOLE_SYSTEM,
                f"Company: {domain} (https://{domain})\n\n"
                f"QUESTION TO INVESTIGATE: {hole['question']}\n\n"
                f"WHY IT MATTERS: {hole.get('why_it_matters', 'Could change ICP score')}\n\n"
                f"WHERE TO LOOK: {hole.get('where_to_look', 'Company website, LinkedIn, Crunchbase, news')}\n\n"
                f"CATEGORY THIS AFFECTS: {hole.get('affects_category', 'unknown')}\n\n"
                f"Find the answer to this specific question. Be thorough."
            )
            for hole in holes_to_chase
        ]

        results = await asyncio.gather(*rabbit_hole_coroutines, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"    Rabbit hole error for {domain}: {result}")
                continue

            rh_data, rh_citations, rh_elapsed = result
            total_calls += 1
            total_elapsed += rh_elapsed
            all_citations.extend(rh_citations)
            rabbit_hole_results.append(rh_data)

        # Merge findings back into initial assessment
        if rabbit_hole_results:
            initial = apply_rabbit_hole_findings(initial, rabbit_hole_results)

    # ── Build final result ──
    initial["domain"] = domain
    initial["citations"] = all_citations
    initial["elapsed_seconds"] = round(total_elapsed, 2)
    initial["api_calls"] = total_calls
    initial["follow_up_categories"] = [h.get("affects_category", "unknown") for h in rabbit_holes[:MAX_RABBIT_HOLES]]
    initial["initial_confidence"] = {
        "small_molecule_confidence": initial.get("small_molecule_confidence"),
        "stage_fit_confidence": initial.get("stage_fit_confidence"),
        "contact_quality_confidence": initial.get("contact_quality_confidence"),
        "strategic_confidence": initial.get("strategic_confidence")
    }
    initial["rabbit_holes_asked"] = rabbit_holes[:MAX_RABBIT_HOLES]
    initial["rabbit_holes_answered"] = rabbit_hole_results
    initial["test"] = "A_holistic"
    return initial


async def upsert_to_supabase(session: aiohttp.ClientSession, result: dict):
    """Upsert a single result to icp_test_a_holistic."""
    if "error" in result:
        return

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
        "sf_stage_type": result.get("sf_stage_type"),
        "sf_employee_range": result.get("sf_employee_range"),
        "sf_funding_stage": result.get("sf_funding_stage"),
        "sf_is_public": result.get("sf_is_public"),
        "sf_scoring_basis": result.get("sf_scoring_basis"),
        # Contact quality sub-signals
        "cq_highest_role": result.get("cq_highest_role"),
        "cq_has_chemistry_team": result.get("cq_has_chemistry_team"),
        "cq_team_size_estimate": result.get("cq_team_size_estimate"),
        "cq_scoring_basis": result.get("cq_scoring_basis"),
        # Strategic indicator sub-signals
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
        "service_match": result.get("service_match", []),
        "reasoning": result.get("reasoning"),
        "key_evidence": result.get("key_evidence", []),
        "citations": result.get("citations", []),
        "elapsed_seconds": result.get("elapsed_seconds"),
        "api_calls": result.get("api_calls", 1),
        "follow_up_categories": result.get("follow_up_categories", []),
        "initial_confidence": result.get("initial_confidence", {}),
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

    url = f"{SUPABASE_URL}/rest/v1/icp_test_a_holistic"
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


async def run_test():
    """Run Test A on all 50 companies."""
    async with aiohttp.ClientSession() as session:
        print("Fetching top 50 companies from emolecules_data_by_company...")
        companies = await fetch_test_companies(session)

    # Build domain → source data lookup for FK enrichment
    source_by_domain = {c["domain"]: c for c in companies}
    domains = [c["domain"] for c in companies]
    results = []
    total = len(domains)

    print(f"\n{'='*60}")
    print(f"TEST A — HOLISTIC AGENT (with rabbit-hole sub-agents)")
    print(f"Model: {MODEL}")
    print(f"Companies: {total}")
    print(f"Max rabbit holes per company: {MAX_RABBIT_HOLES}")
    print(f"Writing to: Supabase → icp_test_a_holistic")
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
                error = r.get("error")
                if error:
                    print(f"  {r['domain']}: ERROR — {error[:80]}")
                else:
                    score = r.get("icp_score", "N/A")
                    status = r.get("qualification_status", "?")
                    calls = r.get("api_calls", 1)
                    holes = len(r.get("rabbit_holes_asked", []))
                    answered = len(r.get("rabbit_holes_answered", []))
                    rh_str = f" → {holes} rabbit holes, {answered} answered" if holes else ""
                    print(f"  {r['domain']}: {score}/100 ({status}) [{calls} call(s), {r['elapsed_seconds']}s]{rh_str}")
                    await upsert_to_supabase(session, r)

            if i + BATCH_SIZE < total:
                await asyncio.sleep(DELAY_BETWEEN_BATCHES)

    # Local backup
    total_api_calls = sum(r.get("api_calls", 1) for r in results if "error" not in r)
    companies_with_holes = len([r for r in results if r.get("rabbit_holes_asked")])
    total_holes = sum(len(r.get("rabbit_holes_asked", [])) for r in results)
    total_answered = sum(len(r.get("rabbit_holes_answered", [])) for r in results)

    output = {
        "test": "A_holistic_with_rabbit_holes",
        "model": MODEL,
        "max_rabbit_holes": MAX_RABBIT_HOLES,
        "run_at": datetime.now().isoformat(),
        "total_companies": total,
        "total_api_calls": total_api_calls,
        "results": results,
        "summary": {
            "high_fit": len([r for r in results if r.get("qualification_status") == "HIGH FIT"]),
            "medium_fit": len([r for r in results if r.get("qualification_status") == "MEDIUM FIT"]),
            "low_fit": len([r for r in results if r.get("qualification_status") == "LOW FIT"]),
            "no_fit": len([r for r in results if r.get("qualification_status") == "NO FIT"]),
            "errors": len([r for r in results if "error" in r]),
            "auto_disqualified": len([r for r in results if r.get("auto_disqualified") == True]),
            "companies_needing_rabbit_holes": companies_with_holes,
            "total_rabbit_holes_asked": total_holes,
            "total_rabbit_holes_answered": total_answered,
            "avg_calls_per_company": round(total_api_calls / max(total, 1), 2),
            "avg_elapsed": round(sum(r.get("elapsed_seconds", 0) for r in results) / max(len(results), 1), 2)
        }
    }

    os.makedirs("results", exist_ok=True)
    with open("results/test_a_results.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\n{'='*60}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*60}")
    for k, v in output["summary"].items():
        print(f"  {k}: {v}")
    print(f"\nResults saved to Supabase (icp_test_a_holistic) + results/test_a_results.json")


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: Set OPENROUTER_API_KEY in .env file")
        exit(1)
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_KEY in .env file")
        exit(1)
    asyncio.run(run_test())
