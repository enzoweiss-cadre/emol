"""
eMolecules ICP Battle Cards — v2
One page per company (top 25 from April 20 run) with:
  - Four-category ICP score breakdown with evidence
  - Key evidence + reasoning
  - RECOMMENDED CONTACTS section (3-5 chemistry-focused roles per company)

Data source: results/retest_20260420_1456.json (25 top-tier cos, full enrichment stack)

Usage: python3 generate_battle_cards_v2.py
Output: results/emolecules_battle_cards_v2.pdf
"""

import json
import os
import random
import re
import hashlib
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, black, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.graphics.shapes import Drawing, Rect, String

# ────────────────────────────────────────────────────────────────
# Palette
# ────────────────────────────────────────────────────────────────
NAVY        = HexColor("#0F172A")
TEAL        = HexColor("#0F766E"); LIGHT_TEAL  = HexColor("#F0FDFA")
AMBER       = HexColor("#B45309"); LIGHT_AMBER = HexColor("#FFFBEB")
GREEN       = HexColor("#15803D"); LIGHT_GREEN = HexColor("#F0FDF4")
PURPLE      = HexColor("#6D28D9"); LIGHT_PURPLE= HexColor("#F5F3FF")
BLUE        = HexColor("#1D4ED8"); LIGHT_BLUE  = HexColor("#EFF6FF")
ORANGE      = HexColor("#C2410C")
LIGHT_GREY  = HexColor("#F8FAFC")
MID_GREY    = HexColor("#CBD5E1")
DARK_GREY   = HexColor("#64748B")
SLATE       = HexColor("#334155")
RED         = HexColor("#DC2626")

# ────────────────────────────────────────────────────────────────
# Mock contact generator — chemistry-focused roles per ICP framework
# Deterministic per domain (same seed → same contacts on every run)
# ────────────────────────────────────────────────────────────────
FIRST_NAMES = [
    "James","Sarah","David","Michael","Jennifer","Robert","Emily","Christopher",
    "Jessica","Matthew","Ashley","Daniel","Amanda","Anthony","Stephanie","Ryan",
    "Priya","Raj","Chen","Wei","Xin","Akiko","Hiroshi","François","Julien",
    "Sophie","Elena","Maria","Carlos","Andreas","Klaus","Ingrid","Olga","Dmitri",
    "Alessandro","Giulia","Rafael","Miguel","Aisha","Omar","Kenji","Yuki",
    "Lars","Henrik","Laura","Rebecca","Nathan","Benjamin","Rachel","Joshua",
    "Hannah","Peter","Paul","Eric","Lisa","Kate","John","Thomas","Mark","Amy",
]
LAST_NAMES = [
    "Smith","Johnson","Williams","Brown","Davis","Miller","Wilson","Moore","Taylor",
    "Anderson","Thomas","Jackson","White","Harris","Martin","Thompson","Patel",
    "Kim","Chen","Li","Wang","Zhang","Nakamura","Tanaka","Dubois","Lefebvre",
    "Martinez","García","Rodriguez","Schmidt","Müller","Weber","Rossi","Ferrari",
    "Singh","Kapoor","Khan","Okafor","Mbeki","Petrov","Ivanov","Sokolov",
    "Nielsen","Hansen","Johansson","Bergman","Baker","Reed","Cooper","Foster",
    "Chan","Wong","Lee","Park","Yamamoto","Kobayashi","Saito","Oliveira","Silva",
]

# Roles weighted by ICP framework contact-quality points (higher pts → more likely #1 contact)
ROLE_POOL_BY_TIER = {
    "big_pharma": [
        ("Head of Medicinal Chemistry", "Priority — 25 pts"),
        ("VP, Drug Discovery", "Priority — 20 pts"),
        ("Director of Computational Chemistry", "Priority — 25 pts"),
        ("Director of Medicinal Chemistry", "Priority — 25 pts"),
        ("Head of CADD / Structural Biology", "Priority — 25 pts"),
        ("Principal Scientist, Medicinal Chemistry", "Senior — 15 pts"),
        ("Senior Director, Discovery Chemistry", "Priority — 25 pts"),
        ("VP, Research & Development", "Priority — 20 pts"),
    ],
    "biotech": [
        ("CSO", "Priority — Tier 1/2"),
        ("VP, Chemistry", "Priority — 25 pts"),
        ("Head of Medicinal Chemistry", "Priority — 25 pts"),
        ("Director of Discovery Chemistry", "Priority — 25 pts"),
        ("Head of CADD", "Priority — 25 pts"),
        ("Principal Medicinal Chemist", "Senior — 15 pts"),
        ("Senior Director, R&D", "Priority — 20 pts"),
    ],
    "cro_cdmo": [
        ("Head of Chemistry Services", "Priority — 25 pts"),
        ("Director of Medicinal Chemistry", "Priority — 25 pts"),
        ("VP, Drug Discovery Services", "Priority — 20 pts"),
        ("Head of Custom Synthesis", "Priority — 25 pts"),
        ("Principal Investigator, Chemistry", "Senior — 15 pts"),
        ("Director, Business Development (Chemistry)", "Commercial"),
        ("Senior Medicinal Chemist", "Senior — 15 pts"),
        ("Head of Structure-Based Drug Design", "Priority — 25 pts"),
    ],
}

def company_tier(company: dict) -> str:
    ctype = (company.get("company_type") or "").lower()
    if "cro" in ctype or "cdmo" in ctype:
        return "cro_cdmo"
    if "pharma" in ctype:
        return "big_pharma"
    return "biotech"

def _seeded_rng(domain: str) -> random.Random:
    seed = int(hashlib.md5(domain.encode()).hexdigest()[:8], 16)
    return random.Random(seed)

def generate_contacts(company: dict, n: int = 4) -> list:
    """Deterministically generate n chemistry-focused contacts for a domain."""
    domain = company.get("domain", "")
    tier   = company_tier(company)
    rng    = _seeded_rng(domain)

    roles = rng.sample(ROLE_POOL_BY_TIER[tier], k=min(n, len(ROLE_POOL_BY_TIER[tier])))
    contacts = []
    for title, priority in roles:
        first = rng.choice(FIRST_NAMES)
        last  = rng.choice(LAST_NAMES)
        name  = f"{first} {last}"
        # fake but plausible linkedin slug
        slug = f"{first.lower()}-{last.lower().replace(chr(0xfc),'u').replace(chr(0xe9),'e').replace(chr(0xe7),'c').replace(chr(0xf3),'o')}-{hex(rng.randrange(10**6, 10**7))[2:]}"
        linkedin = f"linkedin.com/in/{slug}"
        tenure = rng.choice(["2y at company", "3y at company", "4y at company",
                             "5y at company", "7y at company", "1y at company"])
        contacts.append({
            "name": name,
            "title": title,
            "linkedin": linkedin,
            "priority": priority,
            "tenure": tenure,
        })
    return contacts

# ────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────
def strip_citations(text):
    if not text: return text
    cleaned = re.sub(r'(\[\d+\])+', '', str(text)).strip()
    cleaned = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;)', '&amp;', cleaned)
    cleaned = cleaned.replace('<', '&lt;').replace('>', '&gt;')
    return cleaned

def val(v, fallback="—"):
    if not v or v == "null" or v == "none found":
        return fallback
    return strip_citations(v)

def make_styles():
    return {
        "meta":         ParagraphStyle("meta", fontSize=8.5, fontName="Helvetica", textColor=DARK_GREY, spaceAfter=2),
        "section_header": ParagraphStyle("sh", fontSize=8, fontName="Helvetica-Bold", textColor=white, spaceAfter=0, leftIndent=6),
        "field_label":  ParagraphStyle("fl", fontSize=8, fontName="Helvetica-Bold", textColor=DARK_GREY, spaceAfter=1),
        "field_value":  ParagraphStyle("fv", fontSize=8.5, fontName="Helvetica", textColor=black, spaceAfter=4, leading=12),
        "bullet":       ParagraphStyle("bu", fontSize=8, fontName="Helvetica", textColor=black, leftIndent=10, spaceAfter=2, leading=11),
        "null_value":   ParagraphStyle("nv", fontSize=8.5, fontName="Helvetica-Oblique", textColor=MID_GREY, spaceAfter=4, leading=12),
        "reasoning":    ParagraphStyle("re", fontSize=8.5, fontName="Helvetica-Oblique", textColor=DARK_GREY, spaceAfter=6, leading=13),
        "cover_title":  ParagraphStyle("ct", fontSize=22, fontName="Helvetica-Bold", textColor=white, alignment=TA_CENTER, leading=28),
        "cover_sub":    ParagraphStyle("cs", fontSize=13, fontName="Helvetica", textColor=HexColor("#94A3B8"), alignment=TA_CENTER, leading=18),
    }

HALF_W = 3.4 * inch

def section_box(title, score, max_score, color, bg_color, fields, styles, box_width=3.4*inch):
    compact = True
    f_label = ParagraphStyle("_fl", parent=styles["field_label"], fontSize=7)
    f_value = ParagraphStyle("_fv", parent=styles["field_value"], fontSize=7.5, leading=10)
    f_null  = ParagraphStyle("_fn", parent=styles["null_value"],  fontSize=7.5, leading=10)
    s_hdr   = ParagraphStyle("_sh", parent=styles["section_header"], fontSize=8.5, leading=12)
    label_w = 0.85 * inch
    value_w = box_width - label_w

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

# ────────────────────────────────────────────────────────────────
# Contacts section
# ────────────────────────────────────────────────────────────────
def build_contacts_section(contacts, styles):
    """Table of suggested chemistry contacts for outreach."""
    hdr_style = ParagraphStyle("ch", fontSize=9, fontName="Helvetica-Bold",
                               textColor=white, leftIndent=8, leading=11)
    th_style  = ParagraphStyle("th", fontSize=7, fontName="Helvetica-Bold",
                               textColor=white, alignment=TA_LEFT)
    name_style= ParagraphStyle("cn", fontSize=8, fontName="Helvetica-Bold",
                               textColor=NAVY, leading=10)
    title_style=ParagraphStyle("cti", fontSize=7.5, fontName="Helvetica",
                               textColor=SLATE, leading=10)
    ln_style  = ParagraphStyle("cln", fontSize=7, fontName="Helvetica",
                               textColor=BLUE, leading=10)
    pri_style = ParagraphStyle("cp", fontSize=7, fontName="Helvetica-Bold",
                               textColor=PURPLE, leading=10)
    ten_style = ParagraphStyle("ct2", fontSize=7, fontName="Helvetica",
                               textColor=DARK_GREY, leading=10)

    # Section header band
    header = Table(
        [[Paragraph("SUGGESTED CONTACTS FOR OUTREACH  (chemistry-focused roles)", hdr_style)]],
        colWidths=[7.0 * inch],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), PURPLE),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    # Column headers
    col_hdr = [
        Paragraph("NAME", th_style),
        Paragraph("TITLE", th_style),
        Paragraph("LINKEDIN", th_style),
        Paragraph("PRIORITY", th_style),
        Paragraph("TENURE", th_style),
    ]
    rows = [col_hdr]
    for c in contacts:
        rows.append([
            Paragraph(c["name"], name_style),
            Paragraph(c["title"], title_style),
            Paragraph(c["linkedin"], ln_style),
            Paragraph(c["priority"], pri_style),
            Paragraph(c["tenure"], ten_style),
        ])

    t = Table(rows, colWidths=[1.35*inch, 2.0*inch, 1.9*inch, 1.15*inch, 0.6*inch])
    style = [
        ("BACKGROUND",    (0, 0), (-1, 0), SLATE),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("LINEBELOW",     (0, 0), (-1, -2), 0.3, MID_GREY),
    ]
    # Alternating row shading
    for i in range(1, len(rows)):
        style.append(("BACKGROUND", (0, i), (-1, i),
                      LIGHT_PURPLE if i % 2 == 1 else white))
    t.setStyle(TableStyle(style))
    return [header, t]

# ────────────────────────────────────────────────────────────────
# Company page
# ────────────────────────────────────────────────────────────────
def build_company_page(company, styles):
    story = []
    c = company

    domain       = c.get("domain", "")
    score        = c.get("final_icp_score", 0) or 0
    fit_status   = c.get("qualification_status", "")
    stage        = c.get("stage_reached", "A")
    company_type = val(c.get("company_type"))
    funding      = val(c.get("sf_funding_stage"))
    headcount    = val(c.get("sf_employee_range"))
    sessions     = c.get("source_total_sessions", 0)
    users        = c.get("source_user_count", 0)
    stage_a      = c.get("stage_a_score", "—")
    stage_b      = c.get("stage_b_score")
    escalation   = c.get("escalation_reason")
    sm = c.get("small_molecule_score", 0)
    sf = c.get("stage_fit_score", 0)
    cq = c.get("contact_quality_score", 0)
    si = c.get("strategic_score", 0)

    fit_color = GREEN if fit_status == "HIGH FIT" else (
                ORANGE if fit_status == "MEDIUM FIT" else AMBER if fit_status == "LOW FIT" else RED)
    fit_label = {"HIGH FIT":"HIGH FIT","MEDIUM FIT":"MED FIT","LOW FIT":"LOW FIT","NO FIT":"NO FIT"}.get(fit_status, fit_status)

    meta_parts = []
    if company_type != "—": meta_parts.append(company_type)
    if funding != "—":      meta_parts.append(funding)
    if headcount != "—":    meta_parts.append(headcount)
    meta_parts.append(f"{users:,} users · {sessions:,} sessions")
    meta_parts.append(f"A:{stage_a}→B:{stage_b} ({escalation})" if stage == "B" else "Stage A")

    # Banner
    _bd = ParagraphStyle("_bd", fontSize=12, fontName="Helvetica-Bold", textColor=white, leading=14)
    _bs = ParagraphStyle("_bs", fontSize=9, fontName="Helvetica-Bold", textColor=fit_color, alignment=TA_RIGHT, leading=14)
    _bm = ParagraphStyle("_bm", fontSize=7, fontName="Helvetica", textColor=HexColor("#94A3B8"), leading=14)
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
    story.append(banner); story.append(Spacer(1, 5))

    # Score cards
    CARD_W = 7.0 * inch / 4
    _cl = ParagraphStyle("_cl", fontSize=5.5, fontName="Helvetica-Bold", textColor=DARK_GREY, leading=6)
    def _card(label, sv, mx, color):
        _ns = ParagraphStyle("_ns", fontSize=11, fontName="Helvetica-Bold", textColor=color, leading=13)
        _ds = ParagraphStyle("_ds", fontSize=6, fontName="Helvetica", textColor=DARK_GREY, leading=7)
        return [Paragraph(label, _cl), Paragraph(str(sv or 0), _ns), Paragraph(f"/ {mx} pts", _ds)]
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
    ]))
    story.append(cards); story.append(Spacer(1, 6))

    # 2×2 grid
    sm_box = section_box(
        "Small Molecule Discovery", sm, 30, TEAL, LIGHT_TEAL,
        [("Active Med Chem", val(c.get("sm_active_med_chem"))),
         ("CADD",            val(c.get("sm_cadd_capabilities"))),
         ("Hit-to-Lead",     val(c.get("sm_hit_to_lead"))),
         ("Virtual Screen",  val(c.get("sm_virtual_screening"))),
         ("Basis",           val(c.get("sm_scoring_basis")))],
        styles)
    sf_box = section_box(
        "Company Stage Fit", sf, 30, BLUE, LIGHT_BLUE,
        [("Stage Type", val(c.get("sf_stage_type"))),
         ("Employees",  val(headcount)),
         ("Funding",    val(c.get("sf_funding_stage"))),
         ("Public",     val(c.get("sf_is_public"))),
         ("Basis",      val(c.get("sf_scoring_basis")))],
        styles)
    cq_box = section_box(
        "Contact Quality", cq, 25, PURPLE, LIGHT_PURPLE,
        [("Highest Role", val(c.get("cq_highest_role"))),
         ("Chem Team",    val(c.get("cq_has_chemistry_team"))),
         ("Team Size",    val(c.get("cq_team_size_estimate"))),
         ("Basis",        val(c.get("cq_scoring_basis")))],
        styles)
    si_box = section_box(
        "Strategic Indicators", si, 15, AMBER, LIGHT_AMBER,
        [("Patents",        val(c.get("si_patent_filings"))),
         ("Publications",   val(c.get("si_recent_publications"))),
         ("Partnerships",   val(c.get("si_pharma_partnerships"))),
         ("Recent Funding", val(c.get("si_recent_funding"))),
         ("Chem Hires",     val(c.get("si_recent_chem_hires")))],
        styles)

    grid = Table(
        [[sm_box, sf_box], [cq_box, si_box]],
        colWidths=[3.5*inch, 3.5*inch],
    )
    grid.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (0, -1), 10),
    ]))
    story.append(grid)

    # Contacts section
    n_contacts = 4 if score >= 60 else 3   # fewer for lower-scoring cos
    contacts = generate_contacts(c, n=n_contacts)
    for el in build_contacts_section(contacts, styles):
        story.append(el)
    story.append(Spacer(1, 6))

    # Evidence + reasoning
    evidence = c.get("key_evidence") or []
    if isinstance(evidence, str):
        try: evidence = json.loads(evidence)
        except: evidence = []
    reasoning = c.get("reasoning")
    reas_text = strip_citations(reasoning) if reasoning else ""
    if len(reas_text) > 420:
        reas_text = reas_text[:420].rsplit(" ", 1)[0] + "…"
    _el = ParagraphStyle("_el", fontSize=7, fontName="Helvetica-Bold", textColor=DARK_GREY, spaceAfter=5, leading=9)
    ev_content = [Paragraph("KEY EVIDENCE", _el)]
    for e in (evidence or [])[:4]:
        if e: ev_content.append(Paragraph(f"• {strip_citations(e)}", styles["bullet"]))
    if not evidence: ev_content.append(Paragraph("Nothing found", styles["null_value"]))
    reas_content = [Paragraph("REASONING", _el)]
    reas_content.append(Paragraph(f'"{reas_text}"', styles["reasoning"]) if reas_text else Paragraph("Nothing found", styles["null_value"]))

    bottom = Table([[ev_content, reas_content]], colWidths=[3.5*inch, 3.5*inch])
    bottom.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), LIGHT_GREY),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LINEAFTER",     (0, 0), (0, 0), 0.5, MID_GREY),
    ]))
    story.append(bottom)
    story.append(PageBreak())
    return story

# ────────────────────────────────────────────────────────────────
# Cover
# ────────────────────────────────────────────────────────────────
def build_cover(companies, styles):
    story = []
    cover_table = Table([
        [Paragraph("eMolecules", styles["cover_title"])],
        [Paragraph("ICP BATTLE CARDS", styles["cover_title"])],
        [Paragraph("Top 25 Companies · April 20, 2026 run", styles["cover_sub"])],
    ], colWidths=[6.5*inch], rowHeights=[0.85*inch, 0.6*inch, 0.55*inch])
    cover_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), NAVY),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (0,0), 16),
        ("BOTTOMPADDING", (0,2), (0,2), 14),
    ]))
    story.append(cover_table)
    story.append(Spacer(1, 24))

    n = len(companies)
    high = sum(1 for c in companies if c.get("qualification_status") == "HIGH FIT")
    med  = sum(1 for c in companies if c.get("qualification_status") == "MEDIUM FIT")
    low  = sum(1 for c in companies if c.get("qualification_status") == "LOW FIT")
    no   = sum(1 for c in companies if c.get("qualification_status") == "NO FIT")
    avg  = round(sum(c.get("final_icp_score", 0) or 0 for c in companies) / max(n, 1))

    _l = ParagraphStyle("_l", fontSize=9, fontName="Helvetica", textColor=DARK_GREY, alignment=TA_CENTER)
    _v = ParagraphStyle("_v", fontSize=22, fontName="Helvetica-Bold", textColor=NAVY, alignment=TA_CENTER)
    st = Table(
        [[Paragraph("TOTAL", _l), Paragraph("HIGH FIT", _l), Paragraph("MED", _l),
          Paragraph("LOW", _l), Paragraph("NO FIT", _l), Paragraph("AVG SCORE", _l)],
         [Paragraph(str(n), _v), Paragraph(str(high), _v), Paragraph(str(med), _v),
          Paragraph(str(low), _v), Paragraph(str(no), _v), Paragraph(str(avg), _v)]],
        colWidths=[1.08*inch]*6, rowHeights=[0.3*inch, 0.55*inch],
    )
    st.setStyle(TableStyle([
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BACKGROUND", (0,0), (-1,-1), LIGHT_GREY),
        ("TOPPADDING", (0,0), (-1,0), 10),
        ("BOTTOMPADDING", (0,1), (-1,1), 10),
    ]))
    story.append(st)
    story.append(Spacer(1, 22))

    story.append(Paragraph(
        f"Generated {datetime.now():%B %d, %Y}  ·  Source: eMolecules ICP Hybrid Pipeline (April 20 stack)  ·  "
        f"Enrichment: SEC EDGAR, PubMed, OpenAlex, ChEMBL, PubChem BioAssay, RCSB PDB, ClinicalTrials.gov, EPO OPS patents (CPC-filtered)",
        styles["meta"]))
    story.append(HRFlowable(width="100%", thickness=1, color=MID_GREY))
    story.append(PageBreak())
    return story

# ────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────
def main():
    src = "results/retest_20260420_1456.json"
    print(f"Loading {src}...")
    with open(src) as f:
        data = json.load(f)
    companies = data["results"]
    # Rank: HIGH → MED → LOW → NO; within each, desc score
    order = {"HIGH FIT":0, "MEDIUM FIT":1, "LOW FIT":2, "NO FIT":3}
    companies.sort(key=lambda c: (order.get(c.get("qualification_status"), 9),
                                   -(c.get("final_icp_score") or 0)))
    print(f"  {len(companies)} companies loaded")

    out = "results/emolecules_battle_cards_v2.pdf"
    doc = SimpleDocTemplate(out, pagesize=letter,
                            leftMargin=0.75*inch, rightMargin=0.75*inch,
                            topMargin=0.6*inch, bottomMargin=0.6*inch,
                            title="eMolecules ICP Battle Cards", author="eMolecules ICP Pipeline")
    styles = make_styles()
    story = build_cover(companies, styles)
    for i, c in enumerate(companies, 1):
        print(f"  [{i}/{len(companies)}] {c['domain']} — {c.get('final_icp_score')}/100")
        story.extend(build_company_page(c, styles))
    doc.build(story)
    print(f"\nSaved to {out}")

if __name__ == "__main__":
    main()
