"""
Generate eMolecules HIGH FIT Companies Report PDF

One page per company. For each: overall score, visual score bar,
and a full breakdown of every subcategory with the evidence behind it.

Usage: python3 generate_high_fit_report.py
Output: results/emolecules_high_fit_report.pdf
"""

import json
import os
import requests
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics import renderPDF

# ── Load .env ────────────────────────────────────────────────────────────────

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
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# ── Colour palette ────────────────────────────────────────────────────────────

NAVY        = HexColor("#0F172A")   # slate-900 — cover bg
TEAL        = HexColor("#0F766E")   # teal-700  — Small Molecule
LIGHT_TEAL  = HexColor("#F0FDFA")   # teal-50
AMBER       = HexColor("#B45309")   # amber-700 — Strategic Indicators
LIGHT_AMBER = HexColor("#FFFBEB")   # amber-50
GREEN       = HexColor("#15803D")   # green-700 — HIGH FIT badge
LIGHT_GREEN = HexColor("#F0FDF4")   # green-50
PURPLE      = HexColor("#6D28D9")   # violet-700 — Contact Quality
LIGHT_PURPLE= HexColor("#F5F3FF")   # violet-50
BLUE        = HexColor("#1D4ED8")   # blue-700   — Stage Fit
LIGHT_BLUE  = HexColor("#EFF6FF")   # blue-50
ORANGE      = HexColor("#C2410C")   # orange-700 — MEDIUM FIT badge
LIGHT_GREY  = HexColor("#F8FAFC")   # slate-50
MID_GREY    = HexColor("#CBD5E1")   # slate-300
DARK_GREY   = HexColor("#64748B")   # slate-500
RED         = HexColor("#DC2626")   # red-600

CATEGORY_COLORS = {
    "small_molecule": (TEAL,   LIGHT_TEAL),
    "stage_fit":      (BLUE,   LIGHT_BLUE),
    "contact":        (PURPLE, LIGHT_PURPLE),
    "strategic":      (AMBER,  LIGHT_AMBER),
}

# ── Fetch data ────────────────────────────────────────────────────────────────

def fetch_high_fit_companies():
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }
    # Fetch HIGH FIT and MEDIUM FIT, sorted by score descending
    all_companies = []
    for status in ["HIGH FIT", "MEDIUM FIT"]:
        url = (
            f"{SUPABASE_URL}/rest/v1/icp_hybrid_results"
            f"?qualification_status=eq.{requests.utils.quote(status)}"
            f"&order=final_icp_score.desc"
            f"&limit=500"
        )
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        all_companies.extend(resp.json())
    # Sort: HIGH FIT first, then MEDIUM FIT, each group by score desc
    order = {"HIGH FIT": 0, "MEDIUM FIT": 1}
    all_companies.sort(key=lambda c: (order.get(c.get("qualification_status"), 9), -(c.get("final_icp_score") or 0)))
    return all_companies

# ── Score bar drawing ─────────────────────────────────────────────────────────

def score_bar(sm, sf, cq, si, width=5.5*inch, height=0.28*inch):
    """Stacked horizontal bar showing contribution of each sub-score."""
    total = 100
    d = Drawing(width, height + 0.18*inch)

    segments = [
        (sm, 30, TEAL,   "SM"),
        (sf, 30, BLUE,   "SF"),
        (cq, 25, PURPLE, "CQ"),
        (si, 15, AMBER,  "SI"),
    ]

    x = 0
    for score, max_score, color, label in segments:
        score = score or 0
        # background (max possible)
        bg_w = (max_score / total) * width
        d.add(Rect(x, 0.18*inch, bg_w, height, fillColor=MID_GREY, strokeColor=None))
        # filled portion
        fill_w = (score / total) * width
        if fill_w > 0:
            d.add(Rect(x, 0.18*inch, fill_w, height, fillColor=color, strokeColor=None))
        x += bg_w

    # Labels below bar
    x = 0
    for score, max_score, color, label in segments:
        score = score or 0
        bg_w = (max_score / total) * width
        d.add(String(x + bg_w/2, 2, f"{label}: {score}/{max_score}",
                     fontSize=6.5, fillColor=DARK_GREY, textAnchor="middle"))
        x += bg_w

    return d

# ── Styles ────────────────────────────────────────────────────────────────────

def make_styles():
    base = getSampleStyleSheet()

    return {
        "company_name": ParagraphStyle(
            "company_name", fontSize=20, fontName="Helvetica-Bold",
            textColor=NAVY, spaceAfter=0
        ),
        "score_badge": ParagraphStyle(
            "score_badge", fontSize=13, fontName="Helvetica-Bold",
            textColor=TEAL
        ),
        "meta": ParagraphStyle(
            "meta", fontSize=8.5, fontName="Helvetica",
            textColor=DARK_GREY, spaceAfter=2
        ),
        "section_header": ParagraphStyle(
            "section_header", fontSize=8, fontName="Helvetica-Bold",
            textColor=white, spaceAfter=0, spaceBefore=0,
            leftIndent=6
        ),
        "field_label": ParagraphStyle(
            "field_label", fontSize=8, fontName="Helvetica-Bold",
            textColor=DARK_GREY, spaceAfter=1
        ),
        "field_value": ParagraphStyle(
            "field_value", fontSize=8.5, fontName="Helvetica",
            textColor=black, spaceAfter=4, leading=12
        ),
        "bullet": ParagraphStyle(
            "bullet", fontSize=8, fontName="Helvetica",
            textColor=black, leftIndent=10, spaceAfter=2,
            leading=11
        ),
        "null_value": ParagraphStyle(
            "null_value", fontSize=8.5, fontName="Helvetica-Oblique",
            textColor=MID_GREY, spaceAfter=4, leading=12
        ),
        "reasoning": ParagraphStyle(
            "reasoning", fontSize=8.5, fontName="Helvetica-Oblique",
            textColor=DARK_GREY, spaceAfter=6, leading=13
        ),
        "cover_title": ParagraphStyle(
            "cover_title", fontSize=22, fontName="Helvetica-Bold",
            textColor=white, alignment=TA_CENTER, spaceAfter=0, leading=28
        ),
        "cover_sub": ParagraphStyle(
            "cover_sub", fontSize=13, fontName="Helvetica",
            textColor=HexColor("#94A3B8"), alignment=TA_CENTER, spaceAfter=0, leading=18
        ),
        "cover_stat_label": ParagraphStyle(
            "cover_stat_label", fontSize=10, fontName="Helvetica",
            textColor=MID_GREY, alignment=TA_CENTER
        ),
        "cover_stat_value": ParagraphStyle(
            "cover_stat_value", fontSize=28, fontName="Helvetica-Bold",
            textColor=white, alignment=TA_CENTER
        ),
        "toc_domain": ParagraphStyle(
            "toc_domain", fontSize=9, fontName="Helvetica-Bold",
            textColor=NAVY
        ),
        "toc_meta": ParagraphStyle(
            "toc_meta", fontSize=8, fontName="Helvetica",
            textColor=DARK_GREY
        ),
    }

# ── Helper: section box ───────────────────────────────────────────────────────

HALF_W = 3.4 * inch  # width of each column in the 2×2 section grid

def section_box(title, score, max_score, color, bg_color, fields, styles, box_width=5.5*inch):
    """Returns a Table for one scoring category. Safe to embed inside a grid Table."""
    compact = box_width < 4.5 * inch
    label_w = 0.85 * inch if compact else 1.4 * inch
    value_w = box_width - label_w

    if compact:
        f_label = ParagraphStyle("_fl", parent=styles["field_label"], fontSize=7)
        f_value = ParagraphStyle("_fv", parent=styles["field_value"], fontSize=7.5, leading=10)
        f_null  = ParagraphStyle("_fn", parent=styles["null_value"],  fontSize=7.5, leading=10)
        s_hdr   = ParagraphStyle("_sh", parent=styles["section_header"], fontSize=8.5, leading=12)
    else:
        f_label, f_value, f_null, s_hdr = (
            styles["field_label"], styles["field_value"],
            styles["null_value"], styles["section_header"],
        )

    body_rows = []
    for label, value in fields:
        display = str(value) if value and value != "—" else None
        body_rows.append([
            Paragraph(label, f_label),
            Paragraph(display, f_value) if display else Paragraph("Nothing found", f_null),
        ])

    all_rows = [[Paragraph(f"{title}   {score or 0}/{max_score}", s_hdr), ""]] + body_rows
    t = Table(all_rows, colWidths=[label_w, value_w])
    t.setStyle(TableStyle([
        ("SPAN",          (0, 0), (1, 0)),
        ("BACKGROUND",    (0, 0), (1, 0), color),
        ("TOPPADDING",    (0, 0), (1, 0), 5),
        ("BOTTOMPADDING", (0, 0), (1, 0), 5),
        ("LEFTPADDING",   (0, 0), (1, 0), 7),
        ("RIGHTPADDING",  (0, 0), (1, 0), 4),
        ("BACKGROUND",    (0, 1), (-1, -1), bg_color),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 1), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
        ("LEFTPADDING",   (0, 1), (0, -1), 6),
        ("RIGHTPADDING",  (0, 1), (0, -1), 3),
        ("LEFTPADDING",   (1, 1), (1, -1), 4),
        ("RIGHTPADDING",  (1, 1), (1, -1), 4),
        ("LINEBELOW",     (0, 1), (-1, -2), 0.3, MID_GREY),
    ]))
    return t


import re

def strip_citations(text):
    """Remove Perplexity citation markers and escape XML special chars for reportlab."""
    if not text:
        return text
    cleaned = re.sub(r'(\[\d+\])+', '', str(text)).strip()
    # Escape & only where not already an entity, then escape < and >
    cleaned = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;)', '&amp;', cleaned)
    cleaned = cleaned.replace('<', '&lt;').replace('>', '&gt;')
    return cleaned

def val(v, fallback="—"):
    if not v or v == "null" or v == "none found":
        return fallback
    return strip_citations(v)


# ── Build company page ────────────────────────────────────────────────────────

def build_company_page(company, styles):
    story = []
    c = company

    domain       = c.get("domain", "")
    score        = c.get("final_icp_score", 0)
    fit_status   = c.get("qualification_status", "")
    stage        = c.get("stage_reached", "A")
    company_type = val(c.get("company_type"))
    funding      = val(c.get("sf_funding_stage"))
    headcount    = val(c.get("sf_employee_range") or c.get("estimated_headcount"))
    sessions     = c.get("source_total_sessions", 0)
    users        = c.get("source_user_count", 0)
    stage_a      = c.get("stage_a_score", "—")
    stage_b      = c.get("stage_b_score")
    escalation   = c.get("escalation_reason")
    sm = c.get("small_molecule_score", 0)
    sf = c.get("stage_fit_score", 0)
    cq = c.get("contact_quality_score", 0)
    si = c.get("strategic_score", 0)

    fit_color = GREEN if fit_status == "HIGH FIT" else ORANGE
    fit_label = "HIGH FIT" if fit_status == "HIGH FIT" else "MED FIT"

    meta_parts = []
    if company_type != "—": meta_parts.append(company_type)
    if funding != "—":      meta_parts.append(funding)
    if headcount != "—":    meta_parts.append(headcount)
    meta_parts.append(f"{users:,} users · {sessions:,} sessions")
    meta_parts.append(f"A:{stage_a}→B:{stage_b} ({escalation})" if stage == "B" else "Stage A")

    # ── 1. Navy header banner ──────────────────────────────────────────────────
    _bd = ParagraphStyle("_bd", fontSize=12, fontName="Helvetica-Bold",
                         textColor=white, leading=14, spaceAfter=0)
    _bs = ParagraphStyle("_bs", fontSize=9, fontName="Helvetica-Bold",
                         textColor=fit_color, alignment=TA_RIGHT, leading=14)
    _bm = ParagraphStyle("_bm", fontSize=7, fontName="Helvetica",
                         textColor=HexColor("#94A3B8"), leading=14, spaceAfter=0)

    banner = Table(
        [[Paragraph(domain, _bd),
          Paragraph("  ·  ".join(meta_parts), _bm),
          Paragraph(f"{score}/100  {fit_label}", _bs)]],
        colWidths=[2.0*inch, 3.6*inch, 1.4*inch],
    )
    banner.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, -1), NAVY),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",  (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",(0, 0), (-1, -1), 12),
        ("ALIGN",       (2, 0), (2, 0),  "RIGHT"),
    ]))
    story.append(banner)
    story.append(Spacer(1, 5))

    # ── 2. Score cards ─────────────────────────────────────────────────────────
    CARD_W = 7.0 * inch / 4

    _cl = ParagraphStyle("_cl", fontSize=5.5, fontName="Helvetica-Bold",
                         textColor=DARK_GREY, spaceAfter=1, leading=6)

    def _card(label, sv, mx, color):
        _ns = ParagraphStyle("_ns", fontSize=11, fontName="Helvetica-Bold",
                             textColor=color, leading=13, spaceAfter=0)
        _ds = ParagraphStyle("_ds", fontSize=6, fontName="Helvetica",
                             textColor=DARK_GREY, leading=7)
        return [Paragraph(label, _cl),
                Paragraph(str(sv or 0), _ns),
                Paragraph(f"/ {mx} pts", _ds)]

    cards = Table(
        [[_card("SMALL MOLECULE", sm, 30, TEAL),
          _card("STAGE FIT",      sf, 30, BLUE),
          _card("CONTACT QUALITY", cq, 25, PURPLE),
          _card("STRATEGIC",      si, 15, AMBER)]],
        colWidths=[CARD_W] * 4,
    )
    cards.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, -1), LIGHT_TEAL),
        ("BACKGROUND",    (1, 0), (1, -1), LIGHT_BLUE),
        ("BACKGROUND",    (2, 0), (2, -1), LIGHT_PURPLE),
        ("BACKGROUND",    (3, 0), (3, -1), LIGHT_AMBER),
        ("LINEBEFORE",    (0, 0), (0, -1), 4, TEAL),
        ("LINEBEFORE",    (1, 0), (1, -1), 4, BLUE),
        ("LINEBEFORE",    (2, 0), (2, -1), 4, PURPLE),
        ("LINEBEFORE",    (3, 0), (3, -1), 4, AMBER),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("LINEAFTER",     (0, 0), (2, -1), 0.5, MID_GREY),
    ]))
    story.append(cards)
    story.append(Spacer(1, 6))

    # ── 3. 2×2 section grid ────────────────────────────────────────────────────
    sm_box = section_box(
        "Small Molecule Discovery", sm, 30, TEAL, LIGHT_TEAL,
        [("Active Med Chem", val(c.get("sm_active_med_chem"))),
         ("CADD",            val(c.get("sm_cadd_capabilities"))),
         ("Hit-to-Lead",     val(c.get("sm_hit_to_lead"))),
         ("Virtual Screen",  val(c.get("sm_virtual_screening"))),
         ("Basis",           val(c.get("sm_scoring_basis")))],
        styles, HALF_W,
    )
    sf_box = section_box(
        "Company Stage Fit", sf, 30, BLUE, LIGHT_BLUE,
        [("Stage Type", val(c.get("sf_stage_type"))),
         ("Employees",  val(headcount)),
         ("Funding",    val(c.get("sf_funding_stage"))),
         ("Public",     val(c.get("sf_is_public"))),
         ("Basis",      val(c.get("sf_scoring_basis")))],
        styles, HALF_W,
    )
    cq_box = section_box(
        "Contact Quality", cq, 25, PURPLE, LIGHT_PURPLE,
        [("Highest Role", val(c.get("cq_highest_role"))),
         ("Chem Team",    val(c.get("cq_has_chemistry_team"))),
         ("Team Size",    val(c.get("cq_team_size_estimate"))),
         ("Basis",        val(c.get("cq_scoring_basis")))],
        styles, HALF_W,
    )
    si_box = section_box(
        "Strategic Indicators", si, 15, AMBER, LIGHT_AMBER,
        [("Recent Funding", val(c.get("si_recent_funding"))),
         ("Amount",         val(c.get("si_funding_amount"))),
         ("Chem Hires",     val(c.get("si_recent_chem_hires"))),
         ("Publications",   val(c.get("si_recent_publications"))),
         ("Partnerships",   val(c.get("si_pharma_partnerships"))),
         ("Patents",        val(c.get("si_patent_filings")))],
        styles, HALF_W,
    )

    grid = Table(
        [[sm_box, sf_box], [cq_box, si_box]],
        colWidths=[3.5*inch, 3.5*inch],
    )
    grid.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (0, -1), 10),
    ]))
    story.append(grid)

    # ── 4. Evidence + Reasoning in framed panel ────────────────────────────────
    evidence = c.get("key_evidence") or []
    if isinstance(evidence, str):
        try:    evidence = json.loads(evidence)
        except: evidence = []

    reasoning = c.get("reasoning")
    reas_text = strip_citations(reasoning) if reasoning else ""
    if len(reas_text) > 520:
        reas_text = reas_text[:520].rsplit(" ", 1)[0] + "…"

    _el = ParagraphStyle("_el", fontSize=7, fontName="Helvetica-Bold",
                         textColor=DARK_GREY, spaceAfter=5, leading=9)
    _rl = ParagraphStyle("_rl", fontSize=7, fontName="Helvetica-Bold",
                         textColor=DARK_GREY, spaceAfter=5, leading=9)

    ev_content = [Paragraph("KEY EVIDENCE", _el)]
    for e in (evidence or [])[:5]:
        if e:
            ev_content.append(Paragraph(f"• {strip_citations(e)}", styles["bullet"]))
    if not evidence:
        ev_content.append(Paragraph("Nothing found", styles["null_value"]))

    reas_content = [Paragraph("REASONING", _rl)]
    reas_content.append(
        Paragraph(f'"{reas_text}"', styles["reasoning"]) if reas_text
        else Paragraph("Nothing found", styles["null_value"])
    )

    bottom = Table(
        [[ev_content, reas_content]],
        colWidths=[3.5*inch, 3.5*inch],
    )
    bottom.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GREY),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LINEAFTER",     (0, 0), (0, 0), 0.5, MID_GREY),
    ]))
    story.append(bottom)

    story.append(PageBreak())
    return story


# ── Cover page ────────────────────────────────────────────────────────────────

def build_cover(companies, styles):
    story = []

    # Single seamless navy cover block with explicit row heights
    cover_table = Table([
        [Paragraph("eMolecules", styles["cover_title"])],
        [Paragraph("HIGH &amp; MEDIUM FIT COMPANIES", styles["cover_title"])],
        [Paragraph("ICP Hybrid Pipeline Analysis", styles["cover_sub"])],
    ], colWidths=[6.5*inch], rowHeights=[0.85*inch, 0.6*inch, 0.55*inch])
    cover_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), NAVY),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (0,0), 16),
        ("BOTTOMPADDING", (0,0), (0,0), 0),
        ("TOPPADDING", (0,1), (0,1), 0),
        ("BOTTOMPADDING", (0,1), (0,1), 0),
        ("TOPPADDING", (0,2), (0,2), 0),
        ("BOTTOMPADDING", (0,2), (0,2), 14),
        ("LINEABOVE", (0,0), (-1,-1), 0, NAVY),
        ("LINEBELOW", (0,0), (-1,-1), 0, NAVY),
        ("LINEBEFORE", (0,0), (-1,-1), 0, NAVY),
        ("LINEAFTER", (0,0), (-1,-1), 0, NAVY),
    ]))
    story.append(cover_table)

    story.append(Spacer(1, 24))

    # Stats row
    avg_score = round(sum(c.get("final_icp_score", 0) for c in companies) / max(len(companies), 1))
    high_count = sum(1 for c in companies if c.get("qualification_status") == "HIGH FIT")
    med_count = sum(1 for c in companies if c.get("qualification_status") == "MEDIUM FIT")

    # Flat 2-row stats table: labels on top, big numbers below
    stat_table = Table(
        [
            [Paragraph("HIGH FIT", styles["cover_stat_label"]),
             Paragraph("MEDIUM FIT", styles["cover_stat_label"]),
             Paragraph("AVG SCORE", styles["cover_stat_label"])],
            [Paragraph(str(high_count), styles["cover_stat_value"]),
             Paragraph(str(med_count), styles["cover_stat_value"]),
             Paragraph(str(avg_score), styles["cover_stat_value"])],
        ],
        colWidths=[2.1*inch, 2.1*inch, 2.1*inch],
        rowHeights=[0.28*inch, 0.55*inch],
    )
    stat_table.setStyle(TableStyle([
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BACKGROUND", (0,0), (-1,-1), LIGHT_GREY),
        ("TOPPADDING", (0,0), (-1,0), 10),
        ("BOTTOMPADDING", (0,0), (-1,0), 2),
        ("TOPPADDING", (0,1), (-1,1), 0),
        ("BOTTOMPADDING", (0,1), (-1,1), 10),
    ]))
    story.append(stat_table)
    story.append(Spacer(1, 24))

    story.append(Paragraph(
        f"Generated {datetime.now().strftime('%B %d, %Y')}  ·  Source: eMolecules query logs 2020–2026  ·  Scored via Hybrid ICP Pipeline",
        styles["meta"]
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=MID_GREY))
    story.append(Spacer(1, 16))

    # Score legend
    legend_data = [
        [
            Paragraph("SCORE BREAKDOWN", styles["field_label"]),
            Paragraph("Small Molecule (SM) — 0 to 30 pts", styles["meta"]),
            Paragraph("Stage Fit (SF) — 0 to 30 pts", styles["meta"]),
            Paragraph("Contact Quality (CQ) — 0 to 25 pts", styles["meta"]),
            Paragraph("Strategic Indicators (SI) — 0 to 15 pts", styles["meta"]),
        ]
    ]
    legend = Table([legend_data[0]], colWidths=[1.4*inch, 1.3*inch, 1.3*inch, 1.3*inch, 1.3*inch])
    legend.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(legend)
    story.append(Spacer(1, 16))

    story.append(PageBreak())
    return story


# ── Executive summary ─────────────────────────────────────────────────────────

def build_executive_summary(companies, styles):
    story = []

    high_count = sum(1 for c in companies if c.get("qualification_status") == "HIGH FIT")
    med_count  = sum(1 for c in companies if c.get("qualification_status") == "MEDIUM FIT")
    n = len(companies)

    _h = ParagraphStyle("_exh", fontSize=16, fontName="Helvetica-Bold",
                        textColor=white, leading=20, spaceAfter=0)
    _s = ParagraphStyle("_exs", fontSize=9, fontName="Helvetica",
                        textColor=HexColor("#94A3B8"), leading=12, spaceAfter=0)
    hdr = Table(
        [[Paragraph("Executive Summary", _h)],
         [Paragraph("eMolecules ICP Hybrid Pipeline — what we built and what we found", _s)]],
        colWidths=[7.0*inch],
    )
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), NAVY),
        ("TOPPADDING",    (0,0), (-1,-1), 14),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ("LEFTPADDING",   (0,0), (-1,-1), 16),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 18))

    _sh = ParagraphStyle("_sh2", fontSize=8.5, fontName="Helvetica-Bold", textColor=NAVY, spaceAfter=4)
    _body = ParagraphStyle("_body", fontSize=8.5, fontName="Helvetica", textColor=DARK_GREY,
                           leading=13, spaceAfter=10)

    story.append(Paragraph("WHAT WE DID", _sh))
    story.append(Paragraph(
        f"We extracted {n} companies from eMolecules' query log database (2020–2026) that showed "
        f"meaningful engagement with the platform. Each company was scored against a four-category "
        f"ICP framework purpose-built for eMolecules: Small Molecule Discovery capability (30 pts), "
        f"Company Stage Fit (30 pts), Contact Quality (25 pts), and Strategic Indicators (15 pts), "
        f"for a maximum of 100 points.",
        _body,
    ))

    story.append(Paragraph("HOW THE PIPELINE WORKS", _sh))
    story.append(Paragraph(
        "The scoring runs in two stages. Stage A is a holistic pass: a single AI agent researches "
        "each company and produces an overall ICP score with reasoning. Companies that score above "
        "a threshold, or that show ambiguous signals, are escalated to Stage B — a deeper categorical "
        "pass where four specialist agents independently evaluate each subcategory and populate "
        "structured evidence fields. The final score blends both stages.",
        _body,
    ))

    story.append(Paragraph("RESULTS", _sh))
    story.append(Paragraph(
        f"Of the {n} companies analyzed, {high_count} were classified as HIGH FIT (≥ 75/100) and "
        f"{med_count} as MEDIUM FIT (60–74/100). These are the companies most likely to benefit "
        f"from eMolecules' catalog — building blocks, screening compounds, virtual libraries, and "
        f"compound management — based on their research focus, team composition, funding stage, "
        f"and recent strategic activity.",
        _body,
    ))

    story.append(Paragraph("HOW TO READ THIS REPORT", _sh))
    story.append(Paragraph(
        "Each company gets one page with a score breakdown across the four subcategories, "
        "the raw evidence the AI found for each signal, and the model's reasoning. The final "
        "page of this report is an AI Data Coverage Audit — it answers a different question: "
        "across all companies, which fields could the AI actually find real data for, and which "
        "ones consistently came up empty? That analysis is the primary tool for evaluating and "
        "improving the pipeline.",
        _body,
    ))

    story.append(HRFlowable(width="100%", thickness=1, color=MID_GREY))
    story.append(Spacer(1, 12))

    # Mini stats row
    avg_score = round(sum(c.get("final_icp_score", 0) for c in companies) / max(n, 1))
    stage_b   = sum(1 for c in companies if c.get("stage_reached") == "B")
    _sl = ParagraphStyle("_sl", fontSize=8, fontName="Helvetica", textColor=DARK_GREY,
                         alignment=TA_CENTER)
    _sv = ParagraphStyle("_sv", fontSize=20, fontName="Helvetica-Bold", textColor=NAVY,
                         alignment=TA_CENTER, leading=22)
    stat_rows = [
        [Paragraph("TOTAL COMPANIES", _sl), Paragraph("HIGH FIT", _sl),
         Paragraph("MEDIUM FIT", _sl), Paragraph("AVG SCORE", _sl),
         Paragraph("STAGE B ESCALATED", _sl)],
        [Paragraph(str(n), _sv), Paragraph(str(high_count), _sv),
         Paragraph(str(med_count), _sv), Paragraph(str(avg_score), _sv),
         Paragraph(str(stage_b), _sv)],
    ]
    st = Table(stat_rows, colWidths=[1.4*inch]*5, rowHeights=[0.25*inch, 0.45*inch])
    st.setStyle(TableStyle([
        ("ALIGN",         (0,0), (-1,-1), "CENTER"),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("BACKGROUND",    (0,0), (-1,-1), LIGHT_GREY),
        ("TOPPADDING",    (0,0), (-1,0), 8),
        ("BOTTOMPADDING", (0,0), (-1,0), 2),
        ("TOPPADDING",    (0,1), (-1,1), 0),
        ("BOTTOMPADDING", (0,1), (-1,1), 8),
    ]))
    story.append(st)
    story.append(PageBreak())
    return story


# ── Analysis page ────────────────────────────────────────────────────────────

def has_real_data(v):
    if not v:
        return False
    s = str(v).strip().lower()
    return s not in ("", "—", "null", "none", "none found", "nothing found", "n/a", "unknown", "no")


def coverage_bar(fill_pct, width=2.8*inch, height=0.14*inch, color=TEAL):
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, fillColor=MID_GREY, strokeColor=None))
    fw = fill_pct / 100 * width
    if fw > 0:
        d.add(Rect(0, 0, fw, height, fillColor=color, strokeColor=None))
    return d


def build_analysis_page(companies, styles):
    """AI data coverage audit: which fields can the pipeline actually populate?"""
    story = []
    n = len(companies)

    _h = ParagraphStyle("_cvh", fontSize=12, fontName="Helvetica-Bold",
                        textColor=white, leading=14, spaceAfter=0)
    _s = ParagraphStyle("_cvs", fontSize=8, fontName="Helvetica",
                        textColor=HexColor("#94A3B8"), leading=10, spaceAfter=0)
    hdr = Table(
        [[Paragraph("AI Data Coverage Audit", _h),
          Paragraph("Which subcategory fields can AI workflows find real data for — and which ones can't they?", _s)]],
        colWidths=[2.2*inch, 4.8*inch],
    )
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), NAVY),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING",   (0,0), (-1,-1), 16),
        ("RIGHTPADDING",  (0,0), (-1,-1), 16),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 14))

    # Field inventory per subcategory
    subcats = [
        ("Small Molecule Discovery", TEAL, LIGHT_TEAL, [
            ("Active Med Chem",    "sm_active_med_chem"),
            ("CADD / Computational","sm_cadd_capabilities"),
            ("Hit-to-Lead",        "sm_hit_to_lead"),
            ("Virtual Screening",  "sm_virtual_screening"),
            ("Scoring Basis",      "sm_scoring_basis"),
        ]),
        ("Stage Fit", BLUE, LIGHT_BLUE, [
            ("Stage Type",         "sf_stage_type"),
            ("Employee Range",     "sf_employee_range"),
            ("Funding Stage",      "sf_funding_stage"),
            ("Public / Private",   "sf_is_public"),
            ("Scoring Basis",      "sf_scoring_basis"),
        ]),
        ("Contact Quality", PURPLE, LIGHT_PURPLE, [
            ("Highest Role Found", "cq_highest_role"),
            ("Has Chemistry Team", "cq_has_chemistry_team"),
            ("Team Size Estimate", "cq_team_size_estimate"),
            ("Scoring Basis",      "cq_scoring_basis"),
        ]),
        ("Strategic Indicators", AMBER, LIGHT_AMBER, [
            ("Recent Funding",     "si_recent_funding"),
            ("Funding Amount",     "si_funding_amount"),
            ("Recent Chem Hires",  "si_recent_chem_hires"),
            ("Recent Publications","si_recent_publications"),
            ("Pharma Partnerships","si_pharma_partnerships"),
            ("Patent Filings",     "si_patent_filings"),
        ]),
    ]

    _cat  = ParagraphStyle("_cat",  fontSize=8.5, fontName="Helvetica-Bold", textColor=white,
                           leftIndent=6, spaceAfter=0)
    _fn   = ParagraphStyle("_fn",   fontSize=7.5, fontName="Helvetica",      textColor=DARK_GREY)
    _fc   = ParagraphStyle("_fc",   fontSize=7.5, fontName="Helvetica-Bold", textColor=DARK_GREY)
    _vrd  = ParagraphStyle("_vrd2", fontSize=7,   fontName="Helvetica-Bold", textColor=white)

    _diag_lbl = ParagraphStyle("_dlbl", fontSize=7, fontName="Helvetica-Bold", textColor=DARK_GREY)
    _diag_txt = ParagraphStyle("_dtxt", fontSize=7.5, fontName="Helvetica", textColor=DARK_GREY,
                               leading=11)

    for cat_title, color, bg, fields in subcats:
        # Compute fill rates first so we can drive both table and diagnosis
        results = []
        for label, key in fields:
            found = sum(1 for c in companies if has_real_data(c.get(key)))
            pct   = found / n * 100 if n else 0
            verdict = "RELIABLE" if pct >= 70 else ("PARTIAL" if pct >= 35 else "SPARSE")
            results.append((label, key, found, pct, verdict))

        reliable = [r[0] for r in results if r[4] == "RELIABLE"]
        partial  = [r[0] for r in results if r[4] == "PARTIAL"]
        sparse   = [r[0] for r in results if r[4] == "SPARSE"]

        # Build field table
        field_rows = [[Paragraph(cat_title, _cat), "", "", ""]]
        for label, key, found, pct, verdict in results:
            verdict_color = GREEN if verdict == "RELIABLE" else (HexColor("#84CC16") if verdict == "PARTIAL" else RED)
            _v = ParagraphStyle(f"_v{key}", fontSize=6.5, fontName="Helvetica-Bold", textColor=white)
            verdict_cell = Table([[Paragraph(verdict, _v)]], colWidths=[0.72*inch])
            verdict_cell.setStyle(TableStyle([
                ("BACKGROUND",    (0,0), (-1,-1), verdict_color),
                ("TOPPADDING",    (0,0), (-1,-1), 2),
                ("BOTTOMPADDING", (0,0), (-1,-1), 2),
                ("LEFTPADDING",   (0,0), (-1,-1), 4),
                ("RIGHTPADDING",  (0,0), (-1,-1), 4),
                ("ALIGN",         (0,0), (-1,-1), "CENTER"),
            ]))
            field_rows.append([
                Paragraph(label, _fn),
                coverage_bar(pct, color=color),
                Paragraph(f"{found}/{n}  ({pct:.0f}%)", _fc),
                verdict_cell,
            ])

        t = Table(field_rows, colWidths=[1.8*inch, 2.9*inch, 1.1*inch, 0.9*inch])
        t.setStyle(TableStyle([
            ("SPAN",          (0,0), (3,0)),
            ("BACKGROUND",    (0,0), (3,0), color),
            ("TOPPADDING",    (0,0), (3,0), 5),
            ("BOTTOMPADDING", (0,0), (3,0), 5),
            ("LEFTPADDING",   (0,0), (3,0), 8),
            ("BACKGROUND",    (0,1), (-1,-1), bg),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,1), (-1,-1), 4),
            ("BOTTOMPADDING", (0,1), (-1,-1), 4),
            ("LEFTPADDING",   (0,1), (0,-1), 8),
            ("LEFTPADDING",   (1,1), (1,-1), 0),
            ("LEFTPADDING",   (2,1), (2,-1), 6),
            ("RIGHTPADDING",  (0,0), (-1,-1), 6),
            ("LINEBELOW",     (0,1), (-1,-2), 0.3, MID_GREY),
        ]))
        story.append(t)

        # Diagnosis block
        can_find    = ", ".join(reliable) if reliable else "none"
        cant_find   = ", ".join(sparse)   if sparse   else "none"
        mixed       = ", ".join(partial)  if partial  else None

        if len(sparse) == 0:
            implication = "Full coverage — workflow has strong signal here. Ready to score with confidence."
        elif len(reliable) == 0:
            implication = ("Significant blind spot across this category. "
                           "Consider alternative data sources or redesign the scoring criteria to "
                           "reflect what is actually discoverable.")
        else:
            gap_note = f"{len(sparse)} of {len(fields)} fields are sparse"
            implication = (f"{gap_note}. Reliable fields can anchor the score; "
                           "sparse fields suggest targeted enrichment workflows (e.g. LinkedIn, "
                           "news APIs, patent databases) before re-running this category.")

        can_str  = f"<b>Can find:</b> {can_find}"
        cant_str = f"<b>Cannot find:</b> {cant_find}"
        impl_str = f"<b>Implication:</b> {implication}"

        diag = Table(
            [[Paragraph("DIAGNOSIS", _diag_lbl),
              Paragraph(f"{can_str}  ·  {cant_str}  ·  {impl_str}", _diag_txt)]],
            colWidths=[0.85*inch, 5.85*inch],
        )
        diag.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), LIGHT_GREY),
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
            ("TOPPADDING",    (0,0), (-1,-1), 6),
            ("BOTTOMPADDING", (0,0), (-1,-1), 6),
            ("LEFTPADDING",   (0,0), (0,-1), 8),
            ("LEFTPADDING",   (1,0), (1,-1), 6),
            ("RIGHTPADDING",  (0,0), (-1,-1), 8),
        ]))
        story.append(diag)
        story.append(Spacer(1, 10))

    # Legend
    story.append(Spacer(1, 4))
    _leg = ParagraphStyle("_leg", fontSize=7, fontName="Helvetica", textColor=DARK_GREY)
    story.append(Paragraph(
        "<b>RELIABLE</b> = AI found data for ≥ 70% of companies  ·  "
        "<b>PARTIAL</b> = 35–69%  ·  "
        "<b>SPARSE</b> = &lt; 35%",
        _leg,
    ))

    return story


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Fetching HIGH FIT companies from Supabase...")
    companies = fetch_high_fit_companies()
    print(f"  {len(companies)} companies found")

    os.makedirs("results", exist_ok=True)
    output_path = "results/emolecules_icp_report.pdf"

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.75*inch,
        rightMargin=0.75*inch,
        topMargin=0.6*inch,
        bottomMargin=0.6*inch,
        title="eMolecules HIGH FIT Companies",
        author="eMolecules ICP Pipeline",
    )

    styles = make_styles()
    story = []

    # Cover
    story.extend(build_cover(companies, styles))

    # Executive summary
    story.extend(build_executive_summary(companies, styles))

    # AI data coverage audit
    story.extend(build_analysis_page(companies, styles))

    # One page per company
    for i, company in enumerate(companies, 1):
        print(f"  [{i}/{len(companies)}] {company['domain']} — {company.get('final_icp_score')}/100")
        story.extend(build_company_page(company, styles))

    doc.build(story)
    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_URL and SUPABASE_KEY in .env")
        exit(1)
    main()
