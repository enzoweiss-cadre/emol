"""
Hybrid Pipeline — Stage 2 (Test A Holistic) → Stage 3 (Test B Categorical)

Three-stage hybrid ICP scoring pipeline for eMolecules.
  Stage 1 — Pre-screen: academic domains already excluded, stored in discarded_email_suggestion
  Stage 2 — Holistic agent (Test A logic) on all remaining companies
  Stage 3 — 5 categorical agents (Test B logic) on escalated companies only

Escalation criteria (Stage 2 → Stage 3):
  - qualification_status is MEDIUM FIT or LOW FIT
  - auto_disqualified=True AND small_molecule_confidence < 6

Results written to Supabase table: icp_hybrid_results

Usage: python3 run_hybrid_pipeline.py
  Requires .env with OPENROUTER_API_KEY, SUPABASE_URL, SUPABASE_KEY

─────────────────────────────────────────────────────────────
CREATE TABLE icp_hybrid_results (
    domain TEXT PRIMARY KEY,
    final_icp_score INTEGER,
    qualification_status TEXT,
    stage_reached TEXT,
    escalation_reason TEXT,
    stage_a_score INTEGER,
    stage_a_status TEXT,
    stage_b_score INTEGER,
    stage_b_status TEXT,
    small_molecule_score INTEGER,
    stage_fit_score INTEGER,
    contact_quality_score INTEGER,
    strategic_score INTEGER,
    sm_active_med_chem TEXT,
    sm_cadd_capabilities TEXT,
    sm_hit_to_lead TEXT,
    sm_virtual_screening TEXT,
    sm_scoring_basis TEXT,
    sf_stage_type TEXT,
    sf_employee_range TEXT,
    sf_funding_stage TEXT,
    sf_is_public TEXT,
    sf_scoring_basis TEXT,
    cq_highest_role TEXT,
    cq_has_chemistry_team TEXT,
    cq_team_size_estimate TEXT,
    cq_scoring_basis TEXT,
    si_recent_funding TEXT,
    si_funding_amount TEXT,
    si_recent_chem_hires TEXT,
    si_recent_publications TEXT,
    si_pharma_partnerships TEXT,
    si_patent_filings TEXT,
    si_scoring_basis TEXT,
    auto_disqualified BOOLEAN,
    disqualify_reason TEXT,
    dq_is_biologics_only TEXT,
    dq_is_manufacturing_only TEXT,
    dq_is_medical_device TEXT,
    dq_is_diagnostics_only TEXT,
    dq_is_pure_software TEXT,
    dq_is_clinical_cro_only TEXT,
    dq_is_academic_no_industry TEXT,
    company_type TEXT,
    stage_tier INTEGER,
    stage_label TEXT,
    estimated_headcount TEXT,
    service_match JSONB,
    reasoning TEXT,
    key_evidence JSONB,
    source_user_count INTEGER,
    source_total_sessions INTEGER,
    source_last_active TEXT,
    api_calls_total INTEGER,
    elapsed_total FLOAT,
    scored_at TIMESTAMPTZ DEFAULT NOW()
);
─────────────────────────────────────────────────────────────
"""

import json
import os
import sys
import time
import asyncio
import aiohttp
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────
# Environment
# ─────────────────────────────────────────────────────────────

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
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
MODEL = "perplexity/sonar-pro"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
BATCH_SIZE = 20
DELAY_BETWEEN_BATCHES = 3
MAX_RABBIT_HOLES = 3
TARGET_TABLE = "icp_hybrid_results"

# ─────────────────────────────────────────────────────────────
# Stage 2 Prompts — Holistic Agent (Test A logic)
# ─────────────────────────────────────────────────────────────

STAGE2_INITIAL_SYSTEM = """You are an ICP qualification specialist for eMolecules, a chemical supplier serving drug discovery organizations. Your job is to evaluate companies to determine fit for eMolecules' services: Building Blocks, Screening Compounds, Virtual Libraries, and Compound Management.

Research the company thoroughly — check their website, pipeline, team, funding, and any available information.

SCORING FRAMEWORK (0-100 SCALE)

CORE REQUIREMENTS (60 points maximum)

Small Molecule Drug Discovery (30 points)
- Active medicinal chemistry programs OR contract chemistry services (CRO/CDMO): 30 points
- Computational chemistry/CADD capabilities: 25 points
- Hit-to-lead/lead optimization activities (internal or contract): 20 points
- Virtual screening programs: 15 points
- No drug discovery or chemistry activities: 0 points

NOTE: "Active med chem" includes both internal drug programs (Gilead, Lilly, Roche) AND contract chemistry services (Selvita, Taros, Jubilant Biosys, Aurigene). Both are high-value eMolecules customers.

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
- Bulk API / commodity manufacturing ONLY (process scale-up, generics, no discovery chemistry)
- Medical device companies
- Diagnostics-only companies
- Pure software/platform companies without wet lab validation
- Clinical-only CROs (IQVIA, ICON, Covance — no wet chemistry, only trial management)
- Academic institutions without industry partnerships

CRITICAL — DO NOT DISQUALIFY THESE; THEY ARE CORE CUSTOMERS:
- Custom synthesis / contract med chem shops (WuXi, Syngene, Charles River Discovery, Enamine, etc.)
- Discovery CROs / CDMOs (companies doing medicinal chemistry, SAR, lead optimization for clients)
- FTE / full-service chemistry service providers
- PROTAC, fragment, or library-design service companies
- Any company whose website advertises "custom synthesis", "medicinal chemistry services", "hit-to-lead services", "lead optimization services", "discovery chemistry", "compound library design"

Rule: if a company DOES discovery chemistry (for itself OR for clients) → NOT disqualified.
Only disqualify when the company does ZERO discovery chemistry (e.g. generic-drug manufacturing, packaging, bulk ingredient supply without design work, or clinical-only operations).

PATENT CAVEAT FOR CROs / CDMOs:
Contract research organizations work on their clients' IP, so they often have FEW or ZERO patents under their own name. This is expected. Absence of patents is NOT a negative signal for a CRO/CDMO that advertises chemistry services (custom synthesis, med chem, lead optimization, PROTAC design, etc.). Score CROs on their service offerings, chemistry team size, and publications — not on patent portfolio size. A CRO with 0 own-name patents but active chemistry service pages is still HIGH FIT.

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
  "sm_active_med_chem": "<evidence string if found, e.g. 'Active kinase inhibitor program in Phase 1' or 'Contract medicinal chemistry CRO serving pharma clients' — if not found, write 'No active med chem programs found on website or pipeline'>",
  "sm_cadd_capabilities": "<evidence string if found, e.g. 'In-house CADD team using Schrodinger' — if not found, write 'No CADD capabilities found'>",
  "sm_hit_to_lead": "<evidence string if found, e.g. 'Lead optimization of XYZ series per ACS 2024' or 'Contract hit-to-lead services offered' — if not found, write 'No hit-to-lead activity found'>",
  "sm_virtual_screening": "<evidence string if found, e.g. 'Virtual screening of 10M library per Nature paper' — if not found, write 'No virtual screening activity found'>",
  "sm_scoring_basis": "<active_med_chem | cadd | hit_to_lead | virtual_screening | none>",

  "stage_fit_score": <0-30>,
  "stage_fit_confidence": <1-10>,
  "sf_stage_type": "<series_a_biotech | mid_tier_pharma | ai_drug_discovery | early_preclinical | phase_3_commercial | manufacturing_clinical | other>",
  "sf_employee_range": "<e.g. '50-150 employees'>",
  "sf_funding_stage": "<e.g. 'Series B' or 'Public' or 'Unknown'>",
  "sf_is_public": "<evidence string if public, e.g. 'Listed on NASDAQ as GILD since 1992' — if private or unknown, write 'Not found in public listings — likely private'>",
  "sf_scoring_basis": "<which stage fit criterion determined the score>",

  "contact_quality_score": <0-25>,
  "contact_quality_confidence": <1-10>,
  "cq_highest_role": "<actual title and name if found — or 'none found'>",
  "cq_has_chemistry_team": "<evidence string if found, e.g. '12 chemists on LinkedIn including 2 senior roles' — if not found, write 'No chemistry team evidence found on LinkedIn or website'>",
  "cq_team_size_estimate": "<e.g. '10-20 chemists' or 'unknown'>",
  "cq_scoring_basis": "<head_med_chem | head_cadd | vp_drug_discovery | senior_chemist | research_scientist | none>",

  "strategic_score": <0-15>,
  "strategic_confidence": <1-10>,
  "si_recent_funding": "<evidence string if found, e.g. '$65M Series B closed March 2025' — if not found, write 'No recent funding found in public records'>",
  "si_funding_amount": "<dollar amount and round if found, e.g. '$65M Series B' — if not found, write 'No funding amount found'>",
  "si_recent_chem_hires": "<evidence string if found, e.g. 'Hired Director of Med Chem from Pfizer Jan 2025' — if not found, write 'No recent chemistry hires found'>",
  "si_recent_publications": "<evidence string if found, e.g. '4 SAR papers in J Med Chem 2024-2025' — if not found, write 'No recent drug discovery publications found'>",
  "si_pharma_partnerships": "<evidence string if found, e.g. 'Roche collaboration announced Sep 2024' — if not found, write 'No pharma partnerships found'>",
  "si_patent_filings": "<evidence string if found, e.g. 'WO2024/123456 filed for novel kinase scaffold' — if not found, write 'No small molecule patents found'>",
  "si_scoring_basis": "<recent_funding | chem_hires | publications | partnerships | patents | none>",

  "auto_disqualified": <true|false>,
  "disqualify_reason": "<reason if auto_disqualified is true — if false, write 'Not disqualified'>",
  "dq_is_biologics_only": "<evidence if triggered, e.g. 'Pipeline is 100% monoclonal antibodies' — if not triggered, write 'Not biologics-only'>",
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

STAGE2_RABBIT_HOLE_SYSTEM = """You are a research investigator. You have been given a SPECIFIC question about a company that a previous analyst could not answer. Your job is to find the answer.

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

# ─────────────────────────────────────────────────────────────
# Stage 3 Prompts — Categorical Agents (Test B logic)
# ─────────────────────────────────────────────────────────────

STAGE3_CATEGORY_PROMPTS = {
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
- Bulk API / commodity manufacturing ONLY (no discovery chemistry — generics, scale-up, packaging)
- Pure software/platform without wet lab
- Clinical-trials-only CRO (no wet chemistry)
- Academic without industry drug discovery partnerships

CRITICAL — DO NOT DISQUALIFY THESE; they do discovery chemistry and are strong fits:
- Custom synthesis / contract med chem shops
- Discovery CROs / CDMOs doing medicinal chemistry, SAR, or lead optimization (for themselves OR for clients)
- PROTAC / fragment / library-design service companies
- Any company whose website advertises "custom synthesis", "medicinal chemistry services",
  "hit-to-lead services", "lead optimization services", "discovery chemistry",
  or "compound library design"

Rule: if the company DOES discovery chemistry (own pipeline OR as a service for clients) → NOT disqualified.

PATENT CAVEAT: Contract research organizations work on clients' IP, so they often
have few or zero patents under their own name. Absence of patents is NOT a
negative signal for CROs/CDMOs advertising chemistry services — score them on
service offerings and team expertise, not patent portfolio size.

Return valid JSON:
{
  "score": <0-30>,
  "has_small_molecule_focus": <true|false>,
  "sm_active_med_chem": "<evidence string if found, e.g. 'Active GPCR kinase program in Phase 1' — if not found, write 'No active med chem programs found'>",
  "sm_cadd_capabilities": "<evidence string if found, e.g. 'In-house CADD using Schrodinger' — if not found, write 'No CADD capabilities found'>",
  "sm_hit_to_lead": "<evidence string if found, e.g. 'Lead optimization of XYZ series' — if not found, write 'No hit-to-lead activity found'>",
  "sm_virtual_screening": "<evidence string if found, e.g. 'Virtual screening of 10M compound library' — if not found, write 'No virtual screening activity found'>",
  "sm_scoring_basis": "<active_med_chem | cadd | hit_to_lead | virtual_screening | none>",
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
  "sf_is_public": "<evidence string if public, e.g. 'Listed on NASDAQ as GILD since 1992' — if private or unknown, write 'Not found in public listings — likely private'>",
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

IMPORTANT — evidence-grounded responses required. For every field:
- If you find evidence, state the specific fact and source (name, title, LinkedIn URL, team page, publication author, EDGAR filing).
- If you searched and found nothing, write exactly what you checked: e.g. "Checked team page and LinkedIn — no chemistry titles found" rather than just "none found".
- Names provided in the CONFIRMED DATA block above (from EDGAR Form 4 or OpenAlex) are REAL people at this company. Use them directly as evidence for cq_highest_role and cq_has_chemistry_team. Search for their current titles via LinkedIn or the company website.

Return valid JSON:
{
  "score": <0-25>,
  "highest_role_found": "<actual title and name if found, e.g. 'Dr. Jane Smith, Head of Medicinal Chemistry (from team page)' — or 'none found' with what you checked>",
  "cq_has_chemistry_team": "<evidence string: e.g. '12 chemists on LinkedIn including 2 senior roles' OR 'Checked LinkedIn and team page — no chemistry titles found'>",
  "cq_team_size_estimate": "<e.g. '10-20 chemists' or 'Checked LinkedIn/team page — count unknown'>",
  "cq_scoring_basis": "<head_med_chem | head_cadd | vp_drug_discovery | senior_chemist | research_scientist | none>",
  "evidence": ["<specific facts found — names, titles, LinkedIn profiles, publication author credits, EDGAR filing names>"],
  "confidence": <1-10>
}""",
        "user": "Research {domain} (https://{domain}). Focus ONLY on whether this company has chemistry decision-makers. FIRST check the pre-fetched homepage/team content provided above — use any names or titles you find there directly. Then search LinkedIn for employees with medicinal chemistry, computational chemistry, or drug discovery titles. Any names listed in the CONFIRMED DATA block are real people at this company — look up their current roles. Ignore funding, pipeline, size — just chemistry leadership.",
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
  "si_recent_funding": "<evidence string if found, e.g. '$65M Series B closed March 2025' — if not found, write 'No recent funding found'>",
  "si_funding_amount": "<dollar amount and round if found, e.g. '$65M Series B' — if not found, write 'No funding amount found'>",
  "si_recent_chem_hires": "<evidence string if found, e.g. 'Hired Director of Med Chem from Pfizer Jan 2025' — if not found, write 'No recent chemistry hires found'>",
  "si_recent_publications": "<evidence string if found, e.g. '4 SAR papers in J Med Chem 2024-2025' — if not found, write 'No recent drug discovery publications found'>",
  "si_pharma_partnerships": "<evidence string if found, e.g. 'Roche collaboration announced Sep 2024' — if not found, write 'No pharma partnerships found'>",
  "si_patent_filings": "<evidence string if found, e.g. 'WO2024/123456 filed for novel kinase scaffold' — if not found, write 'No small molecule patents found'>",
  "si_scoring_basis": "<recent_funding | chem_hires | publications | partnerships | patents | none>",
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

# ─────────────────────────────────────────────────────────────
# Shared API call
# ─────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────
# Stage 2 helpers
# ─────────────────────────────────────────────────────────────

def apply_rabbit_hole_findings(initial: dict, findings: list) -> dict:
    """Merge rabbit hole findings back into the initial assessment."""
    for finding in findings:
        if not finding.get("answer_found"):
            continue

        impact = finding.get("score_impact", {})
        category = impact.get("category", "")
        change = impact.get("suggested_score_change", "")

        if "auto_disqualify" in change.lower():
            initial["auto_disqualified"] = True
            initial["disqualify_reason"] = impact.get("reasoning", "Identified via follow-up investigation")
        elif change and "no change" not in change.lower():
            try:
                num_str = change.split(" ")[0].replace("+", "")
                delta = int(num_str)
                score_key_map = {
                    "small_molecule": "small_molecule_score",
                    "stage_fit": "stage_fit_score",
                    "contact_quality": "contact_quality_score",
                    "strategic": "strategic_score"
                }
                max_scores = {
                    "small_molecule_score": 30,
                    "stage_fit_score": 30,
                    "contact_quality_score": 25,
                    "strategic_score": 15
                }
                if category in score_key_map:
                    key = score_key_map[category]
                    old = initial.get(key, 0)
                    new = max(0, min(old + delta, max_scores.get(key, 100)))
                    initial[key] = new
            except (ValueError, IndexError):
                pass

        existing = initial.get("key_evidence", [])
        new_evidence = finding.get("evidence", [])
        initial["key_evidence"] = (existing + new_evidence)[:10]

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

# ─────────────────────────────────────────────────────────────
# Escalation decision
# ─────────────────────────────────────────────────────────────

def should_escalate(stage_a_result: dict) -> tuple:
    """Return (escalate: bool, reason: str|None)."""
    status = stage_a_result.get("qualification_status")
    auto_dq = stage_a_result.get("auto_disqualified", False)

    if status in ("MEDIUM FIT", "LOW FIT"):
        return True, f"Stage A: {status}"

    if auto_dq:
        sm_conf = stage_a_result.get("small_molecule_confidence", 10)
        if sm_conf is not None and sm_conf < 6:
            return True, f"auto_disqualified with low confidence (sm_conf={sm_conf})"

    return False, None

# ─────────────────────────────────────────────────────────────
# Stage 2: Score company with holistic agent + rabbit holes
# ─────────────────────────────────────────────────────────────

async def score_company_stage_a(session: aiohttp.ClientSession, domain: str, enrichment: dict = None) -> dict:
    total_calls = 0
    total_elapsed = 0.0
    all_citations = []
    rabbit_hole_results = []

    enrichment_context = build_enrichment_context(enrichment or {})
    user_message = (
        f"{enrichment_context}"
        f"Research and score this company: {domain}\n\n"
        f"Visit their website at https://{domain} and research them thoroughly. "
        f"Check their pipeline, team, funding, publications, and any other relevant information. "
        f"Then score them using the framework above."
    )

    try:
        initial, citations, elapsed = await perplexity_call(
            session,
            STAGE2_INITIAL_SYSTEM,
            user_message,
        )
        total_calls += 1
        total_elapsed += elapsed
        all_citations.extend(citations)
    except Exception as e:
        return {"domain": domain, "error": str(e), "elapsed_seconds": 0}

    rabbit_holes = initial.get("rabbit_holes", [])

    if rabbit_holes:
        holes_to_chase = rabbit_holes[:MAX_RABBIT_HOLES]
        rh_coroutines = [
            perplexity_call(
                session,
                STAGE2_RABBIT_HOLE_SYSTEM,
                f"Company: {domain} (https://{domain})\n\n"
                f"QUESTION TO INVESTIGATE: {hole['question']}\n\n"
                f"WHY IT MATTERS: {hole.get('why_it_matters', 'Could change ICP score')}\n\n"
                f"WHERE TO LOOK: {hole.get('where_to_look', 'Company website, LinkedIn, Crunchbase, news')}\n\n"
                f"CATEGORY THIS AFFECTS: {hole.get('affects_category', 'unknown')}\n\n"
                f"Find the answer to this specific question. Be thorough."
            )
            for hole in holes_to_chase
        ]

        rh_results = await asyncio.gather(*rh_coroutines, return_exceptions=True)

        for result in rh_results:
            if isinstance(result, Exception):
                continue
            rh_data, rh_citations, rh_elapsed = result
            total_calls += 1
            total_elapsed += rh_elapsed
            all_citations.extend(rh_citations)
            rabbit_hole_results.append(rh_data)

        if rabbit_hole_results:
            initial = apply_rabbit_hole_findings(initial, rabbit_hole_results)

    initial["domain"] = domain
    initial["citations"] = all_citations
    initial["elapsed_seconds"] = round(total_elapsed, 2)
    initial["api_calls"] = total_calls
    initial["rabbit_holes_asked"] = rabbit_holes[:MAX_RABBIT_HOLES]
    initial["rabbit_holes_answered"] = rabbit_hole_results
    return initial

# ─────────────────────────────────────────────────────────────
# Stage 3: Score company with 5 categorical agents in parallel
# ─────────────────────────────────────────────────────────────

async def call_category_agent(session: aiohttp.ClientSession, domain: str, category: str, prompts: dict, enrichment: dict = None) -> dict:
    enrichment_context = build_enrichment_context(enrichment or {}) if enrichment else ""
    user_content = enrichment_context + prompts["user"].format(domain=domain)
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": prompts["system"]},
            {"role": "user", "content": user_content}
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
    try:
        async with session.post(API_URL, json=payload, headers=headers) as resp:
            elapsed = time.time() - start
            if resp.status != 200:
                error_text = await resp.text()
                return {"category": category, "error": f"API error {resp.status}: {error_text[:200]}", "elapsed_seconds": round(elapsed, 2)}
            data = await resp.json()

        content = data["choices"][0]["message"]["content"]
        citations = data.get("citations", [])

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
        return {"category": category, "error": f"JSON parse error: {str(e)}", "elapsed_seconds": round(time.time() - start, 2)}
    except Exception as e:
        return {"category": category, "error": str(e), "elapsed_seconds": 0}


async def score_company_stage_b(session: aiohttp.ClientSession, domain: str, enrichment: dict = None) -> dict:
    tasks = [
        call_category_agent(session, domain, cat, prompts, enrichment=enrichment)
        for cat, prompts in STAGE3_CATEGORY_PROMPTS.items()
    ]
    category_results = await asyncio.gather(*tasks)

    cats = {r["category"]: r for r in category_results}
    sm = cats.get("small_molecule", {})
    sf = cats.get("stage_fit", {})
    cq = cats.get("contact_quality", {})
    si = cats.get("strategic_indicators", {})
    svc = cats.get("service_match", {})

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

    if auto_disqualified or icp_score < 40:
        qualification_status = "NO FIT"
    elif icp_score < 60:
        qualification_status = "LOW FIT"
    elif icp_score < 80:
        qualification_status = "MEDIUM FIT"
    else:
        qualification_status = "HIGH FIT"

    all_evidence = []
    for r in category_results:
        all_evidence.extend(r.get("evidence", []))

    total_elapsed = sum(r.get("elapsed_seconds", 0) for r in category_results)

    return {
        "domain": domain,
        "icp_score": min(icp_score, 100),
        "qualification_status": qualification_status,
        "small_molecule_score": sm.get("score", 0),
        "stage_fit_score": sf.get("score", 0),
        "contact_quality_score": cq.get("score", 0),
        "strategic_score": si.get("score", 0),
        "sm_active_med_chem": sm.get("sm_active_med_chem"),
        "sm_cadd_capabilities": sm.get("sm_cadd_capabilities"),
        "sm_hit_to_lead": sm.get("sm_hit_to_lead"),
        "sm_virtual_screening": sm.get("sm_virtual_screening"),
        "sm_scoring_basis": sm.get("sm_scoring_basis"),
        "sf_scoring_basis": sf.get("sf_scoring_basis"),
        "cq_highest_role": cq.get("highest_role_found"),
        "cq_has_chemistry_team": cq.get("cq_has_chemistry_team"),
        "cq_team_size_estimate": cq.get("cq_team_size_estimate"),
        "cq_scoring_basis": cq.get("cq_scoring_basis"),
        "si_recent_funding": si.get("si_recent_funding"),
        "si_funding_amount": si.get("si_funding_amount"),
        "si_recent_chem_hires": si.get("si_recent_chem_hires"),
        "si_recent_publications": si.get("si_recent_publications"),
        "si_pharma_partnerships": si.get("si_pharma_partnerships"),
        "si_patent_filings": si.get("si_patent_filings"),
        "si_scoring_basis": si.get("si_scoring_basis"),
        "auto_disqualified": auto_disqualified,
        "disqualify_reason": disqualify_reason,
        "dq_is_biologics_only": sm.get("dq_is_biologics_only"),
        "dq_is_manufacturing_only": sm.get("dq_is_manufacturing_only"),
        "dq_is_medical_device": sm.get("dq_is_medical_device"),
        "dq_is_diagnostics_only": sm.get("dq_is_diagnostics_only"),
        "dq_is_pure_software": sm.get("dq_is_pure_software"),
        "dq_is_clinical_cro_only": sm.get("dq_is_clinical_cro_only"),
        "dq_is_academic_no_industry": sm.get("dq_is_academic_no_industry"),
        "company_type": sf.get("company_type"),
        "stage_tier": sf.get("stage_tier"),
        "stage_label": sf.get("stage_label"),
        "estimated_headcount": sf.get("estimated_headcount"),
        "sf_stage_type": sf.get("sf_stage_type"),
        "sf_funding_stage": sf.get("sf_funding_stage"),
        "sf_is_public": sf.get("sf_is_public"),
        "service_match": svc.get("service_match", []),
        "key_evidence": all_evidence[:10],
        "total_elapsed_seconds": round(total_elapsed, 2),
        "api_calls": len(category_results),
    }

# ─────────────────────────────────────────────────────────────
# Merge Stage A + Stage B into final hybrid result
# ─────────────────────────────────────────────────────────────

def merge_results(stage_a_result: dict, stage_b_result: dict = None, escalation_reason: str = None) -> dict:
    """Produce a single result dict for icp_hybrid_results.
    Final scores come from Stage B if escalated, Stage A otherwise.
    """
    if stage_b_result and not stage_b_result.get("error"):
        source = stage_b_result
        stage_reached = "B"
    else:
        source = stage_a_result
        stage_reached = "A"

    return {
        "domain": stage_a_result["domain"],
        "final_icp_score": source.get("icp_score"),
        "qualification_status": source.get("qualification_status"),
        "stage_reached": stage_reached,
        "escalation_reason": escalation_reason,
        "stage_a_score": stage_a_result.get("icp_score"),
        "stage_a_status": stage_a_result.get("qualification_status"),
        "stage_b_score": stage_b_result.get("icp_score") if stage_b_result else None,
        "stage_b_status": stage_b_result.get("qualification_status") if stage_b_result else None,
        # Category scores
        "small_molecule_score": source.get("small_molecule_score"),
        "stage_fit_score": source.get("stage_fit_score"),
        "contact_quality_score": source.get("contact_quality_score"),
        "strategic_score": source.get("strategic_score"),
        # SM sub-signals
        "sm_active_med_chem": source.get("sm_active_med_chem"),
        "sm_cadd_capabilities": source.get("sm_cadd_capabilities"),
        "sm_hit_to_lead": source.get("sm_hit_to_lead"),
        "sm_virtual_screening": source.get("sm_virtual_screening"),
        "sm_scoring_basis": source.get("sm_scoring_basis"),
        # SF sub-signals
        "sf_stage_type": source.get("sf_stage_type"),
        "sf_employee_range": source.get("sf_employee_range") or source.get("estimated_headcount"),
        "sf_funding_stage": source.get("sf_funding_stage"),
        "sf_is_public": source.get("sf_is_public"),
        "sf_scoring_basis": source.get("sf_scoring_basis"),
        # CQ sub-signals
        "cq_highest_role": source.get("cq_highest_role"),
        "cq_has_chemistry_team": source.get("cq_has_chemistry_team"),
        "cq_team_size_estimate": source.get("cq_team_size_estimate"),
        "cq_scoring_basis": source.get("cq_scoring_basis"),
        # SI sub-signals
        "si_recent_funding": source.get("si_recent_funding"),
        "si_funding_amount": source.get("si_funding_amount"),
        "si_recent_chem_hires": source.get("si_recent_chem_hires"),
        "si_recent_publications": source.get("si_recent_publications"),
        "si_pharma_partnerships": source.get("si_pharma_partnerships"),
        "si_patent_filings": source.get("si_patent_filings"),
        "si_scoring_basis": source.get("si_scoring_basis"),
        # DQ sub-signals
        "auto_disqualified": source.get("auto_disqualified", False),
        "disqualify_reason": source.get("disqualify_reason"),
        "dq_is_biologics_only": source.get("dq_is_biologics_only"),
        "dq_is_manufacturing_only": source.get("dq_is_manufacturing_only"),
        "dq_is_medical_device": source.get("dq_is_medical_device"),
        "dq_is_diagnostics_only": source.get("dq_is_diagnostics_only"),
        "dq_is_pure_software": source.get("dq_is_pure_software"),
        "dq_is_clinical_cro_only": source.get("dq_is_clinical_cro_only"),
        "dq_is_academic_no_industry": source.get("dq_is_academic_no_industry"),
        # Meta
        "company_type": source.get("company_type"),
        "stage_tier": source.get("stage_tier"),
        "stage_label": source.get("stage_label"),
        "estimated_headcount": source.get("estimated_headcount"),
        "service_match": source.get("service_match", []),
        "reasoning": source.get("reasoning"),
        "key_evidence": source.get("key_evidence", []),
        # Source data (always from emolecules_data_by_company)
        "source_user_count": stage_a_result.get("source_user_count"),
        "source_total_sessions": stage_a_result.get("source_total_sessions"),
        "source_last_active": stage_a_result.get("source_last_active"),
        # Pipeline meta
        "api_calls_total": (
            stage_a_result.get("api_calls", 1) +
            (stage_b_result.get("api_calls", 0) if stage_b_result else 0)
        ),
        "elapsed_total": round(
            stage_a_result.get("elapsed_seconds", 0) +
            (stage_b_result.get("total_elapsed_seconds", 0) if stage_b_result else 0),
            2
        ),
        "scored_at": datetime.now(timezone.utc).isoformat()
    }

# ─────────────────────────────────────────────────────────────
# Pre-enrichment data fetch + context builder
# ─────────────────────────────────────────────────────────────

async def fetch_all_enrichment(session: aiohttp.ClientSession) -> dict:
    """
    Load all rows from icp_enrichment into a domain-keyed dict.
    Returns {} if the table is empty or unreachable.
    """
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    enrichment = {}
    page_size = 1000
    offset = 0
    while True:
        url = (
            f"{SUPABASE_URL}/rest/v1/icp_enrichment"
            f"?select=domain,is_public,ticker,exchange,ct_total_trials,"
            f"sig_is_public,sig_sf_employee_range,sig_si_recent_funding,"
            f"sig_si_recent_publications,sig_si_patent_filings,"
            f"sig_sm_active_med_chem,sig_sm_cadd,sig_sm_hit_to_lead,sig_sm_virtual_screening,"
            f"sig_cq_exec_names,sig_cq_authors,site_summary_text,sig_web_people,sig_web_context"
            f"&limit={page_size}&offset={offset}"
        )
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                break
            rows = await resp.json()
            if not rows:
                break
            for r in rows:
                enrichment[r["domain"]] = r
            if len(rows) < page_size:
                break
            offset += page_size
    return enrichment


def build_enrichment_context(enrichment: dict) -> str:
    """
    Format pre-enrichment signal strings into a context block for agent prompts.
    Only includes fields that have a non-trivial value.
    """
    if not enrichment:
        return ""

    lines = []

    sig = enrichment.get("sig_is_public", "")
    if sig:
        lines.append(f"- Public status (SEC EDGAR): {sig}")

    sig = enrichment.get("sig_sf_employee_range", "")
    if sig and sig != "Unknown — private company":
        lines.append(f"- Employee range (EDGAR 10-K): {sig}")

    sig = enrichment.get("sig_si_recent_funding", "")
    if sig and "No recent offering" not in sig:
        lines.append(f"- Recent SEC filing: {sig}")

    sig = enrichment.get("sig_sm_active_med_chem", "")
    if sig and "No confirmed" not in sig:
        lines.append(f"- Small molecule activity: {sig}")

    ct_total = enrichment.get("ct_total_trials") or 0
    if ct_total > 0:
        lines.append(f"- ClinicalTrials.gov: {ct_total} total interventional trials as lead sponsor")

    sig = enrichment.get("sig_sm_hit_to_lead", "")
    if sig and "No active" not in sig:
        lines.append(f"- Active clinical trials: {sig}")

    sig = enrichment.get("sig_sm_cadd", "")
    if sig and "No CADD" not in sig:
        lines.append(f"- CADD publications: {sig}")

    sig = enrichment.get("sig_sm_virtual_screening", "")
    if sig and "No virtual" not in sig:
        lines.append(f"- Virtual screening publications: {sig}")

    sig = enrichment.get("sig_si_recent_publications", "")
    if sig and "No drug discovery" not in sig:
        lines.append(f"- Drug discovery publications: {sig}")

    sig = enrichment.get("sig_si_patent_filings", "")
    if sig and "No patents" not in sig:
        if "unavailable" in sig.lower():
            lines.append("- Patent filings: NOT CHECKED THIS RUN — write exactly 'Patent lookup not run' for si_patent_filings, do not search independently")
        else:
            lines.append(f"- Patent filings: {sig}")

    if not lines:
        # Always include public status even if negative — it's confirmed data
        sig = enrichment.get("sig_is_public", "")
        if sig:
            lines.append(f"- Public status (SEC EDGAR): {sig}")

    # ── Executive / researcher names ─────────────────────────
    sig = enrichment.get("sig_cq_exec_names", "")
    if sig:
        lines.append(f"- Chemistry executives (SEC EDGAR Form 4): {sig}")

    sig = enrichment.get("sig_cq_authors", "")
    if sig:
        lines.append(f"- Researcher names (OpenAlex publications): {sig}")

    if not lines:
        return ""

    header = (
        "CONFIRMED DATA FROM STRUCTURED SOURCES "
        "(treat these as verified facts — do not contradict):\n"
        + "\n".join(lines)
        + "\n\n"
    )

    # ── Web search findings (Perplexity) ─────────────────────
    web_ctx = enrichment.get("sig_web_context", "")
    if web_ctx:
        header += (
            "WEB SEARCH FINDINGS (Perplexity live search — treat as strong evidence):\n"
            + web_ctx
            + "\n\n"
        )

    # ── Homepage / team page content ─────────────────────────
    site_text = enrichment.get("site_summary_text", "")
    if site_text:
        # Cap at 8000 chars to capture more team/pipeline/news content
        preview = site_text[:8000]
        if len(site_text) > 8000:
            preview += "\n[...site content truncated...]"
        header += (
            "HOMEPAGE / TEAM PAGE CONTENT (pre-fetched — use as primary evidence "
            "for chemistry team, pipeline, and executive names):\n"
            + preview
            + "\n\n"
        )

    return header


# ─────────────────────────────────────────────────────────────
# Data fetch from Supabase
# ─────────────────────────────────────────────────────────────

async def fetch_all_companies(session: aiohttp.ClientSession, limit: int = None) -> list:
    """Fetch companies from emolecules_data_by_company, excluding discarded domains."""
    base_headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    # Fetch discarded domains
    print("  Fetching discarded domains...")
    discarded_domains = set()
    url = f"{SUPABASE_URL}/rest/v1/discarded_email_suggestion?select=domain&limit=10000"
    async with session.get(url, headers=base_headers) as resp:
        if resp.status == 200:
            rows = await resp.json()
            discarded_domains = {r["domain"] for r in rows if r.get("domain")}
    print(f"  {len(discarded_domains)} discarded domains loaded")

    # Paginate through emolecules_data_by_company
    print("  Fetching companies from emolecules_data_by_company...")
    companies = []
    page_size = 1000
    offset = 0

    while True:
        url = (
            f"{SUPABASE_URL}/rest/v1/emolecules_data_by_company"
            f"?select=domain,user_count,total_sessions,last_active"
            f"&order=total_sessions.desc"
            f"&limit={page_size}&offset={offset}"
        )
        async with session.get(url, headers=base_headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Failed to fetch companies: {resp.status} — {text[:200]}")
            page = await resp.json()
            if not page:
                break
            companies.extend(page)
            if len(page) < page_size:
                break
            offset += page_size

    filtered = [c for c in companies if c["domain"] not in discarded_domains]
    print(f"  {len(companies)} companies total, {len(filtered)} after excluding discarded domains")

    if limit:
        filtered = filtered[:limit]
        print(f"  Limited to {len(filtered)} for test run")

    return filtered

# ─────────────────────────────────────────────────────────────
# Supabase write
# ─────────────────────────────────────────────────────────────

async def upsert_hybrid_result(session: aiohttp.ClientSession, result: dict):
    """Upsert a single merged result to icp_hybrid_results."""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    url = f"{SUPABASE_URL}/rest/v1/{TARGET_TABLE}"
    async with session.post(url, json=result, headers=headers) as resp:
        if resp.status not in (200, 201):
            text = await resp.text()
            print(f"    Supabase write error for {result['domain']}: {resp.status} — {text[:120]}")

# ─────────────────────────────────────────────────────────────
# Pipeline orchestration
# ─────────────────────────────────────────────────────────────

async def run_pipeline(companies: list, session: aiohttp.ClientSession) -> list:
    """Run the full hybrid pipeline: Stage 2 on all, Stage 3 on escalated."""
    domains = [c["domain"] for c in companies]
    source_by_domain = {c["domain"]: c for c in companies}
    total = len(domains)

    # Load pre-enrichment data once — injected into every agent prompt
    print("Loading pre-enrichment data from icp_enrichment...")
    enrichment_by_domain = await fetch_all_enrichment(session)
    covered = sum(1 for d in domains if d in enrichment_by_domain)
    print(f"  {covered}/{total} companies have pre-enrichment data\n")

    print(f"\n{'='*65}")
    print(f"STAGE 2 — HOLISTIC AGENT ({total} companies, batch={BATCH_SIZE})")
    print(f"Model: {MODEL}")
    print(f"{'='*65}\n")

    stage_a_by_domain = {}
    total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

    async with aiohttp.ClientSession() as s2:
        for i in range(0, total, BATCH_SIZE):
            batch = domains[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            print(f"Batch {batch_num}/{total_batches}: {', '.join(batch[:5])}{'...' if len(batch) > 5 else ''}")

            tasks = [score_company_stage_a(s2, domain, enrichment=enrichment_by_domain.get(domain)) for domain in batch]
            batch_results = await asyncio.gather(*tasks)

            for r in batch_results:
                src = source_by_domain.get(r["domain"], {})
                r["source_user_count"] = src.get("user_count")
                r["source_total_sessions"] = src.get("total_sessions")
                r["source_last_active"] = src.get("last_active")
                stage_a_by_domain[r["domain"]] = r

                if r.get("error"):
                    print(f"  {r['domain']}: ERROR — {r['error'][:80]}")
                else:
                    score = r.get("icp_score", "N/A")
                    status = r.get("qualification_status", "?")
                    calls = r.get("api_calls", 1)
                    holes = len(r.get("rabbit_holes_asked", []))
                    rh_str = f" [{holes} rabbit holes]" if holes else ""
                    escalate, reason = should_escalate(r)
                    esc_str = f" → ESCALATE ({reason})" if escalate else ""
                    print(f"  {r['domain']}: {score}/100 ({status}) [{calls} call(s)]{rh_str}{esc_str}")

            if i + BATCH_SIZE < total:
                await asyncio.sleep(DELAY_BETWEEN_BATCHES)

    # Determine escalations
    to_escalate = []
    escalation_reasons = {}
    for domain, r in stage_a_by_domain.items():
        if r.get("error"):
            continue
        escalate, reason = should_escalate(r)
        if escalate:
            to_escalate.append(domain)
            escalation_reasons[domain] = reason

    a_high = sum(1 for r in stage_a_by_domain.values() if r.get("qualification_status") == "HIGH FIT" and not r.get("error"))
    a_medium = sum(1 for r in stage_a_by_domain.values() if r.get("qualification_status") == "MEDIUM FIT" and not r.get("error"))
    a_low = sum(1 for r in stage_a_by_domain.values() if r.get("qualification_status") == "LOW FIT" and not r.get("error"))
    a_no = sum(1 for r in stage_a_by_domain.values() if r.get("qualification_status") == "NO FIT" and not r.get("error"))
    a_errors = sum(1 for r in stage_a_by_domain.values() if r.get("error"))

    print(f"\nStage 2 complete:")
    print(f"  HIGH FIT:  {a_high} → accepted")
    print(f"  MEDIUM FIT: {a_medium} → escalating")
    print(f"  LOW FIT:   {a_low} → escalating")
    print(f"  NO FIT:    {a_no} ({a_no - sum(1 for d in to_escalate if stage_a_by_domain[d].get('qualification_status') == 'NO FIT')} accepted, "
          f"{sum(1 for d in to_escalate if stage_a_by_domain[d].get('qualification_status') == 'NO FIT')} low-confidence auto-dq → escalating)")
    print(f"  Errors:    {a_errors}")
    print(f"  Escalating {len(to_escalate)} companies to Stage 3 ({len(to_escalate)/max(total,1)*100:.1f}%)")

    # Stage 3: score escalated companies
    stage_b_by_domain = {}

    if to_escalate:
        print(f"\n{'='*65}")
        print(f"STAGE 3 — CATEGORICAL AGENTS ({len(to_escalate)} escalated, batch={BATCH_SIZE})")
        print(f"{'='*65}\n")

        total_b = len(to_escalate)
        total_b_batches = (total_b + BATCH_SIZE - 1) // BATCH_SIZE

        async with aiohttp.ClientSession() as s3:
            for i in range(0, total_b, BATCH_SIZE):
                batch = to_escalate[i:i + BATCH_SIZE]
                batch_num = (i // BATCH_SIZE) + 1
                print(f"Batch {batch_num}/{total_b_batches}: {', '.join(batch[:5])}{'...' if len(batch) > 5 else ''}")

                tasks = [score_company_stage_b(s3, domain, enrichment=enrichment_by_domain.get(domain)) for domain in batch]
                batch_results = await asyncio.gather(*tasks)

                for r in batch_results:
                    stage_b_by_domain[r["domain"]] = r
                    if r.get("error"):
                        print(f"  {r['domain']}: Stage B ERROR — {r['error'][:80]}")
                    else:
                        score = r.get("icp_score", "N/A")
                        status = r.get("qualification_status", "?")
                        sm = r.get("small_molecule_score", "?")
                        sf = r.get("stage_fit_score", "?")
                        cq = r.get("contact_quality_score", "?")
                        si = r.get("strategic_score", "?")
                        print(f"  {r['domain']}: {score}/100 ({status}) [SM:{sm} SF:{sf} CQ:{cq} SI:{si}]")

                if i + BATCH_SIZE < total_b:
                    await asyncio.sleep(DELAY_BETWEEN_BATCHES)

    # Merge results and write to Supabase
    print(f"\n{'='*65}")
    print(f"Writing results to Supabase → {TARGET_TABLE}")
    print(f"{'='*65}\n")

    final_results = []
    async with aiohttp.ClientSession() as sw:
        for domain in domains:
            stage_a = stage_a_by_domain.get(domain)
            if not stage_a:
                continue

            if stage_a.get("error"):
                continue

            stage_b = stage_b_by_domain.get(domain)
            reason = escalation_reasons.get(domain)
            merged = merge_results(stage_a, stage_b, reason)
            final_results.append(merged)
            await upsert_hybrid_result(sw, merged)

    return final_results

# ─────────────────────────────────────────────────────────────
# Entry point with confirmation prompts
# ─────────────────────────────────────────────────────────────

async def main():
    print(f"\n{'='*65}")
    print("HYBRID ICP PIPELINE")
    print("Stage 1 (pre-screen): already done — discarded_email_suggestion")
    print("Stage 2: Holistic agent on all remaining companies")
    print("Stage 3: Categorical agents on escalated companies")
    print(f"Target table: {TARGET_TABLE}")
    print(f"Batch size: {BATCH_SIZE} concurrent workers per stage")
    print(f"{'='*65}\n")

    # Load companies first so we can show the count
    print("Loading company list from Supabase...")
    async with aiohttp.ClientSession() as session:
        all_companies = await fetch_all_companies(session, limit=None)

    print(f"\nReady to process {len(all_companies)} companies.\n")

    # Skip interactive prompt when running non-interactively (e.g. Render)
    import sys
    if not sys.stdin.isatty():
        print("Non-interactive mode — skipping test, running full pipeline.\n")
        answer = "n"
    else:
        try:
            answer = input("Run a test on 10 companies first? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return

    if answer not in ("n", "no"):
        test_companies = all_companies[:10]
        print(f"\nRunning test on {len(test_companies)} companies...\n")

        async with aiohttp.ClientSession() as session:
            test_results = await run_pipeline(test_companies, session)

        print(f"\n{'='*65}")
        print("TEST RUN COMPLETE")
        print(f"{'='*65}")
        for r in test_results:
            stage = r.get("stage_reached", "?")
            print(f"  {r['domain']}: {r.get('final_icp_score')}/100 ({r.get('qualification_status')}) [Stage {stage}]")

        print(f"\nVerify the results above and check Supabase → {TARGET_TABLE}")

        try:
            answer2 = input(f"\nRun full pipeline on all {len(all_companies)} companies? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return

        if answer2 not in ("y", "yes"):
            print("Full run cancelled.")
            return

        # Full run — skip the 10 we already scored
        remaining = all_companies[10:]
        print(f"\nRunning full pipeline on remaining {len(remaining)} companies...\n")
        async with aiohttp.ClientSession() as session:
            full_results = await run_pipeline(remaining, session)
        all_final = test_results + full_results
    else:
        # Skip test, run everything
        print(f"\nRunning full pipeline on all {len(all_companies)} companies...\n")
        async with aiohttp.ClientSession() as session:
            all_final = await run_pipeline(all_companies, session)

    # Summary + local backup
    high = sum(1 for r in all_final if r.get("qualification_status") == "HIGH FIT")
    medium = sum(1 for r in all_final if r.get("qualification_status") == "MEDIUM FIT")
    low = sum(1 for r in all_final if r.get("qualification_status") == "LOW FIT")
    no_fit = sum(1 for r in all_final if r.get("qualification_status") == "NO FIT")
    stage_b_count = sum(1 for r in all_final if r.get("stage_reached") == "B")
    total_calls = sum(r.get("api_calls_total", 0) for r in all_final)

    print(f"\n{'='*65}")
    print("PIPELINE COMPLETE — SUMMARY")
    print(f"{'='*65}")
    print(f"  Total companies scored: {len(all_final)}")
    print(f"  HIGH FIT:   {high}")
    print(f"  MEDIUM FIT: {medium}")
    print(f"  LOW FIT:    {low}")
    print(f"  NO FIT:     {no_fit}")
    print(f"  Went to Stage 3: {stage_b_count} ({stage_b_count/max(len(all_final),1)*100:.1f}%)")
    print(f"  Total API calls: {total_calls}")
    print(f"  Avg calls/company: {total_calls/max(len(all_final),1):.1f}")

    os.makedirs("results", exist_ok=True)
    output_path = "results/hybrid_pipeline_results.json"
    with open(output_path, "w") as f:
        json.dump({
            "run_at": datetime.now().isoformat(),
            "model": MODEL,
            "total_companies": len(all_final),
            "stage_b_escalated": stage_b_count,
            "total_api_calls": total_calls,
            "summary": {
                "high_fit": high,
                "medium_fit": medium,
                "low_fit": low,
                "no_fit": no_fit,
            },
            "results": all_final
        }, f, indent=2)
    print(f"\nResults saved to Supabase ({TARGET_TABLE}) + {output_path}")


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: Set OPENROUTER_API_KEY in .env file")
        sys.exit(1)
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_KEY in .env file")
        sys.exit(1)
    asyncio.run(main())
