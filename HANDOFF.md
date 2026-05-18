# Hybrid Pipeline Handoff

## What We're Building
A hybrid ICP scoring pipeline for eMolecules — a chemical supplier targeting drug discovery organizations. The pipeline scores company domains from the eMolecules session database to identify which companies are the best fit for their services (Building Blocks, Screening Compounds, Virtual Libraries, Compound Management).

## The Problem We're Solving
The original pipeline asked LLMs (Perplexity Sonar) to find structured facts cold — company size, public status, patent counts, publication history. A fill rate audit (April 9) showed this fails 85%+ of the time. 14 of 17 scored fields were BLIND (<15% fill rate). The model was scoring from absence of evidence, creating systematic bias against companies it simply couldn't find.

## The Fix: Two-Part Approach

### Part 1 — Pre-Enrichment Layer (pre_enrichment.py)
Run a deterministic data pass BEFORE the LLM agents. Pull from authoritative free APIs, write structured facts to Supabase `icp_enrichment`, inject pre-populated context into every agent prompt.

**APIs wired up:**
- **SEC EDGAR** — public status, ticker, exchange, filer category (funding stage), recent offerings
- **PubMed E-utilities** — drug discovery / CADD / virtual screening publication counts (tries 3 name variants per company, takes max)
- **PatentsView** — patent count last 3 years, most recent title/date (POST to api.patentsview.org)
- **ChEMBL** — approved drug count by applicant
- **ClinicalTrials.gov v2** — total trials and active/recruiting trials by lead sponsor

**Supabase table:** `icp_enrichment` — created April 15. Contains raw counts + 9 human-readable `sig_*` signal strings ready to inject into agent prompts.

### Part 2 — Prompt Fix (all 4 agent files)
Every field that previously returned `null` when not found now requires a meaningful negative string instead. Before: agent returns `null` → field is unfilled. After: agent returns `"No active med chem programs found on website or pipeline"` → field is filled. Applied to `test_a_holistic.py`, `test_b_categorical.py`, `run_hybrid_pipeline.py` (Stage A + Stage 3 prompts).

**Files changed April 15:**
- `pre_enrichment.py` — PatentsView restored, PubMed multi-variant, patents re-enabled
- `run_hybrid_pipeline.py` — all `or null` → required negative strings (Stage A + Stage 3)
- `test_a_holistic.py` — same prompt fix
- `test_b_categorical.py` — same prompt fix

## Current State (April 15)

### Pre-enrichment: working, not yet run at scale
- `icp_enrichment` table just created in Supabase (was missing — caused 0-company fetch bug)
- Single domain test (`gilead.com`) confirmed: EDGAR ✓, PubMed 53 pubs ✓, ClinicalTrials 679 ✓
- PatentsView results for Gilead not yet confirmed — check `results/pre_enrichment_results.json`
- **Next step:** `python3 pre_enrichment.py --limit 50` to test full batch, then full run

### Agent pipeline: not re-run since prompt changes
- Last pipeline run was April 1 (`results/hybrid_pipeline_results.json`, 489 companies)
- Fill rates from that run: most fields 2–14% (BLIND)
- Prompt changes predict ~100% fill rate on next run (negative strings instead of null)
- **Next step:** run pipeline on 20–30 companies and re-run `generate_fill_rate_report.py`

## Fill Rate Baseline (April 9, pre-changes)
| Field | Before | Expected After |
|---|---|---|
| sm_active_med_chem | 8% | ~100% (prompt fix) |
| sm_cadd_capabilities | 4% | ~100% (prompt fix) |
| sm_hit_to_lead | 10% | ~100% (prompt fix) |
| sm_virtual_screening | 0% | ~100% (prompt fix) |
| sf_is_public | 14% | ~100% (EDGAR) |
| sf_funding_stage | 60% | ~90% (EDGAR) |
| si_recent_publications | 6% | ~85% (PubMed multi-variant) |
| si_patent_filings | 2% | ~80% (PatentsView restored) |
| si_recent_funding | 8% | ~60% (EDGAR offerings) |
| cq_highest_role | 8% | ~40% (prompt fix forces response) |
| cq_has_chemistry_team | 14% | ~40% (prompt fix forces response) |

## Remaining Gaps (Phase 2/3 from the plan)
- `sf_employee_range` for private companies → Crunchbase Basic API ($29/mo)
- `si_recent_funding` for private companies → Crunchbase Basic API
- `cq_*` fields with verified contacts → Apollo.io ($49/mo)
- `sf_employee_range` from 10-K for public companies → never implemented in fetcher

## Key Files
- `pre_enrichment.py` — pre-enrichment layer (run first, before pipeline)
- `run_hybrid_pipeline.py` — main hybrid pipeline (Stage A holistic → Stage B categorical)
- `test_a_holistic.py` — standalone Stage A holistic agent
- `test_b_categorical.py` — standalone Stage B categorical agents
- `generate_fill_rate_report.py` — generates fill rate scorecard from pipeline results
- `results/hybrid_pipeline_results.json` — last full pipeline run (April 1, 489 companies)
- `results/pre_enrichment_results.json` — last pre-enrichment run (gilead.com only as of April 15)
- `.env` — SUPABASE_URL, SUPABASE_KEY, OPENROUTER_API_KEY, NCBI_API_KEY
- `CLAUDE.md` — Supabase table schemas

## Supabase Tables
- `emolecules_data_by_company` — source company list (5,224 domains)
- `discarded_email_suggestion` — pre-screened out domains (academic, etc.)
- `icp_enrichment` — pre-enrichment output (created April 15)
- `icp_hybrid_results` — final pipeline scores

## Open Questions
1. **Scale / rate limits** — How many domains are you enriching in a typical batch? PubMed at 3 req/sec without an API key (10/sec with) could bottleneck at thousands of companies. At 489 companies × 3 PubMed queries × 3 name variants = ~4,400 requests — that's ~25 minutes at 3/sec just for PubMed. Worth registering for a free NCBI API key (`NCBI_API_KEY` in `.env`) to 3× throughput.

2. **Perplexity Sonar usage** — Is Sonar running as the Stage A holistic agent, Stage B categorical agents, or both? This matters for where the pre-enrichment context injection has the most leverage — and for cost estimation if you're paying per Sonar call.

3. **Supabase schema: raw vs. derived** — The current `icp_enrichment` table stores raw counts (e.g. `pubmed_drug_discovery_count`, `ct_total_trials`) plus 9 pre-built `sig_*` signal strings. The agents receive the signal strings, not the raw numbers. If you want to change signal wording later without re-running enrichment, the raw counts are there to rebuild from.
