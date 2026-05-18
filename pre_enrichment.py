"""
Pre-Enrichment Layer — Free API lookups for deterministic fields.

Populates icp_enrichment table with structured data from:
  - SEC EDGAR        (public status, funding filings, headcount)
  - PubMed           (publications, CADD, virtual screening keywords)
  - PatentsView      (patent filings by assignee)
  - ChEMBL           (approved drugs by applicant)
  - ClinicalTrials   (active trials by sponsor)

Run this BEFORE the hybrid pipeline. Results are written to Supabase
table `icp_enrichment`. The hybrid pipeline can then pass pre-populated
facts to agents as context instead of asking them to find it cold.

Usage:
  python3 pre_enrichment.py                          # full run (all companies from Supabase)
  python3 pre_enrichment.py --limit 50               # test run on top 50
  python3 pre_enrichment.py --domain gilead.com      # single domain
  python3 pre_enrichment.py --from-json              # use the 489 from hybrid_pipeline_results.json

─────────────────────────────────────────────────────────────────────
CREATE TABLE icp_enrichment (
    domain                      TEXT PRIMARY KEY,
    company_name_guess          TEXT,

    -- Public status (SEC EDGAR)
    is_public                   BOOLEAN,
    ticker                      TEXT,
    exchange                    TEXT,
    cik                         TEXT,

    -- Stage fit (EDGAR 10-K / filings)
    sf_funding_stage            TEXT,
    sf_employee_range           TEXT,
    sf_recent_offering          BOOLEAN,
    sf_offering_date            TEXT,
    sf_offering_form            TEXT,

    -- Publications (PubMed + OpenAlex)
    pubmed_drug_discovery_count INTEGER,
    pubmed_cadd_count           INTEGER,
    pubmed_virtual_screening_count INTEGER,
    openalex_works_count        INTEGER,

    -- Patents (PatentsView / EPO OPS fallback)
    patent_count_3yr            INTEGER,
    patent_most_recent_title    TEXT,
    patent_most_recent_date     TEXT,
    patent_source               TEXT,

    -- ChEMBL (approved drugs)
    chembl_drug_count           INTEGER,
    chembl_sample_drugs         JSONB,

    -- Clinical trials
    ct_total_trials             INTEGER,
    ct_phase12_trials           INTEGER,
    ct_most_recent_title        TEXT,

    -- Derived signal strings (passed as context to agents)
    sig_is_public               TEXT,
    sig_sf_employee_range       TEXT,
    sig_si_recent_funding       TEXT,
    sig_si_recent_publications  TEXT,
    sig_si_patent_filings       TEXT,
    sig_sm_active_med_chem      TEXT,
    sig_sm_cadd                 TEXT,
    sig_sm_hit_to_lead          TEXT,
    sig_sm_virtual_screening    TEXT,

    enrichment_errors           JSONB,
    enriched_at                 TIMESTAMPTZ DEFAULT NOW()
);
─────────────────────────────────────────────────────────────────────
"""

import asyncio
import json
import os
import sys
import time
import re
import argparse
from datetime import datetime, timezone, timedelta

import aiohttp
import trafilatura

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

SUPABASE_URL        = os.environ.get("SUPABASE_URL")
SUPABASE_KEY        = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
NCBI_API_KEY        = os.environ.get("NCBI_API_KEY", "")
PATENTSVIEW_API_KEY  = os.environ.get("PATENTSVIEW_API_KEY", "")
EPO_OPS_KEY          = os.environ.get("EPO_OPS_KEY", "")
OPENROUTER_API_KEY   = os.environ.get("OPENROUTER_API_KEY", "")   # "consumer_key:consumer_secret" from ops.epo.org

TARGET_TABLE = "icp_enrichment"
BATCH_SIZE   = 100      # companies per batch
EDGAR_UA     = "eMolecules ICP Enrichment pipeline@emolecules.com"

# Minimum name length to make fuzzy API queries (ChEMBL, CT, PubMed)
# Domains like i.ua → "I" return garbage results from substring-search APIs
MIN_QUERY_NAME_LEN = 3

# Domains ending in these TLDs are ICP auto-disqualifiers — skip all enrichment
DISQUALIFIED_TLDS = {".gov", ".edu", ".mil"}

# Academic second-level domain patterns not caught by TLD list
# e.g. ic.ac.uk (Imperial College), cam.ac.uk (Cambridge), kit.edu.tr
DISQUALIFIED_ACADEMIC_PATTERNS = [
    ".ac.uk", ".ac.jp", ".ac.nz", ".ac.in", ".ac.kr", ".ac.za", ".ac.il",
    ".ac.at", ".ac.be", ".ac.id", ".ac.ir", ".ac.th", ".ac.tz", ".ac.cn",
    ".edu.au", ".edu.cn", ".edu.hk", ".edu.sg", ".edu.tw",
    ".edu.tr", ".edu.mx", ".edu.ar", ".edu.co", ".edu.br",
    ".edu.pl", ".edu.sa", ".edu.it", ".edu.si", ".edu.vn", ".edu.ua",
    ".edu.ru", ".edu.eg", ".edu.pk", ".edu.ng", ".edu.gh", ".edu.in",
]

# Subdomain prefixes that are always academic/non-commercial regardless of TLD
# e.g. student.vu.nl, doctoral.uj.edu.pl, phd.xxx.com
DISQUALIFIED_SUBDOMAIN_PREFIXES = {"student", "doctoral", "phd", "alumni"}

# Domain prefixes strongly indicating a university (on country-code TLDs like .fr .ch .br)
# e.g. univ-rouen.fr, unistra.fr, unibas.ch, unicamp.br, uni-lj.si
UNIVERSITY_NAME_PREFIXES = ("univ-", "univ.", "univ ", "uni-", "unistra", "unibas", "unicamp", "unimelb")

# Rate-limit semaphores
SEM_EDGAR   = asyncio.Semaphore(8)   # 10 req/s allowed, use 8
SEM_PUBMED  = asyncio.Semaphore(3 if not NCBI_API_KEY else 8)
SEM_PATENTS = asyncio.Semaphore(3)   # 45 req/min with key
SEM_CHEMBL  = asyncio.Semaphore(5)   # push harder, ChEMBL is lenient
SEM_CT      = asyncio.Semaphore(8)   # 10 req/s allowed
SEM_SCRAPER      = asyncio.Semaphore(20)  # concurrent site page fetches
SEM_PLAYWRIGHT   = asyncio.Semaphore(3)   # concurrent headless browser instances (memory-heavy)
SEM_OPENROUTER   = asyncio.Semaphore(10)  # Perplexity sonar via OpenRouter

SCRAPE_PATHS = [
    # Homepage + about (Stage Fit: company type, size, overview)
    "/", "/about", "/about-us", "/company", "/company/about",
    # Contact Quality: people, team, leadership
    "/team", "/our-team", "/leadership", "/management",
    "/company/team", "/company/leadership", "/company/people", "/people",
    # Small Molecule: technology platform, CADD, capabilities
    "/technology", "/platform", "/capabilities", "/science", "/our-science",
    "/research", "/approach", "/discovery",
    # Pipeline / programs (Small Molecule + Stage Fit)
    "/pipeline", "/programs", "/therapeutic-areas", "/drug-discovery",
    # Strategic Intelligence: news, funding, partnerships
    "/news", "/press", "/newsroom", "/press-releases", "/investors",
    "/partnerships", "/collaborations",
    # Careers (team size signal)
    "/careers",
]
SCRAPE_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Keyword scoring for link discovery — maps to all four scoring categories
_LINK_SCORE: dict[str, int] = {
    # Contact Quality
    "team": 10, "leadership": 10, "management": 10, "people": 9,
    # Small Molecule
    "platform": 9, "technology": 9, "capabilit": 8, "cadd": 10,
    "computat": 8, "discovery": 7, "approach": 6,
    # Pipeline / programs (Small Molecule + Stage Fit)
    "pipeline": 9, "program": 7, "therapeutic": 7, "drug": 6,
    "science": 8, "research": 8,
    # Strategic Intelligence
    "news": 7, "press": 7, "newsroom": 7, "partner": 8,
    "collaborat": 8, "investor": 6, "funding": 7,
    # General
    "about": 5, "therapy": 5,
    # Lower priority
    "career": 3, "contact": 2,
}

def _score_path(path: str) -> int:
    p = path.lower()
    return sum(v for k, v in _LINK_SCORE.items() if k in p)

def _extract_internal_links(html: str, domain: str) -> list[str]:
    """Parse <a href> from raw HTML, return same-domain paths sorted by keyword score."""
    hrefs = re.findall(r'href=["\']([^"\'#?][^"\']*)["\']', html, re.IGNORECASE)
    paths: set[str] = set()
    prefix = f"https://{domain}"
    for href in hrefs:
        href = href.strip()
        if href.startswith(prefix):
            path = href[len(prefix):]
        elif href.startswith("/") and not href.startswith("//"):
            path = href
        else:
            continue
        path = path.split("?")[0].split("#")[0].rstrip("/") or "/"
        if path and path != "/" and "." not in path.split("/")[-1]:
            paths.add(path)
    scored = sorted(paths, key=_score_path, reverse=True)
    return [p for p in scored if _score_path(p) > 0][:10]


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def domain_to_company_name(domain: str) -> str:
    """
    Best-guess company name from a domain.
    'gilead.com' → 'Gilead'
    'boehringer-ingelheim.com' → 'Boehringer Ingelheim'
    'astrazeneca.com' → 'Astrazeneca'
    """
    base = domain.split(".")[0]
    name = base.replace("-", " ").replace("_", " ").title()
    return name


def domain_to_search_variants(domain: str) -> list:
    """
    Returns a ranked list of name variants to try in searches.
    e.g. 'abbvie.com' → ['Abbvie', 'AbbVie']
    """
    base = domain_to_company_name(domain)
    variants = [base]
    # Also try the raw domain base without title casing
    raw = domain.split(".")[0].replace("-", " ")
    if raw.lower() != base.lower():
        variants.append(raw)
    return variants


def three_years_ago() -> str:
    return (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")

def two_years_ago() -> str:
    return (datetime.now() - timedelta(days=2 * 365)).strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────
# SEC EDGAR — ticker file (loaded once, shared)
# ─────────────────────────────────────────────────────────────

_edgar_tickers: dict = {}       # title_lower → {cik, ticker, title}
_edgar_by_normalized: dict = {} # title with spaces/punct stripped, lowercase → entry
_edgar_loaded = False


def _normalize_name(s: str) -> str:
    """Lowercase, strip spaces/punctuation/legal suffixes for fuzzy-matching
    domain-style concatenated names against EDGAR's spaced titles.
    'Thermo Fisher Scientific Inc' → 'thermofisherscientific'
    'Glaxo Smith Kline plc' → 'glaxosmithkline'
    """
    s = s.lower()
    s = re.sub(r',?\s*(and\s+|&\s*)?\b(inc|ltd|corp|llc|ag|plc|gmbh|sa|nv|bv|se|co|company|holdings?|group|international|intl|pharmaceuticals?|pharma|therapeutics|biosciences|sciences|technolog(y|ies))\b\.?', '', s)
    s = re.sub(r'[^a-z0-9]', '', s)
    return s

async def load_edgar_tickers(session: aiohttp.ClientSession):
    global _edgar_tickers, _edgar_loaded
    if _edgar_loaded:
        return

    # Use the broader ticker file (~12K entries) which includes foreign private
    # issuers with US ADRs (GSK, Novartis, etc.). The _exchange file only has
    # 8K and misses many ADRs.
    url = "https://www.sec.gov/files/company_tickers.json"
    headers = {"User-Agent": EDGAR_UA, "Accept": "application/json"}

    try:
        async with SEM_EDGAR:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    print(f"  [EDGAR] Failed to load tickers: {resp.status}")
                    _edgar_loaded = True
                    return
                data = await resp.json(content_type=None)

        # company_tickers.json shape: {"0": {"cik_str": ..., "ticker": ..., "title": ...}, ...}
        rows = data.values() if isinstance(data, dict) else data

        for row in rows:
            title = str(row.get("title", "")).strip()
            if not title:
                continue
            entry = {
                "cik":      str(row.get("cik_str", "")).zfill(10),
                "title":    title,
                "ticker":   row.get("ticker", ""),
                "exchange": row.get("exchange", ""),
            }
            _edgar_tickers[title.lower()] = entry
            norm = _normalize_name(title)
            if norm and len(norm) >= 4 and norm not in _edgar_by_normalized:
                _edgar_by_normalized[norm] = entry

        print(f"  [EDGAR] Loaded {len(_edgar_tickers):,} public companies from EDGAR")

    except Exception as e:
        print(f"  [EDGAR] Ticker load error: {e}")

    _edgar_loaded = True


def find_in_edgar(company_name: str) -> dict | None:
    """
    Fuzzy lookup against the EDGAR ticker file.
    Returns entry dict or None.

    Guards against false positives:
    - Minimum 4-character name (prevents "Its", "Nih", etc. from matching)
    - Starts-with match requires name ≥ 5 chars
    - Word-boundary match requires name ≥ 5 chars
    - Generic English words blocklist (prevents "Student" matching "Students International Inc")
    """
    if not _edgar_tickers:
        return None

    name_lower = company_name.lower().strip()

    # Reject names that are too short — common with subdomains like its.jnj.com → "Its"
    # Allow 3-char names for exact match (e.g. "gsk", "ucb") — just skip fuzzy starts-with/word-boundary
    if len(name_lower) < 3:
        return None

    # Reject generic English words that appear in many company names but are not company identifiers
    # These come from academic/subdomain prefixes like student.vu.nl → "Student"
    _GENERIC_WORD_BLOCKLIST = {
        "student", "students", "doctoral", "alumni", "education", "university",
        "institute", "faculty", "college", "research", "science", "sciences",
        "lab", "labs", "health", "medical", "hospital", "clinic", "center",
        "global", "national", "international", "federal", "regional",
    }
    if name_lower in _GENERIC_WORD_BLOCKLIST:
        return None

    # 1. Exact match
    if name_lower in _edgar_tickers:
        return _edgar_tickers[name_lower]

    # 2. EDGAR title starts with our name — only for names ≥ 5 chars
    if len(name_lower) >= 5:
        for title_lower, entry in _edgar_tickers.items():
            if title_lower.startswith(name_lower):
                return entry

    # 3. Word-boundary substring match — only for names ≥ 5 chars to avoid noise
    if len(name_lower) >= 5:
        pattern = r'\b' + re.escape(name_lower) + r'\b'
        for title_lower, entry in _edgar_tickers.items():
            if re.search(pattern, title_lower):
                return entry

    # 4. Normalized (spaces-stripped) match — catches domain-style concatenated names.
    # 'thermofisher' → 'thermofisherscientific' (EDGAR)
    # 'gsk' → ticker match
    norm = _normalize_name(company_name)
    if norm and len(norm) >= 3:
        # Exact normalized match (covers GSK plc → 'gsk', GlaxoSmithKline plc → 'glaxosmithkline')
        if norm in _edgar_by_normalized:
            return _edgar_by_normalized[norm]

    # 5. Ticker-symbol fallback for short domains (e.g. 'gsk' → GSK PLC ticker)
    if len(name_lower) <= 5:
        name_up = name_lower.upper()
        for entry in _edgar_tickers.values():
            if entry.get("ticker", "").upper() == name_up:
                return entry

    # 6. Prefix match: domain is a prefix of a normalized EDGAR title.
    # Require ≥ 6 chars AND prefix covers ≥ 50% of EDGAR name (relaxed from 70%
    # to catch 'thermofisher' → 'thermofisherscientific' at 57%).
    # Additionally require the next char in the EDGAR name to not continue the
    # prefix word (avoids 'abc' matching 'abcxyzcorp' where there's no split).
    if norm and len(norm) >= 6:
        candidates = [
            entry for edgar_norm, entry in _edgar_by_normalized.items()
            if edgar_norm.startswith(norm) and len(norm) / max(len(edgar_norm), 1) >= 0.5
        ]
        # Only accept if the match is unambiguous (single candidate)
        if len(candidates) == 1:
            return candidates[0]

    return None


# ─────────────────────────────────────────────────────────────
# SEC EDGAR — submissions (funding stage + employee range)
# ─────────────────────────────────────────────────────────────

OFFERING_FORMS = {"S-1", "S-3", "424B4", "424B3", "S-11", "F-1"}
FILER_TO_STAGE = {
    "Large accelerated filer": "Public — Large Cap",
    "Accelerated filer":       "Public — Mid Cap",
    "Non-accelerated filer":   "Public — Small Cap",
    "Smaller reporting company": "Public — Micro Cap",
}

async def fetch_edgar_submissions(cik: str, session: aiohttp.ClientSession) -> dict:
    """
    Pull submissions JSON for a public company.
    Extracts: filer category, recent offering filings.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    headers = {"User-Agent": EDGAR_UA}

    try:
        async with SEM_EDGAR:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json(content_type=None)

        category = data.get("category", "")
        stage = FILER_TO_STAGE.get(category, "Public")

        # Look for recent offering filings in the last 18 months
        cutoff = (datetime.now() - timedelta(days=540)).strftime("%Y-%m-%d")
        recent_offering = False
        offering_date   = None
        offering_form   = None

        filings = data.get("filings", {}).get("recent", {})
        forms   = filings.get("form", [])
        dates   = filings.get("filingDate", [])

        for form, date in zip(forms, dates):
            if form in OFFERING_FORMS and date >= cutoff:
                recent_offering = True
                offering_date   = date
                offering_form   = form
                break

        return {
            "sf_funding_stage":  stage,
            "sf_recent_offering": recent_offering,
            "sf_offering_date":  offering_date,
            "sf_offering_form":  offering_form,
        }

    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────
# SEC EDGAR — XBRL employee count (public companies only)
# ─────────────────────────────────────────────────────────────

def _employee_count_to_range(count: int) -> str:
    if count < 10:
        return "<10"
    elif count <= 50:
        return "10–50"
    elif count <= 150:
        return "51–150"
    elif count <= 500:
        return "151–500"
    elif count <= 1000:
        return "501–1,000"
    elif count <= 5000:
        return "1,001–5,000"
    else:
        return "5,000+"


async def fetch_xbrl_employees(cik: str, session: aiohttp.ClientSession) -> dict:
    """
    Pull EntityNumberOfEmployees from XBRL companyconcept API.
    Only works for public companies that tag this DEI element in 10-K.
    Coverage: ~85% of public filers.
    """
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/dei/EntityNumberOfEmployees.json"
    headers = {"User-Agent": EDGAR_UA}
    try:
        async with SEM_EDGAR:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 404:
                    return {"sf_employee_range": None, "sf_employee_count": None}
                if resp.status != 200:
                    return {}
                data = await resp.json(content_type=None)

        # units.pure is an array of filings with val, end, form
        facts = data.get("units", {}).get("pure", []) or []

        # Take the most recent 10-K filing value
        ten_k_facts = [f for f in facts if f.get("form") == "10-K"]
        if not ten_k_facts:
            return {"sf_employee_range": None, "sf_employee_count": None}

        # Sort by end date descending
        ten_k_facts.sort(key=lambda x: x.get("end", ""), reverse=True)
        count = ten_k_facts[0].get("val")
        if count is None:
            return {"sf_employee_range": None, "sf_employee_count": None}

        return {
            "sf_employee_count": int(count),
            "sf_employee_range": _employee_count_to_range(int(count)),
        }
    except Exception as e:
        return {"xbrl_error": str(e)}


# ─────────────────────────────────────────────────────────────
# SEC EDGAR — Form D (private company funding)
#
# Regulation D private placements — most VC-backed Series A/B/C
# biotechs file Form D within 15 days of closing.
# Free via EDGAR full-text search.
# ─────────────────────────────────────────────────────────────

async def fetch_form_d(company_name: str, name_variants: list, session: aiohttp.ClientSession) -> dict:
    """
    Search EDGAR for Form D filings (private placements) where this company is the filer.

    Uses EDGAR EFTS full-text search then validates the hit's display_names
    contains the queried company name — prevents false positives where the name
    appears as an investor or mention inside someone else's Form D.

    Returns file_date of the most recent matching filing if found.
    (Amount is in the filing XML — not available from the EFTS search response.)
    """
    cutoff = two_years_ago()
    headers = {"User-Agent": EDGAR_UA}
    url = "https://efts.sec.gov/LATEST/search-index"

    for name in name_variants:
        if len(name) < 5:   # Skip short names — too many false positives
            continue
        name_lower = name.lower()
        params = {
            "q":         f'"{name}"',
            "forms":     "D",
            "dateRange": "custom",
            "startdt":   cutoff,
        }
        try:
            async with SEM_EDGAR:
                async with session.get(url, params=params, headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)

            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                continue

            # Only accept hits where the filer name matches (display_names contains company name)
            matched = []
            for h in hits:
                src = h.get("_source", {})
                display_names = src.get("display_names", []) or []
                if any(name_lower in dn.lower() for dn in display_names):
                    matched.append(src)

            if not matched:
                continue

            # Take the most recent filing by file_date
            matched.sort(key=lambda s: s.get("file_date", ""), reverse=True)
            best = matched[0]

            return {
                "si_form_d_found": True,
                "si_form_d_date":  best.get("file_date"),
                "si_form_d_amount": None,   # amount requires fetching the filing XML
            }
        except Exception:
            continue

    return {"si_form_d_found": False}


# ─────────────────────────────────────────────────────────────
# PubMed E-utilities
# ─────────────────────────────────────────────────────────────

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EMAIL = "pipeline@emolecules.com"

PUBMED_QUERIES = {
    "drug_discovery": (
        '("{name}"[ad]) AND ('
        '"drug discovery"[tiab] OR "medicinal chemistry"[tiab] OR '
        '"small molecule"[tiab] OR "lead optimization"[tiab] OR '
        '"hit-to-lead"[tiab] OR "SAR"[tiab])'
        ' AND 2022:2026[dp]'
    ),
    "cadd": (
        '("{name}"[ad]) AND ('
        '"computational chemistry"[tiab] OR "CADD"[tiab] OR '
        '"virtual screening"[tiab] OR "molecular docking"[tiab] OR '
        '"structure-activity relationship"[tiab] OR "in silico"[tiab])'
        ' AND 2022:2026[dp]'
    ),
    "virtual_screening": (
        '("{name}"[ad]) AND ('
        '"virtual screening"[tiab] OR "molecular docking"[tiab] OR '
        '"docking simulation"[tiab] OR "in silico screening"[tiab])'
        ' AND 2022:2026[dp]'
    ),
}

async def query_pubmed(company_name: str, query_type: str, session: aiohttp.ClientSession) -> int:
    """Returns count of PubMed papers matching the query for this company."""
    term = PUBMED_QUERIES[query_type].format(name=company_name)
    params = {
        "db":      "pubmed",
        "term":    term,
        "retmode": "json",
        "retmax":  "0",   # count only
        "email":   PUBMED_EMAIL,
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    try:
        async with SEM_PUBMED:
            async with session.get(PUBMED_BASE, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return 0
                data = await resp.json()
        count = int(data.get("esearchresult", {}).get("count", 0))
        # brief delay to respect rate limit
        await asyncio.sleep(0.4 if not NCBI_API_KEY else 0.1)
        return count
    except Exception:
        return 0


async def query_all_pubmed(company_name: str, session: aiohttp.ClientSession, name_variants: list = None) -> dict:
    """
    Run all three PubMed queries. If name_variants is provided, tries each
    variant and returns the max count across all variants per query type.
    Trying multiple name forms (e.g. 'Gilead Sciences Inc', 'Gilead Sciences',
    'Gilead') catches affiliation strings that don't match a single form.
    """
    variants = name_variants if name_variants else [company_name]

    best_dd, best_cad, best_vs = 0, 0, 0
    for name in variants:
        dd  = await query_pubmed(name, "drug_discovery",    session)
        cad = await query_pubmed(name, "cadd",              session)
        vs  = await query_pubmed(name, "virtual_screening", session)
        best_dd  = max(best_dd,  dd)
        best_cad = max(best_cad, cad)
        best_vs  = max(best_vs,  vs)

    return {
        "pubmed_drug_discovery_count":    best_dd,
        "pubmed_cadd_count":              best_cad,
        "pubmed_virtual_screening_count": best_vs,
    }


# ─────────────────────────────────────────────────────────────
# PatentsView / PatentSearch API (USPTO Open Data Portal)
#
# Migrated to search.patentsview.org on March 20, 2026.
# Old endpoint (api.patentsview.org) is discontinued.
# Requires free API key: https://patentsview.org/apis/keyrequest
# Set PATENTSVIEW_API_KEY in .env — without it requests return 401.
# ─────────────────────────────────────────────────────────────

PATENTSVIEW_URL = "https://search.patentsview.org/api/v1/patent/"

async def query_patents(company_name: str, session: aiohttp.ClientSession) -> dict:
    """
    Count patents assigned to this company in the last 3 years.
    Uses new PatentSearch API at search.patentsview.org.
    Requires PATENTSVIEW_API_KEY env var (free — request at patentsview.org).
    """
    if not PATENTSVIEW_API_KEY:
        return {"patent_error": "PATENTSVIEW_API_KEY not set — request free key at patentsview.org/apis/keyrequest"}

    q = json.dumps({"_and": [
        {"_contains": {"assignees_at_grant.assignee_organization": company_name}},
        {"_gte": {"patent_date": three_years_ago()}}
    ]})
    f = json.dumps(["patent_id", "patent_date", "patent_title",
                    "assignees_at_grant.assignee_organization"])
    o = json.dumps({"size": 5})

    headers = {
        "User-Agent":  EDGAR_UA,
        "X-Api-Key":   PATENTSVIEW_API_KEY,
        "Accept":      "application/json",
    }

    try:
        async with SEM_PATENTS:
            async with session.get(
                PATENTSVIEW_URL,
                params={"q": q, "f": f, "o": o},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status in (401, 403):
                    return {"patent_error": f"PatentSearch API auth failed ({resp.status}) — check PATENTSVIEW_API_KEY"}
                if resp.status != 200:
                    return {"patent_error": f"PatentSearch API HTTP {resp.status}"}
                data = await resp.json(content_type=None)
            await asyncio.sleep(1.4)   # 45 req/min limit

        # Response format: {"hits": {"total": {"value": N}, "hits": [{"_source": {...}}]}}
        hits_block = data.get("hits", {})
        total_val  = hits_block.get("total", {})
        total      = total_val.get("value", 0) if isinstance(total_val, dict) else int(total_val or 0)
        hits_list  = hits_block.get("hits", []) or []

        most_recent_title = None
        most_recent_date  = None
        if hits_list:
            src = hits_list[0].get("_source", {})
            most_recent_title = src.get("patent_title")
            most_recent_date  = src.get("patent_date")

        return {
            "patent_count_3yr":         total,
            "patent_most_recent_title": most_recent_title,
            "patent_most_recent_date":  most_recent_date,
        }
    except Exception as e:
        return {"patent_error": str(e)}


# ─────────────────────────────────────────────────────────────
# ChEMBL REST API
# ─────────────────────────────────────────────────────────────

CHEMBL_BASE = "https://www.ebi.ac.uk/chembl/api/data"

async def query_chembl(company_name: str, session: aiohttp.ClientSession) -> dict:
    """Check if company has approved drugs listed in ChEMBL."""
    url = f"{CHEMBL_BASE}/drug"
    params = {
        "applicants__icontains": company_name,
        "format": "json",
        "limit": "10",
    }
    try:
        async with SEM_CHEMBL:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
            await asyncio.sleep(1.1)   # 1 req/s

        count = data.get("page_meta", {}).get("total_count", 0) or 0
        results = data.get("drugs", []) or data.get("molecules", []) or data.get("results", []) or []

        sample_drugs = [
            r.get("pref_name") or r.get("molecule_chembl_id")
            for r in results[:5]
            if r.get("pref_name") or r.get("molecule_chembl_id")
        ]

        return {
            "chembl_drug_count":  count,
            "chembl_sample_drugs": sample_drugs,
        }
    except Exception as e:
        return {"chembl_error": str(e)}


async def query_chembl_assays(company_name: str, session: aiohttp.ClientSession) -> dict:
    """
    Count ChEMBL assays where this company is listed as source.
    Catches preclinical med chem (bioactivity data) that didn't produce approved drugs.
    A company appearing as assay source = they deposited compound screening data.
    """
    url = f"{CHEMBL_BASE}/source"
    params = {
        "src_description__icontains": company_name,
        "format": "json",
        "limit": "5",
    }
    try:
        async with SEM_CHEMBL:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
            await asyncio.sleep(1.1)

        sources = data.get("sources", []) or data.get("results", []) or []
        src_ids = [s.get("src_id") for s in sources if s.get("src_id") is not None]
        if not src_ids:
            return {"chembl_assay_count": 0, "chembl_document_count": 0}

        # For each source id, count assays + documents
        total_assays = 0
        total_docs   = 0
        for sid in src_ids[:3]:   # cap at 3 source IDs to limit requests
            # Assays
            a_url = f"{CHEMBL_BASE}/assay"
            a_params = {"src_id": sid, "format": "json", "limit": "1"}
            async with SEM_CHEMBL:
                async with session.get(a_url, params=a_params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        a_data = await resp.json()
                        total_assays += a_data.get("page_meta", {}).get("total_count", 0) or 0
                await asyncio.sleep(1.1)
            # Documents (papers)
            d_url = f"{CHEMBL_BASE}/document"
            d_params = {"src_id": sid, "format": "json", "limit": "1"}
            async with SEM_CHEMBL:
                async with session.get(d_url, params=d_params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        d_data = await resp.json()
                        total_docs += d_data.get("page_meta", {}).get("total_count", 0) or 0
                await asyncio.sleep(1.1)

        return {
            "chembl_assay_count":    total_assays,
            "chembl_document_count": total_docs,
        }
    except Exception as e:
        return {"chembl_assays_error": str(e)}


# ─────────────────────────────────────────────────────────────
# PubChem BioAssay — HTS screening campaigns deposited by companies
# Free, no key. https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest
# ─────────────────────────────────────────────────────────────

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
SEM_PUBCHEM  = asyncio.Semaphore(3)

async def query_pubchem_bioassay(company_name: str, session: aiohttp.ClientSession) -> dict:
    """
    Count BioAssays sourced/deposited by this company in PubChem.
    Uses E-utilities esearch against the pcassay db filtered by SourceName.
    Very strong med-chem signal — if they're screening, they have chemists.
    """
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db":      "pcassay",
        "term":    f'"{company_name}"[SourceName]',
        "retmode": "json",
        "retmax":  "0",
        "email":   PUBMED_EMAIL,
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    try:
        async with SEM_PUBCHEM:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json(content_type=None)
            await asyncio.sleep(0.3)

        count = int(data.get("esearchresult", {}).get("count", 0) or 0)
        return {"pubchem_bioassay_count": count}
    except Exception as e:
        return {"pubchem_error": str(e)}


# ─────────────────────────────────────────────────────────────
# RCSB PDB — protein-ligand crystal structures (SBDD signal)
# Free, no key. Structure-based drug design = med chem + CADD.
# ─────────────────────────────────────────────────────────────

RCSB_SEARCH = "https://search.rcsb.org/rcsbsearch/v2/query"
SEM_RCSB    = asyncio.Semaphore(4)

async def query_rcsb_pdb(company_name: str, session: aiohttp.ClientSession) -> dict:
    """
    Count PDB structures where the company appears as a depositor institution.
    A company with co-crystal structures is doing structure-based drug design.

    Guards against false positives from short or single-letter tokens
    (e.g. "X Chem" would match every Chinese author "Xu/Xiao/..." in PDB).
    Searches the 'pdbx_descriptor' / host org fields when name is specific
    enough; bails out on ambiguous short names.
    """
    # Reject short or ambiguous queries
    name = company_name.strip()
    tokens = name.split()
    if len(name) < 5 or any(len(t) <= 2 for t in tokens):
        return {"rcsb_pdb_count": 0, "rcsb_skipped": "name too short/ambiguous"}

    # Use exact_match on full phrase rather than contains_words on loose tokens
    query = {
        "query": {
            "type": "terminal",
            "service": "text",
            "parameters": {
                "attribute": "rcsb_primary_citation.rcsb_authors",
                "operator": "contains_phrase",
                "value": name,
            },
        },
        "return_type": "entry",
        "request_options": {"return_counts": True},
    }
    try:
        async with SEM_RCSB:
            async with session.post(RCSB_SEARCH, json=query, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 204:   # no results
                    return {"rcsb_pdb_count": 0}
                if resp.status != 200:
                    return {}
                data = await resp.json(content_type=None)
            await asyncio.sleep(0.2)

        # With return_counts, RCSB returns the integer directly or in total_count key
        if isinstance(data, int):
            count = data
        else:
            count = data.get("total_count", 0) or 0
        return {"rcsb_pdb_count": int(count)}
    except Exception as e:
        return {"rcsb_error": str(e)}


# ─────────────────────────────────────────────────────────────
# EPO Open Patent Services (OPS) — free fallback for USPTO patents
#
# Register at ops.epo.org for a free consumer key + secret.
# Set EPO_OPS_KEY="consumer_key:consumer_secret" in .env.
# Covers EP + PCT + USPTO via DOCDB. Token valid 20 min; cached here.
# ─────────────────────────────────────────────────────────────

import base64

_epo_token: str = ""
_epo_token_expires: float = 0.0
SEM_EPO = asyncio.Semaphore(4)   # EPO OPS: 30 req/min on free tier


async def _get_epo_token(session: aiohttp.ClientSession) -> str:
    """Fetch or return cached EPO OPS OAuth2 access token."""
    global _epo_token, _epo_token_expires
    now = time.time()
    if _epo_token and now < _epo_token_expires - 60:
        return _epo_token

    if not EPO_OPS_KEY or ":" not in EPO_OPS_KEY:
        return ""

    consumer_key, consumer_secret = EPO_OPS_KEY.split(":", 1)
    credentials = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()

    try:
        async with SEM_EPO:
            async with session.post(
                "https://ops.epo.org/3.2/auth/accesstoken",
                data={"grant_type": "client_credentials"},
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return ""
                data = await resp.json(content_type=None)
        _epo_token = data.get("access_token", "")
        _epo_token_expires = now + int(data.get("expires_in", 1200))
        return _epo_token
    except Exception:
        return ""


async def _epo_search_count(session: aiohttp.ClientSession, token: str, cql: str) -> int:
    """Return total count for an EPO OPS CQL query via published-data/search."""
    async with SEM_EPO:
        async with session.get(
            "https://ops.epo.org/3.2/rest-services/published-data/search",
            params={"q": cql, "Range": "1-1"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status == 404:
                return 0
            if resp.status != 200:
                raise RuntimeError(f"EPO OPS HTTP {resp.status}")
            data = await resp.json(content_type=None)
        await asyncio.sleep(2.1)
    total_str = data.get("ops:world-patent-data",{}).get("ops:biblio-search",{}).get("@total-result-count","0")
    return int(total_str) if str(total_str).isdigit() else 0


async def _epo_search_biblio_titles(session: aiohttp.ClientSession, token: str,
                                    cql: str, limit: int = 3) -> list:
    """Fetch real invention titles (not just patent numbers) via /search/biblio."""
    async with SEM_EPO:
        async with session.get(
            "https://ops.epo.org/3.2/rest-services/published-data/search/biblio",
            params={"q": cql, "Range": f"1-{limit}"},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=25),
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json(content_type=None)
        await asyncio.sleep(2.1)

    docs = data.get("ops:world-patent-data",{}).get("ops:biblio-search",{})\
               .get("ops:search-result",{}).get("exchange-documents",[])
    if not isinstance(docs, list):
        docs = [docs]

    titles = []
    for entry in docs[:limit]:
        if not isinstance(entry, dict):
            continue
        doc = entry.get("exchange-document", {})
        biblio = doc.get("bibliographic-data", {}) if isinstance(doc, dict) else {}
        title_list = biblio.get("invention-title", []) or []
        if isinstance(title_list, dict):
            title_list = [title_list]
        en_title = next(
            (t.get("$","") for t in title_list if isinstance(t, dict) and t.get("@lang")=="en"),
            next((t.get("$","") for t in title_list if isinstance(t, dict)), "")
        )
        if en_title:
            # Titlecase for readability; EPO returns ALL CAPS
            titles.append(en_title.strip().title())
    return titles


async def query_epo_patents(company_name: str, session: aiohttp.ClientSession) -> dict:
    """
    Count patents filed by company using EPO OPS published-data search.
    Covers EP + PCT + USPTO via DOCDB. Two counts returned:
      - patent_count_3yr        — all patent classes (tools, instruments, pharma, etc.)
      - patent_pharma_count_3yr — filtered to CPC A61K / C07D / C07K (drug-related)
    The pharma count is a much stronger ICP signal — distinguishes drug-discovery
    patents from instrument / reagent / device patents.
    """
    if not EPO_OPS_KEY:
        return {"patent_error": "EPO_OPS_KEY not set — register free at ops.epo.org"}

    token = await _get_epo_token(session)
    if not token:
        return {"patent_error": "EPO OPS auth failed — check EPO_OPS_KEY"}

    year_cutoff = datetime.now().year - 3
    base_cql   = f'pa="{company_name}" AND pd>={year_cutoff}0101'
    pharma_cql = f'{base_cql} AND (cpc=A61K OR cpc=C07D OR cpc=C07K)'

    try:
        # 1. Total count (all classes)
        total_all = await _epo_search_count(session, token, base_cql)
        # 2. Pharma-class count
        total_pharma = 0
        try:
            total_pharma = await _epo_search_count(session, token, pharma_cql)
        except Exception:
            pass   # pharma filter optional — total already captured
        # 3. Recent pharma patent titles (real titles via biblio constituent)
        titles = []
        if total_pharma > 0:
            try:
                titles = await _epo_search_biblio_titles(session, token, pharma_cql, limit=3)
            except Exception:
                pass
        elif total_all > 0:
            try:
                titles = await _epo_search_biblio_titles(session, token, base_cql, limit=3)
            except Exception:
                pass

        most_recent_title = titles[0] if titles else None

        return {
            "patent_count_3yr":         total_all,
            "patent_pharma_count_3yr":  total_pharma,
            "patent_recent_titles":     titles,   # list of up to 3 real invention titles
            "patent_most_recent_title": most_recent_title,
            "patent_most_recent_date":  None,
            "patent_source":            "EPO OPS",
        }
    except Exception as e:
        return {"patent_error": f"EPO OPS: {e}"}


# ─────────────────────────────────────────────────────────────
# OpenAlex — free supplement to PubMed
#
# No API key required (email in params for polite pool).
# Searches by institution name — more comprehensive than PubMed
# for EU/Asian biotechs whose papers may not use [ad] tagging.
# Two-step: resolve institution ID → count works.
# ─────────────────────────────────────────────────────────────

OPENALEX_EMAIL = "pipeline@emolecules.com"
OPENALEX_BASE  = "https://api.openalex.org"
SEM_OPENALEX   = asyncio.Semaphore(5)   # ~10 req/sec polite pool


async def query_openalex(company_name: str, session: aiohttp.ClientSession) -> dict:
    """
    Count drug-discovery-related works from this institution on OpenAlex.
    Returns total work count (2022+). Free, no key required.
    """
    try:
        # Step 1: Resolve institution — try company/healthcare types first,
        # then fall back to unrestricted search (pharma may be tagged as healthcare)
        inst_id = None
        for type_filter in ["type:company|healthcare", None]:
            params = {
                "search": company_name,
                "per-page": "3",
                "select": "id,display_name,type,works_count",
                "mailto": OPENALEX_EMAIL,
            }
            if type_filter:
                params["filter"] = type_filter

            async with SEM_OPENALEX:
                async with session.get(
                    f"{OPENALEX_BASE}/institutions",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        return {"openalex_works_count": 0}
                    inst_data = await resp.json()

            results = inst_data.get("results", [])
            if results:
                inst_id = results[0].get("id", "")
                break

        if not inst_id:
            return {"openalex_works_count": 0}

        # Step 2: Count works (drug discovery topics, 2022+)
        async with SEM_OPENALEX:
            async with session.get(
                f"{OPENALEX_BASE}/works",
                params={
                    "filter": f"authorships.institutions.id:{inst_id},publication_year:>2021",
                    "per-page": "1",
                    "select": "id",
                    "mailto": OPENALEX_EMAIL,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return {"openalex_works_count": 0}
                works_data = await resp.json()
        count = works_data.get("meta", {}).get("count", 0) or 0

        # Step 3: Count med-chem works using OpenAlex concept ID
        # C71924100 = "Medicinal chemistry" concept
        medchem_count = 0
        async with SEM_OPENALEX:
            async with session.get(
                f"{OPENALEX_BASE}/works",
                params={
                    "filter": (
                        f"authorships.institutions.id:{inst_id},"
                        f"concepts.id:C71924100,publication_year:>2021"
                    ),
                    "per-page": "1",
                    "select": "id",
                    "mailto": OPENALEX_EMAIL,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    mc_data = await resp.json()
                    medchem_count = mc_data.get("meta", {}).get("count", 0) or 0

        # Step 4: Collect author names from recent medchem (or any) papers.
        # These become sig_cq_authors — real chemist names from publications.
        author_names: list[str] = []
        works_filter = (
            f"authorships.institutions.id:{inst_id},concepts.id:C71924100,publication_year:>2021"
            if medchem_count > 0
            else f"authorships.institutions.id:{inst_id},publication_year:>2021"
        )
        async with SEM_OPENALEX:
            async with session.get(
                f"{OPENALEX_BASE}/works",
                params={
                    "filter":  works_filter,
                    "per-page": "8",
                    "select":  "authorships",
                    "mailto":  OPENALEX_EMAIL,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    w_data = await resp.json()
                    for work in (w_data.get("results") or []):
                        for authorship in (work.get("authorships") or []):
                            # Only include authors affiliated with this institution
                            inst_ids = [i.get("id") for i in (authorship.get("institutions") or [])]
                            if inst_id not in inst_ids:
                                continue
                            name = (authorship.get("author") or {}).get("display_name")
                            if name and name not in author_names:
                                author_names.append(name)
                            if len(author_names) >= 12:
                                break
                        if len(author_names) >= 12:
                            break

        return {
            "openalex_works_count":   int(count),
            "openalex_medchem_works": int(medchem_count),
            "openalex_author_names":  author_names,
        }

    except Exception:
        return {"openalex_works_count": 0, "openalex_medchem_works": 0,
                "openalex_author_names": []}


# ─────────────────────────────────────────────────────────────
# OpenDART (Korean FSS) — Korean public company register
# Uses manually-seeded opendart_registry (domain → corp_code → stock_code)
# Augments sig_is_public for Korean pharma/biotech.
# ─────────────────────────────────────────────────────────────

_OPENDART_REGISTRY: dict = {}
_OPENDART_LOADED = False

async def _load_opendart_registry(session: aiohttp.ClientSession) -> None:
    global _OPENDART_REGISTRY, _OPENDART_LOADED
    if _OPENDART_LOADED:
        return
    if not SUPABASE_URL or not SUPABASE_KEY:
        _OPENDART_LOADED = True
        return
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    url = f"{SUPABASE_URL}/rest/v1/opendart_registry?select=domain,corp_code,corp_name_kr,stock_code&limit=5000"
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                rows = await resp.json()
                for r in rows:
                    _OPENDART_REGISTRY[r["domain"]] = r
                print(f"  [OpenDART] Loaded {len(_OPENDART_REGISTRY)} Korean corp mappings")
    except Exception as e:
        print(f"  [OpenDART] registry load error: {e}")
    _OPENDART_LOADED = True


async def query_opendart(domain: str, session: aiohttp.ClientSession) -> dict:
    """Lookup Korean public company via seeded opendart_registry."""
    await _load_opendart_registry(session)
    entry = _OPENDART_REGISTRY.get(domain)
    if not entry:
        return {"opendart_registry": "not_registered"}
    return {
        "opendart_registry":   "registered",
        "opendart_corp_code":  entry.get("corp_code"),
        "opendart_corp_name_kr": entry.get("corp_name_kr"),
        "opendart_stock_code": (entry.get("stock_code") or "").strip(),
    }


# ─────────────────────────────────────────────────────────────
# Sirene (France) via recherche-entreprises.api.gouv.fr
# Free, no auth. Augments sig_sf_is_public + sig_sf_employee_range
# for French companies (biotech R&D via NAF code 72.11Z etc.)
# ─────────────────────────────────────────────────────────────

SIRENE_URL = "https://recherche-entreprises.api.gouv.fr/search"
SEM_SIRENE = asyncio.Semaphore(4)

# NAF codes we care about — biotech / pharma / chemistry
_SIRENE_BIOTECH_NAF = {
    "72.11Z",  # Recherche-développement en biotechnologie
    "72.19Z",  # R&D en autres sciences physiques et naturelles
    "21.10Z",  # Fabrication produits pharmaceutiques de base
    "21.20Z",  # Fabrication de préparations pharmaceutiques
    "20.59Z",  # Fabrication d'autres produits chimiques
    "46.46Z",  # Commerce de gros produits pharmaceutiques
    "74.9XZ",  # Other specialized services
}

# INSEE employee bracket codes → our standard ranges
_SIRENE_EMP_BUCKETS = {
    "00": "0",
    "01": "<10",   "02": "<10",   "03": "<10",
    "11": "10-50", "12": "10-50",
    "21": "51-150","22": "51-150",
    "31": "151-500","32": "151-500",
    "41": "501-1,000",
    "42": "1,001-5,000", "51": "1,001-5,000",
    "52": "5,000+",      "53": "5,000+",
}
_SIRENE_EMP_EST = {  # midpoint estimates
    "01": 2, "02": 4, "03": 7,
    "11": 15, "12": 35,
    "21": 75, "22": 150,
    "31": 225, "32": 375,
    "41": 750,
    "42": 1500, "51": 3500,
    "52": 7500, "53": 15000,
}


async def query_sirene(company_name: str, domain: str,
                        session: aiohttp.ClientSession) -> dict:
    """
    Search the French company register (Sirene) for biotech/pharma/chemistry cos.
    Filters results to relevant NAF codes only. Returns top match's SIREN + legal
    form + employee bracket.
    """
    if len(company_name) < 4:
        return {}

    # Strip common corporate suffixes for search
    core = re.sub(
        r',?\s*(and\s+|&\s*)?\b(Inc|Ltd|Corp|LLC|AG|Plc|Gmbh|Sa|Sas|Nv|Bv|Se|Co|Company|Holding|Pharmaceuticals?|Pharma|Biosciences|Therapeutics)\b\.?',
        '', company_name, flags=re.IGNORECASE,
    ).strip()
    if len(core) < 4:
        return {}

    params = {"q": core, "page": 1, "per_page": 15}
    try:
        async with SEM_SIRENE:
            async with session.get(
                SIRENE_URL, params=params,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return {"sirene_error": f"HTTP {resp.status}"}
                data = await resp.json()
            await asyncio.sleep(0.35)

        results = data.get("results", []) or []
        if not results:
            return {"sirene_found": False}

        # Filter to biotech/pharma/chemistry NAF codes
        biotech_hits = [
            r for r in results
            if (r.get("activite_principale") or "") in _SIRENE_BIOTECH_NAF
        ]
        if not biotech_hits:
            return {"sirene_found": False, "sirene_non_biotech_only": True,
                    "sirene_total_results": data.get("total_results", 0)}

        # Rank: prefer hits where the name matches the query word-start
        core_lower = core.lower()
        def score(r):
            name_lower = (r.get("nom_complet") or r.get("nom") or "").lower()
            starts_with = 0 if name_lower.startswith(core_lower) else 1
            # Prefer PME/ETI/GE over unclassified (real operating companies)
            has_cat = 0 if r.get("categorie_entreprise") else 1
            return (starts_with, has_cat, len(name_lower))
        biotech_hits.sort(key=score)
        best = biotech_hits[0]

        emp_code = best.get("tranche_effectif_salarie") or "NN"
        emp_range = _SIRENE_EMP_BUCKETS.get(emp_code)
        emp_est   = _SIRENE_EMP_EST.get(emp_code)
        emp_year  = best.get("annee_tranche_effectif_salarie")

        siege = best.get("siege") or {}
        city  = siege.get("libelle_commune")

        return {
            "sirene_found":       True,
            "sirene_siren":       best.get("siren"),
            "sirene_name":        best.get("nom_complet") or best.get("nom"),
            "sirene_naf":         best.get("activite_principale"),
            "sirene_categorie":   best.get("categorie_entreprise"),   # PME/ETI/GE
            "sirene_city":        city,
            "sirene_emp_code":    emp_code,
            "sirene_emp_range":   emp_range,
            "sirene_emp_est":     emp_est,
            "sirene_emp_year":    emp_year,
        }
    except Exception as e:
        return {"sirene_error": f"Sirene: {e}"}


# ─────────────────────────────────────────────────────────────
# Greenhouse ATS — chemistry-role open positions
# Public boards API, no auth. Needs `ats_registry` Supabase helper
# table mapping domain → board_token (manually seeded, ~50 companies).
# Feeds: sig_si_recent_chem_hires (ONLY new sig_* introduced by this layer)
# ─────────────────────────────────────────────────────────────

SEM_GREENHOUSE = asyncio.Semaphore(4)

# Keywords that flag a job as chemistry-relevant (title-match, case-insensitive).
# Ordered rough seniority-first for future weighting.
_CHEM_ROLE_KEYWORDS = [
    "medicinal chemist", "medicinal chemistry",
    "computational chemist", "computational chemistry",
    "cheminformatics", "cadd",
    "drug discovery", "discovery chemistry",
    "structure-based design", "sbdd",
    "process chemistry", "process chemist",
    "synthetic chemist", "organic chemist",
    "chemistry", "chemist",   # coarse catch-all last
]

# ats_registry cache — loaded once per pipeline run
_ATS_REGISTRY: dict = {}
_ATS_LOADED = False


async def _load_ats_registry(session: aiohttp.ClientSession) -> None:
    """Load ats_registry into memory once. Returns {domain: {ats_type, board_token}}."""
    global _ATS_REGISTRY, _ATS_LOADED
    if _ATS_LOADED:
        return
    if not SUPABASE_URL or not SUPABASE_KEY:
        _ATS_LOADED = True
        return
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    url = f"{SUPABASE_URL}/rest/v1/ats_registry?select=domain,ats_type,board_token&limit=5000"
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 200:
                rows = await resp.json()
                for r in rows:
                    _ATS_REGISTRY[r["domain"]] = {
                        "ats_type": r.get("ats_type", "greenhouse"),
                        "board_token": r.get("board_token"),
                    }
                print(f"  [ATS] Loaded {len(_ATS_REGISTRY)} Greenhouse board tokens")
    except Exception as e:
        print(f"  [ATS] registry load error: {e}")
    _ATS_LOADED = True


def _chem_matches(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in _CHEM_ROLE_KEYWORDS)


async def query_greenhouse(domain: str, session: aiohttp.ClientSession) -> dict:
    """
    Fetch open jobs from the company's Greenhouse board (if registered) and
    count chemistry-relevant roles. Only runs if domain is in ats_registry.
    """
    await _load_ats_registry(session)
    entry = _ATS_REGISTRY.get(domain)
    if not entry or entry.get("ats_type") != "greenhouse":
        return {"greenhouse_registry": "not_registered"}

    token = entry["board_token"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    try:
        async with SEM_GREENHOUSE:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 404:
                    return {"greenhouse_error": f"board '{token}' returned 404"}
                if resp.status != 200:
                    return {"greenhouse_error": f"HTTP {resp.status}"}
                data = await resp.json()
            await asyncio.sleep(0.3)

        jobs = data.get("jobs", []) or []
        chem_jobs = []
        for j in jobs:
            title = j.get("title", "")
            if _chem_matches(title):
                chem_jobs.append({
                    "title":      title,
                    "updated_at": (j.get("updated_at") or "")[:10],
                    "location":   (j.get("location") or {}).get("name"),
                })
        return {
            "greenhouse_registry":   "registered",
            "greenhouse_board":      token,
            "greenhouse_total_jobs": len(jobs),
            "greenhouse_chem_count": len(chem_jobs),
            "greenhouse_chem_jobs":  chem_jobs[:5],   # keep top 5 for signal string
        }
    except Exception as e:
        return {"greenhouse_error": f"Greenhouse: {e}"}


# ─────────────────────────────────────────────────────────────
# Swiss Zefix via LINDAS SPARQL — Swiss company register
# Free, no auth, no signup. Augments sig_sf_is_public for Swiss cos
# (Roche, Idorsia, Novartis, etc.) that SEC EDGAR misses.
# ─────────────────────────────────────────────────────────────

LINDAS_URL = "https://lindas.admin.ch/query"
SEM_LINDAS = asyncio.Semaphore(2)

# Common legal-form tokens that are subsidiaries/foundations (not the main op co)
# Filter these out of name matches.
_SWISS_SUBSIDIARY_NOISE = (
    "personalvorsorge", "pensionskasse", "stiftung", "foundation",
    "vorsorgestiftung", "hilfsfonds", "club",
    # Branch / subsidiary indicators (any language)
    "branch", "zweigniederlassung", "succursale", "sucursal",
    "filiale", "filial",
)


async def query_zefix_sparql(company_name: str, domain: str,
                              session: aiohttp.ClientSession) -> dict:
    """
    Look up Swiss company register via LINDAS SPARQL.
    Returns Swiss legal entity info if a match is found.
    Runs for all domains — LINDAS returns nothing for non-Swiss, no cost.
    """
    if len(company_name) < 4:
        return {}

    # Normalize: strip Inc/Ltd/Corp/etc., search by core name
    core = re.sub(
        r',?\s*(and\s+|&\s*)?\b(Inc|Ltd|Corp|LLC|AG|Plc|Gmbh|Sa|Nv|Bv|Se|Co|Company|Holding|Pharmaceuticals?|Pharma)\b\.?',
        '', company_name, flags=re.IGNORECASE,
    ).strip().lower()
    if len(core) < 4:
        return {}

    # Escape quote for SPARQL literal safety
    core_safe = core.replace('"', '\\"').replace('\\', '\\\\')

    # Word-boundary regex: core must match at start of a word (not mid-word).
    # This avoids "roche" matching "envirochemie" and "osmo" matching "belcosmo".
    # \b doesn't always work in SPARQL REGEX — use explicit start-or-space boundary.
    sparql = f"""
    PREFIX schema: <http://schema.org/>
    PREFIX admin: <https://schema.ld.admin.ch/>
    SELECT ?company ?name ?uid ?status WHERE {{
      ?company a admin:ZefixOrganisation ;
               schema:name ?name ;
               schema:identifier ?uid .
      OPTIONAL {{ ?company admin:companyStatus ?status }}
      FILTER(REGEX(LCASE(STR(?name)), "(^|[^a-z]){core_safe}([^a-z]|$)"))
    }} LIMIT 20
    """

    try:
        async with SEM_LINDAS:
            async with session.post(
                LINDAS_URL,
                data={"query": sparql},
                headers={"Accept": "application/sparql-results+json",
                         "Content-Type": "application/x-www-form-urlencoded"},
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                if resp.status != 200:
                    return {"zefix_error": f"LINDAS HTTP {resp.status}"}
                data = await resp.json(content_type=None)
            await asyncio.sleep(0.4)

        bindings = data.get("results", {}).get("bindings", []) or []
        if not bindings:
            return {"zefix_found": False}

        # Filter out: noise entities + hits without valid UIDs
        main_hits = []
        for b in bindings:
            name = b.get("name", {}).get("value", "")
            name_lower = name.lower()
            uid_uri = b.get("uid", {}).get("value", "") or ""
            # Reject if no valid UID URI (strips out "eselvita Kostelac" style non-company hits)
            if "UID/" not in uid_uri:
                continue
            if any(n in name_lower for n in _SWISS_SUBSIDIARY_NOISE):
                continue
            main_hits.append(b)
        if not main_hits:
            return {"zefix_found": False, "zefix_noise_only": True}

        # Ranking:
        # 1. Strong preference for hits where our search term starts the name
        #    (e.g. "Idorsia AG" starts with "idorsia" → prefer over mid-name matches)
        # 2. Among starts-with matches, prefer shortest name (closer to bare op co)
        def score(b):
            name_lower = b.get("name", {}).get("value", "").lower()
            starts_with = 0 if name_lower.startswith(core) else 1
            return (starts_with, len(name_lower))
        main_hits.sort(key=score)
        best = main_hits[0]
        name = best.get("name", {}).get("value", "")
        uid_uri = best.get("uid", {}).get("value", "")
        # UID URI looks like https://register.ld.admin.ch/zefix/company/898388/UID/CHE114062278
        uid_match = re.search(r'UID/(CHE\d+)', uid_uri)
        che_uid = uid_match.group(1) if uid_match else None
        # Format CHE114062278 as CHE-114.062.278 (standard Swiss UID format)
        che_formatted = None
        if che_uid and len(che_uid) == 12:
            che_formatted = f"{che_uid[:3]}-{che_uid[3:6]}.{che_uid[6:9]}.{che_uid[9:12]}"

        status_val = best.get("status", {}).get("value", "")
        # URI → short tag
        status_short = status_val.rsplit("/", 1)[-1] if status_val else None

        return {
            "zefix_found":  True,
            "zefix_name":   name,
            "zefix_uid":    che_formatted or che_uid,
            "zefix_status": status_short,
            "zefix_match_count": len(main_hits),
        }
    except Exception as e:
        return {"zefix_error": f"LINDAS: {e}"}


# ─────────────────────────────────────────────────────────────
# SBIR.gov — US SBIR/STTR award database
# Public REST, no auth. Endpoint intermittently throttles globally.
# Feeds: sf_employee_range (number_employees from awards)
#        si_recent_funding (non-dilutive SBIR/STTR awards)
# ─────────────────────────────────────────────────────────────

SBIR_URL = "https://api.www.sbir.gov/public/api/awards"
SEM_SBIR = asyncio.Semaphore(2)
SBIR_UA  = "eMolecules ICP Enrichment pipeline@emolecules.com"


async def query_sbir(company_name: str, session: aiohttp.ClientSession) -> dict:
    """
    Fetch SBIR/STTR awards where this company is the awardee firm.
    Returns aggregate + most-recent employee count (firm-reported).
    SBIR.gov API sometimes returns 429 globally ('not available'); swallow gracefully.
    """
    if len(company_name) < 3:
        return {}

    cutoff = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")
    params = {"firm": company_name, "start": cutoff}
    try:
        async with SEM_SBIR:
            async with session.get(
                SBIR_URL, params=params,
                headers={"User-Agent": SBIR_UA, "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status == 429:
                    return {"sbir_error": "SBIR API globally throttled (429)"}
                if resp.status != 200:
                    return {"sbir_error": f"SBIR HTTP {resp.status}"}
                data = await resp.json(content_type=None)
            await asyncio.sleep(0.5)

        if not isinstance(data, list):
            # API returns {"Code":..., "Message":...} on error
            return {"sbir_error": str(data)[:150]}

        if not data:
            return {"sbir_award_count": 0, "sbir_total_funding": 0}

        # Aggregate
        total_funding = 0
        emp_counts    = []
        latest_date   = ""
        for award in data:
            amt = award.get("award_amount")
            try:
                if amt: total_funding += int(float(str(amt).replace(",", "").replace("$", "")))
            except Exception:
                pass
            emp = award.get("number_employees")
            try:
                if emp is not None: emp_counts.append(int(emp))
            except Exception:
                pass
            d = award.get("proposal_award_date") or award.get("contract_end_date") or ""
            if d and d > latest_date:
                latest_date = d

        # Most recent employee count reported (trust latest filing)
        most_recent_emp = None
        if emp_counts:
            # Sort awards by date desc and take first with employee count
            sorted_awards = sorted(
                [a for a in data if a.get("number_employees") is not None],
                key=lambda a: a.get("proposal_award_date") or "",
                reverse=True,
            )
            if sorted_awards:
                try:
                    most_recent_emp = int(sorted_awards[0]["number_employees"])
                except Exception:
                    most_recent_emp = None

        return {
            "sbir_award_count":       len(data),
            "sbir_total_funding":     total_funding,
            "sbir_latest_award_date": latest_date or None,
            "sbir_employee_count":    most_recent_emp,
        }
    except Exception as e:
        return {"sbir_error": f"SBIR: {e}"}


# ─────────────────────────────────────────────────────────────
# NIH RePORTER — NIH grants database
# POST, no auth. Rate limit ~1 req/sec.
# Feeds: si_recent_funding (NIH grant total + latest FY)
# Note: requires exact UPPERCASE org names. Coverage skews to
# academic/hospital awardees; biotechs appear mainly via SBIR-through-NIH.
# ─────────────────────────────────────────────────────────────

NIH_URL = "https://api.reporter.nih.gov/v2/projects/search"
SEM_NIH = asyncio.Semaphore(1)


async def query_nih_reporter(company_name: str, session: aiohttp.ClientSession) -> dict:
    """
    Search NIH grants for the company as awardee organization.
    Tries uppercase variants since NIH org_names match is case-sensitive.
    """
    if len(company_name) < 3:
        return {}

    # Build uppercase variants to try (NIH stores names as ALL CAPS)
    variants = {company_name.upper()}
    # Also try "COMPANY INC", "COMPANY LLC", common suffixes — but keep set bounded
    variants.add(company_name.upper().replace(",", "").strip())

    current_fy = datetime.now().year
    fiscal_years = list(range(current_fy - 3, current_fy + 1))

    best = {"nih_grant_count": 0, "nih_total_funding": 0, "nih_latest_fiscal_year": None}
    try:
        for v in list(variants)[:3]:
            body = {
                "criteria": {"org_names": [v], "fiscal_years": fiscal_years},
                "limit": 100,
            }
            async with SEM_NIH:
                async with session.post(
                    NIH_URL, json=body,
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=25),
                ) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json(content_type=None)
                await asyncio.sleep(1.1)

            results = data.get("results") or []
            if not results:
                continue

            total_funding = 0
            latest_fy     = 0
            for proj in results:
                amt = proj.get("award_amount")
                try:
                    if amt: total_funding += int(amt)
                except Exception:
                    pass
                fy = proj.get("fiscal_year")
                if fy and fy > latest_fy:
                    latest_fy = fy

            # Keep the variant with the most results
            if len(results) > best["nih_grant_count"]:
                best = {
                    "nih_grant_count":        len(results),
                    "nih_total_funding":      total_funding,
                    "nih_latest_fiscal_year": latest_fy or None,
                }
        return best
    except Exception as e:
        return {"nih_error": f"NIH: {e}"}


# ─────────────────────────────────────────────────────────────
# ClinicalTrials.gov API v2
# ─────────────────────────────────────────────────────────────

CT_BASE = "https://clinicaltrials.gov/api/v2/studies"

async def query_clinicaltrials(company_name: str, session: aiohttp.ClientSession) -> dict:
    """
    Count trials where company is lead sponsor.
    Fetches total count and active recruiting trials (CT v2 doesn't support filter.phase).
    """
    params_total = {
        "query.lead":  company_name,
        "countTotal":  "true",
        "pageSize":    "1",
        "format":      "json",
    }
    params_active = {
        "query.lead":   company_name,
        "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING",
        "countTotal":  "true",
        "pageSize":    "5",
        "format":      "json",
    }

    total     = 0
    active    = 0
    most_recent_title = None

    try:
        async with SEM_CT:
            async with session.get(CT_BASE, params=params_total, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    total = data.get("totalCount", 0) or 0

            async with session.get(CT_BASE, params=params_active, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    active = data.get("totalCount", 0) or 0
                    studies = data.get("studies", [])
                    if studies:
                        try:
                            most_recent_title = (
                                studies[0]["protocolSection"]
                                ["identificationModule"]["briefTitle"]
                            )
                        except (KeyError, IndexError):
                            pass

        return {
            "ct_total_trials":      total,
            "ct_phase12_trials":    active,   # now: active recruiting trials (phase filter was invalid in v2)
            "ct_most_recent_title": most_recent_title,
        }
    except Exception as e:
        return {"ct_error": str(e)}


# ─────────────────────────────────────────────────────────────
# Homepage / subpage scraper
#
# Fetches /, /about, /team, /pipeline, /careers with aiohttp,
# extracts clean text via trafilatura, caps at 8 KB total.
# Produces site_summary_text stored in Supabase and injected
# into agent prompts as raw evidence for contact quality, pipeline,
# and stage-fit fields.
# ─────────────────────────────────────────────────────────────

async def _fetch_page_text(
    domain: str, path: str, session: aiohttp.ClientSession, *, return_html: bool = False
) -> tuple | None:
    """
    Fetch one page.
    - Normally returns (path, clean_text) or None on failure.
    - With return_html=True: returns (path, clean_text_or_None, raw_html) always on HTTP 200,
      so link discovery works even when trafilatura finds no text (JS-heavy SPAs).
    """
    url = f"https://{domain}{path}"
    try:
        async with SEM_SCRAPER:
            async with session.get(
                url,
                headers={"User-Agent": SCRAPE_UA},
                timeout=aiohttp.ClientTimeout(total=8),
                allow_redirects=True,
                ssl=False,
            ) as resp:
                if resp.status != 200:
                    return None
                ct = resp.headers.get("Content-Type", "")
                if "html" not in ct.lower():
                    return None
                html = await resp.text(errors="replace")
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            favor_precision=False,
        )
        good_text = text if (text and len(text.strip()) > 80) else None
        if return_html:
            return (path, good_text, html)  # always return HTML even if text extraction failed
        if good_text:
            return (path, good_text)
    except Exception:
        pass
    return None


async def _scrape_site_playwright(domain: str) -> list[tuple[str, str]]:
    """
    Headless browser fallback for JS-rendered SPAs.
    Launches one Chromium instance, renders homepage, discovers links,
    then fetches the top keyword-scored pages sequentially.
    Called only when static aiohttp scraping yields < 500 chars total.
    """
    from playwright.async_api import async_playwright

    pages: list[tuple[str, str]] = []

    async with SEM_PLAYWRIGHT:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                ctx = await browser.new_context(user_agent=SCRAPE_UA)

                _404_MARKERS = ("404 not found", "page not found", "doesn't exist",
                                "page doesn't exist", "page could not be found")

                async def _render(path: str) -> tuple[str, str | None, str | None]:
                    pg = await ctx.new_page()
                    html: str | None = None
                    text: str | None = None
                    try:
                        resp = await pg.goto(f"https://{domain}{path}", wait_until="load", timeout=15000)
                        if resp and resp.status not in (200, 304):
                            return (path, None, None)
                        html = await pg.content()
                        t = trafilatura.extract(html, include_comments=False, include_tables=True, no_fallback=False)
                        if t and len(t.strip()) > 80:
                            # Drop pages that are clearly SPA-rendered 404s
                            if not any(m in t.lower()[:120] for m in _404_MARKERS):
                                text = t
                    except Exception:
                        pass
                    finally:
                        await pg.close()
                    return (path, text, html)

                # Render homepage first for link discovery
                _, home_text, home_html = await _render("/")
                if home_text:
                    pages.append(("/", home_text))

                # Discover links from rendered HTML (now JS-populated)
                extra_paths: list[str] = []
                if home_html:
                    discovered = _extract_internal_links(home_html, domain)
                    extra_paths = [p for p in discovered if p not in set(SCRAPE_PATHS)][:5]

                # Fetch static paths + discovered, cap at 8 total additional
                to_fetch = [p for p in SCRAPE_PATHS if p != "/"] + extra_paths
                seen_paths = {"/"}
                for path in to_fetch:
                    if path in seen_paths:
                        continue
                    seen_paths.add(path)
                    if len(pages) >= 10:
                        break
                    _, text, _ = await _render(path)
                    if text:
                        pages.append((path, text))

            finally:
                await browser.close()

    return pages


async def scrape_company_site(domain: str, session: aiohttp.ClientSession) -> dict:
    """
    Three-phase site scraper with progressive fallback.

    Phase 1: fetch all static SCRAPE_PATHS in parallel (fast, aiohttp).
    Phase 2: parse homepage HTML for same-domain links; fetch top keyword-scored ones.
    Phase 3 (www. retry): if phases 1+2 got nothing, retry with www. prefix.
    Phase 4 (Playwright fallback): if total text < 500 chars, run headless browser
             for JS-rendered SPAs.

    Returns: site_scrape_found, site_scraped_paths, site_summary_text.
    """
    async def _run_static_phases(d: str) -> tuple[list[tuple[str, str]], str | None]:
        """Run phases 1+2 for a given domain. Returns (pages, homepage_html)."""
        tasks = []
        for p in SCRAPE_PATHS:
            if p == "/":
                tasks.append(_fetch_page_text(d, p, session, return_html=True))
            else:
                tasks.append(_fetch_page_text(d, p, session))
        results = await asyncio.gather(*tasks)

        _pages: list[tuple[str, str]] = []
        _homepage_html: str | None = None
        fetched: set[str] = set(SCRAPE_PATHS)

        for r in results:
            if not r:
                continue
            if len(r) == 3:
                if r[1]:  # text may be None on SPA homepage (but we still got HTML)
                    _pages.append((r[0], r[1]))
                _homepage_html = r[2]
            else:
                _pages.append((r[0], r[1]))

        # Phase 2 — link discovery from homepage HTML
        if _homepage_html:
            discovered = _extract_internal_links(_homepage_html, d)
            new_paths = [p for p in discovered if p not in fetched][:8]
            if new_paths:
                p2 = await asyncio.gather(*[_fetch_page_text(d, p, session) for p in new_paths])
                for r in p2:
                    if r:
                        _pages.append((r[0], r[1]))

        return _pages, _homepage_html

    # Phase 1+2
    pages, homepage_html = await _run_static_phases(domain)

    # Phase 3 — www. retry if we got nothing and domain has no www. prefix
    if not pages and not domain.startswith("www."):
        pages, homepage_html = await _run_static_phases(f"www.{domain}")

    total_chars = sum(len(t) for _, t in pages)

    # Phase 4 — Playwright disabled for bulk run (speed)

    if not pages:
        return {"site_scrape_found": False, "site_scraped_paths": [], "site_summary_text": None}

    # Deduplicate by path
    seen: set[str] = set()
    unique_pages: list[tuple[str, str]] = []
    for path, text in pages:
        if path not in seen:
            seen.add(path)
            unique_pages.append((path, text))

    # Sort by keyword score so high-value pages (team, pipeline) fill the budget first
    unique_pages.sort(key=lambda pt: _score_path(pt[0]), reverse=True)

    # Fill up to 24 KB, giving each page its full text
    TOTAL_CAP = 24_000
    parts: list[str] = []
    used = 0
    for path, text in unique_pages:
        chunk = f"[{path}]\n{text}"
        if used + len(chunk) > TOTAL_CAP:
            remaining = TOTAL_CAP - used
            if remaining > 200:
                parts.append(chunk[:remaining])
            break
        parts.append(chunk)
        used += len(chunk)
    combined = "\n\n".join(parts)

    return {
        "site_scrape_found": True,
        "site_scraped_paths": [p for p, _ in unique_pages],
        "site_summary_text": combined,
    }


# ─────────────────────────────────────────────────────────────
# SEC EDGAR — Form 4 officer names (US public cos only)
#
# Fetches up to 5 Form 4 XML documents from the submissions JSON
# (already loaded in fetch_edgar_submissions). Each Form 4 XML
# contains <rptOwnerName> and <officerTitle> for the executive
# who filed. Officers only (isOfficer=1); directors skipped.
# ─────────────────────────────────────────────────────────────

async def fetch_edgar_insiders(cik: str, session: aiohttp.ClientSession) -> dict:
    """
    Pull officer names from recent Form 4 XMLs filed for this issuer company.
    Returns up to 8 unique (name, title) pairs from most-recent filings.
    """
    # Step 1: get submissions to find Form 4 accession numbers
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    headers = {"User-Agent": EDGAR_UA}
    try:
        async with SEM_EDGAR:
            async with session.get(url, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json(content_type=None)
    except Exception:
        return {}

    recent   = data.get("filings", {}).get("recent", {})
    forms    = recent.get("form", [])
    accnos   = recent.get("accessionNumber", [])
    prim_docs = recent.get("primaryDocument", [])
    cik_short = cik.lstrip("0")

    # Collect accession + primary doc for Form 4 entries (most recent first)
    form4_docs = [
        (accnos[i].replace("-", ""), prim_docs[i])
        for i, f in enumerate(forms[:200])
        if f == "4" and i < len(accnos) and i < len(prim_docs)
    ][:6]   # cap at 6 to limit HTTP requests

    if not form4_docs:
        return {"edgar_insiders_found": False}

    # Step 2: fetch each Form 4 XML and parse officer name + title
    names: list[str] = []
    seen: set = set()

    async def _fetch_form4_xml(accno: str, prim_doc: str) -> tuple[str, str] | None:
        # Strip XSL transform prefix if present (e.g. xslF345X06/)
        raw = prim_doc.split("/")[-1] if "/" in prim_doc else prim_doc
        xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik_short}/{accno}/{raw}"
        try:
            async with SEM_EDGAR:
                async with session.get(xml_url, headers={"User-Agent": EDGAR_UA},
                                       timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status != 200:
                        return None
                    text = await r.text(errors="replace")
            import re as _re
            owner = (_re.findall(r"<rptOwnerName>(.*?)</rptOwnerName>", text) or [""])[0].strip()
            title = (_re.findall(r"<officerTitle>(.*?)</officerTitle>", text) or [""])[0].strip()
            is_off = (_re.findall(r"<isOfficer>(.*?)</isOfficer>", text) or ["0"])[0].strip()
            if owner and is_off == "1":
                return (owner, title)
        except Exception:
            pass
        return None

    tasks = [_fetch_form4_xml(acc, doc) for acc, doc in form4_docs]
    results = await asyncio.gather(*tasks)

    for res in results:
        if not res:
            continue
        owner, title = res
        owner_norm = owner.lower()
        if owner_norm not in seen:
            seen.add(owner_norm)
            label = f"{owner} ({title})" if title else owner
            names.append(label)

    if not names:
        return {"edgar_insiders_found": False}

    return {
        "edgar_insiders_found": True,
        "edgar_insider_names":  names[:8],
    }


# ─────────────────────────────────────────────────────────────
# Perplexity web search via OpenRouter
#
# Uses perplexity/sonar (live web search) to answer targeted
# questions about a company's chemistry/drug-discovery leadership.
# Only fires when site scraping + other enrichers left sig_cq_exec_names
# and sig_cq_authors both empty — i.e. we have no people data at all.
# ─────────────────────────────────────────────────────────────

async def search_company_contacts(
    company_name: str,
    domain: str,
) -> dict:
    """
    Ask Perplexity sonar (live web search) three targeted questions about
    a company's chemistry leadership. Returns sig_web_search_people (list of
    name+title strings) and sig_web_search_snippets (raw answer text for the
    contact quality agent to reason over).
    """
    if not OPENROUTER_API_KEY:
        return {}

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )

    queries = [
        # Contact Quality
        (
            "leadership",
            f'Who are the chemistry, medicinal chemistry, drug discovery, or biology '
            f'leadership at {company_name} ({domain})? '
            f'List every person you can find with their name and title. '
            f'Focus on VP Chemistry, Head of Chemistry, CSO, CMO, Director of Chemistry, '
            f'and similar roles. Be concise — name and title only.',
        ),
        # Small Molecule — pipeline + capabilities
        (
            "small_molecule",
            f'Does {company_name} ({domain}) have active small molecule drug discovery programs? '
            f'Do they use CADD, computational chemistry, virtual screening, or hit-to-lead '
            f'optimization? What drug targets and modalities are they working on? '
            f'One short paragraph.',
        ),
        # Stage Fit + Strategic Intelligence — funding, stage, partnerships
        (
            "stage",
            f'What is the funding status, company stage, and recent news for {company_name} '
            f'({domain})? Are they preclinical, clinical, or commercial stage? '
            f'Most recent funding round and amount? Any pharma partnerships or collaborations '
            f'announced recently? Two to three sentences.',
        ),
    ]

    answers: dict[str, str] = {}
    total_prompt_tokens = 0
    total_completion_tokens = 0
    for label, prompt in queries:
        try:
            async with SEM_OPENROUTER:
                resp = await client.chat.completions.create(
                    model="perplexity/sonar",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=400,
                )
            answers[label] = resp.choices[0].message.content.strip()
            if resp.usage:
                total_prompt_tokens     += resp.usage.prompt_tokens or 0
                total_completion_tokens += resp.usage.completion_tokens or 0
        except Exception as e:
            answers[label] = ""

    leadership_text   = answers.get("leadership", "")
    small_mol_text    = answers.get("small_molecule", "")
    stage_text        = answers.get("stage", "")

    if not any([leadership_text, small_mol_text, stage_text]):
        return {"web_search_attempted": True, "web_search_found": False}

    # Strip Perplexity citation markers [1][2] and markdown bold **
    _cite_re = re.compile(r'\[\d+\]')

    def _clean(t: str) -> str:
        return _cite_re.sub("", t).replace("**", "").strip()

    # Parse name+title pairs out of the leadership answer
    people: list[str] = []
    for line in leadership_text.splitlines():
        line = _cite_re.sub("", line).replace("**", "").strip().lstrip("-•*·").strip()
        if line and len(line) > 8 and not line.lower().startswith("no "):
            people.append(line)

    # Build combined context block — scored agents read this for all four categories
    parts = []
    if leadership_text:
        parts.append(f"[web search: contact quality — leadership]\n{_clean(leadership_text)}")
    if small_mol_text:
        parts.append(f"[web search: small molecule — pipeline & capabilities]\n{_clean(small_mol_text)}")
    if stage_text:
        parts.append(f"[web search: stage fit & strategic intelligence — funding/partnerships]\n{_clean(stage_text)}")

    if total_prompt_tokens or total_completion_tokens:
        print(f"    [Perplexity] {domain}: {total_prompt_tokens}pt + {total_completion_tokens}ct tokens")

    return {
        "web_search_attempted":        True,
        "web_search_found":            bool(people or small_mol_text or stage_text),
        "sig_web_people":              people[:12],
        "sig_web_context":             "\n\n".join(parts),
        "_web_prompt_tokens":          total_prompt_tokens,
        "_web_completion_tokens":      total_completion_tokens,
    }


# ─────────────────────────────────────────────────────────────
# Derived signal strings
# ─────────────────────────────────────────────────────────────

def build_signals(data: dict) -> dict:
    """
    Convert raw enrichment data into explicit signal strings for agent prompts.

    Three states:
      CONFIRMED: <fact>           — authoritative source confirmed this
      CONFIRMED: <no/none/zero>   — authoritative source confirmed absence
      [lookup failed/not checked] — unknown, do not infer
    """
    # Return early if already set (e.g. auto-disqualified domains)
    if data.get("sig_is_public"):
        return {}

    sigs = {}

    # ── Public status ─────────────────────────────────────────
    if data.get("is_public"):
        ticker   = data.get("ticker", "")
        exchange = data.get("exchange", "")
        base = f"CONFIRMED: Publicly traded on {exchange} as {ticker} (SEC EDGAR)"
        if data.get("zefix_found"):
            status_suffix = f", status {data['zefix_status']}" if data.get("zefix_status") else ""
            base += (f". Also registered in Swiss commercial register as "
                     f"'{data.get('zefix_name')}' (Zefix UID {data.get('zefix_uid')}{status_suffix})")
        sigs["sig_is_public"] = base
    elif data.get("opendart_registry") == "registered":
        # Korean public company via manually-verified seeded registry (high priority —
        # beats fuzzy Zefix/Sirene SPARQL matches that can produce false positives
        # on Korean domains like donga.co.kr)
        name_kr = data.get("opendart_corp_name_kr")
        corp    = data.get("opendart_corp_code")
        stock   = data.get("opendart_stock_code")
        if stock:
            sigs["sig_is_public"] = (
                f"CONFIRMED: Korean public company '{name_kr}' listed on KRX "
                f"(ticker {stock}, OpenDART corp_code {corp}). "
                f"Not in US SEC EDGAR — primary listing on Korea Exchange"
            )
        else:
            sigs["sig_is_public"] = (
                f"CONFIRMED: Korean legal entity '{name_kr}' in OpenDART registry "
                f"(corp_code {corp}, unlisted). Not in US SEC EDGAR"
            )
    elif data.get("zefix_found"):
        name = data.get("zefix_name")
        uid  = data.get("zefix_uid")
        status_suffix = f", status {data['zefix_status']}" if data.get("zefix_status") else ""
        sigs["sig_is_public"] = (
            f"CONFIRMED: Swiss legal entity '{name}' (Zefix UID {uid}{status_suffix}). "
            f"Not in US SEC EDGAR — may be listed on SIX Swiss Exchange (verify ticker independently)"
        )
    elif data.get("sirene_found"):
        # French biotech/pharma via Sirene
        name = data.get("sirene_name")
        siren = data.get("sirene_siren")
        cat   = data.get("sirene_categorie")   # PME/ETI/GE
        city  = data.get("sirene_city")
        naf   = data.get("sirene_naf")
        cat_str = {"PME": "SME", "ETI": "mid-size enterprise",
                   "GE": "large group"}.get(cat, cat or "")
        sigs["sig_is_public"] = (
            f"CONFIRMED: French legal entity '{name}' (SIREN {siren}, "
            f"NAF {naf}{', '+cat_str if cat_str else ''}"
            f"{', HQ '+city if city else ''}). "
            f"Not in US SEC EDGAR — may be listed on Euronext Paris (verify ticker independently)"
        )
    else:
        sigs["sig_is_public"] = "Not found in US SEC EDGAR — may be non-US listed or private (verify public status independently)"

    # ── Employee range ────────────────────────────────────────
    sf_range = data.get("sf_employee_range")
    sf_count = data.get("sf_employee_count")
    sbir_emp = data.get("sbir_employee_count")
    sbir_date = data.get("sbir_latest_award_date")
    if sf_range and sf_count:
        sigs["sig_sf_employee_range"] = (
            f"CONFIRMED: ~{sf_count:,} employees ({sf_range} range) per most recent 10-K (SEC EDGAR)"
        )
    elif sf_range:
        sigs["sig_sf_employee_range"] = f"CONFIRMED: {sf_range} employees per most recent 10-K (SEC EDGAR)"
    elif sbir_emp is not None:
        # SBIR-reported employee count for private US biotechs
        sbir_range = _employee_count_to_range(sbir_emp)
        date_str = f" (latest SBIR award {sbir_date})" if sbir_date else ""
        sigs["sig_sf_employee_range"] = (
            f"CONFIRMED: {sbir_emp} employees ({sbir_range} range) per SBIR.gov firm record{date_str}"
        )
    elif data.get("sirene_emp_range"):
        yr  = data.get("sirene_emp_year")
        yr_str = f" ({yr})" if yr else ""
        sigs["sig_sf_employee_range"] = (
            f"CONFIRMED: {data['sirene_emp_range']} employees per Sirene French register"
            f"{yr_str}"
        )
    elif data.get("is_public"):
        sigs["sig_sf_employee_range"] = "[Employee count not tagged in XBRL 10-K — treat as unknown]"
    else:
        sigs["sig_sf_employee_range"] = "[Not in US SEC EDGAR, SBIR.gov, or Sirene — employee count unknown, verify independently]"

    # ── Recent funding / offering ─────────────────────────────
    # Build primary funding statement from SEC (public offering > Form D > nothing).
    # Then append SBIR/NIH non-dilutive funding as augmentation.
    sbir_total = data.get("sbir_total_funding") or 0
    sbir_count = data.get("sbir_award_count") or 0
    sbir_date  = data.get("sbir_latest_award_date")
    nih_total  = data.get("nih_total_funding") or 0
    nih_count  = data.get("nih_grant_count") or 0
    nih_fy     = data.get("nih_latest_fiscal_year")

    def _fmt_millions(dollars):
        if dollars >= 1_000_000:
            return f"${dollars/1_000_000:.1f}M"
        return f"${dollars:,}"

    sbir_tail = ""
    if sbir_total > 0:
        sbir_tail = (
            f". Additionally {_fmt_millions(sbir_total)} across {sbir_count} SBIR/STTR awards "
            f"(last 3 years" + (f", latest {sbir_date}" if sbir_date else "") + ")"
        )
    nih_tail = ""
    if nih_total > 0:
        nih_tail = (
            f". Additionally {_fmt_millions(nih_total)} in NIH grants across {nih_count} projects"
            + (f" (latest FY {nih_fy})" if nih_fy else "")
        )

    if data.get("sf_recent_offering"):
        base = (f"CONFIRMED: Filed {data.get('sf_offering_form')} on {data.get('sf_offering_date')} "
                f"— capital raise confirmed via SEC EDGAR")
    elif data.get("si_form_d_found"):
        date = data.get("si_form_d_date")
        base = f"CONFIRMED: SEC Form D filed {date} — private placement confirmed (Reg D)"
    elif sbir_total > 0 or nih_total > 0:
        base = "CONFIRMED: No Form D or S-1/S-3 filing found in SEC EDGAR (last 2 years)"
    elif data.get("is_public"):
        base = "CONFIRMED: No S-1/S-3/424B4 offering in SEC EDGAR (last 18 months)"
    elif data.get("si_form_d_found") is False:
        base = ("CONFIRMED: No Form D filing found in SEC EDGAR (last 2 years) — "
                "may not have raised a Reg D round")
    else:
        base = "[Funding lookup not completed — treat as unknown]"

    sigs["sig_si_recent_funding"] = base + sbir_tail + nih_tail

    # ── Publications (PubMed + OpenAlex) ─────────────────────
    dd  = data.get("pubmed_drug_discovery_count", 0)
    oax = data.get("openalex_works_count", 0)
    if dd > 0 and oax > 0:
        sigs["sig_si_recent_publications"] = (
            f"CONFIRMED: {dd} drug discovery papers on PubMed + {oax} matched works on OpenAlex (2022–2026)"
        )
    elif dd > 0:
        sigs["sig_si_recent_publications"] = (
            f"CONFIRMED: {dd} drug discovery / medicinal chemistry papers on PubMed (2022–2026)"
        )
    elif oax > 0:
        sigs["sig_si_recent_publications"] = (
            f"CONFIRMED: 0 drug discovery papers on PubMed (2022–2026), but {oax} total publications on OpenAlex — may publish under different affiliation strings"
        )
    else:
        sigs["sig_si_recent_publications"] = (
            "CONFIRMED: 0 drug discovery publications on PubMed (2022–2026) — no research output found"
        )

    # ── Patents ───────────────────────────────────────────────
    pc        = data.get("patent_count_3yr")
    pc_pharma = data.get("patent_pharma_count_3yr")
    titles    = data.get("patent_recent_titles") or []
    source    = data.get("patent_source", "USPTO PatentSearch")

    if pc is not None and pc > 0:
        parts = [f"{pc} total patents in last 3 years ({source})"]
        if pc_pharma is not None:
            # Pharma-class = CPC A61K (pharmaceutical preparations), C07D (heterocycles),
            # C07K (peptides). Strong proxy for real drug-discovery patenting.
            parts.append(f"{pc_pharma} of those are pharma-class (CPC A61K/C07D/C07K)")
        if titles:
            sample = "; ".join(f"'{t}'" for t in titles[:3])
            parts.append(f"recent titles: {sample}")
        sigs["sig_si_patent_filings"] = "CONFIRMED: " + ". ".join(parts)
    elif pc == 0:
        sigs["sig_si_patent_filings"] = f"CONFIRMED: 0 patents found in {source} (last 3 years)"
    else:
        sigs["sig_si_patent_filings"] = "[Patent lookup unavailable — treat as unknown]"

    # ── Small molecule — active med chem ─────────────────────
    chembl   = data.get("chembl_drug_count", 0)
    ct_total = data.get("ct_total_trials", 0)
    assays   = data.get("chembl_assay_count", 0)
    docs     = data.get("chembl_document_count", 0)
    bioassay = data.get("pubchem_bioassay_count", 0)
    oax_mc   = data.get("openalex_medchem_works", 0)

    med_chem_evidence = []
    if chembl > 0:
        drugs = data.get("chembl_sample_drugs", []) or []
        sample = ", ".join(str(d) for d in drugs[:3] if d)
        med_chem_evidence.append(
            f"{chembl} approved drugs in ChEMBL" + (f" (e.g. {sample})" if sample else "")
        )
    if assays > 0:
        med_chem_evidence.append(f"{assays} bioactivity assays sourced in ChEMBL (preclinical)")
    if docs > 0:
        med_chem_evidence.append(f"{docs} compound-linked papers in ChEMBL")
    if bioassay > 0:
        med_chem_evidence.append(f"{bioassay} HTS BioAssays in PubChem")
    if ct_total > 0:
        med_chem_evidence.append(f"{ct_total} interventional trials on ClinicalTrials.gov")
    if oax_mc > 0:
        med_chem_evidence.append(f"{oax_mc} medicinal-chemistry papers on OpenAlex")

    if med_chem_evidence:
        sigs["sig_sm_active_med_chem"] = "CONFIRMED: " + "; ".join(med_chem_evidence)
    else:
        sigs["sig_sm_active_med_chem"] = (
            "CONFIRMED: 0 approved drugs in ChEMBL, 0 ChEMBL assays, 0 PubChem BioAssays, "
            "0 interventional trials, 0 medicinal-chemistry papers — no confirmed small molecule program"
        )

    # ── CADD ──────────────────────────────────────────────────
    cadd = data.get("pubmed_cadd_count", 0)
    pdb  = data.get("rcsb_pdb_count", 0)
    cadd_evidence = []
    if cadd > 0:
        cadd_evidence.append(f"{cadd} computational chemistry / CADD papers on PubMed (2022–2026)")
    if pdb > 0:
        cadd_evidence.append(f"{pdb} PDB structures (structure-based drug design)")
    if cadd_evidence:
        sigs["sig_sm_cadd"] = "CONFIRMED: " + "; ".join(cadd_evidence)
    else:
        sigs["sig_sm_cadd"] = "CONFIRMED: 0 CADD publications on PubMed and 0 PDB structures (2022–2026)"

    # ── Hit-to-lead ───────────────────────────────────────────
    active = data.get("ct_phase12_trials", 0)
    if active > 0:
        title = data.get("ct_most_recent_title", "")
        sigs["sig_sm_hit_to_lead"] = (
            f"CONFIRMED: {active} active/recruiting trials on ClinicalTrials.gov. "
            f"Most recent: '{title}'"
        )
    else:
        sigs["sig_sm_hit_to_lead"] = "CONFIRMED: 0 active/recruiting trials on ClinicalTrials.gov"

    # ── Virtual screening ─────────────────────────────────────
    vs = data.get("pubmed_virtual_screening_count", 0)
    if vs > 0:
        sigs["sig_sm_virtual_screening"] = (
            f"CONFIRMED: {vs} virtual screening / molecular docking papers on PubMed (2022–2026)"
        )
    else:
        sigs["sig_sm_virtual_screening"] = (
            "CONFIRMED: 0 virtual screening publications on PubMed (2022–2026)"
        )

    # ── Recent chemistry hires (Greenhouse ATS) ──────────────
    # This is the only NEW sig_* field introduced by the free-API additions
    # (per integration brief). Only populated for ats_registry-listed domains.
    gh_reg = data.get("greenhouse_registry")
    if gh_reg == "registered":
        total  = data.get("greenhouse_total_jobs") or 0
        chem_n = data.get("greenhouse_chem_count") or 0
        chem_jobs = data.get("greenhouse_chem_jobs") or []
        board  = data.get("greenhouse_board")
        if chem_n > 0:
            titles = "; ".join(
                f"{j['title']} [{j.get('updated_at','')}]" for j in chem_jobs
            )
            sigs["sig_si_recent_chem_hires"] = (
                f"CONFIRMED: {chem_n} open chemistry roles on Greenhouse "
                f"(board '{board}'): {titles}"
            )
        else:
            sigs["sig_si_recent_chem_hires"] = (
                f"CONFIRMED: No open chemistry roles on Greenhouse "
                f"(company has {total} total open roles, 0 chemistry-tagged)"
            )
    else:
        # Not in the manual registry → no ATS signal; agent can still try web.
        sigs["sig_si_recent_chem_hires"] = "Company not in ATS registry — agent-only evaluation"

    # ── EDGAR insider names (Form 3/4/5) ─────────────────────
    insider_names = data.get("edgar_insider_names") or []
    if insider_names:
        sigs["sig_cq_exec_names"] = (
            "CONFIRMED: Executive/director names from SEC EDGAR Form 4 filings: "
            + ", ".join(insider_names)
        )

    # ── OpenAlex author names ─────────────────────────────────
    author_names = data.get("openalex_author_names") or []
    if author_names:
        sigs["sig_cq_authors"] = (
            "CONFIRMED: Researcher names from OpenAlex drug-discovery publications: "
            + ", ".join(author_names)
        )

    return sigs


# ─────────────────────────────────────────────────────────────
# Main enrichment function for one domain
# ─────────────────────────────────────────────────────────────

async def enrich_domain(domain: str, session: aiohttp.ClientSession) -> dict:
    company_name = domain_to_company_name(domain)
    errors = {}

    result = {
        "domain":             domain,
        "company_name_guess": company_name,
    }

    # ── 0. Domain-type pre-filter ─────────────────────────────
    # .gov / .edu / .mil domains are ICP auto-disqualifiers.
    # Also catch academic second-level domains (.ac.uk, .edu.au, .edu.pl, etc.),
    # student/doctoral subdomains (student.vu.nl), and university name prefixes
    # (univ-rouen.fr, unistra.fr, unibas.ch, unicamp.br).
    subdomain_prefix = domain.split(".")[0].lower()
    name_prefix_match = any(company_name.lower().startswith(p) for p in UNIVERSITY_NAME_PREFIXES)

    disq_tld     = next((t for t in DISQUALIFIED_TLDS if domain.endswith(t)), None)
    disq_acad    = next((p for p in DISQUALIFIED_ACADEMIC_PATTERNS if domain.endswith(p)), None)
    disq_prefix  = subdomain_prefix if subdomain_prefix in DISQUALIFIED_SUBDOMAIN_PREFIXES else None
    disq_uni     = company_name if name_prefix_match else None
    disq_pattern = disq_tld or disq_acad or disq_prefix or disq_uni
    if disq_pattern:
        result["is_public"] = False
        result["sig_is_public"] = f"CONFIRMED: Auto-disqualified ({disq_pattern} domain — not pharma/biotech)"
        result["enrichment_errors"] = {"auto_disqualified": disq_pattern}
        result["enriched_at"] = datetime.now(timezone.utc).isoformat()
        return result

    # ── 0b. Short-name guard ──────────────────────────────────
    # Domains like i.ua → name "I" produce garbage hits in ChEMBL/PubMed/CT
    # (substring searches match every record containing that letter).
    # Skip all fuzzy-name lookups; record as unresolvable.
    if len(company_name) < MIN_QUERY_NAME_LEN:
        result["is_public"] = False
        result["sig_is_public"]              = "[Name too short to resolve — treat as unknown]"
        result["sig_si_recent_publications"] = "[Name too short to query — treat as unknown]"
        result["sig_si_patent_filings"]      = "[Name too short to query — treat as unknown]"
        result["sig_sm_active_med_chem"]     = "[Name too short to query — treat as unknown]"
        result["sig_sm_cadd"]                = "[Name too short to query — treat as unknown]"
        result["sig_sm_hit_to_lead"]         = "[Name too short to query — treat as unknown]"
        result["sig_sm_virtual_screening"]   = "[Name too short to query — treat as unknown]"
        result["sig_si_recent_funding"]      = "[Name too short to query — treat as unknown]"
        result["sig_sf_employee_range"]      = "[Name too short to query — treat as unknown]"
        result["enrichment_errors"] = {"short_name": f"Name too short: {company_name!r}"}
        result["enriched_at"] = datetime.now(timezone.utc).isoformat()
        return result

    # ── 0c. Homepage + subpage scrape ─────────────────────────
    site = await scrape_company_site(domain, session)
    result.update(site)

    # ── 1. SEC EDGAR — public status ─────────────────────────
    edgar_entry = find_in_edgar(company_name)
    if edgar_entry:
        result["is_public"] = True
        result["ticker"]    = edgar_entry.get("ticker")
        result["exchange"]  = edgar_entry.get("exchange")
        result["cik"]       = edgar_entry.get("cik")

        # Fetch submissions for funding stage / recent offerings
        subs = await fetch_edgar_submissions(edgar_entry["cik"], session)
        if "error" in subs:
            errors["edgar_submissions"] = subs["error"]
        else:
            result.update(subs)

        # Fetch employee count via XBRL
        xbrl = await fetch_xbrl_employees(edgar_entry["cik"], session)
        if "xbrl_error" in xbrl:
            errors["xbrl"] = xbrl.pop("xbrl_error")
        else:
            result.update(xbrl)

        # Fetch officer names from Form 4 XMLs
        insiders = await fetch_edgar_insiders(edgar_entry["cik"], session)
        if "edgar_insiders_error" in insiders:
            errors["edgar_insiders"] = insiders.pop("edgar_insiders_error")
        else:
            result.update(insiders)
    else:
        result["is_public"] = False

    # For PubMed: full EDGAR name is more accurate (e.g. "Gilead Sciences Inc")
    # For ChEMBL/CT: use short domain guess — those APIs match on partial names
    pubmed_name = edgar_entry["title"].title() if edgar_entry else company_name
    # Strip legal suffixes for CT/ChEMBL (Inc, Ltd, Corp, LLC, AG, plc, etc.)
    # Strip legal suffixes including "And Co", "& Co", trailing "And" etc.
    # e.g. "Eli Lilly And Co" → "Eli Lilly", "Gilead Sciences, Inc." → "Gilead Sciences"
    short_name = re.sub(
        r',?\s*(and\s+|&\s*)?\b(Inc|Ltd|Corp|LLC|AG|Plc|Gmbh|Sa|Nv|Bv|Se|Co|Company)\b\.?$',
        '', pubmed_name, flags=re.IGNORECASE
    )
    short_name = re.sub(r'[\s,&]+and\s*$', '', short_name, flags=re.IGNORECASE).strip()

    # Build name variants for PubMed — try up to 3 forms to maximise hit rate.
    # PubMed [ad] (affiliation) is free-text, so "Gilead" and "Gilead Sciences Inc"
    # both appear depending on how authors wrote their affiliation.
    pubmed_variants: list[str] = []
    for v in [pubmed_name, short_name, company_name]:
        if v and v not in pubmed_variants:
            pubmed_variants.append(v)

    # ── 2. PubMed + OpenAlex ─────────────────────────────────
    pubmed = await query_all_pubmed(pubmed_name, session, name_variants=pubmed_variants)
    result.update(pubmed)

    # OpenAlex — run concurrently, supplement PubMed (free, no key)
    oax = await query_openalex(short_name, session)
    result.update(oax)

    # ── 3. Patents ────────────────────────────────────────────
    patents = await query_patents(short_name, session)
    if "patent_error" in patents:
        errors["patents_patentsview"] = patents.pop("patent_error")
        # PatentsView unavailable — try EPO OPS as fallback
        if EPO_OPS_KEY:
            epo = await query_epo_patents(short_name, session)
            if "patent_error" in epo:
                errors["patents_epo"] = epo.pop("patent_error")
            result.update(epo)
        # else: patent fields stay absent → build_signals emits "lookup unavailable"
    else:
        result.update(patents)

    # ── 4. ChEMBL ─────────────────────────────────────────────
    chembl = await query_chembl(short_name, session)
    if "chembl_error" in chembl:
        errors["chembl"] = chembl.pop("chembl_error")
    result.update(chembl)

    # ── 4b. ChEMBL assays + documents (preclinical signal) ───
    chembl_a = await query_chembl_assays(short_name, session)
    if "chembl_assays_error" in chembl_a:
        errors["chembl_assays"] = chembl_a.pop("chembl_assays_error")
    result.update(chembl_a)

    # ── 4c. PubChem BioAssay (HTS screening signal) ──────────
    pubchem = await query_pubchem_bioassay(short_name, session)
    if "pubchem_error" in pubchem:
        errors["pubchem"] = pubchem.pop("pubchem_error")
    result.update(pubchem)

    # ── 4d. RCSB PDB (structure-based drug design) ───────────
    rcsb = await query_rcsb_pdb(short_name, session)
    if "rcsb_error" in rcsb:
        errors["rcsb"] = rcsb.pop("rcsb_error")
    result.update(rcsb)

    # ── 5. ClinicalTrials.gov ─────────────────────────────────
    ct = await query_clinicaltrials(short_name, session)
    if "ct_error" in ct:
        errors["clinicaltrials"] = ct.pop("ct_error")
    result.update(ct)

    # ── 6. Form D (private companies only) ───────────────────
    if not result.get("is_public"):
        form_d = await fetch_form_d(company_name, pubmed_variants, session)
        result.update(form_d)

    # ── 6b. SBIR.gov (non-dilutive awards + firm-reported employees) ──
    sbir = await query_sbir(short_name, session)
    if "sbir_error" in sbir:
        errors["sbir"] = sbir.pop("sbir_error")
    result.update(sbir)

    # ── 6c. NIH RePORTER (academic-adjacent grants) ──────────
    nih = await query_nih_reporter(short_name, session)
    if "nih_error" in nih:
        errors["nih_reporter"] = nih.pop("nih_error")
    result.update(nih)

    # ── 6d. Swiss Zefix via LINDAS (non-US disambiguation) ────
    zefix = await query_zefix_sparql(short_name, domain, session)
    if "zefix_error" in zefix:
        errors["zefix"] = zefix.pop("zefix_error")
    result.update(zefix)

    # ── 6d2. Sirene (French company register, biotech NAF only) ──
    sirene = await query_sirene(short_name, domain, session)
    if "sirene_error" in sirene:
        errors["sirene"] = sirene.pop("sirene_error")
    result.update(sirene)

    # ── 6d3. OpenDART (Korean public company register, seeded) ──
    opendart = await query_opendart(domain, session)
    if "opendart_error" in opendart:
        errors["opendart"] = opendart.pop("opendart_error")
    result.update(opendart)

    # ── 6e. Greenhouse ATS (open chemistry roles) ────────────
    gh = await query_greenhouse(domain, session)
    if "greenhouse_error" in gh:
        errors["greenhouse"] = gh.pop("greenhouse_error")
    result.update(gh)

    # ── 7. Perplexity web search (fires when we have no people data) ──
    # Conditions: no Form 4 insiders, no OpenAlex authors, AND
    # site scraping found little useful text (< 500 chars total)
    site_text_len = len(result.get("site_summary_text") or "")
    has_people    = bool(result.get("edgar_insider_names") or result.get("sig_cq_authors"))
    if OPENROUTER_API_KEY and (not has_people or site_text_len < 500):
        web = await search_company_contacts(company_name, domain)
        result.update(web)

    # ── 8. Build derived signal strings ───────────────────────
    sigs = build_signals(result)
    result.update(sigs)

    result["enrichment_errors"] = errors if errors else None
    result["enriched_at"] = datetime.now(timezone.utc).isoformat()

    return result


# ─────────────────────────────────────────────────────────────
# Supabase helpers
# ─────────────────────────────────────────────────────────────

def load_from_hybrid_json(json_path: str, limit: int = None) -> list:
    """Load domains from a previous hybrid pipeline results JSON."""
    with open(json_path) as f:
        data = json.load(f)
    results = data.get("results", [])
    companies = [
        {
            "domain":         r["domain"],
            "user_count":     r.get("source_user_count", 0),
            "total_sessions": r.get("source_total_sessions", 0),
            "last_active":    r.get("source_last_active"),
        }
        for r in results
        if r.get("domain")
    ]
    if limit:
        companies = companies[:limit]
    return companies


async def fetch_companies(session: aiohttp.ClientSession, limit: int = None, single_domain: str = None) -> list:
    if single_domain:
        return [{"domain": single_domain, "user_count": 0, "total_sessions": 0, "last_active": None}]

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    # Load discarded domains
    discarded = set()
    url = f"{SUPABASE_URL}/rest/v1/discarded_email_suggestion?select=domain&limit=10000"
    async with session.get(url, headers=headers) as resp:
        if resp.status == 200:
            rows = await resp.json()
            discarded = {r["domain"] for r in rows if r.get("domain")}

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
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                raise Exception(f"Supabase fetch failed: {resp.status}")
            page = await resp.json()
            if not page:
                break
            companies.extend(page)
            if len(page) < page_size:
                break
            offset += page_size

    filtered = [c for c in companies if c["domain"] not in discarded]
    if limit:
        filtered = filtered[:limit]
    return filtered


async def upsert_enrichment(result: dict, session: aiohttp.ClientSession):
    import aiohttp as _aiohttp
    headers = {
        "apikey":        SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "resolution=merge-duplicates",
    }
    # Supabase REST JSONB columns need JSON-serialized lists/dicts
    for key in ("chembl_sample_drugs", "enrichment_errors"):
        if key in result and isinstance(result[key], (list, dict)):
            result[key] = json.dumps(result[key])
    # TEXT[] columns accept plain Python lists via PostgREST — no change needed
    # but drop transient keys that aren't DB columns
    for key in ("edgar_insider_names", "openalex_author_names",
                "edgar_insiders_found", "site_scrape_found",
                "web_search_attempted", "web_search_found",
                "_web_prompt_tokens", "_web_completion_tokens"):
        result.pop(key, None)

    url = f"{SUPABASE_URL}/rest/v1/{TARGET_TABLE}"
    base_keys = {
        "domain", "company_name_guess", "is_public", "ticker", "exchange", "cik",
        "sf_funding_stage", "sf_employee_range", "sf_recent_offering",
        "sf_offering_date", "sf_offering_form",
        "pubmed_drug_discovery_count", "pubmed_cadd_count", "pubmed_virtual_screening_count",
        "patent_count_3yr", "patent_most_recent_title", "patent_most_recent_date",
        "chembl_drug_count", "chembl_sample_drugs",
        "ct_total_trials", "ct_phase12_trials", "ct_most_recent_title",
        "sig_is_public", "sig_sf_employee_range", "sig_si_recent_funding",
        "sig_si_recent_publications", "sig_si_patent_filings",
        "sig_sm_active_med_chem", "sig_sm_cadd", "sig_sm_hit_to_lead",
        "sig_sm_virtual_screening",
        "site_summary_text", "site_scraped_paths",
        "sig_cq_exec_names", "sig_cq_authors",
        "sig_web_people", "sig_web_context",
        "enrichment_errors", "enriched_at",
    }
    # Fresh session per write — avoids ServerDisconnectedError on long runs
    _write_timeout = _aiohttp.ClientTimeout(total=30, sock_connect=10, sock_read=20)
    async with _aiohttp.ClientSession(timeout=_write_timeout) as write_session:
        async with write_session.post(url, json=result, headers=headers) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                # If column doesn't exist, retry with only the known base columns
                if resp.status == 400 and "Could not find" in text:
                    trimmed = {k: v for k, v in result.items() if k in base_keys}
                    async with write_session.post(url, json=trimmed, headers=headers) as resp2:
                        if resp2.status not in (200, 201):
                            text2 = await resp2.text()
                            print(f"    [Supabase] Write error for {result['domain']}: {resp2.status} — {text2[:100]}")
                else:
                    print(f"    [Supabase] Write error for {result['domain']}: {resp.status} — {text[:100]}")


# ─────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────

def summarize_result(r: dict) -> str:
    pub  = r.get("pubmed_drug_discovery_count", 0)
    pat  = r.get("patent_count_3yr", 0) or 0
    chem = r.get("chembl_drug_count", 0)
    ct   = r.get("ct_total_trials", 0)
    pub_str  = f"pubs={pub}"   if pub  else ""
    pat_str  = f"patents={pat}" if pat else ""
    chem_str = f"chembl={chem}" if chem else ""
    ct_str   = f"ct={ct}"      if ct   else ""
    public_str = f"PUBLIC({r.get('ticker')})" if r.get("is_public") else "private"
    parts = [x for x in [public_str, pub_str, pat_str, chem_str, ct_str] if x]
    return " | ".join(parts) if parts else "no signals found"


async def run(limit: int = None, single_domain: str = None, from_json: str = None,
              skip_since: str = None):
    print("\n" + "=" * 65)
    print("eMolecules Pre-Enrichment Layer")
    print("=" * 65 + "\n")

    connector = aiohttp.TCPConnector(limit=40)
    default_timeout = aiohttp.ClientTimeout(total=30, sock_connect=10, sock_read=20)
    async with aiohttp.ClientSession(connector=connector, timeout=default_timeout) as session:

        # Load EDGAR ticker file once
        print("Loading SEC EDGAR ticker data...")
        await load_edgar_tickers(session)

        # Fetch company list
        if from_json:
            print(f"Loading companies from {from_json}...")
            companies = load_from_hybrid_json(from_json, limit=limit)
            print(f"  {len(companies)} companies loaded from JSON")
        elif single_domain:
            companies = [{"domain": single_domain}]
            print(f"  Single domain mode: {single_domain}")
        else:
            print("Fetching company list from Supabase...")
            companies = await fetch_companies(session, limit=limit)
            print(f"  {len(companies)} companies to enrich")

        # Skip domains already enriched after a given timestamp
        if skip_since and not single_domain:
            headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
            skip_url = (
                f"{SUPABASE_URL}/rest/v1/icp_enrichment"
                f"?select=domain&enriched_at=gte.{skip_since}&limit=2000"
            )
            async with session.get(skip_url, headers=headers) as r:
                already_done = {row["domain"] for row in (await r.json())} if r.status == 200 else set()
            before = len(companies)
            companies = [c for c in companies if c["domain"] not in already_done]
            print(f"  Skipping {before - len(companies)} already enriched since {skip_since}")
        print(f"  {len(companies)} companies to process\n")

        total      = len(companies)
        done       = 0
        errors_n   = 0
        public_n   = 0
        has_pubs_n = 0
        all_results = []
        web_prompt_tokens_total     = 0
        web_completion_tokens_total = 0

        for i in range(0, total, BATCH_SIZE):
            batch = companies[i:i + BATCH_SIZE]
            batch_num = (i // BATCH_SIZE) + 1
            total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

            print(f"Batch {batch_num}/{total_batches} ({len(batch)} companies)...")

            tasks = [enrich_domain(c["domain"], session) for c in batch]
            results = await asyncio.gather(*tasks)

            # Write to Supabase
            if SUPABASE_URL and SUPABASE_KEY:
                write_tasks = [upsert_enrichment(r, session) for r in results]
                await asyncio.gather(*write_tasks)

            for r in results:
                done += 1
                all_results.append(r)
                if r.get("is_public"):
                    public_n += 1
                if r.get("pubmed_drug_discovery_count", 0) > 0:
                    has_pubs_n += 1
                if r.get("enrichment_errors"):
                    errors_n += 1
                web_prompt_tokens_total     += r.get("_web_prompt_tokens", 0)
                web_completion_tokens_total += r.get("_web_completion_tokens", 0)
                print(f"  [{done}/{total}] {r['domain']}: {summarize_result(r)}")

            # Small pause between batches
            if i + BATCH_SIZE < total:
                await asyncio.sleep(0.5)

    # Always write JSON output
    os.makedirs("results", exist_ok=True)
    out_path = "results/pre_enrichment_results.json"
    with open(out_path, "w") as f:
        json.dump({
            "run_at":         datetime.now().isoformat(),
            "total_companies": len(all_results),
            "source":         from_json or "supabase",
            "summary": {
                "public":    public_n,
                "has_pubs":  has_pubs_n,
                "errors":    errors_n,
            },
            "results": all_results
        }, f, indent=2)

    print(f"\n{'='*65}")
    print("ENRICHMENT COMPLETE")
    print(f"{'='*65}")
    print(f"  Total enriched : {done}")
    print(f"  Public (EDGAR) : {public_n}  ({public_n/max(done,1)*100:.1f}%)")
    print(f"  Has PubMed pubs: {has_pubs_n}  ({has_pubs_n/max(done,1)*100:.1f}%)")
    print(f"  API errors     : {errors_n}")
    if web_prompt_tokens_total or web_completion_tokens_total:
        total_web_tokens = web_prompt_tokens_total + web_completion_tokens_total
        # sonar: ~$1/1M tokens (input+output blended est.)
        est_cost = total_web_tokens / 1_000_000
        print(f"\n  Perplexity web search:")
        print(f"    Prompt tokens     : {web_prompt_tokens_total:,}")
        print(f"    Completion tokens : {web_completion_tokens_total:,}")
        print(f"    Total tokens      : {total_web_tokens:,}")
        print(f"    Est. cost (~$1/1M): ${est_cost:.4f}")
    print(f"\nSaved to: {out_path}")
    if SUPABASE_URL and SUPABASE_KEY:
        print(f"Also written to Supabase table: {TARGET_TABLE}")


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_KEY in .env")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="eMolecules pre-enrichment layer")
    parser.add_argument("--limit",     type=int,  default=None,  help="Only process top N companies")
    parser.add_argument("--domain",    type=str,  default=None,  help="Single domain to enrich")
    parser.add_argument("--from-json", type=str,  nargs="?",
                        const="results/hybrid_pipeline_results.json",
                        help="Load domains from hybrid results JSON (default: results/hybrid_pipeline_results.json)")
    parser.add_argument("--skip-since", type=str, default=None,
                        help="Skip domains already enriched after this ISO timestamp (e.g. 2026-04-22T18:00:00)")
    args = parser.parse_args()

    asyncio.run(run(limit=args.limit, single_domain=args.domain, from_json=args.from_json,
                    skip_since=args.skip_since))
