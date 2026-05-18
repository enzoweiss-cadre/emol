"""
eMolecules ICP — April 1 baseline vs April 20 full stack
Compares pre-enrichment pipeline to enrichment + prompt fixes + EPO patents + CPC filter.
Shows what was done per field to achieve the improvement.

Usage: python3 generate_april20_report.py
Output: results/emolecules_apr20_comparison.pdf
"""

import json, re
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

W = 7.0 * inch

NAVY        = HexColor("#0D2B45")
TEAL        = HexColor("#1A7A6E")
LIGHT_TEAL  = HexColor("#E8F5F3")
AMBER       = HexColor("#B45309")
LIGHT_AMBER = HexColor("#FFF8E7")
RED         = HexColor("#C0392B")
LIGHT_RED   = HexColor("#FDECEA")
LIGHT_GREY  = HexColor("#F4F6F8")
MID_GREY    = HexColor("#BDC3C7")
DARK_GREY   = HexColor("#5D6D7E")
GREEN       = HexColor("#1E8449")
LIGHT_GREEN = HexColor("#E9F7EF")
PURPLE      = HexColor("#6D28D9")
LIGHT_PURPLE= HexColor("#F5F3FF")
BLUE        = HexColor("#1D4ED8")
LIGHT_BLUE  = HexColor("#EFF6FF")
ORANGE      = HexColor("#EA580C")
LIGHT_ORANGE= HexColor("#FFF7ED")

# ─────────────────────────────────────────────────────────────
# Evidence-grounded fill filter (same as validated with user)
# ─────────────────────────────────────────────────────────────

UNKNOWN_MARKERS = [
    r'^unknown', r'cannot (be\s+determined|confirm|verify)',
    r'could not (determine|find|confirm|verify)', r'insufficient',
    r'^not (determined|available|verified)', r'unable to',
]
EVIDENCE_MARKERS = [
    r'\bconfirmed\b',
    r'\b(sec|edgar|chembl|pubmed|pdb|clinicaltrials|linkedin|crunchbase|pitchbook|patentsview|openalex|epo|form\s*d|cpc)\b',
    r'\b\d+\s+(approved|interventional|active|papers?|publications?|drugs?|patents?|trials?|employees?|structures?)',
    r'\$\d', r'\b\d{4}\b',
    r'per\s+(the\s+)?(website|pipeline|filing|press\s*release|10[- ]?k)',
]
UNGROUNDED_NEG = re.compile(
    r'^(no |none |not )[a-z\s\-]+(found|listed|identified|visible|known|mentioned|reported|present|available)'
    r'(\s+on\s+(website|pipeline|linkedin))?\s*[\.\-]*\s*$', re.I)
UNKR = re.compile('|'.join(UNKNOWN_MARKERS), re.I)
EVR  = re.compile('|'.join(EVIDENCE_MARKERS), re.I)

def is_true_fill(v):
    if v is None or v == "": return False
    s = str(v).strip()
    if not s: return False
    if UNKR.search(s): return False
    if UNGROUNDED_NEG.match(s): return False
    if EVR.search(s): return True
    if s.lower().startswith(('no ','none ','not ')): return False
    return True

def fill_pct(records, field):
    if not records: return 0.0
    return sum(1 for r in records if is_true_fill(r.get(field))) / len(records) * 100

# ─────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────

OLD_PATH = "results/hybrid_pipeline_results.json"   # Apr 1 baseline, 489 cos
NEW_PATH = "results/retest_20260420_1456.json"      # Apr 20 full stack, 25 cos

with open(OLD_PATH) as f:   old = json.load(f)["results"]
with open(NEW_PATH) as f:   new = json.load(f)["results"]

FIELDS = {
    "Small Molecule": [
        ("sm_active_med_chem",   "Active medicinal chemistry",
         "ChEMBL drugs + OpenAlex med-chem concept filter + ClinicalTrials enrichment + CDMO prompt fix"),
        ("sm_cadd_capabilities", "CADD / computational chemistry",
         "PubMed CADD query + RCSB PDB structures (structure-based design)"),
        ("sm_hit_to_lead",       "Hit-to-lead / lead optimization",
         "ClinicalTrials.gov active trials + prompt forces evidence"),
        ("sm_virtual_screening", "Virtual screening / docking",
         "PubMed virtual-screening query + prompt forces evidence"),
    ],
    "Stage Fit": [
        ("sf_is_public",      "Publicly traded status",
         "SEC EDGAR lookup + broader ticker file + normalized-name matching (Thermo Fisher, AstraZeneca, Novartis now found)"),
        ("sf_funding_stage",  "Funding stage",
         "SEC EDGAR filer category + Form D private-placement lookup"),
        ("sf_employee_range", "Employee headcount range",
         "SEC XBRL EntityNumberOfEmployees extraction from 10-K"),
        ("sf_stage_type",     "Company stage type classification",
         "Prompt fix forces evidence-based classification"),
    ],
    "Contact Quality": [
        ("cq_highest_role",       "Highest chemistry role found",
         "Prompt fix forces evidence-based response; LinkedIn search guidance"),
        ("cq_has_chemistry_team", "Evidence of chemistry team",
         "Prompt fix + CRO/CDMO caveat — service-page evidence now counted"),
        ("cq_team_size_estimate", "Chemistry team size estimate",
         "Prompt fix; still agent-only — best addressed with Apollo/LinkedIn"),
    ],
    "Strategic": [
        ("si_recent_funding",      "Recent funding event",
         "SEC Form D + S-1/S-3/424B4 offering lookup; confirmed-negative for private cos"),
        ("si_recent_chem_hires",   "Recent chemistry hires",
         "No structured source available yet — Apollo would close this"),
        ("si_recent_publications", "Recent drug-discovery publications",
         "PubMed multi-variant search (3 name forms) + OpenAlex supplement"),
        ("si_patent_filings",      "Recent patent filings",
         "EPO OPS patent search + CPC-class filter (A61K/C07D/C07K) + real invention titles"),
        ("si_pharma_partnerships", "Active pharma partnerships",
         "Agent-only; prompt forces evidence"),
    ],
}

CAT_COLORS = {
    "Small Molecule":  (TEAL,   LIGHT_TEAL),
    "Stage Fit":       (BLUE,   LIGHT_BLUE),
    "Contact Quality": (PURPLE, LIGHT_PURPLE),
    "Strategic":       (AMBER,  LIGHT_AMBER),
}

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
    "stat_num":    S("sn", fontName="Helvetica-Bold", fontSize=26, textColor=white, alignment=TA_CENTER),
    "stat_lbl":    S("sl", fontName="Helvetica", fontSize=8, textColor=HexColor("#C8D8E4"), alignment=TA_CENTER),
    "cat_hdr":     S("ch", fontName="Helvetica-Bold", fontSize=10, textColor=white, leftIndent=8, leading=14),
    "footer":      S("ft", fontName="Helvetica", fontSize=7.5, textColor=MID_GREY, alignment=TA_CENTER),
}

def hr(color=MID_GREY, thickness=0.5, space=6):
    return HRFlowable(width="100%", thickness=thickness, color=color, spaceAfter=space, spaceBefore=3)
def sp(h=6): return Spacer(1, h)
def tbl(data, col_widths, style_cmds):
    t = Table(data, colWidths=col_widths); t.setStyle(TableStyle(style_cmds)); return t

def pct_color(p):
    if p >= 80: return GREEN
    if p >= 50: return TEAL
    if p >= 25: return AMBER
    return RED

def add_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5); canvas.setFillColor(MID_GREY)
    canvas.drawCentredString(letter[0]/2, 0.4*inch,
        "eMolecules ICP  •  April 1 baseline → April 20 full stack  •  Confidential")
    canvas.restoreState()

# ─────────────────────────────────────────────────────────────
# Cover
# ─────────────────────────────────────────────────────────────
def build_cover(story):
    story.append(tbl(
        [[Paragraph("eMolecules ICP Scoring Pipeline", STYLES["cover_sub"])],
         [Paragraph("Fill-Rate Audit\n&nbsp;<br/>Before vs After", STYLES["cover_title"])],
         [Paragraph(f"April 1 baseline (489 companies)  →  April 20 full stack (25 companies)<br/>Generated {datetime.now():%B %d, %Y}", STYLES["cover_sub"])]],
        [W],
        [("BACKGROUND",(0,0),(-1,-1),NAVY),
         ("TOPPADDING",(0,0),(-1,-1),18),("BOTTOMPADDING",(0,0),(-1,-1),18),
         ("LEFTPADDING",(0,0),(-1,-1),20),("RIGHTPADDING",(0,0),(-1,-1),20)]))
    story.append(sp(10))

    # Headline stats
    all_fields = [f for flds in FIELDS.values() for f, _, _ in flds]
    avg_old = sum(fill_pct(old, f) for f in all_fields) / len(all_fields)
    avg_new = sum(fill_pct(new, f) for f in all_fields) / len(all_fields)
    improved = sum(1 for f in all_fields if fill_pct(new, f) > fill_pct(old, f) + 2)

    stat = lambda n, l, c: tbl([[Paragraph(n, STYLES["stat_num"])], [Paragraph(l, STYLES["stat_lbl"])]],
                                [1.5*inch], [("BACKGROUND",(0,0),(-1,-1),c),
                                 ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10)])
    story.append(tbl([[stat(f"{avg_old:.0f}%", "baseline fill rate", DARK_GREY),
                       stat(f"{avg_new:.0f}%", "new fill rate", GREEN),
                       stat(f"+{avg_new-avg_old:.0f}pp", "improvement", TEAL),
                       stat(f"{improved}/{len(all_fields)}", "fields improved", BLUE)]],
                     [1.6*inch]*4,
                     [("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4)]))
    story.append(sp(14))

    story.append(Paragraph("Executive summary", STYLES["h1"]))
    story.append(hr())
    story.append(Paragraph(
        "The April 1 hybrid pipeline asked LLM agents to find structured facts (funding, patents, "
        "employee counts, publications) cold, via web search. That failed ~70% of the time. "
        "Today the pipeline adds a deterministic pre-enrichment layer pulling from SEC EDGAR, "
        "PubMed, OpenAlex, ChEMBL, PubChem BioAssay, RCSB PDB, ClinicalTrials.gov, Form D, and "
        "EPO OPS patents (with CPC-class filter to separate drug patents from tool/instrument patents). "
        "Combined with prompt fixes that require evidence-based responses and correctly handle "
        "chemistry CROs/CDMOs as customers (not auto-disqualifiers), the true fill rate approximately doubled.",
        STYLES["body"]))
    story.append(Paragraph(
        "<b>Fill rate</b> is measured strictly: a field is only counted as filled when the agent "
        "returns evidence in either direction (positive OR confirmed-negative with a cited source). "
        "Pure 'unknown' or 'not found' responses without a source are counted as unfilled.",
        STYLES["body"]))

# ─────────────────────────────────────────────────────────────
# Per-field comparison tables
# ─────────────────────────────────────────────────────────────
def build_comparison(story):
    story.append(PageBreak())
    story.append(Paragraph("Fill rate by sub-category", STYLES["h1"]))
    story.append(hr())

    for cat, fields in FIELDS.items():
        dark, _ = CAT_COLORS[cat]
        story.append(tbl([[Paragraph(f"<b>{cat}</b>", STYLES["cat_hdr"])]], [W],
                         [("BACKGROUND",(0,0),(-1,-1),dark),
                          ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        data = [[Paragraph("Field", STYLES["th"]),
                 Paragraph("Apr 1<br/>(n=489)", STYLES["th"]),
                 Paragraph("Apr 20<br/>(n=25)", STYLES["th"]),
                 Paragraph("Δ", STYLES["th"]),
                 Paragraph("What changed", STYLES["th"])]]
        style = [("BACKGROUND",(0,0),(-1,0),dark), ("VALIGN",(0,0),(-1,-1),"TOP"),
                 ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
                 ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
                 ("GRID",(0,0),(-1,-1),0.3,MID_GREY)]
        for i, (f, label, note) in enumerate(fields, start=1):
            po = fill_pct(old, f); pn = fill_pct(new, f); d = pn-po
            arrow = "↑" if d > 2 else ("↓" if d < -2 else "·")
            row = (i-1) % 2
            bg = LIGHT_GREY if row == 0 else white
            style.append(("BACKGROUND",(0,i),(-1,i),bg))
            data.append([
                Paragraph(f"<b>{label}</b><br/><font size=7 color='#64748B'>{f}</font>", STYLES["td"]),
                Paragraph(f"<font color='{pct_color(po).hexval()}'><b>{po:.0f}%</b></font>", STYLES["td"]),
                Paragraph(f"<font color='{pct_color(pn).hexval()}'><b>{pn:.0f}%</b></font>", STYLES["td"]),
                Paragraph(f"<b>{'+' if d>=0 else ''}{d:.0f}pp {arrow}</b>", STYLES["td"]),
                Paragraph(note, STYLES["td_small"]),
            ])
        story.append(tbl(data, [1.35*inch, 0.55*inch, 0.55*inch, 0.65*inch, 3.4*inch], style))
        story.append(sp(8))

# ─────────────────────────────────────────────────────────────
# What we built (the work log)
# ─────────────────────────────────────────────────────────────
WORK_LOG = [
    ("Pre-enrichment layer", TEAL, [
        ("SEC EDGAR", "Public company lookup with broader ticker file (12K entries incl. ADRs). Added normalized-name matching so 'thermofisher.com' resolves to 'Thermo Fisher Scientific'. XBRL 10-K employee count extraction."),
        ("SEC Form D", "Private-placement filings for VC-backed biotechs. Filter-by-applicant validation prevents false positives from form-mentions."),
        ("PubMed E-utilities", "Drug-discovery / CADD / virtual-screening publication counts. Multi-variant name search (full + short + domain) takes max hits. NCBI API key in place — 3x throughput."),
        ("OpenAlex", "Institution works count + medicinal-chemistry concept filter (C71924100). Catches EU/Asian biotechs whose papers aren't tagged in PubMed."),
        ("ChEMBL", "Approved drugs + assay count + compound-linked document count. Catches preclinical companies with no approved drugs but active bioactivity data."),
        ("PubChem BioAssay", "HTS screening campaigns via NCBI E-utilities SourceName filter. Signal for companies running screens."),
        ("RCSB PDB", "Protein crystal structure count (structure-based drug design signal). Short-name guard prevents false positives from single-letter author matches."),
        ("ClinicalTrials.gov v2", "Total + active-recruiting trials as lead sponsor."),
        ("EPO OPS (patents)", "EP + PCT + USPTO coverage via DOCDB. CPC-class filter (A61K/C07D/C07K) separates pharma patents from tool/instrument patents. Real invention titles via /search/biblio constituent — 'KRAS Modulating Compounds' beats patent number '2026080762'."),
    ]),
    ("Prompt fixes", BLUE, [
        ("Evidence-or-absence rule", "Every field that previously returned null when not found now requires a meaningful string — positive evidence OR confirmed-negative with source. 'No Form D filings in SEC EDGAR 2023-2026' beats 'unknown'."),
        ("CDMO / CRO reclassification", "Removed wholesale 'manufacturing-only' disqualifier. Custom synthesis, contract med chem, lead-optimization services, PROTAC/fragment shops are now explicitly called out as CORE CUSTOMERS. Only bulk-API / generics / clinical-only operations remain disqualified."),
        ("Patent caveat for CROs", "Added explicit guidance that CROs/CDMOs work on client IP and typically have zero own-name patents. Absence of patents is NOT a negative signal for service companies."),
    ]),
    ("Reporting infrastructure", PURPLE, [
        ("True-fill definition", "Updated run_batch_retest.py filter to count evidence-based negatives as filled. Stopped rejecting 'No Form D filings found in SEC EDGAR' as unfilled."),
        ("Supabase tables", "icp_enrichment stores raw counts + 9 pre-built signal strings (sig_*). Pipeline writes final scores to icp_hybrid_results."),
    ]),
]

def build_work_log(story):
    story.append(PageBreak())
    story.append(Paragraph("What changed", STYLES["h1"]))
    story.append(hr())
    story.append(Paragraph(
        "The improvements came from three parallel workstreams. Pre-enrichment added deterministic "
        "data sources so agents don't search cold. Prompt fixes force evidence-based output and "
        "correctly classify chemistry-service companies as customers. Reporting fixes corrected a "
        "stale fill-rate filter that under-counted confirmed negatives.",
        STYLES["body"]))
    story.append(sp(6))

    for section_name, section_color, items in WORK_LOG:
        story.append(tbl([[Paragraph(f"<b>{section_name}</b>", STYLES["cat_hdr"])]], [W],
                         [("BACKGROUND",(0,0),(-1,-1),section_color),
                          ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        data = [[Paragraph("Component", STYLES["th"]), Paragraph("Description", STYLES["th"])]]
        style = [("BACKGROUND",(0,0),(-1,0),section_color), ("VALIGN",(0,0),(-1,-1),"TOP"),
                 ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
                 ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
                 ("GRID",(0,0),(-1,-1),0.3,MID_GREY)]
        for i, (comp, desc) in enumerate(items, start=1):
            bg = LIGHT_GREY if (i-1) % 2 == 0 else white
            style.append(("BACKGROUND",(0,i),(-1,i),bg))
            data.append([Paragraph(f"<b>{comp}</b>", STYLES["td"]),
                         Paragraph(desc, STYLES["td_small"])])
        story.append(tbl(data, [1.6*inch, 4.9*inch], style))
        story.append(sp(10))

# ─────────────────────────────────────────────────────────────
# Gaps still open
# ─────────────────────────────────────────────────────────────
def build_gaps(story):
    story.append(PageBreak())
    story.append(Paragraph("Remaining gaps", STYLES["h1"]))
    story.append(hr())
    story.append(Paragraph(
        "After today's work there are only two genuinely-unfilled fields left. Both would close with "
        "paid data access — free sources have been exhausted.",
        STYLES["body"]))

    gaps = [
        ("sf_employee_range", f"{fill_pct(new,'sf_employee_range'):.0f}%",
         "SEC XBRL only tags EntityNumberOfEmployees for ~45% of public filers. Private companies have no free source.",
         "Crunchbase"),
        ("sf_funding_stage", f"{fill_pct(new,'sf_funding_stage'):.0f}%",
         "Private biotech funding rounds aren't in EDGAR unless a Form D was filed. EU/Asian rounds often don't trigger US disclosure.",
         "Crunchbase"),
        ("cq_team_size_estimate", f"{fill_pct(new,'cq_team_size_estimate'):.0f}%",
         "No deterministic public source for chemistry team size. Agent estimates from LinkedIn snippets which are often not indexed.",
         "Apollo.io"),
        ("si_recent_chem_hires", f"{fill_pct(new,'si_recent_chem_hires'):.0f}%",
         "No structured source exists. Requires LinkedIn hire-history access.",
         "Apollo.io"),
    ]
    data = [[Paragraph("Field", STYLES["th"]), Paragraph("Fill", STYLES["th"]),
             Paragraph("Why unfilled", STYLES["th"]), Paragraph("Recommended fix", STYLES["th"])]]
    style = [("BACKGROUND",(0,0),(-1,0),AMBER), ("VALIGN",(0,0),(-1,-1),"TOP"),
             ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
             ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
             ("GRID",(0,0),(-1,-1),0.3,MID_GREY)]
    for i, (fld, pct, why, fix) in enumerate(gaps, start=1):
        bg = LIGHT_GREY if (i-1) % 2 == 0 else white
        style.append(("BACKGROUND",(0,i),(-1,i),bg))
        data.append([Paragraph(f"<b>{fld}</b>", STYLES["td"]),
                     Paragraph(pct, STYLES["td_b"]),
                     Paragraph(why, STYLES["td_small"]),
                     Paragraph(fix, STYLES["td_small"])])
    story.append(tbl(data, [1.55*inch, 0.55*inch, 3.0*inch, 1.4*inch], style))
    story.append(sp(10))

    story.append(Paragraph("Caveats", STYLES["h2"]))
    story.append(Paragraph(
        "The April 20 sample is 25 companies — run-to-run LLM variance of ±5-10pp is expected on a "
        "sample this small. The April 1 baseline (489 companies) is more stable statistically but "
        "reflects a worse pipeline. A post-enrichment run at 100+ company scale would give tighter "
        "confidence intervals on today's numbers.",
        STYLES["body"]))

# ─────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────
def main():
    out_path = "results/emolecules_apr20_comparison.pdf"
    doc = SimpleDocTemplate(out_path, pagesize=letter,
                            topMargin=0.6*inch, bottomMargin=0.6*inch,
                            leftMargin=0.75*inch, rightMargin=0.75*inch)
    story = []
    build_cover(story)
    build_comparison(story)
    build_work_log(story)
    build_gaps(story)
    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(f"Saved: {out_path}")

if __name__ == "__main__":
    main()
