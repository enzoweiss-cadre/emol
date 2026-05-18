"""
Generate eMolecules Hybrid Pipeline — Knowledge Coverage (Fill Rate) Report

For each scoring subcategory, shows what % of prospects the workflow
found data on. Identifies model strengths and blind spots.

Usage: python3 generate_fill_rate_report.py
Output: results/emolecules_fill_rate_report.pdf
"""

import json
import re
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

# ── Dimensions ────────────────────────────────────────────────────────────────
W = 7.0 * inch   # usable content width (8.5 - 0.75 - 0.75 margins)

# ── Colour palette ────────────────────────────────────────────────────────────
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
WHITE       = white

CATEGORY_COLORS = {
    "Small Molecule":        (TEAL,   LIGHT_TEAL),
    "Stage Fit":             (BLUE,   LIGHT_BLUE),
    "Contact Quality":       (PURPLE, LIGHT_PURPLE),
    "Strategic Intelligence":(AMBER,  LIGHT_AMBER),
}

# ── Load data ─────────────────────────────────────────────────────────────────
with open("results/hybrid_489_rerun_20260422_1511.json") as f:
    data = json.load(f)

results = data["results"]
total   = len(results)
stage_a = [r for r in results if r["stage_reached"] == "A"]
stage_b = [r for r in results if r["stage_reached"] == "B"]

# ── Fill rate logic ───────────────────────────────────────────────────────────
EMPTY = {None, "none", "none found", "unknown", "", "n/a"}
NEGATIVE_STARTS = ("no ", "not found", "patent lookup not run")
NEGATIVE_CONTAINS = (" — no ", "count unknown")

def is_filled(val):
    if val is None: return False
    if isinstance(val, list): return len(val) > 0
    s = str(val).strip().lower()
    if s in EMPTY: return False
    if any(s.startswith(p) for p in NEGATIVE_STARTS): return False
    if any(p in s for p in NEGATIVE_CONTAINS): return False
    return True

def fill_pct(records, field):
    if not records: return 0.0
    return sum(1 for r in records if is_filled(r.get(field))) / len(records) * 100

def classify(pct):
    if pct >= 70: return "STRONG",   GREEN,  LIGHT_GREEN
    if pct >= 40: return "MODERATE", TEAL,   LIGHT_TEAL
    if pct >= 15: return "WEAK",     AMBER,  LIGHT_AMBER
    return              "BLIND",    RED,    LIGHT_RED

# ── Field definitions ─────────────────────────────────────────────────────────
FIELDS = {
    "Small Molecule": [
        ("sm_active_med_chem",    "Active medicinal chemistry program"),
        ("sm_cadd_capabilities",  "CADD / computational chemistry capabilities"),
        ("sm_hit_to_lead",        "Hit-to-lead or lead optimisation activity"),
        ("sm_virtual_screening",  "Virtual screening / docking activity"),
    ],
    "Stage Fit": [
        ("sf_stage_type",         "Company stage type (pharma / biotech / CRO / other)"),
        ("sf_employee_range",     "Employee headcount range"),
        ("sf_funding_stage",      "Funding stage (seed / Series A-D / public / etc.)"),
        ("sf_is_public",          "Publicly traded status"),
    ],
    "Contact Quality": [
        ("cq_highest_role",       "Highest seniority chemistry or biology role found"),
        ("cq_has_chemistry_team", "Evidence of an internal chemistry team"),
        ("cq_team_size_estimate", "Estimated chemistry team size"),
    ],
    "Strategic Intelligence": [
        ("si_recent_funding",     "Recent funding event (within ~2 years)"),
        ("si_funding_amount",     "Specific funding amount"),
        ("si_recent_chem_hires",  "Recent chemistry / drug discovery hires"),
        ("si_recent_publications","Recent scientific publications"),
        ("si_pharma_partnerships","Active pharma partnerships or collaborations"),
        ("si_patent_filings",     "Recent patent filings"),
    ],
}

# ── Styles ────────────────────────────────────────────────────────────────────
def S(name, **kwargs):
    return ParagraphStyle(name, **kwargs)

STYLES = {
    "cover_title": S("ct", fontName="Helvetica-Bold", fontSize=26,
                     textColor=white, leading=32, alignment=TA_LEFT),
    "cover_sub":   S("cs", fontName="Helvetica", fontSize=12,
                     textColor=HexColor("#C8D8E4"), leading=18, alignment=TA_LEFT),
    "cover_meta_k":S("cmk", fontName="Helvetica-Bold", fontSize=9,
                     textColor=DARK_GREY),
    "cover_meta_v":S("cmv", fontName="Helvetica", fontSize=9,
                     textColor=HexColor("#2C3E50")),
    "stat_num":    S("sn", fontName="Helvetica-Bold", fontSize=22,
                     textColor=white, alignment=TA_CENTER),
    "stat_lbl":    S("sl", fontName="Helvetica", fontSize=8,
                     textColor=MID_GREY, alignment=TA_CENTER),
    "h1":          S("h1", fontName="Helvetica-Bold", fontSize=16,
                     textColor=NAVY, spaceBefore=16, spaceAfter=6, leading=20),
    "h2":          S("h2", fontName="Helvetica-Bold", fontSize=11,
                     textColor=NAVY, spaceBefore=10, spaceAfter=4, leading=14),
    "body":        S("body", fontName="Helvetica", fontSize=9,
                     textColor=HexColor("#2C3E50"), leading=14, spaceAfter=6,
                     alignment=TA_JUSTIFY),
    "body_sm":     S("body_sm", fontName="Helvetica", fontSize=8.5,
                     textColor=DARK_GREY, leading=13, spaceAfter=4),
    "label":       S("lbl", fontName="Helvetica-Bold", fontSize=8,
                     textColor=DARK_GREY, spaceAfter=2),
    "th":          S("th", fontName="Helvetica-Bold", fontSize=8.5,
                     textColor=white, alignment=TA_CENTER),
    "td":          S("td", fontName="Helvetica", fontSize=8.5,
                     textColor=HexColor("#1E293B"), leading=12),
    "td_field":    S("tdf", fontName="Helvetica-BoldOblique", fontSize=8.5,
                     textColor=NAVY, leading=12),
    "td_desc":     S("tdd", fontName="Helvetica", fontSize=8,
                     textColor=DARK_GREY, leading=11),
    "td_pct":      S("tdp", fontName="Helvetica-Bold", fontSize=10,
                     alignment=TA_CENTER),
    "td_stage":    S("tds", fontName="Helvetica", fontSize=7.5,
                     textColor=DARK_GREY, alignment=TA_CENTER, leading=10),
    "badge":       S("bdg", fontName="Helvetica-Bold", fontSize=7.5,
                     textColor=white, alignment=TA_CENTER),
    "insight_h":   S("ih", fontName="Helvetica-Bold", fontSize=10,
                     textColor=NAVY, spaceAfter=3),
    "insight_b":   S("ib", fontName="Helvetica", fontSize=9,
                     textColor=HexColor("#334155"), leading=14, spaceAfter=2),
    "footer":      S("ft", fontName="Helvetica", fontSize=7.5,
                     textColor=MID_GREY, alignment=TA_CENTER),
    "cat_hdr":     S("ch", fontName="Helvetica-Bold", fontSize=10,
                     textColor=white, leftIndent=8, leading=14),
    "cat_desc":    S("cd", fontName="Helvetica-Oblique", fontSize=8.5,
                     textColor=DARK_GREY, leading=13, spaceAfter=6),
    "field_name":  S("fn", fontName="Helvetica-BoldOblique", fontSize=9,
                     textColor=NAVY, leading=12),
    "field_desc":  S("fd", fontName="Helvetica", fontSize=8,
                     textColor=DARK_GREY, leading=11),
    "pct_big":     S("pb", fontName="Helvetica-Bold", fontSize=18,
                     alignment=TA_CENTER, leading=20),
    "pct_lbl":     S("pl", fontName="Helvetica", fontSize=7,
                     textColor=DARK_GREY, alignment=TA_CENTER),
    "stage_cmp":   S("sc", fontName="Helvetica", fontSize=8,
                     textColor=DARK_GREY, alignment=TA_CENTER, leading=11),
}

# ── Helpers ───────────────────────────────────────────────────────────────────
def hr(color=MID_GREY, thickness=0.5, space=8):
    return HRFlowable(width="100%", thickness=thickness, color=color,
                      spaceAfter=space, spaceBefore=4)

def sp(h=6):
    return Spacer(1, h)

def tbl(data, col_widths, style_cmds):
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle(style_cmds))
    return t

def badge_para(label, color):
    return Paragraph(label, ParagraphStyle(
        "_b", fontName="Helvetica-Bold", fontSize=7, textColor=white, alignment=TA_CENTER
    ))

# ── Footer ────────────────────────────────────────────────────────────────────
def add_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MID_GREY)
    canvas.drawCentredString(
        letter[0] / 2, 0.4 * inch,
        f"eMolecules ICP Knowledge Coverage Report  •  "
        f"Generated {datetime.now().strftime('%B %d, %Y')}  •  Confidential"
    )
    canvas.restoreState()

# ── Cover page ────────────────────────────────────────────────────────────────
def build_cover(story):
    run_at = data.get("run_at", "")
    try:
        dt = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
        date_str = dt.strftime("%B %d, %Y")
    except Exception:
        date_str = datetime.now().strftime("%B %d, %Y")

    # Navy title block
    story.append(tbl(
        [[Paragraph("eMolecules ICP Scoring", STYLES["cover_sub"])],
         [Paragraph("Knowledge Coverage\nAnalysis", STYLES["cover_title"])],
         [Paragraph("Hybrid Pipeline — Fill Rate Report", STYLES["cover_sub"])]],
        [W],
        [("BACKGROUND",    (0,0), (-1,-1), NAVY),
         ("TOPPADDING",    (0,0), (-1,-1), 14),
         ("BOTTOMPADDING", (0,0), (-1,-1), 14),
         ("LEFTPADDING",   (0,0), (-1,-1), 20),
         ("RIGHTPADDING",  (0,0), (-1,-1), 20)]
    ))
    story.append(sp(4))

    # Stats bar — hybrid-only summary
    high_fit  = sum(1 for r in results if r.get("qualification_status") == "HIGH FIT")
    med_fit   = sum(1 for r in results if r.get("qualification_status") == "MEDIUM FIT")
    no_fit    = sum(1 for r in results if r.get("qualification_status") in ("LOW FIT", "NO FIT"))
    story.append(tbl(
        [
            [Paragraph(str(total),    STYLES["stat_num"]),
             Paragraph(str(high_fit), STYLES["stat_num"]),
             Paragraph(str(med_fit),  STYLES["stat_num"]),
             Paragraph(str(no_fit),   STYLES["stat_num"])],
            [Paragraph("Prospects Scored", STYLES["stat_lbl"]),
             Paragraph("High Fit",         STYLES["stat_lbl"]),
             Paragraph("Medium Fit",       STYLES["stat_lbl"]),
             Paragraph("Low / No Fit",     STYLES["stat_lbl"])],
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

    # About section
    story.append(Paragraph("About This Report", STYLES["h1"]))
    story.append(hr(NAVY, 1))
    story.append(Paragraph(
        "This report measures the <b>knowledge coverage</b> of the eMolecules hybrid ICP scoring pipeline. "
        "For each scoring subcategory, it shows what percentage of the 50 evaluated prospects had "
        "sufficient information available for the workflow to make a scoring determination.",
        STYLES["body"]
    ))
    story.append(Paragraph(
        "A high fill rate means the pipeline reliably finds data in that dimension. "
        "A low fill rate means the pipeline is scoring from absence of evidence — "
        "not from confirmed signal. Understanding these gaps allows scoring weights to be "
        "recalibrated to reflect where the model has genuine knowledge vs. where it is guessing.",
        STYLES["body"]
    ))
    story.append(sp(16))

    # Legend
    story.append(Paragraph("Rating Scale", STYLES["h2"]))
    legend = [
        (GREEN,  LIGHT_GREEN,  "STRONG",   "70%+ fill rate — reliable signal, full scoring weight appropriate"),
        (TEAL,   LIGHT_TEAL,   "MODERATE", "40–69% — useful but incomplete, use with awareness of gaps"),
        (AMBER,  LIGHT_AMBER,  "WEAK",     "15–39% — sparse data, interpret results with caution"),
        (RED,    LIGHT_RED,    "BLIND",    "< 15% — near-zero coverage, scoring weight should be minimal or gated"),
    ]
    leg_rows = [[
        tbl([[badge_para(lbl, c)]], [0.85*inch], [
            ("BACKGROUND", (0,0), (-1,-1), c),
            ("TOPPADDING", (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("ALIGN", (0,0), (-1,-1), "CENTER"),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ]),
        Paragraph(desc, ParagraphStyle("_ld", fontName="Helvetica", fontSize=9,
                                        textColor=HexColor("#334155"), leading=13))
    ] for c, bg, lbl, desc in legend]

    story.append(tbl(
        leg_rows,
        [0.9*inch, 6.0*inch],
        [("ROWBACKGROUNDS", (1,0), (1,-1),
          [LIGHT_GREEN, LIGHT_TEAL, LIGHT_AMBER, LIGHT_RED]),
         ("TOPPADDING",    (0,0), (-1,-1), 7),
         ("BOTTOMPADDING", (0,0), (-1,-1), 7),
         ("LEFTPADDING",   (0,0), (-1,-1), 8),
         ("RIGHTPADDING",  (0,0), (-1,-1), 8),
         ("LINEBELOW",     (0,0), (-1,-2), 0.4, MID_GREY),
         ("VALIGN",        (0,0), (-1,-1), "MIDDLE")]
    ))
    story.append(PageBreak())

# ── Scorecard page ────────────────────────────────────────────────────────────
def build_scorecard(story):
    story.append(Paragraph("Section 1 — Fill Rate Scorecard", STYLES["h1"]))
    story.append(hr(NAVY, 1))
    story.append(Paragraph(
        "Fill rate for every scored field across all 50 prospects in the hybrid pipeline test run.",
        STYLES["body"]
    ))
    story.append(sp(8))

    # Column widths: field | description | fill rate | rating
    cw = [1.9*inch, 3.6*inch, 0.7*inch, 0.8*inch]

    header = [
        Paragraph("Field",       STYLES["th"]),
        Paragraph("Description", STYLES["th"]),
        Paragraph("Fill Rate",   STYLES["th"]),
        Paragraph("Rating",      STYLES["th"]),
    ]
    rows  = [header]
    cmds  = [
        ("BACKGROUND",    (0,0), (-1,0), NAVY),
        ("ALIGN",         (2,0), (-1,-1), "CENTER"),
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
            "", "", ""
        ])
        cmds += [
            ("BACKGROUND", (0, row_i), (-1, row_i), cat_color),
            ("SPAN",       (0, row_i), (1,  row_i)),
        ]
        row_i += 1

        for field, desc in field_list:
            ap  = fill_pct(results, field)
            lbl, color, bg = classify(ap)

            rows.append([
                Paragraph(field, ParagraphStyle("_tf", fontName="Helvetica-BoldOblique",
                                                 fontSize=8.5, textColor=NAVY, leading=12)),
                Paragraph(desc,  ParagraphStyle("_td", fontName="Helvetica",
                                                 fontSize=8, textColor=DARK_GREY, leading=11)),
                Paragraph(f"{ap:.0f}%", ParagraphStyle("_tp", fontName="Helvetica-Bold",
                                                         fontSize=10, textColor=color, alignment=TA_CENTER)),
                Paragraph(lbl,          ParagraphStyle("_lb", fontName="Helvetica-Bold",
                                                         fontSize=7.5, textColor=white, alignment=TA_CENTER)),
            ])
            cmds += [
                ("BACKGROUND", (0, row_i), (-1, row_i), bg),
                ("BACKGROUND", (3, row_i), (3,  row_i), color),
            ]
            row_i += 1

    story.append(tbl(rows, cw, cmds))
    story.append(PageBreak())

# ── Per-category deep dive pages ──────────────────────────────────────────────
def build_category_pages(story):
    for cat, field_list in FIELDS.items():
        cat_color, cat_bg = CATEGORY_COLORS[cat]

        # Category header
        story.append(tbl(
            [[Paragraph(cat, STYLES["cat_hdr"])]],
            [W],
            [("BACKGROUND",    (0,0), (-1,-1), cat_color),
             ("TOPPADDING",    (0,0), (-1,-1), 10),
             ("BOTTOMPADDING", (0,0), (-1,-1), 10),
             ("LEFTPADDING",   (0,0), (-1,-1), 10)]
        ))
        story.append(sp(6))
        story.append(hr(cat_color, 0.5, 10))

        for field, desc in field_list:
            ap  = fill_pct(results, field)
            lbl, color, bg = classify(ap)

            left_data = [
                [Paragraph(
                    f"{field}  "
                    f"<font name='Helvetica-Bold' size='7' color='#{color.hexval()[2:]}'>[{lbl}]</font>",
                    STYLES["field_name"]
                )],
                [Paragraph(desc, STYLES["field_desc"])],
            ]
            right_data = [
                [Paragraph(f"{ap:.0f}%",
                           ParagraphStyle("_pb", fontName="Helvetica-Bold", fontSize=18,
                                          textColor=color, alignment=TA_CENTER, leading=20))],
                [Paragraph("fill rate", STYLES["pct_lbl"])],
            ]

            left_t  = tbl(left_data,  [5.2*inch], [
                ("BACKGROUND",    (0,0), (-1,-1), bg),
                ("TOPPADDING",    (0,0), (-1,-1), 8),
                ("BOTTOMPADDING", (0,0), (-1,-1), 8),
                ("LEFTPADDING",   (0,0), (-1,-1), 12),
                ("RIGHTPADDING",  (0,0), (-1,-1), 8),
                ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ])
            right_t = tbl(right_data, [1.8*inch], [
                ("BACKGROUND",    (0,0), (-1,-1), bg),
                ("TOPPADDING",    (0,0), (-1,-1), 6),
                ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                ("LEFTPADDING",   (0,0), (-1,-1), 4),
                ("RIGHTPADDING",  (0,0), (-1,-1), 8),
                ("ALIGN",         (0,0), (-1,-1), "CENTER"),
                ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ])

            row_t = tbl(
                [[left_t, right_t]],
                [5.2*inch, 1.8*inch],
                [("TOPPADDING",    (0,0), (-1,-1), 0),
                 ("BOTTOMPADDING", (0,0), (-1,-1), 0),
                 ("LEFTPADDING",   (0,0), (-1,-1), 0),
                 ("RIGHTPADDING",  (0,0), (-1,-1), 0),
                 ("LINEBELOW",     (0,0), (-1,-1), 0.5, cat_color),
                 ("VALIGN",        (0,0), (-1,-1), "TOP")]
            )
            story.append(row_t)
            story.append(sp(6))

        story.append(PageBreak())

# ── Insights & recommendations page ──────────────────────────────────────────
def build_insights(story):
    story.append(Paragraph("Section — Key Findings & Recommendations", STYLES["h1"]))
    story.append(hr(NAVY, 1))
    story.append(sp(4))

    insights = [
        (GREEN,  LIGHT_GREEN,  "STRENGTH — Stage Fit Classification (98%)",
         "The workflow can almost always categorise a company's type and stage. sf_stage_type "
         "hits a 98% fill rate, meaning the pipeline reliably determines whether a prospect is "
         "pharma, biotech, CRO, or other. This dimension anchors the scoring model and can be "
         "weighted with confidence."),

        (TEAL,   LIGHT_TEAL,   "STRENGTH — Small Molecule Coverage Doubled via Enrichment",
         "Pre-enrichment data from ChEMBL, OpenAlex, and ClinicalTrials.gov is now injected before "
         "any LLM call. sm_active_med_chem reached 45% (+25pp vs April 1 baseline) and sm_hit_to_lead "
         "43% (+25pp). For the 105 Stage B escalated companies these jump further — 70% and 61% "
         "respectively — confirming the specialist agents extract significantly more signal when given "
         "enriched context."),

        (TEAL,   LIGHT_TEAL,   "STRENGTH — Contact Quality Improved via EDGAR + OpenAlex Names",
         "SEC EDGAR Form 4 executive names and OpenAlex researcher names are now injected as confirmed "
         "data. cq_highest_role reached 44% (+27pp) and cq_team_size_estimate 30% (+17pp). When the "
         "agent has real names to anchor on, contact quality scoring becomes evidence-based rather than "
         "inferred."),

        (AMBER,  LIGHT_AMBER,  "WEAKNESS — Strategic Intelligence Partially Covered",
         "si_recent_publications (36%), si_patent_filings (29%), and si_pharma_partnerships (30%) now "
         "have meaningful coverage via OpenAlex and EPO enrichment. However si_recent_funding (18%) "
         "and si_funding_amount (22%) remain sparse — EDGAR only covers public companies and Reg D "
         "rounds. Private company funding still requires a Crunchbase integration to close."),

        (RED,    LIGHT_RED,    "BLIND SPOT — Chemistry Hires Remain Near Zero",
         "si_recent_chem_hires is at 3% — effectively unchanged from the April 1 baseline. "
         "No enrichment source covers individual hiring activity. Perplexity web search rarely "
         "surfaces individual hires unless they generated a press release. This is a data source "
         "gap, not a prompt problem. Fix requires a LinkedIn or hiring data integration."),
    ]

    for color, bg, title, body_text in insights:
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
        story.append(sp(8))

    # Weight recalibration table
    story.append(sp(8))
    story.append(Paragraph("Suggested Scoring Weight Recalibration", STYLES["h2"]))
    story.append(Paragraph(
        "Based on fill rate coverage, the following adjustments reduce model bias "
        "from low-coverage dimensions inflating or suppressing scores:",
        STYLES["body"]
    ))
    story.append(sp(6))

    wcw = [1.6*inch, 1.1*inch, 1.2*inch, 3.1*inch]
    wrows = [
        [Paragraph("Subcategory",         STYLES["th"]),
         Paragraph("Current Weight",      STYLES["th"]),
         Paragraph("Avg Fill Rate",       STYLES["th"]),
         Paragraph("Suggested Adjustment",STYLES["th"])],
        [Paragraph("Stage Fit (sf_*)",    STYLES["td"]),
         Paragraph("30 pts",              STYLES["td"]),
         Paragraph("72%",  ParagraphStyle("_g", fontName="Helvetica-Bold", fontSize=8.5, textColor=GREEN)),
         Paragraph("Maintain — strong and reliable signal", STYLES["td"])],
        [Paragraph("Small Molecule (sm_*)", STYLES["td"]),
         Paragraph("30 pts",              STYLES["td"]),
         Paragraph("15%  (70% in Stg B)", ParagraphStyle("_a", fontName="Helvetica-Bold", fontSize=8.5, textColor=AMBER)),
         Paragraph("Maintain for Stage B; consider reducing SM weight in Stage A until escalation confirms activity", STYLES["td"])],
        [Paragraph("Contact Quality (cq_*)", STYLES["td"]),
         Paragraph("25 pts",              STYLES["td"]),
         Paragraph("21%",  ParagraphStyle("_a2", fontName="Helvetica-Bold", fontSize=8.5, textColor=AMBER)),
         Paragraph("Reduce to 15 pts, or require a minimum evidence threshold before assigning full points", STYLES["td"])],
        [Paragraph("Strategic Intel (si_*)", STYLES["td"]),
         Paragraph("15 pts",              STYLES["td"]),
         Paragraph("12%",  ParagraphStyle("_r", fontName="Helvetica-Bold", fontSize=8.5, textColor=RED)),
         Paragraph("Reduce to 5 pts; or assign SI points only when 2+ signals are confirmed", STYLES["td"])],
    ]
    story.append(tbl(wrows, wcw, [
        ("BACKGROUND",    (0,0), (-1,0), NAVY),
        ("ROWBACKGROUNDS",(0,1), (-1,-1), [LIGHT_GREY, white]),
        ("LINEBELOW",     (0,0), (-1,-2), 0.5, MID_GREY),
        ("GRID",          (0,0), (-1,-1), 0.3, MID_GREY),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
    ]))

# ── Build PDF ─────────────────────────────────────────────────────────────────
def build():
    output = "results/emolecules_knowledge_coverage_apr22.pdf"
    doc = SimpleDocTemplate(
        output,
        pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.65*inch,  bottomMargin=0.65*inch,
    )
    story = []
    build_cover(story)
    build_scorecard(story)
    build_category_pages(story)
    build_insights(story)
    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(f"Report written to {output}")

if __name__ == "__main__":
    build()
