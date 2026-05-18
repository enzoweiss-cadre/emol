# eMolecules ICP Scoring Pipeline

## Overview

Two-stage pipeline that scores company domains as drug discovery prospects for eMolecules.
Input: company domains from website activity logs. Output: 0–100 ICP score with sub-scores.

---

## Stage 0 — Activity Source

Companies come from `emolecules_data_by_company` in Supabase.

| Column | Description |
|---|---|
| `domain` | Company domain extracted from email |
| `user_count` | Unique users from that domain |
| `total_sessions` | Total search sessions |
| `last_active` | Most recent activity timestamp |

**Top 10%** = ≥ 1,295 sessions (523 companies)
**Bottom 10%** = ≤ 2 sessions (626 companies)

The bot domain `vip.net.ru` (915K sessions, 88% of all data) is always excluded.

---

## Stage 1 — Pre-Enrichment (`pre_enrichment.py`)

Free API lookups that run before the AI agents. Results cached in `icp_enrichment` table.

| Source | Fields populated |
|---|---|
| SEC EDGAR | `is_public`, `ticker`, `sf_funding_stage`, `sf_employee_range` |
| PubMed | `pubmed_drug_discovery_count`, `pubmed_cadd_count`, `pubmed_virtual_screening_count` |
| ChEMBL | `chembl_drug_count` |
| ClinicalTrials.gov | `ct_total_trials`, `ct_phase12_trials` |
| PatentsView / EPO | `patent_count_3yr` |

These signals are passed as structured context to the AI agents so they don't have to find them cold.

---

## Stage 2 — Holistic Agent (`perplexity/sonar-pro`)

Scores every company 0–100 using a single agent with web search access.

- Score ≥ 80 → **HIGH FIT** → accepted
- Score 60–79 → **MEDIUM FIT** → escalate to Stage 3
- Score 40–59 → **LOW FIT** → escalate to Stage 3
- Score < 40 → **NO FIT** → accepted (rejected)
- Low-confidence auto-disqualifications also escalate

Uses up to 4 API calls per company with self-correction ("rabbit hole" logic).

---

## Stage 3 — Categorical Agents (escalated companies only)

Four specialist agents score each sub-dimension independently:

| Sub-score | Max points | What it measures |
|---|---|---|
| SM (Small Molecule) | 30 | Active med chem, CADD, hit-to-lead, virtual screening |
| SF (Stage Fit) | 30 | Company size, funding stage, public status |
| CQ (Contact Quality) | 25 | Chemistry team, seniority of contacts |
| SI (Strategic Intel) | 15 | Patents, publications, funding, partnerships |

Final score = SM + SF + CQ + SI (max 100).

---

## Fill Rate Standard

A field is only counted as **filled** if the agent returned a value containing actual confirmed evidence:
a number, date, source citation, or explicit confirmation.

Values like `"Unknown"`, `"No X found"`, `"Not listed"` are treated as **empty** — they carry no confirmed signal.

**Real fill rates (top 10% vs bottom 10%):**

| Field | Top 10% | Bottom 10% | Delta |
|---|---|---|---|
| si_patent_filings | 80% | 20% | +60pp |
| sm_active_med_chem | 58% | 6% | +52pp |
| sm_hit_to_lead | 50% | 6% | +44pp |
| si_recent_publications | 32% | 4% | +28pp |
| sf_employee_range | 66% | 42% | +24pp |
| sm_cadd_capabilities | 24% | 2% | +22pp |
| sf_is_public | 34% | 12% | +22pp |
| sf_funding_stage | 56% | 38% | +18pp |
| sm_virtual_screening | 18% | 4% | +14pp |
| si_recent_funding | 4% | 10% | -6pp |

---

## Key Findings

- High-activity companies are **8× more likely** to be HIGH FIT (32% vs 4%)
- Top tier avg score: **40.2/100** vs bottom tier **4.4/100** (~9× higher)
- Drug-discovery fields show the sharpest gaps — confirming activity is a strong ICP proxy
- Bottom tier is mostly academic institutions and one-off visitors — not prospects
- `si_recent_funding` is the only field where bottom tier fills higher (noise from university grants)

---

## Scripts

| Script | Purpose |
|---|---|
| `pre_enrichment.py` | Stage 1 free-API enrichment |
| `run_hybrid_pipeline.py` | Core pipeline logic (Stage 2 + 3) |
| `run_batch_retest.py` | Run pipeline on a set of domains, print fill rates |
| `run_activity_tiers.py` | Compare top 10% vs bottom 10% activity tiers |
| `generate_tier_comparison_report.py` | PDF report of tier comparison |
| `generate_fill_rate_report.py` | PDF fill rate report for a single run |
