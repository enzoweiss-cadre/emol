"""
Smoke test: can perplexity/sonar-pro via OpenRouter do structured tool-calling reliably?

Goal: validate that we can move Stage 2A off inline JSON-schema prompts onto a proper
tool-call pattern with few-shot examples.

Runs on 10 companies (mix of clear HIGH/MEDIUM/NO FIT). For each we measure:
  - HTTP success
  - Did the model invoke the tool (vs return plain text)?
  - Did the tool arguments parse as JSON?
  - Do the arguments match the schema?
  - Token counts + elapsed time

Usage: python3 smoketest_sonar_tool_calling.py
"""

import asyncio, aiohttp, json, os, time
from typing import Any

# ── env ──────────────────────────────────────────────────────
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if v and not os.environ.get(k):
                        os.environ[k] = v
load_env()

API_KEY = os.environ.get("OPENROUTER_API_KEY")
MODEL   = "perplexity/sonar-pro"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# ── tool definition ─────────────────────────────────────────
# Subset of the full Stage A schema — enough to validate structured output works.
ICP_TOOL = {
    "type": "function",
    "function": {
        "name": "score_company_icp",
        "description": (
            "Return an evidence-grounded ICP score for the researched company. "
            "Call this exactly once with the final assessment after web research. "
            "Every string field must cite the source (website URL, EDGAR filing, ChEMBL ID, "
            "PubMed ID, etc.) — bare 'not found' is not acceptable. If a field cannot be "
            "verified, use the exact token 'UNKNOWN' so the caller knows it's unverified."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "final_icp_score", "qualification_status",
                "small_molecule_score", "stage_fit_score",
                "contact_quality_score", "strategic_score",
                "sm_active_med_chem", "sf_is_public",
                "cq_has_chemistry_team", "si_patent_filings",
                "company_type", "reasoning",
            ],
            "properties": {
                "final_icp_score":        {"type": "integer", "minimum": 0, "maximum": 100},
                "qualification_status":   {"type": "string", "enum": ["HIGH FIT","MEDIUM FIT","LOW FIT","NO FIT"]},
                "small_molecule_score":   {"type": "integer", "minimum": 0, "maximum": 30},
                "stage_fit_score":        {"type": "integer", "minimum": 0, "maximum": 30},
                "contact_quality_score":  {"type": "integer", "minimum": 0, "maximum": 25},
                "strategic_score":        {"type": "integer", "minimum": 0, "maximum": 15},
                "sm_active_med_chem":     {"type": "string", "description": "Evidence + source. e.g. 'Active med chem program on lilly.com pipeline page' or 'UNKNOWN'."},
                "sf_is_public":           {"type": "string", "description": "Listed status with source. e.g. 'Public on NASDAQ as GILD (SEC EDGAR)' or 'Private per Crunchbase' or 'UNKNOWN'."},
                "cq_has_chemistry_team":  {"type": "string", "description": "Team evidence with source. e.g. '12 chemists on LinkedIn; head of med chem is X' or 'UNKNOWN'."},
                "si_patent_filings":      {"type": "string", "description": "Patent evidence. e.g. '329 pharma patents in EPO OPS, recent KRAS work' or 'UNKNOWN'."},
                "company_type":           {"type": "string", "enum": ["Pharma","Biotech","CRO/CDMO","Tool/Instrumentation","Academic","Other"]},
                "reasoning":              {"type": "string", "description": "2-3 sentences explaining the score with specific facts."},
            },
        },
    },
}

FEW_SHOTS = """
Example of a correct tool call — HIGH FIT pharma:
{
  "final_icp_score": 92,
  "qualification_status": "HIGH FIT",
  "small_molecule_score": 28,
  "stage_fit_score": 30,
  "contact_quality_score": 22,
  "strategic_score": 12,
  "sm_active_med_chem": "19 approved small molecules in ChEMBL (e.g. CHEMBL152, CHEMBL158); active kinase inhibitor pipeline on gilead.com/science",
  "sf_is_public": "Listed NASDAQ as GILD since 1992 (SEC EDGAR CIK 0000882095)",
  "cq_has_chemistry_team": "300+ LinkedIn profiles at Gilead with 'medicinal chemistry' in title; Head of Med Chem is Dr. Sean Cho",
  "si_patent_filings": "329 pharma-class patents last 3 years (EPO OPS, CPC A61K/C07D); recent: 'KRAS Modulating Compounds'",
  "company_type": "Pharma",
  "reasoning": "Large-cap pharma with active small-molecule medicinal chemistry programs across virology and oncology. 19 approved drugs, 394 total patents (329 pharma-class), 679 clinical trials. Core ICP profile."
}

Example of a correct tool call — NO FIT non-pharma:
{
  "final_icp_score": 5,
  "qualification_status": "NO FIT",
  "small_molecule_score": 3,
  "stage_fit_score": 2,
  "contact_quality_score": 0,
  "strategic_score": 0,
  "sm_active_med_chem": "No active med chem pipeline — Thermo Fisher's business is analytical instruments and reagents per thermofisher.com. Only 4 of 285 total patents are pharma-class per EPO OPS CPC filter.",
  "sf_is_public": "Listed NYSE as TMO (SEC EDGAR CIK 0000097745)",
  "cq_has_chemistry_team": "Analytical chemistry staff exists but no medicinal-chemistry roles visible on LinkedIn search",
  "si_patent_filings": "285 total patents in EPO OPS but only 4 pharma-class (CPC A61K/C07D); recent titles focus on mass spectrometry and protein sample prep",
  "company_type": "Tool/Instrumentation",
  "reasoning": "Tool and reagent manufacturer, not a drug-discovery organization. Patent portfolio is >98% non-pharma — this is a supplier-side company, not an ICP target."
}
"""

SYSTEM = f"""You are an ICP qualification analyst for eMolecules (chemical supplier for drug discovery). Your job: research a company from its domain, then call the `score_company_icp` tool exactly once with an evidence-grounded assessment.

IMPORTANT:
- Every evidence string must cite a specific source (website URL, SEC filing, ChEMBL ID, PubMed ID, EPO patent, LinkedIn profile). Bare "not found" / "no evidence" is not acceptable — return the literal token "UNKNOWN" instead.
- CRO/CDMO companies doing discovery chemistry (custom synthesis, med chem services, PROTAC design) are HIGH FIT customers, NOT disqualified.
- Tool/instrument companies, bulk-API manufacturing, medical devices, academia, and pure biologics → NO FIT / disqualify.

Here are two correct example outputs so you understand the shape and evidence style required:
{FEW_SHOTS}

Now research the company the user asks about and call the tool."""

# ── test set ────────────────────────────────────────────────
TEST_DOMAINS = [
    ("gilead.com",          "HIGH FIT",  "big pharma"),
    ("lilly.com",           "HIGH FIT",  "big pharma"),
    ("aurigene.com",        "HIGH FIT",  "chemistry CRO"),
    ("selvita.com",         "HIGH FIT",  "chemistry CDMO"),
    ("vividion.com",        "MEDIUM FIT","emerging biotech"),
    ("boundlessbio.com",    "MEDIUM FIT","emerging biotech"),
    ("thermofisher.com",    "NO FIT",    "tool co"),
    ("its.jnj.com",         "NO FIT",    "J&J consumer subdomain"),
    ("colostate.edu",       "NO FIT",    "academic"),
    ("osmo.ai",             "NO FIT",    "AI fragrance platform"),
]

# ── call helper ─────────────────────────────────────────────
async def call_with_tool(session, domain: str) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": f"Research {domain} (https://{domain}). Score against eMolecules ICP (small molecule drug discovery)."},
        ],
        "tools": [ICP_TOOL],
        "tool_choice": "required",   # force the tool call
        "temperature": 0.1,
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://emolecules.com",
        "X-Title":       "eMolecules ICP Smoketest",
    }
    t0 = time.time()
    try:
        async with session.post(API_URL, json=payload, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=120)) as resp:
            elapsed = round(time.time() - t0, 2)
            status = resp.status
            body = await resp.text()
    except Exception as e:
        return {"domain": domain, "http_error": str(e), "elapsed": round(time.time()-t0,2)}

    if status != 200:
        return {"domain": domain, "http_status": status, "http_body": body[:300], "elapsed": elapsed}

    try:
        data = json.loads(body)
    except Exception as e:
        return {"domain": domain, "json_parse_error": str(e), "body_preview": body[:300], "elapsed": elapsed}

    msg = data.get("choices",[{}])[0].get("message", {})
    tool_calls = msg.get("tool_calls") or []
    content = msg.get("content", "")
    usage = data.get("usage", {})

    result = {
        "domain": domain,
        "elapsed": elapsed,
        "tool_call_present": bool(tool_calls),
        "raw_content_len": len(content or ""),
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
    }

    if not tool_calls:
        result["fallback_content_preview"] = (content or "")[:300]
        return result

    # Parse first tool call args
    call = tool_calls[0]
    fn = call.get("function", {})
    result["tool_name_returned"] = fn.get("name")
    args_raw = fn.get("arguments", "")
    result["args_raw_len"] = len(args_raw)
    try:
        args = json.loads(args_raw)
        result["args_parsed"] = True
        # Check schema compliance
        required = ICP_TOOL["function"]["parameters"]["required"]
        missing = [k for k in required if k not in args]
        result["missing_fields"] = missing
        # Type sanity
        score = args.get("final_icp_score")
        result["score_type_ok"] = isinstance(score, int) and 0 <= score <= 100
        result["score"] = score
        result["status"] = args.get("qualification_status")
        # Evidence quality spot-check — does sm_active_med_chem cite something?
        sm = args.get("sm_active_med_chem", "")
        has_source = any(x in sm.lower() for x in ['chembl','edgar','epo','pubmed','.com','.edu','.org','linkedin','doi','patent','clinicaltrials','openalex','pdb'])
        result["sm_has_source_citation"] = has_source or sm.strip().upper() == "UNKNOWN"
        result["sm_preview"] = sm[:200]
    except Exception as e:
        result["args_parse_error"] = str(e)
        result["args_preview"] = args_raw[:300]

    return result

# ── runner ──────────────────────────────────────────────────
async def main():
    print(f"Model: {MODEL}")
    print(f"Running {len(TEST_DOMAINS)} companies with tool_choice='required'\n")
    async with aiohttp.ClientSession() as s:
        results = []
        for i, (domain, expected, note) in enumerate(TEST_DOMAINS, 1):
            print(f"  [{i}/{len(TEST_DOMAINS)}] {domain} (expect {expected}, {note})...", end=" ", flush=True)
            r = await call_with_tool(s, domain)
            r["expected"] = expected
            r["note"] = note
            results.append(r)
            # Summary line
            if r.get("tool_call_present"):
                if r.get("args_parsed"):
                    match = "✓" if r.get("status") == expected else ("~" if expected in ["HIGH FIT","MEDIUM FIT"] and r.get("status") in ["HIGH FIT","MEDIUM FIT"] else "✗")
                    miss = f", missing: {r.get('missing_fields')}" if r.get("missing_fields") else ""
                    src = "src-OK" if r.get("sm_has_source_citation") else "NO-SRC"
                    print(f"tool✓ parse✓ {match} {r.get('status')} ({r.get('score')}) {src}{miss} [{r['elapsed']}s, {r.get('input_tokens')}in/{r.get('output_tokens')}out]")
                else:
                    print(f"tool✓ parse✗ {r.get('args_parse_error')}")
            else:
                err = r.get("http_status") or r.get("http_error") or "no tool call"
                print(f"tool✗ {err}")

    # Roll-up
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    n = len(results)
    tool_ok = sum(1 for r in results if r.get("tool_call_present"))
    parse_ok = sum(1 for r in results if r.get("args_parsed"))
    match_ok = sum(1 for r in results if r.get("status") == r.get("expected"))
    fuzzy_match = sum(1 for r in results if r.get("status") in (["HIGH FIT","MEDIUM FIT"] if r.get("expected") in ["HIGH FIT","MEDIUM FIT"] else ["LOW FIT","NO FIT"]))
    src_ok = sum(1 for r in results if r.get("sm_has_source_citation"))
    avg_in = sum(r.get("input_tokens") or 0 for r in results) / max(n,1)
    avg_out = sum(r.get("output_tokens") or 0 for r in results) / max(n,1)
    print(f"  Tool call invoked:        {tool_ok}/{n}")
    print(f"  Args parsed as JSON:      {parse_ok}/{n}")
    print(f"  Exact status match:       {match_ok}/{n}")
    print(f"  Fuzzy high/low match:     {fuzzy_match}/{n}")
    print(f"  Evidence cites source:    {src_ok}/{n}")
    print(f"  Avg tokens:               {avg_in:.0f}in / {avg_out:.0f}out")
    est_cost_per_call = (avg_in * 3 + avg_out * 15) / 1_000_000 + 0.009
    print(f"  Est cost/call:            ${est_cost_per_call:.4f}")

    # Save detailed
    os.makedirs("results", exist_ok=True)
    with open("results/smoketest_tool_calling.json","w") as f:
        json.dump({"model": MODEL, "results": results}, f, indent=2)
    print(f"\nDetailed results → results/smoketest_tool_calling.json")

    # Verdict
    print("\n" + "="*70)
    if tool_ok == n and parse_ok == n and src_ok >= n * 0.8:
        print("VERDICT: ✅ GO — Sonar-Pro does tool-calling reliably. Safe to roll out Edit 1.")
    elif tool_ok < n * 0.6 or parse_ok < n * 0.6:
        print("VERDICT: ❌ NO-GO — tool-calling is unreliable on Sonar-Pro. Stick with inline-JSON or switch orchestration model (Claude / GPT-4o) for Stage 2A.")
    else:
        print("VERDICT: ⚠️ PARTIAL — some tool calls work but reliability is mixed. Recommend fallback: try tool-call first, parse as JSON from content if tool_call missing.")
    print("="*70)

if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: OPENROUTER_API_KEY not in .env")
        exit(1)
    asyncio.run(main())
