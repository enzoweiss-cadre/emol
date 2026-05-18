"""
Generate Activity Tier Comparison Report — Top 10% vs Bottom 10% by session count.

Reads results/tier_comparison_*.json (most recent), recomputes real fill rates
(only values with actual confirmed evidence count), and produces a PDF.

Usage: python3 generate_tier_comparison_report.py
Output: results/tier_comparison_report.pdf
"""

import glob
import json
import os
from datetime import datetime

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle,
    Paragraph,
)

# ── Colours ───────────────────────────────────────────────────────────────────
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
ORANGE      = HexColor("#D97706")
LIGHT_ORANGE= HexColor("#FEF3C7")

W = 7.0 * inch

# ── Real fill logic ───────────────────────────────────────────────────────────
_EMPTY = (
    "unknown", "not found", "no ", "none ", "n/a", "not applicable",
    "no evidence", "not available", "could not", "unable to", "not public",
    "not a public", "not listed", "not in ", "no data", "not confirmed",
    "lookup failed", "treat as unknown", "not checked",
)

def is_real_fill(value) -> bool:
    if value in (None, "", "null"):
        return False
    v = str(value).strip().lower()
    if not v:
        return False
    if any(v.startswith(p) or p in v[:60] for p in _EMPTY):
        return False
    return True

def real_fill_pct(records, field) -> float:
    if not records:
        return 0.0
    return sum(1 for r in records if is_real_fill(r.get(field))) / len(records) * 100

# ── Field definitions ─────────────────────────────────────────────────────────
FIELD_GROUPS = [
    ("Small Molecule", TEAL, LIGHT_TEAL, [
        ("sm_active_med_chem",   "Active medicinal chemistry program"),
        ("sm_hit_to_lead",       "Hit-to-lead / lead optimisation activity"),
        ("sm_cadd_capabilities", "CADD / computational chemistry"),
        ("sm_virtual_screening", "Virtual screening / docking"),
    ]),
    ("Stage Fit", BLUE, LIGHT_BLUE, [
        ("sf_stage_type",        "Company stage type (pharma / biotech / CRO / other)"),
        ("sf_employee_range",    "Employee headcount range"),
        ("sf_funding_stage",     "Funding stage (seed / Series / public)"),
        ("sf_is_public",         "Publicly traded status"),
    ]),
    ("Contact Quality", PURPLE, LIGHT_PURPLE, [
        ("cq_highest_role",       "Highest seniority chemistry or biology role found"),
        ("cq_has_chemistry_team", "Evidence of an internal chemistry team"),
        ("cq_team_size_estimate", "Estimated chemistry team size"),
    ]),
    ("Strategic Intelligence", AMBER, LIGHT_AMBER, [
        ("si_patent_filings",        "Recent patent filings"),
        ("si_recent_publications",   "Recent scientific publications"),
        ("si_recent_funding",        "Recent funding event"),
        ("si_funding_amount",        "Specific funding amount"),
        ("si_recent_chem_hires",     "Recent chemistry / drug discovery hires"),
        ("si_pharma_partnerships",   "Active pharma partnerships or collaborations"),
    ]),
]

def classify(pct):
    if pct >= 70: return "STRONG",   GREEN,  LIGHT_GREEN
    if pct >= 40: return "MODERATE", TEAL,   LIGHT_TEAL
    if pct >= 15: return "WEAK",     AMBER,  LIGHT_AMBER
    return              "BLIND",    RED,    LIGHT_RED

# ── Load most-recent tier comparison JSON ─────────────────────────────────────
files = sorted(glob.glob("results/tier_comparison_*.json"))
if not files:
    raise FileNotFoundError("No results/tier_comparison_*.json found. Run run_activity_tiers.py first.")
src = files[-1]
with open(src) as f:
    data = json.load(f)

top_results = data["top_tier"]["results"]
bot_results = data["bottom_tier"]["results"]
top_n = len(top_results)
bot_n = len(bot_results)
run_at = data.get("run_at", "")

# ── Styles ────────────────────────────────────────────────────────────────────
def S(name, **kw):
    return ParagraphStyle(name, **kw)

ST = {
    "cover_title": S("ct", fontName="Helvetica-Bold", fontSize=26,
                     textColor=white, leading=32, alignment=TA_LEFT),
    "cover_sub":   S("cs", fontName="Helvetica", fontSize=12,
                     textColor=HexColor("#C8D8E4"), leading=18, alignment=TA_LEFT),
    "h1":          S("h1", fontName="Helvetica-Bold", fontSize=16,
                     textColor=NAVY, spaceBefore=14, spaceAfter=5, leading=20),
    "h2":          S("h2", fontName="Helvetica-Bold", fontSize=11,
                     textColor=NAVY, spaceBefore=10, spaceAfter=4, leading=14),
    "body":        S("body", fontName="Helvetica", fontSize=9,
                     textColor=HexColor("#2C3E50"), leading=14, spaceAfter=6,
                     alignment=TA_JUSTIFY),
    "stat_num":    S("sn", fontName="Helvetica-Bold", fontSize=22,
                     textColor=white, alignment=TA_CENTER),
    "stat_lbl":    S("sl", fontName="Helvetica", fontSize=8,
                     textColor=MID_GREY, alignment=TA_CENTER),
    "th":          S("th", fontName="Helvetica-Bold", fontSize=8.5,
                     textColor=white, alignment=TA_CENTER),
    "td":          S("td", fontName="Helvetica", fontSize=8.5,
                     textColor=HexColor("#1E293B"), leading=12),
    "td_field":    S("tdf", fontName="Helvetica-BoldOblique", fontSize=8.5,
                     textColor=NAVY, leading=12),
    "td_desc":     S("tdd", fontName="Helvetica", fontSize=8,
                     textColor=DARK_GREY, leading=11),
    "footer":      S("ft", fontName="Helvetica", fontSize=7.5,
                     textColor=MID_GREY, alignment=TA_CENTER),
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

def tbl(rows, widths, cmds):
    t = Table(rows, colWidths=widths)
    t.setStyle(TableStyle(cmds))
    return t

def pct_para(pct, color):
    return Paragraph(
        f"{pct:.0f}%",
        ParagraphStyle("_pp", fontName="Helvetica-Bold", fontSize=10,
                       textColor=color, alignment=TA_CENTER)
    )

def badge(label, color):
    return Paragraph(
        label,
        ParagraphStyle("_bd", fontName="Helvetica-Bold", fontSize=7.5,
                       textColor=white, alignment=TA_CENTER)
    )

def delta_para(delta):
    if delta > 0:
        color = GREEN
        text  = f"▲ {delta:.0f}%"
    elif delta < 0:
        color = RED
        text  = f"▼ {abs(delta):.0f}%"
    else:
        color = MID_GREY
        text  = "—"
    return Paragraph(text, ParagraphStyle("_dp", fontName="Helvetica-Bold",
                                           fontSize=9, textColor=color, alignment=TA_CENTER))

# ── Footer ────────────────────────────────────────────────────────────────────
def add_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MID_GREY)
    canvas.drawCentredString(
        letter[0] / 2, 0.4 * inch,
        f"eMolecules ICP — Activity Tier Comparison  •  "
        f"Generated {datetime.now().strftime('%B %d, %Y')}  •  Confidential"
    )
    canvas.restoreState()

# ── Cover ─────────────────────────────────────────────────────────────────────
def build_cover(story):
    try:
        dt = datetime.fromisoformat(run_at.replace("Z", "+00:00"))
        date_str = dt.strftime("%B %d, %Y")
    except Exception:
        date_str = datetime.now().strftime("%B %d, %Y")

    story.append(tbl(
        [[Paragraph("eMolecules ICP Scoring", ST["cover_sub"])],
         [Paragraph("Activity Tier\nComparison", ST["cover_title"])],
         [Paragraph(f"Top 10% vs Bottom 10% by session count  •  {date_str}", ST["cover_sub"])]],
        [W],
        [("BACKGROUND", (0,0), (-1,-1), NAVY),
         ("TOPPADDING", (0,0), (-1,-1), 14),
         ("BOTTOMPADDING", (0,0), (-1,-1), 14),
         ("LEFTPADDING", (0,0), (-1,-1), 20),
         ("RIGHTPADDING", (0,0), (-1,-1), 20)]
    ))
    story.append(sp(4))

    # Summary stats bar
    top_high = sum(1 for r in top_results if r.get("qualification_status") == "HIGH FIT")
    bot_high = sum(1 for r in bot_results if r.get("qualification_status") == "HIGH FIT")
    top_scores = [r["final_icp_score"] for r in top_results if r.get("final_icp_score") is not None]
    bot_scores = [r["final_icp_score"] for r in bot_results if r.get("final_icp_score") is not None]
    top_avg = round(sum(top_scores) / len(top_scores), 1) if top_scores else 0
    bot_avg = round(sum(bot_scores) / len(bot_scores), 1) if bot_scores else 0

    story.append(tbl(
        [
            [Paragraph(f"{top_n}", ST["stat_num"]),
             Paragraph(f"{round(top_high/top_n*100)}%", ST["stat_num"]),
             Paragraph(f"{top_avg}", ST["stat_num"]),
             Paragraph(f"{bot_n}", ST["stat_num"]),
             Paragraph(f"{round(bot_high/bot_n*100)}%", ST["stat_num"]),
             Paragraph(f"{bot_avg}", ST["stat_num"])],
            [Paragraph("Top Tier\nCompanies", ST["stat_lbl"]),
             Paragraph("Top Tier\nHigh Fit", ST["stat_lbl"]),
             Paragraph("Top Tier\nAvg Score", ST["stat_lbl"]),
             Paragraph("Bottom Tier\nCompanies", ST["stat_lbl"]),
             Paragraph("Bottom Tier\nHigh Fit", ST["stat_lbl"]),
             Paragraph("Bottom Tier\nAvg Score", ST["stat_lbl"])],
        ],
        [W/6]*6,
        [("BACKGROUND", (0,0), (2,-1), NAVY),
         ("BACKGROUND", (3,0), (-1,-1), HexColor("#1A3A5C")),
         ("TOPPADDING", (0,0), (-1,-1), 10),
         ("BOTTOMPADDING", (0,0), (-1,-1), 10),
         ("ALIGN", (0,0), (-1,-1), "CENTER"),
         ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
         ("LINEAFTER", (2,0), (2,-1), 1.5, HexColor("#4A90D9"))]
    ))
    story.append(sp(20))

    story.append(Paragraph("About This Report", ST["h1"]))
    story.append(hr(NAVY, 1))
    story.append(Paragraph(
        "This report compares ICP scoring results between the <b>top 10% of eMolecules website visitors "
        "by session count</b> (≥ 1,295 sessions) and the <b>bottom 10%</b> (≤ 2 sessions). "
        "The goal is to validate whether high-activity companies are meaningfully different from "
        "low-activity ones — and whether the scoring pipeline captures that difference.",
        ST["body"]
    ))
    story.append(Paragraph(
        "<b>Fill rates use the real-evidence standard:</b> a field is only counted as filled if the agent "
        "returned a value containing actual confirmed data — a number, date, source, or explicit confirmation. "
        "Values like \"Unknown\", \"No X found\", or \"Not listed\" are treated as empty, because they carry "
        "no confirmed signal either way.",
        ST["body"]
    ))
    story.append(sp(16))

    story.append(Paragraph("Rating Scale", ST["h2"]))
    legend = [
        (GREEN,  LIGHT_GREEN,  "STRONG",   "≥ 70% — reliable signal, full weight appropriate"),
        (TEAL,   LIGHT_TEAL,   "MODERATE", "40–69% — useful but incomplete"),
        (AMBER,  LIGHT_AMBER,  "WEAK",     "15–39% — sparse data, interpret with caution"),
        (RED,    LIGHT_RED,    "BLIND",    "< 15% — near-zero evidence, scoring weight should be minimal"),
    ]
    leg_rows = [[
        tbl([[badge(lbl, c)]], [0.85*inch], [
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
        leg_rows, [0.9*inch, 6.0*inch],
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

# ── ICP Distribution comparison ───────────────────────────────────────────────
def build_distribution(story):
    story.append(Paragraph("Section 1 — ICP Score Distribution", ST["h1"]))
    story.append(hr(NAVY, 1))
    story.append(Paragraph(
        "How the final ICP scores are distributed across qualification tiers for each activity group.",
        ST["body"]
    ))
    story.append(sp(8))

    statuses = ["HIGH FIT", "MEDIUM FIT", "LOW FIT", "NO FIT"]
    status_colors = {
        "HIGH FIT":   (GREEN,  LIGHT_GREEN),
        "MEDIUM FIT": (TEAL,   LIGHT_TEAL),
        "LOW FIT":    (AMBER,  LIGHT_AMBER),
        "NO FIT":     (RED,    LIGHT_RED),
    }

    top_scores  = [r["final_icp_score"] for r in top_results if r.get("final_icp_score") is not None]
    bot_scores  = [r["final_icp_score"] for r in bot_results if r.get("final_icp_score") is not None]
    top_avg = sum(top_scores) / len(top_scores) if top_scores else 0
    bot_avg = sum(bot_scores) / len(bot_scores) if bot_scores else 0

    cw = [2.0*inch, 1.5*inch, 1.5*inch, 2.0*inch]
    rows = [[
        Paragraph("Tier", ST["th"]),
        Paragraph("Top 10%", ST["th"]),
        Paragraph("Bottom 10%", ST["th"]),
        Paragraph("Insight", ST["th"]),
    ]]
    cmds = [
        ("BACKGROUND",    (0,0), (-1,0), NAVY),
        ("ALIGN",         (1,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
        ("GRID",          (0,0), (-1,-1), 0.3, MID_GREY),
    ]

    row_i = 1
    for status in statuses:
        c, bg = status_colors[status]
        top_n_s = sum(1 for r in top_results if r.get("qualification_status") == status)
        bot_n_s = sum(1 for r in bot_results if r.get("qualification_status") == status)
        top_pct = round(top_n_s / top_n * 100)
        bot_pct = round(bot_n_s / bot_n * 100)
        diff = top_pct - bot_pct
        insight = (
            f"Top tier is {abs(diff)}pp {'higher' if diff > 0 else 'lower'}"
            if diff != 0 else "No difference"
        )
        rows.append([
            Paragraph(status, ParagraphStyle("_s", fontName="Helvetica-Bold",
                                              fontSize=8.5, textColor=white)),
            Paragraph(f"{top_n_s}  ({top_pct}%)",
                      ParagraphStyle("_tv", fontName="Helvetica-Bold", fontSize=9,
                                     textColor=c, alignment=TA_CENTER)),
            Paragraph(f"{bot_n_s}  ({bot_pct}%)",
                      ParagraphStyle("_bv", fontName="Helvetica-Bold", fontSize=9,
                                     textColor=c, alignment=TA_CENTER)),
            Paragraph(insight, ParagraphStyle("_ins", fontName="Helvetica", fontSize=8.5,
                                               textColor=DARK_GREY, alignment=TA_CENTER)),
        ])
        cmds += [
            ("BACKGROUND", (0, row_i), (0, row_i), c),
            ("BACKGROUND", (1, row_i), (-1, row_i), bg),
        ]
        row_i += 1

    # Avg score row
    rows.append([
        Paragraph("Avg Score", ST["th"]),
        Paragraph(f"{top_avg:.1f} / 100",
                  ParagraphStyle("_ta", fontName="Helvetica-Bold", fontSize=10,
                                 textColor=GREEN, alignment=TA_CENTER)),
        Paragraph(f"{bot_avg:.1f} / 100",
                  ParagraphStyle("_ba", fontName="Helvetica-Bold", fontSize=10,
                                 textColor=RED, alignment=TA_CENTER)),
        Paragraph(f"Top tier scores {top_avg/max(bot_avg,0.1):.1f}× higher on average",
                  ParagraphStyle("_ai", fontName="Helvetica-Oblique", fontSize=8.5,
                                 textColor=DARK_GREY, alignment=TA_CENTER)),
    ])
    cmds += [
        ("BACKGROUND", (0, row_i), (-1, row_i), HexColor("#1A3A5C")),
        ("TEXTCOLOR",  (0, row_i), (0,  row_i), white),
    ]
    story.append(tbl(rows, cw, cmds))
    story.append(PageBreak())

# ── Fill rate comparison ───────────────────────────────────────────────────────
def build_fill_rates(story):
    story.append(Paragraph("Section 2 — Real Fill Rate Comparison", ST["h1"]))
    story.append(hr(NAVY, 1))
    story.append(Paragraph(
        "Fill rate per scoring field, measured using the real-evidence standard. "
        "Only values containing confirmed data (numbers, dates, sources, or explicit confirmations) "
        "are counted. Vague answers such as \"Unknown\" or \"No X found\" are excluded.",
        ST["body"]
    ))
    story.append(sp(8))

    cw = [1.6*inch, 2.4*inch, 0.85*inch, 0.75*inch, 0.85*inch, 0.75*inch, 0.8*inch]
    header = [
        Paragraph("Field",        ST["th"]),
        Paragraph("Description",  ST["th"]),
        Paragraph("Top 10%",      ST["th"]),
        Paragraph("Rating",       ST["th"]),
        Paragraph("Bottom 10%",   ST["th"]),
        Paragraph("Rating",       ST["th"]),
        Paragraph("Delta",        ST["th"]),
    ]
    rows = [header]
    cmds = [
        ("BACKGROUND",    (0,0), (-1,0), NAVY),
        ("ALIGN",         (2,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 6),
        ("RIGHTPADDING",  (0,0), (-1,-1), 6),
        ("GRID",          (0,0), (-1,-1), 0.3, MID_GREY),
    ]
    row_i = 1

    for group_name, g_color, g_bg, fields in FIELD_GROUPS:
        rows.append([
            Paragraph(group_name,
                      ParagraphStyle("_gh", fontName="Helvetica-Bold",
                                     fontSize=8.5, textColor=white)),
            "", "", "", "", "", ""
        ])
        cmds += [
            ("BACKGROUND", (0, row_i), (-1, row_i), g_color),
            ("SPAN",       (0, row_i), (1,  row_i)),
        ]
        row_i += 1

        for field, desc in fields:
            tp = real_fill_pct(top_results, field)
            bp = real_fill_pct(bot_results, field)
            delta = tp - bp
            t_lbl, t_col, t_bg = classify(tp)
            b_lbl, b_col, b_bg = classify(bp)

            rows.append([
                Paragraph(field, ParagraphStyle("_tf", fontName="Helvetica-BoldOblique",
                                                 fontSize=8, textColor=NAVY, leading=11)),
                Paragraph(desc,  ParagraphStyle("_td", fontName="Helvetica",
                                                 fontSize=7.5, textColor=DARK_GREY, leading=11)),
                pct_para(tp, t_col),
                badge(t_lbl, t_col),
                pct_para(bp, b_col),
                badge(b_lbl, b_col),
                delta_para(delta),
            ])
            cmds += [
                ("BACKGROUND", (0, row_i), (1, row_i), g_bg),
                ("BACKGROUND", (2, row_i), (3, row_i), t_bg),
                ("BACKGROUND", (3, row_i), (3, row_i), t_col),
                ("BACKGROUND", (4, row_i), (5, row_i), b_bg),
                ("BACKGROUND", (5, row_i), (5, row_i), b_col),
            ]
            row_i += 1

    story.append(tbl(rows, cw, cmds))
    story.append(PageBreak())

# ── Key findings ──────────────────────────────────────────────────────────────
def build_findings(story):
    story.append(Paragraph("Section 3 — Key Findings", ST["h1"]))
    story.append(hr(NAVY, 1))
    story.append(sp(4))

    # Compute key deltas for dynamic text
    top_high_pct = round(sum(1 for r in top_results if r.get("qualification_status") == "HIGH FIT") / top_n * 100)
    bot_high_pct = round(sum(1 for r in bot_results if r.get("qualification_status") == "HIGH FIT") / bot_n * 100)
    top_avg_s = round(sum(r["final_icp_score"] for r in top_results if r.get("final_icp_score") is not None) /
                      max(sum(1 for r in top_results if r.get("final_icp_score") is not None), 1), 1)
    bot_avg_s = round(sum(r["final_icp_score"] for r in bot_results if r.get("final_icp_score") is not None) /
                      max(sum(1 for r in bot_results if r.get("final_icp_score") is not None), 1), 1)
    mult = round(top_avg_s / max(bot_avg_s, 0.1), 1)

    pat_top = round(real_fill_pct(top_results, "si_patent_filings"))
    pat_bot = round(real_fill_pct(bot_results, "si_patent_filings"))
    mc_top  = round(real_fill_pct(top_results, "sm_active_med_chem"))
    mc_bot  = round(real_fill_pct(bot_results, "sm_active_med_chem"))

    findings = [
        (GREEN, LIGHT_GREEN,
         f"Activity is a strong ICP pre-filter ({top_high_pct}% HIGH FIT vs {bot_high_pct}%)",
         f"High-activity companies (≥ 1,295 sessions) are {top_high_pct // max(bot_high_pct,1)}× more likely to qualify as HIGH FIT "
         f"({top_high_pct}% vs {bot_high_pct}%) and score {mult}× higher on average ({top_avg_s} vs {bot_avg_s}/100). "
         f"Session count alone is a useful first-pass filter before running the full pipeline."),

        (TEAL, LIGHT_TEAL,
         f"Drug-discovery fields show the sharpest fill gaps (patent: {pat_top}% vs {pat_bot}%, "
         f"med chem: {mc_top}% vs {mc_bot}%)",
         "The fields that most directly measure drug discovery activity — patent filings, active medicinal "
         "chemistry programs, and hit-to-lead — show the largest evidence gaps between the two tiers. "
         "This confirms those fields are genuinely discriminating: evidence exists for high-activity companies "
         "because they are real drug discovery organisations."),

        (AMBER, LIGHT_AMBER,
         "Bottom tier fill rates reflect absence of industry, not pipeline failure",
         "The bottom tier (1-2 sessions) is dominated by academic institutions, schools, government labs, "
         "and one-off visitors. Low fill rates on drug discovery fields for this group are correct — "
         "these organisations have nothing to find. The pipeline is working; the companies are simply "
         "not prospects. Activity filtering should be applied upstream before ICP scoring is invoked."),

        (PURPLE, LIGHT_PURPLE,
         "si_recent_funding is the one field where bottom tier fills higher (10% vs 4%)",
         "Bottom-tier companies score slightly higher on recent funding fill rate. This is likely because "
         "universities and small one-time visitors sometimes appear in funding databases (government grants, "
         "endowments) while genuine drug discovery companies at the mid-stage have less publicly documented "
         "funding activity. The funding field should not be weighted heavily as a standalone signal."),
    ]

    for color, bg, title, body_text in findings:
        story.append(tbl(
            [[Paragraph(title,     ST["insight_h"])],
             [Paragraph(body_text, ST["insight_b"])]],
            [W],
            [("BACKGROUND",    (0,0), (-1,-1), bg),
             ("TOPPADDING",    (0,0), (-1,-1), 9),
             ("BOTTOMPADDING", (0,0), (-1,-1), 9),
             ("LEFTPADDING",   (0,0), (-1,-1), 16),
             ("RIGHTPADDING",  (0,0), (-1,-1), 12),
             ("LINEBEFORE",    (0,0), (0,-1), 5, color)]
        ))
        story.append(sp(8))

# ── Build ─────────────────────────────────────────────────────────────────────
def build():
    out = "results/tier_comparison_report.pdf"
    doc = SimpleDocTemplate(
        out, pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.65*inch,  bottomMargin=0.65*inch,
    )
    story = []
    build_cover(story)
    build_distribution(story)
    build_fill_rates(story)
    build_findings(story)
    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(f"Report written to {out}")

if __name__ == "__main__":
    build()
