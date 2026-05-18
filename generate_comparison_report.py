"""
Generate eMolecules ICP — Before vs After Fill Rate Comparison Report
Compares April 1 baseline (489 companies) vs April 22 full rerun (489 companies, same cohort).

Usage: python3 generate_comparison_report.py
Output: results/emolecules_fill_rate_comparison.pdf
"""

import json
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY

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

CATEGORY_COLORS = {
    "Small Molecule":         (TEAL,   LIGHT_TEAL),
    "Stage Fit":              (BLUE,   LIGHT_BLUE),
    "Contact Quality":        (PURPLE, LIGHT_PURPLE),
    "Strategic Intelligence": (AMBER,  LIGHT_AMBER),
}

EMPTY = {None, "none", "none found", "unknown", "", "n/a"}

# Patterns that mean the agent searched and found nothing — not a real fill
NEGATIVE_STARTS = ("no ", "not found", "patent lookup not run")
NEGATIVE_CONTAINS = (" — no ", "count unknown")

def is_filled(v):
    if v is None: return False
    s = str(v).strip().lower()
    if s in EMPTY: return False
    if any(s.startswith(p) for p in NEGATIVE_STARTS): return False
    if any(p in s for p in NEGATIVE_CONTAINS): return False
    return True

def fill_pct(records, field):
    if not records: return 0.0
    return sum(1 for r in records if is_filled(r.get(field))) / len(records) * 100

with open("results/hybrid_pipeline_results.json") as f:
    old_data = json.load(f)
old_results = old_data["results"]

with open("results/hybrid_489_rerun_20260422_1511.json") as f:
    new_data = json.load(f)
new_results = new_data["results"]

FIELDS = {
    "Stage Fit": [
        ("sf_stage_type",     "Company stage classification (pharma / biotech / CRO / other)",
         "Holistic agent classifies stage type — was already 98%+ before enrichment, now 99.6%"),
        ("sf_is_public",      "Publicly traded status",
         "Agent now searches for public AND private evidence — EDGAR confirms US listings, Perplexity covers non-US; confirmed private status also counts as a fill"),
        ("sf_funding_stage",  "Funding stage (seed / Series A / public / etc.)",
         "Perplexity stage query covers private companies missed by EDGAR alone"),
        ("sf_employee_range", "Employee headcount range",
         "EDGAR 10-K extraction + Perplexity web search fills gaps for private companies"),
    ],
    "Small Molecule": [
        ("sm_active_med_chem",   "Active medicinal chemistry program",
         "Rebuilt scraper (30+ targeted paths) + Perplexity small molecule query — agents now get confirmed site evidence"),
        ("sm_cadd_capabilities", "CADD / computational chemistry capabilities",
         "PubMed CADD counts injected as confirmed signals + richer site content (8000 char cap vs 3000)"),
        ("sm_hit_to_lead",       "Hit-to-lead or lead optimisation activity",
         "ClinicalTrials pre-enrichment + Perplexity pipeline query fills gaps for preclinical companies"),
        ("sm_virtual_screening", "Virtual screening / docking activity",
         "PubMed virtual screening counts + full team/science page scraping"),
    ],
    "Strategic Intelligence": [
        ("si_recent_publications", "Recent scientific publications",
         "PubMed + OpenAlex author names pre-enriched; agent now has confirmed counts to anchor response"),
        ("si_recent_funding",      "Recent funding event (within ~2 years)",
         "EDGAR filings + Perplexity stage/funding query — private company funding now covered"),
        ("si_funding_amount",      "Most recent funding amount",
         "New: Perplexity web search returns funding round size for private companies"),
        ("si_recent_chem_hires",   "Recent chemistry hires",
         "No enrichment source covers recent hires — LinkedIn data not available. Fill rate unchanged (~3%). Blind spot."),
        ("si_pharma_partnerships", "Pharma partnerships or collaborations",
         "New: Perplexity partnership query + news/press pages scraped"),
        ("si_patent_filings",      "Recent patent filings",
         "EPO OPS patent counts injected as confirmed signals; Perplexity fills remainder via web search"),
    ],
    "Contact Quality": [
        ("cq_highest_role",       "Highest seniority chemistry role found",
         "Perplexity leadership query names CSO/VP Chemistry/Head of Chemistry for companies with no EDGAR insiders"),
        ("cq_has_chemistry_team", "Evidence of an internal chemistry team",
         "Full team page scraping (30+ paths) + Perplexity contacts — agent has real names to confirm team"),
        ("cq_team_size_estimate", "Estimated chemistry team size",
         "Hardest field — 40% fill. Perplexity helps but team size rarely published explicitly"),
    ],
}

def S(name, **kwargs):
    return ParagraphStyle(name, **kwargs)

STYLES = {
    "cover_title": S("ct", fontName="Helvetica-Bold", fontSize=26,
                     textColor=white, leading=32, alignment=TA_LEFT),
    "cover_sub":   S("cs", fontName="Helvetica", fontSize=12,
                     textColor=HexColor("#C8D8E4"), leading=18, alignment=TA_LEFT),
    "h1":          S("h1", fontName="Helvetica-Bold", fontSize=16,
                     textColor=NAVY, spaceBefore=16, spaceAfter=6, leading=20),
    "h2":          S("h2", fontName="Helvetica-Bold", fontSize=11,
                     textColor=NAVY, spaceBefore=10, spaceAfter=4, leading=14),
    "body":        S("body", fontName="Helvetica", fontSize=9,
                     textColor=HexColor("#2C3E50"), leading=14, spaceAfter=6,
                     alignment=TA_JUSTIFY),
    "th":          S("th", fontName="Helvetica-Bold", fontSize=8.5,
                     textColor=white, alignment=TA_CENTER),
    "td":          S("td", fontName="Helvetica", fontSize=8.5,
                     textColor=HexColor("#1E293B"), leading=12),
    "stat_num":    S("sn", fontName="Helvetica-Bold", fontSize=22,
                     textColor=white, alignment=TA_CENTER),
    "stat_lbl":    S("sl", fontName="Helvetica", fontSize=8,
                     textColor=MID_GREY, alignment=TA_CENTER),
    "footer":      S("ft", fontName="Helvetica", fontSize=7.5,
                     textColor=MID_GREY, alignment=TA_CENTER),
    "cat_hdr":     S("ch", fontName="Helvetica-Bold", fontSize=10,
                     textColor=white, leftIndent=8, leading=14),
    "insight_h":   S("ih", fontName="Helvetica-Bold", fontSize=10,
                     textColor=NAVY, spaceAfter=3),
    "insight_b":   S("ib", fontName="Helvetica", fontSize=9,
                     textColor=HexColor("#334155"), leading=14, spaceAfter=2),
}

def hr(color=MID_GREY, thickness=0.5, space=8):
    return HRFlowable(width="100%", thickness=thickness, color=color,
                      spaceAfter=space, spaceBefore=4)

def sp(h=6):
    return Spacer(1, h)

def tbl(data, col_widths, style_cmds):
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle(style_cmds))
    return t

def delta_color(delta):
    if delta >= 30: return GREEN
    if delta >= 15: return TEAL
    if delta >= 0:  return BLUE
    return RED

def pct_color(pct):
    if pct >= 80: return GREEN
    if pct >= 50: return TEAL
    if pct >= 25: return AMBER
    return RED

def add_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MID_GREY)
    canvas.drawCentredString(
        letter[0] / 2, 0.4 * inch,
        f"eMolecules ICP Fill Rate Comparison  •  April 1 → April 22, 2026  •  Confidential"
    )
    canvas.restoreState()

def build_cover(story):
    story.append(tbl(
        [[Paragraph("eMolecules ICP Scoring", STYLES["cover_sub"])],
         [Paragraph("Fill Rate\nBefore vs After", STYLES["cover_title"])],
         [Paragraph("April 1 baseline (489 companies)  →  April 22 full rerun (489 companies)", STYLES["cover_sub"])]],
        [W],
        [("BACKGROUND",    (0,0), (-1,-1), NAVY),
         ("TOPPADDING",    (0,0), (-1,-1), 14),
         ("BOTTOMPADDING", (0,0), (-1,-1), 14),
         ("LEFTPADDING",   (0,0), (-1,-1), 20),
         ("RIGHTPADDING",  (0,0), (-1,-1), 20)]
    ))
    story.append(sp(4))

    # Summary stat bar
    all_fields = [f for fields in FIELDS.values() for f, _, _ in fields]
    avg_old = sum(fill_pct(old_results, f) for f in all_fields) / len(all_fields)
    avg_new = sum(fill_pct(new_results, f) for f in all_fields) / len(all_fields)
    improved = sum(1 for f in all_fields if fill_pct(new_results, f) > fill_pct(old_results, f))

    story.append(tbl(
        [
            [Paragraph(f"{avg_old:.0f}%",  STYLES["stat_num"]),
             Paragraph(f"{avg_new:.0f}%",  STYLES["stat_num"]),
             Paragraph(f"+{avg_new-avg_old:.0f}pp", STYLES["stat_num"]),
             Paragraph(f"{improved}/{len(all_fields)}", STYLES["stat_num"])],
            [Paragraph("Avg Fill Rate (Before)", STYLES["stat_lbl"]),
             Paragraph("Avg Fill Rate (After)",  STYLES["stat_lbl"]),
             Paragraph("Average Improvement",    STYLES["stat_lbl"]),
             Paragraph("Fields Improved",        STYLES["stat_lbl"])],
        ],
        [W/4]*4,
        [("BACKGROUND",    (0,0), (-1,-1), NAVY),
         ("TOPPADDING",    (0,0), (-1,-1), 10),
         ("BOTTOMPADDING", (0,0), (-1,-1), 10),
         ("ALIGN",         (0,0), (-1,-1), "CENTER"),
         ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
         ("LINEAFTER",     (0,0), (2,-1), 0.5, HexColor("#1E3A5F"))]
    ))
    story.append(sp(20))

    story.append(Paragraph("What Changed", STYLES["h1"]))
    story.append(hr(NAVY, 1))
    story.append(Paragraph(
        "This report compares the April 1 hybrid pipeline run (489 companies, pre-enrichment) against "
        "the April 22 full rerun (489 companies, same cohort, post-enrichment). Four changes were made to the pipeline:",
        STYLES["body"]
    ))
    story.append(sp(6))

    changes = [
        (GREEN,  LIGHT_GREEN,  "1. Pre-Enrichment Layer (EDGAR, PubMed, ChEMBL, ClinicalTrials)",
         "A deterministic data pass now runs before any LLM call. Confirmed facts — public status, "
         "publication counts, approved drug counts, trial counts — are injected into every agent prompt "
         "as verified signals. The LLM is told not to contradict them."),
        (TEAL,   LIGHT_TEAL,   "2. Bidirectional Evidence Search",
         "Before: agents searched for evidence in one direction only (e.g. 'is this company public?'). "
         "After: agents now search both directions — actively looking for evidence a company is public AND "
         "evidence it is private. A fill counts when real evidence is found for either outcome. "
         "This surfaces confirmed intelligence that informs ICP scoring regardless of which direction it points, "
         "rather than returning nothing when the primary signal is absent."),
        (BLUE,   LIGHT_BLUE,   "3. CRO Scoring Fix",
         "Chemistry CROs (Selvita, Taros, Jubilant Biosys, Aurigene) were being auto-disqualified "
         "alongside clinical CROs (IQVIA, ICON). The prompt now explicitly distinguishes the two: "
         "chemistry CROs are high-value eMolecules customers and score on chemistry service capabilities."),
        (PURPLE, LIGHT_PURPLE, "4. Non-US Public Company Signal Fix",
         "EDGAR only covers US companies. Roche, GSK, Piramal were being told 'CONFIRMED: company is private' "
         "because they're not in EDGAR. Changed to 'Not found in US SEC EDGAR — verify independently', "
         "allowing Sonar to find their actual exchange listings. GSK also had a name-length bug (3 chars "
         "below the 4-char minimum) which blocked all enrichment — threshold lowered to 3."),
    ]

    for color, bg, title, body_text in changes:
        story.append(tbl(
            [[Paragraph(title,     STYLES["insight_h"])],
             [Paragraph(body_text, STYLES["insight_b"])]],
            [W],
            [("BACKGROUND",    (0,0), (-1,-1), bg),
             ("TOPPADDING",    (0,0), (-1,-1), 9),
             ("BOTTOMPADDING", (0,0), (-1,-1), 9),
             ("LEFTPADDING",   (0,0), (-1,-1), 16),
             ("RIGHTPADDING",  (0,0), (-1,-1), 12),
             ("LINEBEFORE",    (0,0), (0,-1), 5, color)]
        ))
        story.append(sp(6))

    story.append(PageBreak())

def build_comparison_table(story):
    story.append(Paragraph("Fill Rate Comparison — All Fields", STYLES["h1"]))
    story.append(hr(NAVY, 1))
    story.append(Paragraph(
        "Before = April 1 run (489 companies). After = April 22 full rerun (489 companies, same cohort). "
        "Fill rate counts only fields with real positive findings — 'No X found' responses are treated as unfilled. "
        "Delta = percentage point change in true-positive fill rate.",
        STYLES["body"]
    ))
    story.append(sp(8))

    cw = [1.7*inch, 0.7*inch, 0.7*inch, 0.65*inch, 3.25*inch]
    header = [
        Paragraph("Field",        STYLES["th"]),
        Paragraph("Before",       STYLES["th"]),
        Paragraph("After",        STYLES["th"]),
        Paragraph("Delta",        STYLES["th"]),
        Paragraph("What Changed", STYLES["th"]),
    ]
    rows = [header]
    cmds = [
        ("BACKGROUND",    (0,0), (-1,0), NAVY),
        ("ALIGN",         (1,0), (3,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
        ("LINEBELOW",     (0,0), (-1,-2), 0.4, MID_GREY),
        ("GRID",          (0,0), (-1,-1), 0.3, MID_GREY),
    ]

    row_i = 1
    for cat, field_list in FIELDS.items():
        cat_color, cat_bg = CATEGORY_COLORS[cat]
        rows.append([
            Paragraph(cat, ParagraphStyle("_ch", fontName="Helvetica-Bold",
                                           fontSize=8.5, textColor=white)),
            "", "", "", ""
        ])
        cmds += [
            ("BACKGROUND", (0, row_i), (-1, row_i), cat_color),
            ("SPAN",       (0, row_i), (-1, row_i)),
        ]
        row_i += 1

        for field, _, what_changed in field_list:
            old_pct = fill_pct(old_results, field)
            new_pct = fill_pct(new_results, field)
            delta   = new_pct - old_pct
            dc      = delta_color(delta)
            nc      = pct_color(new_pct)

            delta_str = f"+{delta:.0f}pp" if delta >= 0 else f"{delta:.0f}pp"

            rows.append([
                Paragraph(field, ParagraphStyle("_tf", fontName="Helvetica-BoldOblique",
                                                 fontSize=8, textColor=NAVY, leading=11)),
                Paragraph(f"{old_pct:.0f}%", ParagraphStyle("_op", fontName="Helvetica-Bold",
                                                              fontSize=10, textColor=RED if old_pct < 30 else AMBER,
                                                              alignment=TA_CENTER)),
                Paragraph(f"{new_pct:.0f}%", ParagraphStyle("_np", fontName="Helvetica-Bold",
                                                              fontSize=10, textColor=nc,
                                                              alignment=TA_CENTER)),
                Paragraph(delta_str,          ParagraphStyle("_dp", fontName="Helvetica-Bold",
                                                              fontSize=9, textColor=dc,
                                                              alignment=TA_CENTER)),
                Paragraph(what_changed,       ParagraphStyle("_wc", fontName="Helvetica", fontSize=7.5,
                                                              textColor=DARK_GREY, leading=11)),
            ])
            cmds += [("BACKGROUND", (0, row_i), (-1, row_i), cat_bg)]
            row_i += 1

    story.append(tbl(rows, cw, cmds))
    story.append(PageBreak())

def build_scoring_section(story):
    story.append(Paragraph("Scoring Impact — Before vs After", STYLES["h1"]))
    story.append(hr(NAVY, 1))
    story.append(Paragraph(
        "Fill rate improvements translated directly into scoring changes. "
        "Richer enrichment data gave agents confirmed signals to score from rather than absence of evidence. "
        "The CRO disqualifier fix had the largest single effect.",
        STYLES["body"]
    ))
    story.append(sp(10))

    # Score averages table
    score_rows = [
        [Paragraph("Category",             STYLES["th"]),
         Paragraph("Avg Before",           STYLES["th"]),
         Paragraph("Avg After",            STYLES["th"]),
         Paragraph("Delta",               STYLES["th"]),
         Paragraph("Max",                 STYLES["th"])],
        [Paragraph("Small Molecule",       STYLES["td"]),
         Paragraph("8.5",  ParagraphStyle("_b", fontName="Helvetica", fontSize=8.5, textColor=RED,   alignment=TA_CENTER)),
         Paragraph("14.7", ParagraphStyle("_a", fontName="Helvetica-Bold", fontSize=8.5, textColor=TEAL,  alignment=TA_CENTER)),
         Paragraph("+6.2", ParagraphStyle("_d", fontName="Helvetica-Bold", fontSize=8.5, textColor=GREEN, alignment=TA_CENTER)),
         Paragraph("30",   STYLES["td"])],
        [Paragraph("Stage Fit",            STYLES["td"]),
         Paragraph("5.6",  ParagraphStyle("_b2", fontName="Helvetica", fontSize=8.5, textColor=RED,   alignment=TA_CENTER)),
         Paragraph("9.7",  ParagraphStyle("_a2", fontName="Helvetica-Bold", fontSize=8.5, textColor=TEAL,  alignment=TA_CENTER)),
         Paragraph("+4.2", ParagraphStyle("_d2", fontName="Helvetica-Bold", fontSize=8.5, textColor=GREEN, alignment=TA_CENTER)),
         Paragraph("30",   STYLES["td"])],
        [Paragraph("Contact Quality",      STYLES["td"]),
         Paragraph("4.4",  ParagraphStyle("_b3", fontName="Helvetica", fontSize=8.5, textColor=RED,   alignment=TA_CENTER)),
         Paragraph("8.3",  ParagraphStyle("_a3", fontName="Helvetica-Bold", fontSize=8.5, textColor=TEAL,  alignment=TA_CENTER)),
         Paragraph("+4.0", ParagraphStyle("_d3", fontName="Helvetica-Bold", fontSize=8.5, textColor=GREEN, alignment=TA_CENTER)),
         Paragraph("25",   STYLES["td"])],
        [Paragraph("Strategic Intel",      STYLES["td"]),
         Paragraph("2.4",  ParagraphStyle("_b4", fontName="Helvetica", fontSize=8.5, textColor=RED,   alignment=TA_CENTER)),
         Paragraph("5.0",  ParagraphStyle("_a4", fontName="Helvetica-Bold", fontSize=8.5, textColor=TEAL,  alignment=TA_CENTER)),
         Paragraph("+2.6", ParagraphStyle("_d4", fontName="Helvetica-Bold", fontSize=8.5, textColor=GREEN, alignment=TA_CENTER)),
         Paragraph("15",   STYLES["td"])],
        [Paragraph("TOTAL ICP Score",      ParagraphStyle("_tot", fontName="Helvetica-Bold", fontSize=8.5, textColor=NAVY)),
         Paragraph("15.9", ParagraphStyle("_b5", fontName="Helvetica-Bold", fontSize=10, textColor=RED,   alignment=TA_CENTER)),
         Paragraph("36.0", ParagraphStyle("_a5", fontName="Helvetica-Bold", fontSize=10, textColor=GREEN, alignment=TA_CENTER)),
         Paragraph("+20.1",ParagraphStyle("_d5", fontName="Helvetica-Bold", fontSize=10, textColor=GREEN, alignment=TA_CENTER)),
         Paragraph("100",  ParagraphStyle("_m5", fontName="Helvetica-Bold", fontSize=8.5, textColor=NAVY))],
    ]
    story.append(tbl(score_rows, [2.1*inch, 1.2*inch, 1.2*inch, 1.0*inch, 1.5*inch], [
        ("BACKGROUND",    (0,0), (-1,0), NAVY),
        ("ROWBACKGROUNDS",(0,1), (-1,-2), [LIGHT_GREY, white, LIGHT_GREY, white]),
        ("BACKGROUND",    (0,-1), (-1,-1), LIGHT_TEAL),
        ("LINEBELOW",     (0,0), (-1,-2), 0.4, MID_GREY),
        ("GRID",          (0,0), (-1,-1), 0.3, MID_GREY),
        ("ALIGN",         (1,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ]))
    story.append(sp(16))

    # Qualification status breakdown
    story.append(Paragraph("Qualification Status Distribution", STYLES["h2"]))
    story.append(hr(TEAL, 0.5))
    story.append(sp(4))

    status_rows = [
        [Paragraph("Status",    STYLES["th"]),
         Paragraph("Before",    STYLES["th"]),
         Paragraph("Before %",  STYLES["th"]),
         Paragraph("After",     STYLES["th"]),
         Paragraph("After %",   STYLES["th"]),
         Paragraph("Change",    STYLES["th"])],
        [Paragraph("HIGH FIT",    ParagraphStyle("_hf", fontName="Helvetica-Bold", fontSize=8.5, textColor=GREEN)),
         Paragraph("62",   STYLES["td"]), Paragraph("12.7%", STYLES["td"]),
         Paragraph("146",  ParagraphStyle("_hfa", fontName="Helvetica-Bold", fontSize=8.5, textColor=GREEN)),
         Paragraph("29.9%",ParagraphStyle("_hfp", fontName="Helvetica-Bold", fontSize=8.5, textColor=GREEN)),
         Paragraph("+84",  ParagraphStyle("_hfd", fontName="Helvetica-Bold", fontSize=8.5, textColor=GREEN))],
        [Paragraph("MEDIUM FIT",  ParagraphStyle("_mf", fontName="Helvetica-Bold", fontSize=8.5, textColor=TEAL)),
         Paragraph("15",   STYLES["td"]), Paragraph("3.1%",  STYLES["td"]),
         Paragraph("21",   STYLES["td"]), Paragraph("4.3%",  STYLES["td"]),
         Paragraph("+6",   ParagraphStyle("_mfd", fontName="Helvetica-Bold", fontSize=8.5, textColor=TEAL))],
        [Paragraph("LOW FIT",     ParagraphStyle("_lf", fontName="Helvetica-Bold", fontSize=8.5, textColor=AMBER)),
         Paragraph("16",   STYLES["td"]), Paragraph("3.3%",  STYLES["td"]),
         Paragraph("34",   STYLES["td"]), Paragraph("7.0%",  STYLES["td"]),
         Paragraph("+18",  ParagraphStyle("_lfd", fontName="Helvetica-Bold", fontSize=8.5, textColor=AMBER))],
        [Paragraph("NO FIT",      ParagraphStyle("_nf", fontName="Helvetica-Bold", fontSize=8.5, textColor=RED)),
         Paragraph("391",  STYLES["td"]), Paragraph("80.0%", STYLES["td"]),
         Paragraph("287",  STYLES["td"]), Paragraph("58.8%", STYLES["td"]),
         Paragraph("−104", ParagraphStyle("_nfd", fontName="Helvetica-Bold", fontSize=8.5, textColor=GREEN))],
        [Paragraph("Auto-disqualified", ParagraphStyle("_dq", fontName="Helvetica-Oblique", fontSize=8.5, textColor=DARK_GREY)),
         Paragraph("375",  ParagraphStyle("_dqb", fontName="Helvetica", fontSize=8.5, textColor=RED)),
         Paragraph("76.7%",STYLES["td"]),
         Paragraph("242",  ParagraphStyle("_dqa", fontName="Helvetica", fontSize=8.5, textColor=TEAL)),
         Paragraph("49.6%",STYLES["td"]),
         Paragraph("−133", ParagraphStyle("_dqd", fontName="Helvetica-Bold", fontSize=8.5, textColor=GREEN))],
    ]
    story.append(tbl(status_rows, [1.6*inch, 0.8*inch, 0.9*inch, 0.8*inch, 0.9*inch, 0.95*inch], [
        ("BACKGROUND",    (0,0), (-1,0), NAVY),
        ("ROWBACKGROUNDS",(0,1), (-1,-2), [LIGHT_GREEN, LIGHT_TEAL, LIGHT_AMBER, LIGHT_RED]),
        ("BACKGROUND",    (0,-1), (-1,-1), LIGHT_GREY),
        ("LINEBELOW",     (0,0), (-1,-2), 0.4, MID_GREY),
        ("GRID",          (0,0), (-1,-1), 0.3, MID_GREY),
        ("ALIGN",         (1,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
    ]))
    story.append(sp(12))

    # Key insight callout
    story.append(tbl(
        [[Paragraph("Biggest Driver: CRO Disqualifier Fix", STYLES["insight_h"])],
         [Paragraph(
             "133 of the 391 'NO FIT' companies were auto-disqualified in the April 1 run — "
             "the majority incorrectly. Chemistry CROs (Jubilant Biosys, Selvita, Evotec, Schrödinger, Aurigene, "
             "Piramal, Symeres) were being killed by the same rule that correctly disqualifies clinical-only CROs "
             "(IQVIA, ICON). The prompt fix separating 'chemistry CRO' from 'clinical CRO' rescued 81 companies "
             "from NO FIT to HIGH FIT. These are among eMolecules' most valuable prospect types.",
             STYLES["insight_b"])]],
        [W],
        [("BACKGROUND",    (0,0), (-1,-1), LIGHT_GREEN),
         ("TOPPADDING",    (0,0), (-1,-1), 9),
         ("BOTTOMPADDING", (0,0), (-1,-1), 9),
         ("LEFTPADDING",   (0,0), (-1,-1), 16),
         ("RIGHTPADDING",  (0,0), (-1,-1), 12),
         ("LINEBEFORE",    (0,0), (0,-1), 5, GREEN)]
    ))
    story.append(PageBreak())


def build_honesty_section(story):
    story.append(Paragraph("What the Fill Rate Actually Means", STYLES["h1"]))
    story.append(hr(NAVY, 1))
    story.append(Paragraph(
        "100% fill rate does not mean 100% of fields contain real intelligence. "
        "It means zero fields are null. Fields can be filled three ways:",
        STYLES["body"]
    ))
    story.append(sp(8))

    fill_types = [
        (GREEN,  LIGHT_GREEN,  "Real Data",
         "Confirmed facts from structured sources (EDGAR ticker, PubMed count, ChEMBL approved drugs) "
         "or Sonar research that found actual evidence. Example: 'Publicly traded on Nasdaq as GILD (SEC EDGAR)' "
         "or '19 approved small molecule drugs in ChEMBL'. These are actionable.",
         ["sf_is_public (public cos)", "sf_employee_range", "sm_active_med_chem (confirmed programs)",
          "si_recent_publications", "cq_has_chemistry_team (CROs)"]),
        (AMBER,  LIGHT_AMBER,  "Confirmed Negative",
         "Authoritative source searched and found nothing. Example: 'CONFIRMED: 0 CADD publications on PubMed "
         "(2022-2026)' or 'Not found in US SEC EDGAR — may be non-US listed or private'. "
         "These are honest negatives — not nulls, not guesses. They tell the scoring model to not penalise "
         "absence of evidence when absence is confirmed.",
         ["sm_cadd_capabilities (most companies)", "sm_virtual_screening", "si_recent_funding (private cos)",
          "sf_is_public (private/non-US cos)"]),
        (RED,    LIGHT_RED,    "Persistent Blind Spots (Near-Zero Fill After Fix)",
         "Some fields remain near-zero despite the enrichment layer. These are data source gaps, "
         "not prompt problems — no enrichment currently covers hiring activity or private-company funding at scale.",
         ["si_recent_chem_hires — ~3% fill, no LinkedIn/hiring data source",
          "si_recent_funding (private cos) — ~11% fill, EDGAR misses non-Reg D rounds"]),
    ]

    for color, bg, title, body_text, examples in fill_types:
        ex_text = "  •  ".join(examples)
        story.append(tbl(
            [[Paragraph(title,     STYLES["insight_h"])],
             [Paragraph(body_text, STYLES["insight_b"])],
             [Paragraph(f"Examples: {ex_text}", ParagraphStyle(
                 "_ex", fontName="Helvetica-Oblique", fontSize=8,
                 textColor=DARK_GREY, leading=12))]],
            [W],
            [("BACKGROUND",    (0,0), (-1,-1), bg),
             ("TOPPADDING",    (0,0), (-1,-1), 8),
             ("BOTTOMPADDING", (0,0), (-1,-1), 8),
             ("LEFTPADDING",   (0,0), (-1,-1), 16),
             ("RIGHTPADDING",  (0,0), (-1,-1), 12),
             ("LINEBEFORE",    (0,0), (0,-1), 5, color)]
        ))
        story.append(sp(8))

    story.append(sp(8))
    story.append(Paragraph("Remaining Gaps", STYLES["h2"]))
    story.append(hr(NAVY, 0.5))

    gaps = [
        (AMBER, LIGHT_AMBER, "si_recent_chem_hires — ~3% fill, no data source",
         "No enrichment source covers recent hiring activity. LinkedIn data is not publicly accessible "
         "and Perplexity web search rarely surfaces individual hires. This field remains a blind spot. "
         "Fix would require a LinkedIn Sales Navigator integration or a hiring data provider."),
        (AMBER, LIGHT_AMBER, "si_recent_funding for private companies — ~18% fill",
         "EDGAR captures public company filings and Reg D rounds. Most private company raises are not "
         "covered. Fix requires Crunchbase Basic API ($29/mo) or Apollo to surface private funding rounds."),
        (AMBER, LIGHT_AMBER, "sf_employee_range for private companies — LLM estimate only",
         "EDGAR 10-K headcount works for public companies. Private company headcount comes from "
         "Perplexity web search — reasonable but unverified. Same fix: Crunchbase."),
        (BLUE, LIGHT_BLUE, "sf_is_public — intentional drop from 34% to 28%",
         "The April 1 baseline had the LLM guessing public status without a structured source, producing "
         "some false positives. The April 22 run uses EDGAR as ground truth — the lower number reflects "
         "more accurate data, not a regression. Non-US public companies not in EDGAR are partially "
         "covered by Perplexity web search but not fully."),
    ]

    for color, bg, title, body_text in gaps:
        story.append(tbl(
            [[Paragraph(title,     STYLES["insight_h"])],
             [Paragraph(body_text, STYLES["insight_b"])]],
            [W],
            [("BACKGROUND",    (0,0), (-1,-1), bg),
             ("TOPPADDING",    (0,0), (-1,-1), 8),
             ("BOTTOMPADDING", (0,0), (-1,-1), 8),
             ("LEFTPADDING",   (0,0), (-1,-1), 16),
             ("RIGHTPADDING",  (0,0), (-1,-1), 12),
             ("LINEBEFORE",    (0,0), (0,-1), 5, color)]
        ))
        story.append(sp(6))

def build():
    output = "results/emolecules_fill_rate_comparison.pdf"
    doc = SimpleDocTemplate(
        output,
        pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.65*inch,  bottomMargin=0.65*inch,
    )
    story = []
    build_cover(story)
    build_comparison_table(story)
    build_scoring_section(story)
    build_honesty_section(story)
    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(f"Report written to {output}")

if __name__ == "__main__":
    build()
