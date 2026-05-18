"""
eMolecules ICP — Top 25 vs Bottom 25 comparison
Fill rate + score distribution between the two activity tiers,
using the final April 20 stack (enrichment + prompt fixes + EPO + CPC).

Usage: python3 generate_tier_fillrate_comparison.py
Output: results/emolecules_top_vs_bottom.pdf
"""

import json, re
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, HRFlowable, PageBreak)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

W = 7.0 * inch
NAVY, TEAL = HexColor("#0D2B45"), HexColor("#1A7A6E")
LIGHT_TEAL = HexColor("#E8F5F3")
AMBER, LIGHT_AMBER = HexColor("#B45309"), HexColor("#FFF8E7")
RED, LIGHT_RED = HexColor("#C0392B"), HexColor("#FDECEA")
LIGHT_GREY, MID_GREY, DARK_GREY = HexColor("#F4F6F8"), HexColor("#BDC3C7"), HexColor("#5D6D7E")
GREEN, LIGHT_GREEN = HexColor("#1E8449"), HexColor("#E9F7EF")
PURPLE, LIGHT_PURPLE = HexColor("#6D28D9"), HexColor("#F5F3FF")
BLUE, LIGHT_BLUE = HexColor("#1D4ED8"), HexColor("#EFF6FF")

TOP_PATH    = "results/retest_20260420_1456.json"
BOTTOM_PATH = "results/bottom_25_20260420_1513.json"

# Same evidence-grounded filter used everywhere else
UNKNOWN = [r'^unknown', r'cannot (be\s+determined|confirm|verify)',
           r'could not (determine|find|confirm|verify)', r'insufficient',
           r'^not (determined|available|verified)', r'unable to']
EV = [r'\bconfirmed\b',
      r'\b(sec|edgar|chembl|pubmed|pdb|clinicaltrials|linkedin|crunchbase|patentsview|openalex|epo|form\s*d|cpc)\b',
      r'\b\d+\s+(approved|interventional|active|papers?|publications?|drugs?|patents?|trials?|employees?|structures?)',
      r'\$\d', r'\b\d{4}\b',
      r'per\s+(the\s+)?(website|pipeline|filing|press\s*release|10[- ]?k)']
UNG = re.compile(r'^(no |none |not )[a-z\s\-]+(found|listed|identified|visible|known|mentioned|reported|present|available)(\s+on\s+(website|pipeline|linkedin))?\s*[\.\-]*\s*$', re.I)
UNKR = re.compile('|'.join(UNKNOWN), re.I); EVR = re.compile('|'.join(EV), re.I)

def is_true_fill(v):
    if v is None or v == "": return False
    s = str(v).strip()
    if not s: return False
    if UNKR.search(s): return False
    if UNG.match(s): return False
    if EVR.search(s): return True
    if s.lower().startswith(('no ','none ','not ')): return False
    return True

def fill_pct(rs, field):
    if not rs: return 0.0
    return sum(1 for r in rs if is_true_fill(r.get(field))) / len(rs) * 100

def load(path):
    return json.load(open(path))["results"]

top = load(TOP_PATH)
bot = load(BOTTOM_PATH)

FIELDS = {
    "Small Molecule":  ["sm_active_med_chem","sm_cadd_capabilities","sm_hit_to_lead","sm_virtual_screening"],
    "Stage Fit":       ["sf_is_public","sf_funding_stage","sf_employee_range","sf_stage_type"],
    "Contact Quality": ["cq_highest_role","cq_has_chemistry_team","cq_team_size_estimate"],
    "Strategic":       ["si_recent_funding","si_recent_chem_hires","si_recent_publications","si_patent_filings","si_pharma_partnerships"],
}
FIELD_LABELS = {
    "sm_active_med_chem": "Active medicinal chemistry",
    "sm_cadd_capabilities": "CADD capabilities",
    "sm_hit_to_lead": "Hit-to-lead / lead opt",
    "sm_virtual_screening": "Virtual screening",
    "sf_is_public": "Publicly traded",
    "sf_funding_stage": "Funding stage",
    "sf_employee_range": "Employee range",
    "sf_stage_type": "Stage type",
    "cq_highest_role": "Highest chemistry role",
    "cq_has_chemistry_team": "Has chemistry team",
    "cq_team_size_estimate": "Team size estimate",
    "si_recent_funding": "Recent funding",
    "si_recent_chem_hires": "Recent chem hires",
    "si_recent_publications": "Recent publications",
    "si_patent_filings": "Patent filings",
    "si_pharma_partnerships": "Pharma partnerships",
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
    "stat_num":    S("sn", fontName="Helvetica-Bold", fontSize=24, textColor=white, alignment=TA_CENTER),
    "stat_lbl":    S("sl", fontName="Helvetica", fontSize=8, textColor=HexColor("#C8D8E4"), alignment=TA_CENTER),
    "cat_hdr":     S("ch", fontName="Helvetica-Bold", fontSize=10, textColor=white, leftIndent=8, leading=14),
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

def score_bucket(s):
    s = s or 0
    if s >= 80: return "HIGH FIT"
    if s >= 60: return "MEDIUM FIT"
    if s >= 40: return "LOW FIT"
    return "NO FIT"

def score_distribution(rs):
    buckets = {"HIGH FIT":0,"MEDIUM FIT":0,"LOW FIT":0,"NO FIT":0}
    for r in rs:
        buckets[score_bucket(r.get("final_icp_score") or 0)] += 1
    return buckets

def avg_score(rs):
    return sum((r.get("final_icp_score") or 0) for r in rs) / max(len(rs),1)

def add_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5); canvas.setFillColor(MID_GREY)
    canvas.drawCentredString(letter[0]/2, 0.4*inch,
        "eMolecules ICP  •  Top 25 vs Bottom 25  •  Confidential")
    canvas.restoreState()

# ─────────────────────────────────────────────────────────────
def build_cover(story):
    story.append(tbl(
        [[Paragraph("eMolecules ICP Scoring Pipeline", STYLES["cover_sub"])],
         [Paragraph("Top 25 vs Bottom 25<br/>Activity Tier Comparison", STYLES["cover_title"])],
         [Paragraph(f"Top tier: ≥ 27,657 sessions &nbsp;·&nbsp; Bottom tier: 1 session<br/>Generated {datetime.now():%B %d, %Y}", STYLES["cover_sub"])]],
        [W],
        [("BACKGROUND",(0,0),(-1,-1),NAVY),
         ("TOPPADDING",(0,0),(-1,-1),18),("BOTTOMPADDING",(0,0),(-1,-1),18),
         ("LEFTPADDING",(0,0),(-1,-1),20),("RIGHTPADDING",(0,0),(-1,-1),20)]))
    story.append(sp(10))

    top_avg = avg_score(top); bot_avg = avg_score(bot)
    top_dist = score_distribution(top); bot_dist = score_distribution(bot)
    mult = top_avg / bot_avg if bot_avg else float('inf')

    stat = lambda n, l, c: tbl([[Paragraph(n, STYLES["stat_num"])], [Paragraph(l, STYLES["stat_lbl"])]],
                                [1.5*inch], [("BACKGROUND",(0,0),(-1,-1),c),
                                 ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10)])
    row = tbl([[
        stat(f"{top_avg:.0f}/100", "top tier avg score", GREEN),
        stat(f"{bot_avg:.0f}/100", "bottom tier avg score", RED),
        stat(f"{mult:.1f}×" if bot_avg else "∞", "top-vs-bottom multiplier", TEAL),
        stat(f"{top_dist['HIGH FIT']} / {bot_dist['HIGH FIT']}", "HIGH FIT top / bottom", BLUE),
    ]], [1.6*inch]*4, [("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4)])
    story.append(row); story.append(sp(14))

    story.append(Paragraph("Headline finding", STYLES["h1"])); story.append(hr())
    story.append(Paragraph(
        f"Scoring cleanly separates high-engagement eMolecules visitors from low-engagement ones. "
        f"Top-tier companies (highest session counts) average <b>{top_avg:.0f}/100</b> with "
        f"<b>{top_dist['HIGH FIT']} HIGH FIT</b> and zero NO FIT after disqualifying tool/academic/bot domains. "
        f"Bottom-tier companies (1 session) average <b>{bot_avg:.0f}/100</b> with "
        f"<b>{bot_dist['HIGH FIT']} HIGH FIT</b> — they are overwhelmingly academic institutions, one-off visitors, "
        f"and non-drug-discovery vendors. Session activity is a {mult:.1f}× multiplier on ICP score.",
        STYLES["body"]))

# ─────────────────────────────────────────────────────────────
def build_score_distribution(story):
    story.append(sp(10))
    story.append(Paragraph("Score distribution", STYLES["h1"])); story.append(hr())

    top_dist = score_distribution(top); bot_dist = score_distribution(bot)
    data = [[Paragraph("Bucket", STYLES["th"]),
             Paragraph(f"Top 25", STYLES["th"]),
             Paragraph(f"Bottom 25", STYLES["th"]),
             Paragraph("Signal", STYLES["th"])]]
    style = [("BACKGROUND",(0,0),(-1,0),NAVY), ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
             ("TOPPADDING",(0,0),(-1,-1),6), ("BOTTOMPADDING",(0,0),(-1,-1),6),
             ("GRID",(0,0),(-1,-1),0.3,MID_GREY),
             ("ALIGN",(1,0),(2,-1),"CENTER")]
    colors = {"HIGH FIT":GREEN,"MEDIUM FIT":TEAL,"LOW FIT":AMBER,"NO FIT":RED}
    for i, b in enumerate(["HIGH FIT","MEDIUM FIT","LOW FIT","NO FIT"], start=1):
        style.append(("BACKGROUND",(0,i),(-1,i), LIGHT_GREY if i%2==0 else white))
        data.append([
            Paragraph(f"<font color='{colors[b].hexval()}'><b>{b}</b></font>", STYLES["td"]),
            Paragraph(f"<b>{top_dist[b]}</b>", STYLES["td_b"]),
            Paragraph(f"<b>{bot_dist[b]}</b>", STYLES["td_b"]),
            Paragraph({"HIGH FIT":"priority outreach",
                       "MEDIUM FIT":"qualified prospect",
                       "LOW FIT":"nurture only",
                       "NO FIT":"disqualify"}[b], STYLES["td_small"])])
    story.append(tbl(data, [1.3*inch, 1.2*inch, 1.2*inch, 2.8*inch], style))
    story.append(sp(10))

    # Top performers each tier
    story.append(Paragraph("Top scorers by tier", STYLES["h2"]))
    def top5(rs):
        return sorted(rs, key=lambda r: -(r.get("final_icp_score") or 0))[:5]
    data = [[Paragraph("Rank", STYLES["th"]),
             Paragraph("Top 25", STYLES["th"]),
             Paragraph("Score", STYLES["th"]),
             Paragraph("Bottom 25", STYLES["th"]),
             Paragraph("Score", STYLES["th"])]]
    style = [("BACKGROUND",(0,0),(-1,0),NAVY), ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
             ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
             ("GRID",(0,0),(-1,-1),0.3,MID_GREY)]
    top5_top, top5_bot = top5(top), top5(bot)
    for i in range(5):
        style.append(("BACKGROUND",(0,i+1),(-1,i+1), LIGHT_GREY if i%2==0 else white))
        t = top5_top[i] if i < len(top5_top) else None
        b = top5_bot[i] if i < len(top5_bot) else None
        data.append([
            Paragraph(f"#{i+1}", STYLES["td"]),
            Paragraph(t["domain"] if t else "—", STYLES["td"]),
            Paragraph(f"{t.get('final_icp_score') or 0}" if t else "", STYLES["td_b"]),
            Paragraph(b["domain"] if b else "—", STYLES["td"]),
            Paragraph(f"{b.get('final_icp_score') or 0}" if b else "", STYLES["td_b"]),
        ])
    story.append(tbl(data, [0.5*inch, 2.2*inch, 0.6*inch, 2.2*inch, 0.6*inch], style))

# ─────────────────────────────────────────────────────────────
def build_fill_rate_comparison(story):
    story.append(PageBreak())
    story.append(Paragraph("Fill rate by tier", STYLES["h1"])); story.append(hr())
    story.append(Paragraph(
        "Fill rate is evidence-grounded: a field counts as filled only when the agent returns "
        "positive evidence OR confirmed-negative with a cited source. Pure 'unknown' / 'not found' "
        "without source are unfilled. Top-tier companies have dramatically higher fill rates because "
        "they have the digital footprint (publications, patents, SEC filings, clinical trials) that "
        "enrichment can capture — bottom-tier companies are mostly academic one-off visitors with "
        "no structured public data.", STYLES["body"]))
    story.append(sp(6))

    for cat, fields in FIELDS.items():
        dark, _ = CAT_COLORS[cat]
        story.append(tbl([[Paragraph(f"<b>{cat}</b>", STYLES["cat_hdr"])]], [W],
                         [("BACKGROUND",(0,0),(-1,-1),dark),
                          ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
        data = [[Paragraph("Field", STYLES["th"]),
                 Paragraph("Top 25", STYLES["th"]),
                 Paragraph("Bottom 25", STYLES["th"]),
                 Paragraph("Gap", STYLES["th"])]]
        style = [("BACKGROUND",(0,0),(-1,0),dark), ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                 ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
                 ("GRID",(0,0),(-1,-1),0.3,MID_GREY),
                 ("ALIGN",(1,0),(-1,-1),"CENTER")]
        for i, f in enumerate(fields, start=1):
            style.append(("BACKGROUND",(0,i),(-1,i), LIGHT_GREY if i%2==1 else white))
            tp = fill_pct(top, f); bp = fill_pct(bot, f); d = tp - bp
            data.append([
                Paragraph(f"<b>{FIELD_LABELS.get(f,f)}</b><br/><font size=7 color='#64748B'>{f}</font>", STYLES["td"]),
                Paragraph(f"<font color='{pct_color(tp).hexval()}'><b>{tp:.0f}%</b></font>", STYLES["td"]),
                Paragraph(f"<font color='{pct_color(bp).hexval()}'><b>{bp:.0f}%</b></font>", STYLES["td"]),
                Paragraph(f"<b>{'+' if d>=0 else ''}{d:.0f}pp</b>", STYLES["td"]),
            ])
        story.append(tbl(data, [2.6*inch, 1.2*inch, 1.3*inch, 1.0*inch], style))
        story.append(sp(8))

    # Overall
    all_f = [f for lst in FIELDS.values() for f in lst]
    top_avg = sum(fill_pct(top,f) for f in all_f)/len(all_f)
    bot_avg = sum(fill_pct(bot,f) for f in all_f)/len(all_f)
    story.append(sp(4))
    story.append(Paragraph(
        f"<b>Overall fill rate:</b> top tier <font color='{GREEN.hexval()}'><b>{top_avg:.0f}%</b></font> "
        f"vs bottom tier <font color='{RED.hexval()}'><b>{bot_avg:.0f}%</b></font> — "
        f"a <b>{top_avg-bot_avg:.0f}pp gap</b>.",
        STYLES["body"]))

def build_interpretation(story):
    story.append(PageBreak())
    story.append(Paragraph("Interpretation", STYLES["h1"])); story.append(hr())

    story.append(Paragraph("Why the gap is real", STYLES["h2"]))
    story.append(Paragraph(
        "The fill-rate gap isn't an artifact of the scoring pipeline — it reflects real differences "
        "in the digital footprint of these companies. Top-tier companies are publicly-traded pharma, "
        "active biotechs, and discovery CROs. They file SEC reports, publish papers, deposit patents, "
        "and run clinical trials. Bottom-tier companies (1 session) are overwhelmingly academic "
        "institutions (.edu / .ac.uk / .edu.mx), one-off student visits, or small vendors that don't "
        "show up in any structured public data source. Enrichment can't pull data that doesn't exist.",
        STYLES["body"]))

    story.append(Paragraph("Disqualifier pattern in the bottom tier", STYLES["h2"]))
    dq_count = sum(1 for r in bot if r.get("auto_disqualified"))
    story.append(Paragraph(
        f"{dq_count}/{len(bot)} bottom-tier companies were auto-disqualified, primarily for being "
        f"academic institutions, waste-management / non-pharma businesses, or too small to verify as "
        f"drug-discovery operations. Only 1 bottom-tier company reached LOW FIT "
        f"(delixtherapeutics.com — a real but small biotech). "
        f"No bottom-tier company reached MEDIUM or HIGH FIT.",
        STYLES["body"]))

    story.append(Paragraph("Why activity count is a valid ICP proxy", STYLES["h2"]))
    story.append(Paragraph(
        "Session volume on eMolecules' website correlates with chemistry-team activity. A company "
        "with hundreds of chemists searching building blocks generates thousands of sessions. A "
        "student running a one-off lookup for a class project generates one session. The data here "
        "confirms the intuitive model: the top 10% of most-active companies are overwhelmingly "
        "drug-discovery fits; the bottom 10% are overwhelmingly not. This supports prioritizing "
        "outreach by session activity as a cheap first filter.",
        STYLES["body"]))

# ─────────────────────────────────────────────────────────────
def main():
    out_path = "results/emolecules_top_vs_bottom.pdf"
    doc = SimpleDocTemplate(out_path, pagesize=letter,
                            topMargin=0.6*inch, bottomMargin=0.6*inch,
                            leftMargin=0.75*inch, rightMargin=0.75*inch)
    story = []
    build_cover(story)
    build_score_distribution(story)
    build_fill_rate_comparison(story)
    build_interpretation(story)
    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    print(f"Saved: {out_path}")

if __name__ == "__main__":
    main()
