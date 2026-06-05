# eMolecules ICP Scoring — Complete Project Overview

**Project:** eMolecules ICP (Ideal Customer Profile) Scoring Pipeline  
**Purpose:** Identify which of eMolecules' ~5,200 website visitors are high-value drug discovery prospects worth sales outreach  
**Final output:** `results/emolecules_scores_may18.xlsx` — 4,488 scored companies  
**Completed:** May 2026

---

## Table of Contents

1. [Background and Problem Statement](#1-background-and-problem-statement)
2. [Data Source — What We Started With](#2-data-source--what-we-started-with)
3. [ICP Definition — What Makes a Good eMolecules Customer](#3-icp-definition--what-makes-a-good-emolecules-customer)
4. [Scoring Framework — The 0–100 Scale](#4-scoring-framework--the-0100-scale)
5. [Pipeline Architecture — How It Works End-to-End](#5-pipeline-architecture--how-it-works-end-to-end)
6. [Stage 1 — Pre-Enrichment Layer](#6-stage-1--pre-enrichment-layer)
7. [Stage 2A — Holistic AI Agent](#7-stage-2a--holistic-ai-agent)
8. [Stage 2B — Categorical AI Agents](#8-stage-2b--categorical-ai-agents)
9. [Output Schema — What Every Row Contains](#9-output-schema--what-every-row-contains)
10. [Fill Rate Results — What the Pipeline Actually Found](#10-fill-rate-results--what-the-pipeline-actually-found)
11. [Key Findings from the Final Run](#11-key-findings-from-the-final-run)
12. [US High Fits Analysis — Interpreting the Top Scores](#12-us-high-fits-analysis--interpreting-the-top-scores)
13. [Known Limitations and Overfit Patterns](#13-known-limitations-and-overfit-patterns)
14. [How to Use the Output](#14-how-to-use-the-output)
15. [Iteration History](#15-iteration-history)

---

## 1. Background and Problem Statement

eMolecules sells chemical building blocks, screening compound collections, virtual libraries, and compound management services to the pharmaceutical drug discovery industry. Their primary buyers are:

- Medicinal chemists at biotech and pharma companies
- CADD (computer-aided drug design) teams doing virtual screening
- Drug discovery CROs doing chemistry for clients
- Platform biotechs running hit-finding and lead optimization programs

eMolecules had a Supabase database of ~50 million raw search queries — every compound search, structure lookup, and catalog browse across their website. From this, 5,224 distinct company domains had been extracted (one row per company with user count, session count, last-active date).

The problem: **they didn't know which of those 5,224 companies were real drug discovery organizations worth calling vs. students, academics, bots, or companies that just browsed once and will never buy.**

The goal of this project was to score every company 0–100 and surface the high-fit prospects.

---

## 2. Data Source — What We Started With

### Raw session data

**Table: `emolecules_data_master`** — ~50 million rows
- `query` — compound name or structure search
- `qtype` — search type (name, SMILES, InChI, etc.)
- `ipaddress` — source IP
- `qdatetime` — timestamp
- `emailaddress` — user email (where available)
- Data spans: January 2020 – March 27, 2026

**Notable: `tdkob@vip.net.ru`** — a single account with 44,157,857 sessions, representing 88% of the entire dataset. This is a bot/scraper and is excluded from all analysis.

### Company-level aggregate

**Table: `emolecules_data_by_company`** — 5,224 rows
- `domain` — company domain extracted from email addresses
- `user_count` — distinct users from that domain
- `total_sessions` — total search sessions
- `last_active` — most recent activity timestamp

Personal email domains (gmail, yahoo, outlook, etc.) and academic domains are pre-filtered out.

### Activity tiers

- Top 10% (≥1,295 sessions): 523 companies
- Bottom 10% (≤2 sessions): 626 companies
- Median: ~12 sessions

High-activity companies are 8× more likely to be HIGH FIT (32% vs 4%) — session count is a strong proxy for genuine engagement even though it's not part of the ICP score.

---

## 3. ICP Definition — What Makes a Good eMolecules Customer

eMolecules' ideal customer is an organization that:

1. **Does small molecule drug discovery** — either internal programs (biotech/pharma) or for clients (discovery CRO). This is the single most important criterion. A company that only does antibodies, cell therapy, gene therapy, diagnostics, or devices is not a buyer.

2. **Has an active chemistry team** — specifically medicinal chemists, computational chemists, or drug discovery scientists. These are the people who purchase and use eMolecules' products.

3. **Is at the right stage** — Series A+ biotech, mid-size pharma, or discovery CRO. Too early (pre-seed, 1–3 employees) = no budget. The sweet spot is active R&D-stage organizations with chemistry programs.

4. **Has growth signals** — recent funding, active publications, patent filings, pharma partnerships. These indicate the company is actively investing in discovery chemistry.

**Products mapped to needs:**

| eMolecules Product | Who needs it |
|---|---|
| Building Blocks | Any medicinal chemist doing synthetic chemistry |
| Screening Compounds | Hit-finding programs, HTS |
| Virtual Libraries | CADD teams doing virtual screening, docking, FEP |
| Compound Management | Companies managing internal compound collections |

---

## 4. Scoring Framework — The 0–100 Scale

The final ICP score is the sum of four independent sub-scores.

### SM — Small Molecule (0–30 points)

Measures whether the company does small molecule drug discovery. This is the gatekeeping dimension.

| Signal | Points |
|---|---|
| Active medicinal chemistry programs OR contract chemistry services | 30 |
| Computational chemistry / CADD capabilities | 25 |
| Hit-to-lead / lead optimization | 20 |
| Virtual screening | 15 |
| No drug discovery or chemistry activities | 0 |

"Active med chem" includes both internal programs (Gilead, a Series A biotech) AND contract services (WuXi AppTec, Charles River Discovery). Both are valid eMolecules customers.

**Automatic disqualifiers (score = 0 regardless of other dimensions):**
- Pure biologics (antibodies, gene therapy, cell therapy, mRNA — no small molecule)
- Bulk API/commodity manufacturing (generics, process scale-up — no discovery)
- Medical devices
- Diagnostics only
- Pure software without wet lab
- Clinical-only CROs (trial management, no chemistry)
- Academic institutions without industry drug discovery partnerships

**CROs are NOT disqualified.** Any company advertising "custom synthesis," "medicinal chemistry services," "hit-to-lead," "lead optimization," or "compound library design" is a target customer.

### SF — Stage Fit (0–30 points)

Measures company size and funding stage as a proxy for purchasing capacity.

| Company type | Points |
|---|---|
| Series A+ biotech with active R&D | 30 |
| Mid-tier pharma (500–5,000 employees) | 30 |
| AI/computational drug discovery company | 25 |
| Early preclinical through Phase II | 20 |
| Phase III/commercial only | 10 |
| Pure manufacturing/clinical/regulatory | 0 |

### CQ — Contact Quality (0–25 points)

Measures whether a chemistry decision-maker can be identified.

| Role found | Points |
|---|---|
| Head of Medicinal Chemistry / Chemistry Director | 25 |
| Head of Computational Chemistry / CADD | 25 |
| VP / Director of Drug Discovery | 20 |
| Principal / Senior Medicinal Chemist | 15 |
| Research Scientist in chemistry | 10 |
| Non-chemistry roles only | 0 |

**Scoring basis codes:** `head_med_chem` · `head_cadd` · `vp_drug_discovery` · `senior_chemist` · `research_scientist` · `none`

### SI — Strategic Intel (0–15 points)

Measures growth signals indicating active investment in drug discovery.

| Signal | Points |
|---|---|
| Recent Series A+ funding | 15 |
| Recent chemistry leadership hires | 10 |
| Published drug discovery research | 10 |
| Active pharma partnerships | 10 |
| Patent filings in small molecules | 5 |
| No growth indicators | 0 |

Multiple signals can be present but the score is capped at 15.

### Score tiers

```
TOTAL = SM + SF + CQ + SI (max 100)

≥ 80 → HIGH FIT    — priority outreach
60–79 → MEDIUM FIT  — qualified prospect
40–59 → LOW FIT     — nurture only
< 40  → NO FIT      — disqualify
```

---

## 5. Pipeline Architecture — How It Works End-to-End

```
┌──────────────────────────────────────────────────────┐
│  Input: emolecules_data_by_company (5,224 domains)   │
│  Sorted by total_sessions DESC                        │
│  Bot domain vip.net.ru excluded                       │
└───────────────────────┬──────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────┐
│  STAGE 1 — Pre-Enrichment (pre_enrichment.py)        │
│  Free deterministic API lookups — no LLM              │
│  ~15-25 seconds per company, $0 cost                  │
│  Output: icp_enrichment table in Supabase             │
└───────────────────────┬──────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────┐
│  STAGE 2A — Holistic Agent                           │
│  Perplexity Sonar-Pro via OpenRouter                  │
│  1 call + up to 3 rabbit-hole follow-ups             │
│  Scores 0-100 with evidence per field                 │
│  ~10-30 seconds, ~$0.05-0.18 per company             │
│                                                       │
│  HIGH FIT (≥80) → accept, skip 2B                    │
│  NO FIT (<40)   → accept, skip 2B                    │
│  40-79 or low confidence → escalate to 2B             │
└───────────────────────┬──────────────────────────────┘
                        ▼ (escalated ~20-30%)
┌──────────────────────────────────────────────────────┐
│  STAGE 2B — 4 Categorical Agents (parallel)          │
│  SM · SF · CQ · SI run simultaneously                │
│  ~15 seconds, ~$0.18 per company                     │
│  Final score = SM + SF + CQ + SI                     │
└───────────────────────┬──────────────────────────────┘
                        ▼
┌──────────────────────────────────────────────────────┐
│  Storage                                             │
│  Supabase: icp_hybrid_results                        │
│  Local: results/*.json, results/*.xlsx               │
└──────────────────────────────────────────────────────┘
```

Stage 2A handles clear cases fast (obvious large pharma = HIGH FIT immediately; obvious university = NO FIT immediately). Only the ambiguous middle escalates to Stage 2B.

---

## 6. Stage 1 — Pre-Enrichment Layer

The original pipeline (pre-April 2026) asked Perplexity to find every fact cold. A fill rate audit showed 14 of 17 fields were effectively blind — the agent couldn't reliably find public status, patent counts, publication history, or funding stage via web search alone.

The fix: **run deterministic API lookups before the LLM ever sees the company.** Pre-built structured signals are injected into every agent prompt so the agent validates rather than discovers.

### APIs used

| Source | What it provides |
|---|---|
| **SEC EDGAR** | Public company status, ticker, exchange, filer category, recent S-1/S-3 offerings, Form D (private placements) |
| **PubMed E-utilities** | Drug discovery, CADD, and virtual screening publication counts — tries 3 name variants per company, takes max |
| **OpenAlex** | Total works count; med-chem concept filter |
| **ChEMBL** | Count of approved drugs where company is applicant |
| **PubChem BioAssay** | HTS campaigns deposited with company as source |
| **ClinicalTrials.gov v2** | Total interventional trials as lead sponsor; active/recruiting count |
| **PatentsView** | Patent count last 3 years; pharma-class count (CPC A61K, C07D, C07K); recent patent titles. Requires free API key. |
| **EPO OPS** | European patent data fallback |
| **SBIR.gov** | Employee counts for private US biotechs |
| **NIH RePORTER** | Grant history for academic spinouts |
| **LINDAS SPARQL / Zefix** | Swiss company registry — covers Roche, Novartis, Idorsia |

### Signal strings injected into agent prompts

Raw numbers are converted to 9 human-readable `sig_*` strings:

```
sig_si_patent_filings →
"CONFIRMED: 394 total patents in last 3 years (EPO OPS).
 329 are pharma-class (CPC A61K/C07D/C07K).
 Recent titles: 'KRAS Modulating Compounds'; 'KRAS G12D Inhibitors'"

sig_sf_is_public →
"CONFIRMED: Publicly traded on NYSE as GILD (SEC EDGAR)"

sig_si_recent_funding →
"CONFIRMED: SEC Form D filed 2025-11-03 — private placement (Reg D)"
```

### Fill rate improvement after pre-enrichment

| Field | Before | After |
|---|---|---|
| `sf_is_public` | 14% | ~95% |
| `sf_funding_stage` | 60% | ~90% |
| `si_recent_publications` | 6% | ~85% |
| `si_patent_filings` | 2% | ~80% |
| `sm_active_med_chem` | 8% | ~58% (top tier) |

---

## 7. Stage 2A — Holistic AI Agent

**Model:** Perplexity Sonar-Pro via OpenRouter

The agent receives the company domain, 9 pre-built signal strings, and session/user counts. It:

1. Crawls the company's website and related sources
2. Applies the full 100-point scoring rubric
3. Returns structured JSON with ~40 fields: sub-scores, evidence per field, DQ checks, service match, reasoning
4. Identifies up to 3 "rabbit holes" — specific questions that would materially change the score

**Rabbit-hole follow-up:** For each rabbit hole, one focused follow-up call is made and the result is merged back. Up to 3 follow-ups per company. This improves accuracy for companies with ambiguous signals.

**Routing:**
- `score ≥ 80` → HIGH FIT, skip Stage 2B
- `score < 40` → NO FIT, skip Stage 2B
- `40–79` or low confidence → escalate to Stage 2B

**Negative string requirement:** Every field requires a meaningful negative string when evidence is absent (e.g. `"No active med chem programs found on website or pipeline"` rather than `null`). This was a critical fix applied in April 2026 — before it, 85%+ of fields were empty.

---

## 8. Stage 2B — Categorical AI Agents

Triggered for ~20–30% of companies. Four specialist agents run in parallel, each focused on one dimension only.

### SM Agent (0–30 pts)
Searches specifically for small molecule signals: pipeline assets, CADD platform, SAR/hit-to-lead, virtual screening. Runs auto-disqualification checks. Does not care about company size or funding.

### SF Agent (0–30 pts)
Determines company size, funding stage, employee count, and whether the company is public. Does not care about the science — just size and stage.

### CQ Agent (0–25 pts)
Searches for chemistry decision-makers: medicinal chemistry heads, CADD leads, drug discovery directors. Checks LinkedIn, team pages, publications, and EDGAR Form 4 filings. **No structured data source exists for this — it's pure web search.** This is the weakest stage.

### SI Agent (0–15 pts)
Looks for growth signals: recent funding rounds, chemistry leadership hires, publications, pharma partnerships, patent filings. Receives pre-enriched signals as context.

---

## 9. Output Schema — What Every Row Contains

The Excel output (`results/emolecules_scores_may18.xlsx`) has 44 columns:

**Identity:** `Domain` · `Company Type` · `Status`

**Scores:** `TOTAL SCORE` · `SM Score` · `SF Score` · `CQ Score` · `SI Score`

**Geography:** `Geo Tier` · `Country (IP/Reg)` · `City` · `Research Country` · `Research City`

**Engagement:** `Users` · `Total Sessions` · `Last Active` · `Users (30d)` · `Users (6mo)` · `Users (12mo)`

**SM evidence:** `SM · Active MedChem` · `SM · CADD` · `SM · Hit-to-Lead` · `SM · Virtual Screen` · `SM · Basis`

**SF evidence:** `SF · Stage Type` · `SF · Funding Stage` · `SF · Employee Range` · `SF · Is Public` · `SF · Basis`

**CQ evidence:** `CQ · Has Chem Team` · `CQ · Highest Role` · `CQ · Team Size Est.` · `CQ · Basis`

**SI evidence:** `SI · Funding Amount` · `SI · Patent Filings` · `SI · Partnerships` · `SI · Recent Hires` · `SI · Recent Funding` · `SI · Publications` · `SI · Basis`

**Synthesis:** `DQ Reason` · `Key Evidence` · `Agent Reasoning`

---

## 10. Fill Rate Results — What the Pipeline Actually Found

Top 10% vs bottom 10% real evidence rates (May 2026 full run):

| Field | Top 10% | Bottom 10% | Delta |
|---|---|---|---|
| `si_patent_filings` | 80% | 20% | +60pp |
| `sm_active_med_chem` | 58% | 6% | +52pp |
| `sm_hit_to_lead` | 50% | 6% | +44pp |
| `si_recent_publications` | 32% | 4% | +28pp |
| `sf_employee_range` | 66% | 42% | +24pp |
| `sm_cadd_capabilities` | 24% | 2% | +22pp |
| `sf_is_public` | 34% | 12% | +22pp |
| `sf_funding_stage` | 56% | 38% | +18pp |
| `sm_virtual_screening` | 18% | 4% | +14pp |
| `si_recent_funding` | 4% | 10% | −6pp |

`si_recent_funding` fills *more* in the bottom tier — low-activity companies include university spinouts and non-profits that get NIH grants, which appear as funding signals but aren't real drug discovery buyers.

---

## 11. Key Findings from the Final Run

- **4,488 companies scored** (May 2026)
- **254 US HIGH FIT** companies (score ≥ 80, Geo Tier = US)
- Average US score: 33.7 / 100, Median: 12 / 100
- High-activity companies are **8× more likely** to be HIGH FIT (32% vs 4%)
- Score distribution is bimodal — lots of 0s, spike at 85–100. This is expected: most visitors are noise, a minority are genuine prospects.

---

## 12. US High Fits Analysis — Interpreting the Top Scores

### What the scores correctly capture

The 254 US HIGH FIT companies are predominantly legitimate small-molecule biotechs and pharma companies with real chemistry teams. The company-selection logic is sound — these are the right *types* of organizations. Well-known examples: Neurocrine, Genentech, Vividion, Frontier Medicines, ORIC Pharma, Ensem Therapeutics, Circle Pharma.

### Where the scores overstate purchase likelihood

**No engagement penalty.** 202 of 254 US HIGH FIT companies have zero users in the past 30 days. 116 haven't been active in 2+ years. The ICP score measures "is this company the right type" — not "are they actively using eMolecules."

A company that visited once in 2021 and a company with 40 active users today can receive identical scores.

**Always cross-reference `Users (30d)` before treating a score as warm pipeline.**

**CQ inflation.** Some large pharma entries (Pfizer, Regeneron) have CQ scores of 20 even though no chemistry contact was identified. The agent awards points based on company type when no actual named contact was found. Regeneron's "contact" was their SVP Controller — a finance role. Always check `CQ · Highest Role` before using it.

**CRO/CDMO buying behavior.** 38 CROs appear in the US HIGH FIT list. They score highly because they do chemistry — that's correct. But they buy compounds differently from biotech. Treat CRO entries as a channel/partner opportunity, not a direct buyer opportunity.

**Defunct and acquired companies.** Several companies in the list no longer exist independently:
- `celgene.com` — acquired by BMS (2019)
- `quanticel.com` — acquired by Pfizer (2014)
- `epizyme.com` — acquired by Ipsen (2022)
- `rayzebio.com` — acquired by BMS (2024)

### The genuinely clean high fits

Filtering to: US, score ≥ 80, ≥2 users in last 30 days, not CRO/CDMO → **20 companies**:

neurocrine.com · gene.com (Genentech) · vividion.com · genesistherapeutics.ai · enanta.com · mazetx.com · lilly.com · takeda.com · pfizer.com · odysseytx.com · ideayabio.com · jnanatx.com · biotheryx.com · crinetics.com · treeline.bio · kimiatx.com · unnaturalproducts.com · montai.com · epigenbiosciences.com · molecure.com

The other ~230 US HIGH FIT companies are **correct ICP designations for cold outbound** — right type of company, just haven't been converted to active accounts.

---

## 13. Known Limitations and Overfit Patterns

**No engagement weighting.** The score is purely firmographic. Create a blended score weighting ICP × engagement (based on `Users (30d)` and recency of `Last Active`) for outreach prioritization.

**CQ has no structured source.** Contact quality comes entirely from what Perplexity can find via web search. Well-known public companies with lots of web presence get higher CQ scores than equally-good private companies with minimal web footprint. Verify named contacts via LinkedIn before using them.

**Non-US companies partially miss enrichment.** SEC EDGAR only covers US-listed companies. Major non-US pharma (Roche, Novartis, GSK, AstraZeneca) get incomplete structured signals.

**PatentsView requires an API key.** Without it, `si_patent_filings` is blank for every company. Free key at patentsview.org/apis/keyrequest.

**No company lifecycle tracking.** No mechanism to detect acquisitions, shutdowns, or pivots away from small molecules. A periodic re-scoring and known-acquired-companies blocklist are needed.

**Third-party contact sources are stale.** Evidence frequently cites theorg.com, RocketReach, and Prospeo — LinkedIn aggregators that can be months or years out of date. Treat as starting points, not confirmed contacts.

---

## 14. How to Use the Output

### Prioritizing outreach

1. Filter: `Geo Tier = "US"` and `TOTAL SCORE >= 80`
2. Sort by: `Users (30d)` DESC, then `Users (12mo)` DESC
3. Exclude: `Company Type = "CRO/CDMO"` (unless channel play), known-acquired domains, `Last Active` > 18 months ago
4. Verify: Check `CQ · Highest Role` has a real name + title, then confirm via LinkedIn before outreach

### Reading the basis codes

Each sub-score has a `· Basis` column with a machine-readable code showing what evidence drove the score:

- SM: `active_med_chem` > `cadd` > `hit_to_lead` > `virtual_screening` > `none`
- CQ: `head_med_chem` / `head_cadd` > `vp_drug_discovery` > `senior_chemist` > `research_scientist` > `none`
- SI: `recent_funding` > `partnerships` > `chem_hires` > `publications` > `patents` > `none`

If `CQ · Basis = "none"` — no chemistry contact was found. A rep needs to source one before outreach.

### Reading Key Evidence

The `Key Evidence` column has the 3–5 specific facts the agent found. If a score looks too high or too low, this is the first place to look — it tells you exactly what the agent was pattern-matching on.

---

## 15. Iteration History

### April 1, 2026 — Initial run (489 companies)

First full pipeline run, holistic agent only, no pre-enrichment. Result: 14 of 17 scored fields had <15% real fill rate. The agent was scoring from absence of evidence — systematic bias.

### April 9, 2026 — Fill rate audit

Deep analysis of what the agent was and wasn't finding. Identified that structured fields (public status, patents, publications, trial counts) were all near-zero fill. Root cause: LLM web search is unreliable for structured fact retrieval.

### April 15, 2026 — Pre-enrichment layer + prompt fixes

Built `pre_enrichment.py` with 8 API integrations. Created `icp_enrichment` table. Fixed all agent prompts to require negative evidence strings instead of null returns.

### April 17–22, 2026 — Retesting and calibration

Multiple retests on 25–50 company batches. Validated fill rate improvements. Added location enrichment (IP geolocation + research location). Tuned escalation threshold.

### May 8, 2026 — Mid-scale run (500 companies)

`results/emolecules_scores_may08.xlsx` — first full-scale run with pre-enrichment injected.

### May 14–18, 2026 — Full run (4,488 companies)

`results/emolecules_scores_may18.xlsx` — final output.

**Estimated pipeline cost for full run:** ~$450–900  
**Runtime:** ~40–60 hours total (batched, resumable)
