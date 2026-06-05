# eMolecules ICP Scoring Pipeline

Automated ICP (Ideal Customer Profile) scoring system for eMolecules. Takes company domains from eMolecules' website activity logs and scores each one 0–100 for how likely they are to be a strong buyer of eMolecules' products: Building Blocks, Screening Compounds, Virtual Libraries, and Compound Management.

---

## What this does

eMolecules has ~5,200 company domains in their session database — companies whose employees have visited the website. Most are noise (one-off visitors, academics, bots). A small fraction are serious drug discovery organizations worth pursuing as customers.

This pipeline:
1. Pulls those domains from Supabase
2. Pre-enriches each company with deterministic data (SEC EDGAR, PubMed, ClinicalTrials, patents)
3. Runs AI agents with web search to score each company across four dimensions
4. Writes final scores + evidence back to Supabase and local Excel/CSV

Final output: `results/emolecules_scores_may18.xlsx` — 4,488 scored companies with sub-scores, evidence chains, and contact quality for each.

---

## Architecture

```
Supabase: emolecules_data_by_company (5,224 domains)
         ↓
Stage 1: pre_enrichment.py
  SEC EDGAR · PubMed · OpenAlex · ChEMBL · ClinicalTrials.gov · PatentsView
  → writes structured signals to: icp_enrichment table
         ↓
Stage 2A: run_hybrid_pipeline.py (Perplexity Sonar-Pro)
  Holistic agent scores 0-100 with enrichment signals injected
  HIGH FIT (≥80) or NO FIT (<40) → accept
  MEDIUM/LOW FIT (40-79) → escalate to Stage 2B
         ↓ (escalated only)
Stage 2B: run_hybrid_pipeline.py (4 parallel categorical agents)
  SM agent  (0-30) · SF agent (0-30) · CQ agent (0-25) · SI agent (0-15)
  Final score = SM + SF + CQ + SI
         ↓
Storage: icp_hybrid_results (Supabase) + results/*.json + results/*.xlsx
```

---

## Score breakdown

| Sub-score | Max | What it measures |
|---|---|---|
| SM (Small Molecule) | 30 | Active med chem programs, CADD, hit-to-lead, virtual screening |
| SF (Stage Fit) | 30 | Company size, funding stage, public status |
| CQ (Contact Quality) | 25 | Seniority of chemistry decision-makers found |
| SI (Strategic Intel) | 15 | Patents, publications, funding rounds, pharma partnerships |
| **Total** | **100** | |

Score tiers:
- **HIGH FIT** ≥ 80 — priority outreach
- **MEDIUM FIT** 60–79 — qualified prospect
- **LOW FIT** 40–59 — nurture only
- **NO FIT** < 40 — disqualify

---

## Setup

```bash
git clone <repo>
cd emolecules-analysis
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env`:
```
OPENROUTER_API_KEY=...       # Perplexity Sonar-Pro via OpenRouter
SUPABASE_URL=...
SUPABASE_KEY=...             # service role key
NCBI_API_KEY=...             # free from NCBI — 10x PubMed throughput
PATENTSVIEW_API_KEY=...      # free from patentsview.org/apis/keyrequest
```

---

## Running the pipeline

### Full run
```bash
# Step 1 — pre-enrich
python3 pre_enrichment.py

# Step 2 — score
python3 run_hybrid_pipeline.py

# Step 3 — fetch full results from Supabase
python3 fetch_full_results.py

# Step 4 — generate location and usage sidecars
python3 enrich_location_from_ip.py
python3 enrich_research_location.py
python3 enrich_usage_windows.py

# Step 5 — export to Excel
python3 export_scores_excel.py
```

### Test run (25 companies)
```bash
python3 pre_enrichment.py --limit 25
python3 run_batch_retest.py --limit 25
```

### Single domain
```bash
python3 run_single_domain.py
# (edit DOMAIN variable in the script first)
```

### Resume interrupted run
The pipeline auto-skips already-scored domains. Just re-run `run_hybrid_pipeline.py` — it picks up where it left off.

---

## Key scripts

| Script | Purpose |
|---|---|
| `pre_enrichment.py` | Stage 1 — deterministic API enrichment |
| `run_hybrid_pipeline.py` | Stage 2A+2B — AI scoring pipeline |
| `fetch_full_results.py` | Fetch all scored results from Supabase to local JSON |
| `export_scores_excel.py` | Export results to Excel |
| `export_scores_csv.py` | Export results to CSV |
| `run_batch_retest.py` | Re-score a batch, check fill rates |
| `run_single_domain.py` | Score a single domain with full output |
| `run_stage_b_rerun.py` | Re-run Stage B for companies where it previously failed |
| `run_activity_tiers.py` | Compare top 10% vs bottom 10% activity tiers |
| `generate_fill_rate_report.py` | Fill rate scorecard PDF |
| `generate_high_fit_report.py` | High fit companies PDF report |
| `generate_engagement_tier_report.py` | Engagement + ICP tier cross-report |
| `generate_battle_cards_v2.py` | Per-company battle card PDF |
| `generate_watchlist.py` | Watchlist of companies to monitor |
| `enrich_location_from_ip.py` | Geo-enrich companies from IP data |
| `enrich_research_location.py` | Enrich with research location signals |
| `enrich_usage_windows.py` | Compute 30d/6mo/12mo user activity windows |
| `compare_results.py` | Diff two result sets |

---

## Supabase tables

| Table | Description |
|---|---|
| `emolecules_data_master` | Raw query log — ~50M rows, do not modify |
| `emolecules_data_by_email` | One row per user email — 17,339 rows |
| `emolecules_data_by_company` | One row per company domain — 5,224 rows |
| `icp_enrichment` | Pre-enrichment output (API-sourced facts) |
| `icp_hybrid_results` | Final ICP scores + evidence |
| `discarded_email_suggestion` | Pre-screened domains (academic, personal, etc.) |
| `ats_registry` | Domain → Greenhouse board_token (manual seed) |

---

## Results files

| File | Description |
|---|---|
| `results/emolecules_scores_may18.xlsx` | Final scored output, May 2026 (4,488 companies) |
| `results/emolecules_scores_may18.csv` | Same as CSV |
| `results/full_run_may18.json` | Raw JSON output from pipeline |
| `results/emolecules_scores_apr22.xlsx` | Prior run, April 22 2026 |
| `results/emolecules_icp_report.pdf` | ICP analysis PDF report |
| `results/emolecules_engagement_tier_report.pdf` | Engagement tier analysis |
| `results/emolecules_fill_rate_report.pdf` | Field fill rate scorecard |

---

## Cost

| Component | Per-company | 500 companies |
|---|---|---|
| Pre-enrichment (free APIs) | $0 | $0 |
| Stage 2A holistic agent | ~$0.05–0.18 | ~$25–90 |
| Stage 2B categorical agents (if escalated) | $0 or ~$0.18 | ~$0–45 |
| **Total typical** | **~$0.10–0.30** | **~$50–135** |

---

## Known limitations

- **No engagement weighting in score** — a dormant 1-user account and a 40-user active account can receive the same ICP score. Always filter by `Users (30d)` when prioritizing outreach.
- **CQ relies on web search only** — no Apollo.io or LinkedIn API; contact quality comes from what Perplexity finds publicly. Named contacts should be verified before outreach.
- **PatentsView requires API key** — without it, `si_patent_filings` returns "Patent lookup not run" for every company. Free key at [patentsview.org/apis/keyrequest](https://patentsview.org/apis/keyrequest).
- **Non-US companies miss EDGAR enrichment** — Roche, Novartis, GSK, AZ get no structured public-status signal. Partial Swiss coverage via LINDAS SPARQL.
- **CRO buying behavior differs** — CROs score highly on the rubric (they do chemistry) but buy differently from biotech. Segment them separately in outreach.

---

## Documentation

- `PIPELINE.md` — technical pipeline reference
- `HANDOFF.md` — pre-enrichment layer and prompt fix context
- `HANDOFF_PATENTS.md` — PatentsView API key setup
- `ICP_SCORING_OVERVIEW.md` — complete end-to-end project narrative and scoring methodology
