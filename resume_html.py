"""
resume_html.py — High-fidelity HTML Resume Generator & Viewer.

Provides pixel-perfect, authentic ATS-styled HTML rendering for:
1. Structured Resume JSON (base_resume.json, tailored_resume.json)
2. Word DOCX files (extracts headings, two-column lines, bullets, bold/italic runs)
3. Headless PDF generation via Playwright (works on Linux Render & Windows)

Renders in 5ms directly inside an <iframe> with zero downloads, selectable text,
responsive paper layout, and @media print support.
"""

import html
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


def sanitize_text(text: str) -> str:
    """Sanitize and strip characters that break ATS parsing."""
    if not text:
        return ""
    text = str(text)
    text = text.replace('\u2014', '-').replace('\u2013', '-')
    text = text.replace('\u2019', "'").replace('\u2018', "'")
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = re.sub(r'^[•·▪▸►\*]\s*', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _get_base_html_template(body_content: str, title: str = "Resume Preview") -> str:
    """Wrap resume body in an authentic, printable paper sheet layout."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --page-bg: #1e222d;
      --paper-bg: #ffffff;
      --text-main: #111827;
      --text-muted: #374151;
      --text-subtle: #4b5563;
      --line-color: #111827;
      --font-family: 'Calibri', 'Segoe UI', Arial, -apple-system, sans-serif;
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      background: var(--page-bg);
      font-family: var(--font-family);
      color: var(--text-main);
      display: flex;
      justify-content: center;
      padding: 24px 16px;
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }}

    .resume-sheet {{
      background: var(--paper-bg);
      width: 100%;
      max-width: 8.5in;
      min-height: 11in;
      padding: 0.5in 0.55in;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
      border-radius: 4px;
      font-size: 10pt;
      line-height: 1.25;
      color: #000000;
    }}

    /* Header */
    .resume-header {{
      text-align: center;
      margin-bottom: 12px;
    }}

    .candidate-name {{
      font-size: 20pt;
      font-weight: 700;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      color: #000000;
      margin-bottom: 2px;
    }}

    .target-role {{
      font-size: 12pt;
      font-weight: 400;
      font-style: italic;
      color: #1f2937;
      margin-bottom: 4px;
    }}

    .contact-line {{
      font-size: 9.5pt;
      color: #2b2f38;
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      align-items: center;
      gap: 6px 10px;
    }}

    .contact-line a {{
      color: #1a56db;
      text-decoration: none;
    }}

    .contact-line a:hover {{
      text-decoration: underline;
    }}

    .contact-sep {{
      color: #9ca3af;
      user-select: none;
    }}

    /* Section Headers */
    .section-title {{
      font-size: 11pt;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: #000000;
      border-bottom: 1px solid var(--line-color);
      padding-bottom: 1px;
      margin-top: 10px;
      margin-bottom: 4px;
      break-after: avoid;
    }}

    /* Summary */
    .summary-text {{
      font-size: 9.5pt;
      line-height: 1.35;
      color: #111827;
      margin-bottom: 6px;
      text-align: justify;
    }}

    /* Experience & Education Entries */
    .entry-item {{
      margin-bottom: 8px;
      break-inside: avoid;
    }}

    .two-col-line {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      width: 100%;
      margin-top: 2px;
      margin-bottom: 1px;
    }}

    .two-col-left {{
      font-size: 10pt;
      font-weight: 700;
      color: #000000;
      text-align: left;
    }}

    .two-col-right {{
      font-size: 9.5pt;
      color: #111827;
      text-align: right;
      white-space: nowrap;
      margin-left: 12px;
    }}

    .sub-line {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      font-size: 9.5pt;
      color: #1f2937;
      margin-bottom: 2px;
    }}

    .sub-left {{
      font-style: italic;
    }}

    .sub-right {{
      font-style: italic;
      color: #4b5563;
      white-space: nowrap;
      margin-left: 12px;
    }}

    /* Bullets */
    .bullet-list {{
      list-style-type: disc;
      margin-left: 1.25rem;
      margin-top: 2px;
      margin-bottom: 4px;
    }}

    .bullet-item {{
      font-size: 9.5pt;
      line-height: 1.3;
      color: #111827;
      margin-bottom: 2px;
      padding-left: 2px;
    }}

    /* Skills Categories */
    .skill-category {{
      font-size: 9.5pt;
      line-height: 1.35;
      margin-bottom: 3px;
      color: #111827;
    }}

    .skill-category-label {{
      font-weight: 700;
      color: #000000;
    }}

    /* Print media styling */
    @media print {{
      body {{
        background: transparent !important;
        padding: 0 !important;
        min-height: auto !important;
      }}
      .resume-sheet {{
        box-shadow: none !important;
        border-radius: 0 !important;
        padding: 0.5in 0.55in !important;
        max-width: 100% !important;
        width: 100% !important;
      }}
      @page {{
        size: letter;
        margin: 0;
      }}
    }}
  </style>
</head>
<body>
  <div class="resume-sheet">
    {body_content}
  </div>
</body>
</html>"""


def resume_json_to_html(resume: dict, company: str = "", role: str = "") -> str:
    """
    Convert a structured resume dictionary (base_resume.json / tailored_resume.json)
    into a high-fidelity HTML document.
    """
    if not isinstance(resume, dict):
        return _get_base_html_template("<p>Invalid resume data.</p>")

    name = sanitize_text(resume.get("name", "Candidate Name"))
    contact = resume.get("contact", {})
    summary = sanitize_text(resume.get("summary", ""))

    # Target role cleaning
    from scraper import clean_role_title
    raw_role = resume.get("target_role") or role or ""
    clean_role = clean_role_title(raw_role)
    if clean_role.upper() in ("UNKNOWN", "NONE"):
        clean_role = ""

    body_parts = []

    # 1. Header
    body_parts.append('<div class="resume-header">')
    body_parts.append(f'<div class="candidate-name">{html.escape(name.upper())}</div>')
    if clean_role:
        body_parts.append(f'<div class="target-role">{html.escape(clean_role)}</div>')

    # Contact line
    contact_parts = []
    if contact.get("email"):
        em = html.escape(contact["email"])
        contact_parts.append(f'<a href="mailto:{em}">{em}</a>')
    if contact.get("phone"):
        ph = html.escape(contact["phone"])
        contact_parts.append(f'<a href="tel:{ph}">{ph}</a>')
    if contact.get("location"):
        contact_parts.append(f'<span>{html.escape(contact["location"])}</span>')
    if contact.get("portfolio"):
        pf = html.escape(contact["portfolio"])
        url = pf if pf.startswith("http") else f"https://{pf}"
        contact_parts.append(f'<a href="{url}" target="_blank">{pf}</a>')
    if contact.get("github"):
        gh = html.escape(contact["github"])
        url = gh if gh.startswith("http") else f"https://{gh}"
        contact_parts.append(f'<a href="{url}" target="_blank">{gh}</a>')
    if contact.get("linkedin"):
        li = html.escape(contact["linkedin"])
        url = li if li.startswith("http") else f"https://{li}"
        contact_parts.append(f'<a href="{url}" target="_blank">{li}</a>')

    if contact_parts:
        sep = '<span class="contact-sep">|</span>'
        body_parts.append(f'<div class="contact-line">{sep.join(contact_parts)}</div>')
    body_parts.append('</div>')  # /resume-header

    # 2. Professional Summary
    if summary:
        body_parts.append('<div class="section-title">Professional Summary</div>')
        body_parts.append(f'<p class="summary-text">{html.escape(summary)}</p>')

    # 3. Technical Skills
    skills = resume.get("skills", [])
    if skills:
        body_parts.append('<div class="section-title">Technical Skills</div>')
        from resume_builder import _categorize_skills
        categorized = _categorize_skills(skills)
        for cat_name, cat_skills in categorized.items():
            if cat_skills:
                skills_str = ", ".join(cat_skills)
                body_parts.append(
                    f'<div class="skill-category"><span class="skill-category-label">{html.escape(cat_name)}:</span> {html.escape(skills_str)}</div>'
                )

    # 4. Professional Experience
    experience = resume.get("experience", [])
    if experience:
        body_parts.append('<div class="section-title">Professional Experience</div>')
        for exp in experience:
            title = sanitize_text(exp.get("title", ""))
            company_name = sanitize_text(exp.get("company", ""))
            dates = sanitize_text(exp.get("dates", ""))
            loc = sanitize_text(exp.get("location", ""))
            bullets = exp.get("bullets", [])

            body_parts.append('<div class="entry-item">')
            # Title on left, Dates on right
            body_parts.append('<div class="two-col-line">')
            body_parts.append(f'<span class="two-col-left">{html.escape(title)}</span>')
            if dates:
                body_parts.append(f'<span class="two-col-right">{html.escape(dates)}</span>')
            body_parts.append('</div>')

            # Company on left, Location on right
            if company_name or loc:
                body_parts.append('<div class="sub-line">')
                body_parts.append(f'<span class="sub-left">{html.escape(company_name)}</span>')
                if loc:
                    body_parts.append(f'<span class="sub-right">{html.escape(loc)}</span>')
                body_parts.append('</div>')

            # Bullets
            if bullets:
                body_parts.append('<ul class="bullet-list">')
                for b in bullets:
                    b_clean = sanitize_text(b)
                    if b_clean and len(b_clean) > 5:
                        body_parts.append(f'<li class="bullet-item">{html.escape(b_clean)}</li>')
                body_parts.append('</ul>')

            body_parts.append('</div>')  # /entry-item

    # 5. Education
    education = resume.get("education", [])
    if education:
        body_parts.append('<div class="section-title">Education</div>')
        for edu in education:
            inst = sanitize_text(edu.get("institution", ""))
            deg = sanitize_text(edu.get("degree", ""))
            fld = sanitize_text(edu.get("field", ""))
            gdate = sanitize_text(edu.get("graduation_date", ""))
            gpa = sanitize_text(edu.get("gpa", ""))

            deg_title = f"{deg} in {fld}" if (deg and fld and not deg.lower().endswith("in")) else (deg or fld or inst)
            body_parts.append('<div class="entry-item">')
            body_parts.append('<div class="two-col-line">')
            body_parts.append(f'<span class="two-col-left">{html.escape(deg_title)}</span>')
            if gdate:
                body_parts.append(f'<span class="two-col-right">{html.escape(gdate)}</span>')
            body_parts.append('</div>')

            if inst and deg_title != inst:
                body_parts.append(f'<div class="sub-line"><span class="sub-left">{html.escape(inst)}</span></div>')
            if gpa:
                body_parts.append(f'<div style="font-size: 9.5pt; color: #374151;">GPA: {html.escape(gpa)}</div>')
            body_parts.append('</div>')

    # 6. Certifications
    certs = resume.get("certifications", [])
    if certs:
        body_parts.append('<div class="section-title">Certifications</div>')
        body_parts.append('<ul class="bullet-list">')
        for c in certs:
            c_clean = sanitize_text(c)
            if c_clean:
                body_parts.append(f'<li class="bullet-item">{html.escape(c_clean)}</li>')
        body_parts.append('</ul>')

    # 7. Projects (if present)
    projects = resume.get("projects", [])
    if projects:
        body_parts.append('<div class="section-title">Key Projects</div>')
        for p in projects:
            pname = sanitize_text(p.get("name", ""))
            pdesc = sanitize_text(p.get("description", ""))
            pbullets = p.get("bullets", [])
            body_parts.append('<div class="entry-item">')
            body_parts.append(f'<div class="two-col-left">{html.escape(pname)}</div>')
            if pdesc:
                body_parts.append(f'<p class="summary-text" style="margin-bottom:2px;">{html.escape(pdesc)}</p>')
            if pbullets:
                body_parts.append('<ul class="bullet-list">')
                for b in pbullets:
                    b_clean = sanitize_text(b)
                    if b_clean:
                        body_parts.append(f'<li class="bullet-item">{html.escape(b_clean)}</li>')
                body_parts.append('</ul>')
            body_parts.append('</div>')

    content = "\n".join(body_parts)
    return _get_base_html_template(content, title=f"{name} - Resume")


def docx_to_html(docx_path: str, company: str = "", role: str = "") -> str:
    """
    Parse an existing .docx file and convert it into clean, ATS-styled HTML.
    Extracts headers, 2-column lines (separated by tabs), bullet lists, and runs.
    """
    if not docx_path or not os.path.exists(docx_path):
        return _get_base_html_template("<p>Document not found.</p>")

    try:
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        return _get_base_html_template("<p>python-docx not installed.</p>")

    try:
        doc = Document(docx_path)
    except Exception as e:
        logger.error(f"[DocxToHtml] Error loading docx: {e}")
        return _get_base_html_template(f"<p>Unable to read document: {html.escape(str(e))}</p>")

    body_parts = []
    in_bullet_list = False

    for para in doc.paragraphs:
        raw_text = para.text.strip()
        if not raw_text:
            if in_bullet_list:
                body_parts.append("</ul>")
                in_bullet_list = False
            continue

        style_name = para.style.name.lower()
        is_bullet = "bullet" in style_name or raw_text.startswith(('•', '·', '▪', '-', '*'))

        # Check if it's a section header (bordered paragraph or short uppercase text)
        is_header = False
        pPr = para._p.get_or_add_pPr()
        if pPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pBdr') is not None:
            is_header = True
        elif raw_text.isupper() and len(raw_text) < 40 and '@' not in raw_text and not raw_text.startswith('HTTP'):
            is_header = True

        if is_header:
            if in_bullet_list:
                body_parts.append("</ul>")
                in_bullet_list = False

            # Check if it's the candidate's name at the very top
            if len(body_parts) == 0 and len(raw_text) < 35:
                body_parts.append('<div class="resume-header">')
                body_parts.append(f'<div class="candidate-name">{html.escape(raw_text)}</div>')
                continue
            else:
                body_parts.append(f'<div class="section-title">{html.escape(raw_text)}</div>')
                continue

        # Handle bullets
        if is_bullet:
            if not in_bullet_list:
                body_parts.append('<ul class="bullet-list">')
                in_bullet_list = True
            clean_b = sanitize_text(raw_text)
            body_parts.append(f'<li class="bullet-item">{html.escape(clean_b)}</li>')
            continue

        # If we reach here and was in bullet list, close it
        if in_bullet_list:
            body_parts.append("</ul>")
            in_bullet_list = False

        # Two-column row check (separated by tab \t)
        if "\t" in raw_text:
            parts = [p.strip() for p in raw_text.split("\t") if p.strip()]
            left = parts[0] if parts else ""
            right = parts[1] if len(parts) > 1 else ""

            # Check if italicized (sub-line e.g. company/location) or bold (role/dates)
            has_bold = any(r.bold for r in para.runs if r.bold)
            has_italic = any(r.italic for r in para.runs if r.italic)

            if has_bold or not has_italic:
                body_parts.append('<div class="two-col-line">')
                body_parts.append(f'<span class="two-col-left">{html.escape(left)}</span>')
                if right:
                    body_parts.append(f'<span class="two-col-right">{html.escape(right)}</span>')
                body_parts.append('</div>')
            else:
                body_parts.append('<div class="sub-line">')
                body_parts.append(f'<span class="sub-left">{html.escape(left)}</span>')
                if right:
                    body_parts.append(f'<span class="sub-right">{html.escape(right)}</span>')
                body_parts.append('</div>')
            continue

        # Centered text (Role, contact info)
        is_center = para.alignment == WD_ALIGN_PARAGRAPH.CENTER
        if is_center or len(body_parts) <= 3:
            # Check if contact line with pipes or separators
            if "@" in raw_text or "|" in raw_text or "linkedin" in raw_text.lower():
                parts = [p.strip() for p in re.split(r'\s*\|\s*', raw_text) if p.strip()]
                c_html = []
                for p in parts:
                    if "@" in p and not p.startswith("http"):
                        c_html.append(f'<a href="mailto:{html.escape(p)}">{html.escape(p)}</a>')
                    elif "http" in p or "linkedin" in p or "github" in p:
                        url = p if p.startswith("http") else f"https://{p}"
                        c_html.append(f'<a href="{url}" target="_blank">{html.escape(p)}</a>')
                    else:
                        c_html.append(f'<span>{html.escape(p)}</span>')
                sep = '<span class="contact-sep">|</span>'
                body_parts.append(f'<div class="contact-line" style="margin-bottom: 8px;">{sep.join(c_html)}</div>')
                if len(body_parts) == 2:
                    body_parts.append('</div>')  # close initial header if open
                continue
            elif len(body_parts) == 1 and not is_header:
                # Target role right under name
                body_parts.append(f'<div class="target-role">{html.escape(raw_text)}</div>')
                continue

        # Category line check (e.g. "Languages: Python, Java...")
        colon_idx = raw_text.find(":")
        if colon_idx > 0 and colon_idx < 30 and not raw_text.startswith("http"):
            cat_label = raw_text[:colon_idx + 1]
            cat_rest = raw_text[colon_idx + 1:].strip()
            body_parts.append(
                f'<div class="skill-category"><span class="skill-category-label">{html.escape(cat_label)}</span> {html.escape(cat_rest)}</div>'
            )
            continue

        # Normal paragraph
        body_parts.append(f'<p class="summary-text">{html.escape(raw_text)}</p>')

    if in_bullet_list:
        body_parts.append("</ul>")

    content = "\n".join(body_parts)
    title = f"{Path(docx_path).stem.replace('_', ' ')} - Resume"
    return _get_base_html_template(content, title=title)


def generate_pdf_from_html(html_content: str, output_pdf_path: str) -> bool:
    """
    Generate an authentic PDF file from an HTML resume string using Playwright headless Chromium.
    Works natively on Render Linux, Docker, and Windows without Word COM!
    """
    try:
        from playwright.sync_api import sync_playwright
        Path(output_pdf_path).parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"]
            )
            page = browser.new_page()
            page.set_content(html_content, wait_until="networkidle")
            page.pdf(
                path=output_pdf_path,
                format="Letter",
                print_background=True,
                margin={
                    "top": "0.5in",
                    "bottom": "0.5in",
                    "left": "0.55in",
                    "right": "0.55in"
                }
            )
            browser.close()
        return os.path.exists(output_pdf_path) and os.path.getsize(output_pdf_path) > 1000
    except Exception as e:
        logger.error(f"[HtmlToPdf] Playwright PDF generation failed: {e}")
        return False
