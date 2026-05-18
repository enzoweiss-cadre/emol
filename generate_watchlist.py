"""
eMolecules ICP Watchlist — emerging future customers
Companies that aren't HIGH FIT today but show clear trajectory signals:
  - Recent funding (Form D / S-1 in last 18mo)
  - First pharma patents filed (1-50 CPC-filtered, not a giant)
  - Recent chemistry publications
  - First preclinical data (ChEMBL assays / PubChem BioAssays)
  - Small-but-real team size

Pulls enrichment data from Supabase icp_enrichment (populated by pre_enrichment.py).
Filters and ranks candidates by trajectory score.

Usage: python3 generate_watchlist.py
Output: results/emolecules_watchlist.pdf
"""

import json, os, re
from datetime import datetime
import requests

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, PageBreak)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

# Load env
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if v and not os.environ.get(k):
                        os.environ[k] = v
load_env()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Palette
NAVY   = HexColor("#0F172A")
TEAL   = HexColor("#0F766E"); LIGHT_TEAL  = HexColor("#F0FDFA")
AMBER  = HexColor("#B45309"); LIGHT_AMBER = HexColor("#FFFBEB")
GREEN  = HexColor("#15803D")
PURPLE = HexColor("#6D28D9"); LIGHT_PURPLE= HexColor("#F5F3FF")
BLUE   = HexColor("#1D4ED8"); LIGHT_BLUE  = HexColor("#EFF6FF")
LIGHT_GREY = HexColor("#F8FAFC")
MID_GREY   = HexColor("#CBD5E1")
DARK_GREY  = HexColor("#64748B")
SLATE      = HexColor("#334155")
RED        = HexColor("#DC2626")
ORANGE     = HexColor("#C2410C")

# ────────────────────────────────────────────────────────────────
# Trajectory scoring (100 pts total)
# ────────────────────────────────────────────────────────────────
#   +25 — Recent funding: Form D found OR S-1/S-3/424B4 offering in last 18mo
#   +20 — First pharma patents (1-50 CPC-filtered pharma patents — emerging, not giant)
#   +15 — Growing publications (PubMed drug_discovery ≥ 2 OR OpenAlex med-chem ≥ 10)
#   +15 — First preclinical data (ChEMBL assays > 0 OR PubChem BioAssays > 0)
#   +10 — Right-size team (employee_range is 10-150 — small but real)
#   +15 — Active clinical work (CT.gov total trials ≥ 1 OR PDB ≥ 1)
# Penalties:
#   -40 — Auto-disqualified (academic/bot) — kills the score
#   -30 — Already big (pharma patents > 500) — not an "emerging" candidate
#   -20 — Zero signal across everything — pure unknown
# ────────────────────────────────────────────────────────────────

def range_to_midpoint(rng: str) -> int:
    """'51-150' → 100, '1,001-5,000' → 3000"""
    if not rng: return 0
    s = rng.replace(',', '').strip()
    if '5,000+' in rng or '5000+' in rng: return 6000
    parts = re.findall(r'\d+', s)
    if len(parts) >= 2:
        return (int(parts[0]) + int(parts[1])) // 2
    if parts:
        return int(parts[0])
    return 0

def trajectory_score(e: dict) -> tuple[int, dict]:
    """Score emerging-customer potential from enrichment row. Returns (score, breakdown)."""
    b = {}

    # Parse signals from sig_* strings (raw fields aren't stored in Supabase schema)
    parsed = parse_new_signals(e)

    # Auto-DQ kill switch — check enrichment_errors + sig_is_public
    errors = e.get("enrichment_errors") or {}
    if isinstance(errors, str):
        try: errors = json.loads(errors)
        except: errors = {}
    sig_pub = (e.get("sig_is_public") or "").lower()
    if errors.get("auto_disqualified") or "auto-disqualified" in sig_pub:
        return (-100, {"disqualified": True})

    # +25 — Recent funding
    if parsed.get("has_recent_offering") or parsed.get("has_form_d"):
        b["recent_funding"] = 25

    # +20 — First pharma patents (emerging: 1-30; giant: >100 → penalty)
    pharma = parsed.get("patent_pharma_count_3yr") or 0
    total_patents = parsed.get("patent_count_3yr") or 0
    # Non-pharma patent business (Thermo Fisher: 4/285 = 1.4% pharma = tool company)
    pharma_ratio = pharma / total_patents if total_patents > 0 else 0
    if total_patents >= 20 and pharma_ratio < 0.10:
        return (-100, {"disqualified": f"non-pharma patent business ({pharma}/{total_patents} pharma)"})
    if 1 <= pharma <= 30:
        b["first_pharma_patents"] = 20
    elif pharma > 100:
        b["already_giant_penalty"] = -40
    elif total_patents > 0 and pharma == 0:
        b["non_pharma_patents_penalty"] = -15

    # +15 — Growing publications
    dd = parsed.get("pubmed_drug_discovery_count") or 0
    oax_mc = parsed.get("openalex_medchem_works") or 0
    if dd >= 2 or oax_mc >= 10:
        b["growing_publications"] = 15

    # +15 — First preclinical data
    if (parsed.get("chembl_assay_count") or 0) > 0 or \
       (parsed.get("chembl_document_count") or 0) > 0 or \
       (parsed.get("pubchem_bioassay_count") or 0) > 0:
        b["first_preclinical_data"] = 15

    # +10 — Right-size team (small-but-real)
    emp = parsed.get("sf_employee_count_parsed") or range_to_midpoint(e.get("sf_employee_range") or "")
    if 10 <= emp <= 150:
        b["right_size_team"] = 10
    elif emp > 1000:
        if b.get("already_giant_penalty", 0) > -30:
            b["already_giant_penalty"] = -30

    # +15 — Active clinical signal
    ct = parsed.get("ct_total_trials") or 0
    pdb = parsed.get("rcsb_pdb_count") or 0
    if ct >= 1 or pdb >= 1:
        b["active_clinical_signal"] = 15

    # ChEMBL drug count > 5 = established pharma → kill
    chembl_drugs = parsed.get("chembl_drug_count") or 0
    if chembl_drugs > 5:
        return (-100, {"disqualified": f"established pharma ({chembl_drugs} approved drugs in ChEMBL)"})

    # Zero signal penalty
    positive = sum(v for v in b.values() if v > 0)
    if positive == 0:
        b["zero_signal"] = -20

    score = max(0, sum(b.values()))
    # Attach parsed signals so the PDF can render them
    e["_parsed"] = parsed
    return (score, b)

# ────────────────────────────────────────────────────────────────
# Fetch enrichment data
# ────────────────────────────────────────────────────────────────
def fetch_enrichment_by_domain(domains: list) -> dict:
    h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    results = {}
    # Batched query
    CHUNK = 30
    for i in range(0, len(domains), CHUNK):
        chunk = domains[i:i+CHUNK]
        filt = ",".join(f'"{d}"' for d in chunk)
        url = f"{SUPABASE_URL}/rest/v1/icp_enrichment?domain=in.({filt})&limit=100"
        r = requests.get(url, headers=h)
        if r.status_code == 200:
            for row in r.json():
                results[row["domain"]] = row
    return results

def load_domains_from_inputs() -> list:
    """Combine domains from today's re-enriched sets only (top 25 + midtier 50).
    Other Supabase rows have stale enrichment (pre-April 20 CPC fix / EPO)."""
    all_domains = set()
    # Top 25 — we know these were re-enriched today with EPO CPC + new sources
    for path in ['results/bottom_tier_input.json', 'results/midtier_50_input.json']:
        try:
            d = json.load(open(path))
            for r in d.get("results", []):
                if r.get("domain"):
                    all_domains.add(r["domain"])
        except Exception:
            pass
    # Also include top 25 (sorted subset of hybrid_pipeline_results.json)
    try:
        top_rs = json.load(open('results/hybrid_pipeline_results.json'))['results']
        for r in top_rs[:25]:
            if r.get("domain"):
                all_domains.add(r["domain"])
    except Exception:
        pass
    return sorted(all_domains)


# Additional DQ patterns (caught by the enrichment layer, but backstop here too)
ACADEMIC_PATTERNS = re.compile(
    r'(\.edu(\.[a-z]{2,3})?$|\.ac\.[a-z]{2,3}$|\.re\.[a-z]{2,3}$|'
    r'\.univ[\-\.]|\.uni[\-\.]|^unistra|^unibas|^unicamp|'
    r'\.gov$|\.mil$|student\.|doctoral\.|phd\.|alumni\.|mail\.|chem\.univ)',
    re.IGNORECASE
)

def parse_int(pattern: str, text: str) -> int:
    if not text: return 0
    m = re.search(pattern, text, re.IGNORECASE)
    return int(m.group(1).replace(',','')) if m else 0

def is_fresh_enrichment(e: dict) -> bool:
    """Row has the new sig_si_patent_filings with CPC pharma-class count."""
    sig = e.get("sig_si_patent_filings") or ""
    return "pharma-class" in sig or "total patents" in sig

def parse_new_signals(e: dict) -> dict:
    """Extract raw numbers from signal strings (since raw columns aren't in Supabase)."""
    out = {}
    pat = e.get("sig_si_patent_filings") or ""
    out["patent_count_3yr"]        = parse_int(r'([\d,]+)\s+total patents', pat) or parse_int(r'([\d,]+)\s+patents in', pat)
    out["patent_pharma_count_3yr"] = parse_int(r'([\d,]+)\s+of those are pharma', pat)
    ttl_match = re.search(r"Most recent:\s*'([^']+)'|recent titles:\s*'([^']+)'", pat)
    if ttl_match:
        out["patent_recent_titles"] = [ttl_match.group(1) or ttl_match.group(2)]

    pub = e.get("sig_si_recent_publications") or ""
    out["pubmed_drug_discovery_count"] = parse_int(r'([\d,]+)\s+drug discovery', pub)
    out["openalex_works_count"]        = parse_int(r'([\d,]+)\s+total publications', pub) or \
                                         parse_int(r'([\d,]+)\s+matched works', pub)

    mc = e.get("sig_sm_active_med_chem") or ""
    out["chembl_drug_count"]       = parse_int(r'([\d,]+)\s+approved (?:small molecule drugs|drugs)', mc)
    out["chembl_assay_count"]      = parse_int(r'([\d,]+)\s+bioactivity assays', mc)
    out["chembl_document_count"]   = parse_int(r'([\d,]+)\s+compound-linked papers', mc)
    out["pubchem_bioassay_count"]  = parse_int(r'([\d,]+)\s+HTS BioAssays', mc)
    out["openalex_medchem_works"]  = parse_int(r'([\d,]+)\s+medicinal-chemistry', mc)
    out["ct_total_trials"]         = parse_int(r'([\d,]+)\s+interventional trials', mc)

    cadd = e.get("sig_sm_cadd") or ""
    out["rcsb_pdb_count"] = parse_int(r'([\d,]+)\s+PDB structures', cadd)
    out["pubmed_cadd_count"] = parse_int(r'([\d,]+)\s+computational', cadd)

    h2l = e.get("sig_sm_hit_to_lead") or ""
    out["ct_phase12_trials"] = parse_int(r'([\d,]+)\s+active/recruiting', h2l)

    vs = e.get("sig_sm_virtual_screening") or ""
    out["pubmed_virtual_screening_count"] = parse_int(r'([\d,]+)\s+virtual screening', vs)

    fund = e.get("sig_si_recent_funding") or ""
    out["has_recent_offering"] = ("Filed S-" in fund or "Filed 424B" in fund)
    out["has_form_d"] = ("Form D filed" in fund)

    emp = e.get("sig_sf_employee_range") or ""
    m = re.search(r'~?([\d,]+)\s+employees', emp)
    if m:
        out["sf_employee_count_parsed"] = int(m.group(1).replace(',',''))

    return out

# ────────────────────────────────────────────────────────────────
# Styles
# ────────────────────────────────────────────────────────────────
def S(name, **k): return ParagraphStyle(name, **k)
STYLES = {
    "cover_title": S("ct", fontName="Helvetica-Bold", fontSize=26, textColor=white, leading=32),
    "cover_sub":   S("cs", fontName="Helvetica", fontSize=12, textColor=HexColor("#C8D8E4"), leading=18),
    "h1":          S("h1", fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, spaceBefore=14, spaceAfter=6, leading=20),
    "h2":          S("h2", fontName="Helvetica-Bold", fontSize=11, textColor=NAVY, spaceBefore=8, spaceAfter=3, leading=14),
    "body":        S("body", fontName="Helvetica", fontSize=9, textColor=HexColor("#2C3E50"), leading=13, spaceAfter=4, alignment=TA_JUSTIFY),
    "th":          S("th", fontName="Helvetica-Bold", fontSize=8.5, textColor=white, alignment=TA_CENTER),
    "td":          S("td", fontName="Helvetica", fontSize=8.5, textColor=HexColor("#1E293B"), leading=11),
    "td_b":        S("tdb", fontName="Helvetica-Bold", fontSize=8.5, textColor=HexColor("#1E293B"), leading=11),
    "td_small":    S("tds", fontName="Helvetica", fontSize=7.5, textColor=DARK_GREY, leading=10),
    "stat_num":    S("sn", fontName="Helvetica-Bold", fontSize=24, textColor=white, alignment=TA_CENTER),
    "stat_lbl":    S("sl", fontName="Helvetica", fontSize=8, textColor=HexColor("#C8D8E4"), alignment=TA_CENTER),
}
def hr(color=MID_GREY, thickness=0.5, space=6):
    return HRFlowable(width="100%", thickness=thickness, color=color, spaceAfter=space, spaceBefore=3)
def sp(h=6): return Spacer(1, h)
def tbl(d, cw, st):
    t = Table(d, colWidths=cw); t.setStyle(TableStyle(st)); return t

def signal_label(breakdown: dict) -> str:
    tags = []
    if breakdown.get("recent_funding"):          tags.append("💰 Recent funding")
    if breakdown.get("first_pharma_patents"):    tags.append("🔬 First patents")
    if breakdown.get("growing_publications"):    tags.append("📚 Growing pubs")
    if breakdown.get("first_preclinical_data"):  tags.append("🧪 Preclinical data")
    if breakdown.get("active_clinical_signal"):  tags.append("⚕️ Clinical work")
    if breakdown.get("right_size_team"):         tags.append("👥 Small team")
    return " · ".join(tags) if tags else "low signal"

# ────────────────────────────────────────────────────────────────
# PDF build
# ────────────────────────────────────────────────────────────────
def build_cover(story, cands, total_enriched):
    cover = Table([
        [Paragraph("eMolecules ICP", STYLES["cover_sub"])],
        [Paragraph("Watchlist<br/>Emerging Customers", STYLES["cover_title"])],
        [Paragraph(f"Companies that may become HIGH FIT within 12-24 months<br/>Generated {datetime.now():%B %d, %Y}",
                   STYLES["cover_sub"])],
    ], colWidths=[7*inch])
    cover.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1), NAVY),
        ("TOPPADDING",(0,0),(-1,-1),18),("BOTTOMPADDING",(0,0),(-1,-1),18),
        ("LEFTPADDING",(0,0),(-1,-1),20),("RIGHTPADDING",(0,0),(-1,-1),20),
    ]))
    story.append(cover); story.append(sp(14))

    stat = lambda n,l,c: tbl([[Paragraph(n, STYLES["stat_num"])],[Paragraph(l, STYLES["stat_lbl"])]],
                              [1.6*inch],
                              [("BACKGROUND",(0,0),(-1,-1),c),
                               ("TOPPADDING",(0,0),(-1,-1),10),
                               ("BOTTOMPADDING",(0,0),(-1,-1),10)])
    story.append(tbl([[stat(str(total_enriched),"companies analyzed",SLATE),
                       stat(str(len(cands)),"watchlist candidates",TEAL),
                       stat(str(sum(1 for c in cands if c["score"]>=60)),"strong trajectory",GREEN),
                       stat(str(sum(1 for c in cands if 40<=c["score"]<60)),"emerging",AMBER)]],
                     [1.7*inch]*4,
                     [("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4)]))
    story.append(sp(16))

    story.append(Paragraph("What this list is", STYLES["h1"])); story.append(hr())
    story.append(Paragraph(
        "These are companies that aren't current HIGH FIT customers but show clear trajectory "
        "signals — recent funding rounds, first pharma patents, growing publication activity, "
        "first preclinical bioassay data, or right-sized chemistry teams. Any of these is a leading "
        "indicator that the company is ramping up drug discovery activity and may become an eMolecules "
        "customer within 12-24 months. The watchlist trajectory score (0-100) weights these "
        "leading indicators. Current giants (500+ pharma patents) and disqualified domains (academic, "
        "bot, tool-only) are excluded.",
        STYLES["body"]))
    story.append(Paragraph("Signal legend", STYLES["h2"]))
    legend = """
    💰 <b>Recent funding</b> (SEC Form D or S-1/S-3 in last 18mo) &nbsp;·&nbsp;
    🔬 <b>First patents</b> (1-50 pharma-class CPC patents) &nbsp;·&nbsp;
    📚 <b>Growing pubs</b> (PubMed drug-discovery ≥ 2 or OpenAlex med-chem ≥ 10) &nbsp;·&nbsp;
    🧪 <b>Preclinical data</b> (ChEMBL assays or PubChem BioAssays) &nbsp;·&nbsp;
    ⚕️ <b>Clinical work</b> (CT.gov trials or PDB structures) &nbsp;·&nbsp;
    👥 <b>Small team</b> (10-150 employees)
    """
    story.append(Paragraph(legend, STYLES["body"]))

def build_table(story, cands):
    story.append(PageBreak())
    story.append(Paragraph(f"Watchlist candidates (ranked by trajectory score)", STYLES["h1"]))
    story.append(hr())

    data = [[Paragraph("#", STYLES["th"]),
             Paragraph("Domain", STYLES["th"]),
             Paragraph("Score", STYLES["th"]),
             Paragraph("Signals", STYLES["th"]),
             Paragraph("Key evidence", STYLES["th"])]]
    style = [("BACKGROUND",(0,0),(-1,0),SLATE),
             ("VALIGN",(0,0),(-1,-1),"TOP"),
             ("TOPPADDING",(0,0),(-1,-1),5),
             ("BOTTOMPADDING",(0,0),(-1,-1),5),
             ("LEFTPADDING",(0,0),(-1,-1),6),
             ("RIGHTPADDING",(0,0),(-1,-1),6),
             ("GRID",(0,0),(-1,-1),0.3,MID_GREY)]
    for i, c in enumerate(cands, start=1):
        e = c["enrichment"]
        p = e.get("_parsed", {})
        bg = LIGHT_GREY if i%2 else white
        style.append(("BACKGROUND",(0,i),(-1,i),bg))
        bits = []
        pharma = p.get("patent_pharma_count_3yr") or 0
        total  = p.get("patent_count_3yr") or 0
        if pharma: bits.append(f"{pharma} pharma patents (of {total})")
        titles = p.get("patent_recent_titles") or []
        if titles: bits.append(f"recent: '{titles[0][:50]}'")
        ct = p.get("ct_total_trials") or 0
        if ct: bits.append(f"{ct} trials")
        oax_mc = p.get("openalex_medchem_works") or 0
        if oax_mc: bits.append(f"{oax_mc} med-chem papers")
        chembl = p.get("chembl_drug_count") or 0
        if chembl: bits.append(f"{chembl} ChEMBL drugs")
        if p.get("has_recent_offering"): bits.append("S-1/S-3 offering filed")
        if p.get("has_form_d"): bits.append("Form D filed")

        signal_color = GREEN if c["score"]>=60 else (AMBER if c["score"]>=40 else MID_GREY)
        data.append([
            Paragraph(f"{i}", STYLES["td"]),
            Paragraph(f"<b>{e['domain']}</b>", STYLES["td"]),
            Paragraph(f"<font color='{signal_color.hexval()}'><b>{c['score']}</b></font>", STYLES["td_b"]),
            Paragraph(signal_label(c["breakdown"]), STYLES["td_small"]),
            Paragraph("; ".join(bits) if bits else "—", STYLES["td_small"]),
        ])
    story.append(tbl(data, [0.3*inch, 1.5*inch, 0.55*inch, 1.85*inch, 2.8*inch], style))

def build_methodology(story):
    story.append(PageBreak())
    story.append(Paragraph("How candidates were selected", STYLES["h1"])); story.append(hr())
    story.append(Paragraph(
        "A trajectory score (0–100) was calculated for every enriched company. "
        "Points are awarded for leading indicators of a ramping drug-discovery operation; "
        "penalties kill the score for auto-disqualified domains (academic/bot) or for "
        "companies that are already giants (>500 pharma patents = not emerging).",
        STYLES["body"]))

    rubric = [
        ["Signal", "Points", "Source", "Logic"],
        ["Recent funding", "+25", "SEC EDGAR Form D / S-1/S-3", "Fresh capital — likely ramping R&D spend"],
        ["First pharma patents", "+20", "EPO OPS (CPC A61K/C07D/C07K)", "1-50 pharma patents = emerging; >500 = giant (penalty)"],
        ["Growing publications", "+15", "PubMed + OpenAlex med-chem", "≥ 2 PubMed drug-discovery OR ≥ 10 OpenAlex med-chem"],
        ["First preclinical data", "+15", "ChEMBL + PubChem BioAssay", "First assays/screening deposited = active med chem"],
        ["Active clinical signal", "+15", "ClinicalTrials.gov + RCSB PDB", "First trials or structures = past hit-to-lead"],
        ["Right-size team", "+10", "EDGAR 10-K XBRL", "10-150 employees = small but real (giant >1000 → penalty)"],
        ["Auto-DQ domain", "−∞", "Pattern filter", "Academic/bot/manufacturing-only domains excluded"],
        ["Already giant", "−30", "EPO / EDGAR", "500+ pharma patents OR 1000+ employees = not a future customer"],
        ["Zero signal", "−20", "All sources", "Enrichment found nothing — insufficient evidence to watch"],
    ]
    header_style = [("BACKGROUND",(0,0),(-1,0),SLATE),
                    ("VALIGN",(0,0),(-1,-1),"TOP"),
                    ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
                    ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
                    ("GRID",(0,0),(-1,-1),0.3,MID_GREY)]
    header_row = [Paragraph("Signal", STYLES["th"]), Paragraph("Pts", STYLES["th"]),
                  Paragraph("Data source", STYLES["th"]), Paragraph("Rationale", STYLES["th"])]
    rows = [header_row]
    for i, row in enumerate(rubric[1:], start=1):
        bg = LIGHT_GREY if i%2 else white
        header_style.append(("BACKGROUND",(0,i),(-1,i),bg))
        rows.append([
            Paragraph(row[0], STYLES["td_b"]),
            Paragraph(row[1], STYLES["td_b"]),
            Paragraph(row[2], STYLES["td_small"]),
            Paragraph(row[3], STYLES["td_small"]),
        ])
    story.append(tbl(rows, [1.5*inch, 0.55*inch, 1.9*inch, 2.8*inch], header_style))

def add_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5); canvas.setFillColor(MID_GREY)
    canvas.drawCentredString(letter[0]/2, 0.4*inch,
        "eMolecules ICP Watchlist  •  Emerging future customers  •  Confidential")
    canvas.restoreState()

def main():
    print("Fetching enrichment data from Supabase...")
    domains = load_domains_from_inputs()
    enrich  = fetch_enrichment_by_domain(domains)
    print(f"  {len(enrich)} of {len(domains)} domains have enrichment data")

    # Exclude companies already in the top-25 battle cards (current HIGH-tier)
    top25_domains = set()
    try:
        rs = json.load(open('results/hybrid_pipeline_results.json'))['results']
        top25_domains = {r['domain'] for r in rs[:25]}
    except Exception:
        pass

    # Score each — require fresh enrichment + not academic + not top-25
    scored = []
    skipped_stale = skipped_acad = skipped_top = 0
    for d, e in enrich.items():
        if not is_fresh_enrichment(e):
            skipped_stale += 1; continue
        if ACADEMIC_PATTERNS.search(d):
            skipped_acad += 1; continue
        if d in top25_domains:
            skipped_top += 1; continue
        s, b = trajectory_score(e)
        if s >= 40:   # only meaningful trajectory candidates
            scored.append({"domain": d, "score": s, "breakdown": b, "enrichment": e})
    print(f"  skipped {skipped_stale} stale, {skipped_acad} academic, {skipped_top} already-top-25")
    scored.sort(key=lambda x: -x["score"])
    cands = scored[:25]
    print(f"  {len(scored)} positive-trajectory candidates; taking top {len(cands)}")

    out = "results/emolecules_watchlist.pdf"
    doc = SimpleDocTemplate(out, pagesize=letter,
                            topMargin=0.6*inch, bottomMargin=0.6*inch,
                            leftMargin=0.75*inch, rightMargin=0.75*inch)
    story = []
    build_cover(story, cands, len(enrich))
    build_table(story, cands)
    build_methodology(story)
    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(f"Saved: {out}")

if __name__ == "__main__":
    main()
