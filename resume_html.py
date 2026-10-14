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
    """Sanitize and strip characters that break ATS parsing and fix encoding corruptions."""
    if not text:
        return ""
    text = str(text)
    # Fix CP1252 / UTF-8 character corruptions
    text = text.replace('\u2014', '-').replace('\u2013', '-')
    text = text.replace('\u2019', "'").replace('\u2018', "'")
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    text = text.replace('\u2026', '...')
    text = text.replace('â€“', '-').replace('â€”', '-').replace('â€"', '-')
    text = text.replace('â€™', "'").replace('â€˜', "'").replace('â€œ', '"').replace('â€\x9d', '"')
    text = text.replace('\ufffd', '')
    text = re.sub(r'^[•·▪▸►\*]\s*', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _get_base_html_template(body_content: str, title: str = "Resume Preview", editor_styles: dict = None) -> str:
    """Wrap resume body in an authentic, printable paper sheet layout with 100% cross-platform parity."""
    styles = editor_styles or {}
    typo = styles.get("typography", {})
    spacing = styles.get("spacing", {})
    colors = styles.get("colors", {})
    page = styles.get("page", {})

    font_family = typo.get("fontFamily") or "'Carlito', 'Calibri', 'Segoe UI', Arial, -apple-system, sans-serif"
    if font_family in ("Carlito", "Arial", "Georgia", "Garamond", "Roboto", "Inter", "Lato", "Open Sans", "Times New Roman", "Playfair Display", "Montserrat"):
        font_family = f"'{font_family}', 'Calibri', 'Segoe UI', Arial, sans-serif"
    font_size = typo.get("fontSize") or "9.5pt"
    if isinstance(font_size, (int, float)) or (isinstance(font_size, str) and font_size.replace(".", "").isdigit()):
        font_size = f"{font_size}pt"
    line_height = str(typo.get("lineHeight") or "1.22")
    letter_spacing = str(typo.get("letterSpacing") or "0px")

    section_gap = spacing.get("sectionGap") or "6px"
    if isinstance(section_gap, (int, float)) or (isinstance(section_gap, str) and section_gap.isdigit()):
        section_gap = f"{section_gap}px"
    entry_gap = spacing.get("entryGap") or "4px"
    if isinstance(entry_gap, (int, float)) or (isinstance(entry_gap, str) and entry_gap.isdigit()):
        entry_gap = f"{entry_gap}px"
    bullet_gap = spacing.get("bulletGap") or "1px"
    if isinstance(bullet_gap, (int, float)) or (isinstance(bullet_gap, str) and bullet_gap.isdigit()):
        bullet_gap = f"{bullet_gap}px"

    text_color = colors.get("text") or "#000000"
    line_color = colors.get("border") or colors.get("line") or "#111827"
    link_color = colors.get("link") or "#1a56db"

    margin_t = page.get("marginTop") or "0.35in"
    margin_b = page.get("marginBottom") or "0.35in"
    margin_l = page.get("marginLeft") or "0.45in"
    margin_r = page.get("marginRight") or "0.45in"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(title)}</title>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Carlito:ital,wght@0,400;0,700;1,400;1,700&family=Inter:wght@400;500;600;700&family=Roboto:wght@400;500;700&family=Lato:wght@400;700&family=Open+Sans:wght@400;600;700&family=Playfair+Display:wght@400;700&family=Montserrat:wght@400;600;700&display=swap">
  <style>
    :root {{
      --page-bg: #1e222d;
      --paper-bg: #ffffff;
      --text-main: {text_color};
      --text-muted: #374151;
      --text-subtle: #4b5563;
      --line-color: {line_color};
      --font-family: {font_family};
      --resume-base-size: {font_size};
      --resume-line-height: {line_height};
      --resume-letter-spacing: {letter_spacing};
      --resume-section-gap: {section_gap};
      --resume-entry-gap: {entry_gap};
      --resume-bullet-gap: {bullet_gap};
      --resume-link-color: {link_color};
      --paper-margin-t: {margin_t};
      --paper-margin-b: {margin_b};
      --paper-margin-l: {margin_l};
      --paper-margin-r: {margin_r};
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
      padding: 20px 16px;
      min-height: 100vh;
      -webkit-font-smoothing: antialiased;
    }}

    .resume-sheet {{
      background: var(--paper-bg);
      width: 100%;
      max-width: 8.5in;
      min-height: 11in;
      padding: var(--paper-margin-t) var(--paper-margin-r) var(--paper-margin-b) var(--paper-margin-l);
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
      border-radius: 4px;
      font-size: var(--resume-base-size);
      line-height: var(--resume-line-height);
      letter-spacing: var(--resume-letter-spacing);
      color: var(--text-main);
    }}

    /* Header */
    .resume-header {{
      text-align: center;
      margin-bottom: 5px;
    }}

    .candidate-name {{
      font-size: 19pt;
      font-weight: 700;
      letter-spacing: 0.5px;
      text-transform: uppercase;
      color: #000000;
      margin-bottom: 2px;
    }}

    .target-role {{
      font-size: 11pt;
      font-weight: 500;
      font-style: italic;
      text-align: center;
      color: #1f2937;
      margin-bottom: 2.5px;
    }}

    .contact-line {{
      font-size: 9pt;
      color: #2b2f38;
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      align-items: center;
      gap: 4px 8px;
      margin-bottom: 2px;
    }}

    .contact-line a {{
      color: var(--resume-link-color);
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
      font-size: 10pt;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      color: var(--text-main);
      border-bottom: 1px solid var(--line-color);
      padding-bottom: 1px;
      margin-top: var(--resume-section-gap);
      margin-bottom: 2px;
      break-after: avoid !important;
      page-break-after: avoid !important;
    }}

    /* Summary */
    .summary-text {{
      font-size: var(--resume-base-size);
      line-height: var(--resume-line-height);
      letter-spacing: var(--resume-letter-spacing);
      color: var(--text-main);
      margin-bottom: 3px;
      text-align: left;
    }}

    /* Experience & Education Entries */
    .entry-item {{
      margin-bottom: var(--resume-entry-gap);
      break-inside: avoid !important;
      page-break-inside: avoid !important;
    }}

    .two-col-line {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      width: 100%;
      margin-top: 1.5px;
      margin-bottom: 1px;
      break-after: avoid !important;
      page-break-after: avoid !important;
      break-inside: avoid !important;
      page-break-inside: avoid !important;
    }}

    .two-col-left {{
      font-size: var(--resume-base-size);
      font-weight: 700;
      color: var(--text-main);
      text-align: left;
    }}

    .two-col-right {{
      font-size: 9pt;
      font-weight: 600;
      color: #111827;
      text-align: right;
      white-space: nowrap;
      margin-left: 12px;
    }}

    .sub-line {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      font-size: 9pt;
      color: #1f2937;
      margin-bottom: 1.5px;
      break-after: avoid !important;
      page-break-after: avoid !important;
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
      margin-left: 1.1rem;
      margin-top: 1px;
      margin-bottom: 2.5px;
      orphans: 2;
      widows: 2;
    }}

    .bullet-item {{
      font-size: var(--resume-base-size);
      line-height: var(--resume-line-height);
      letter-spacing: var(--resume-letter-spacing);
      color: var(--text-main);
      margin-bottom: var(--resume-bullet-gap);
      padding-left: 2px;
      break-inside: avoid !important;
      page-break-inside: avoid !important;
      text-align: left;
    }}

    /* Skills Categories */
    .skill-category {{
      font-size: 9pt;
      line-height: 1.25;
      margin-bottom: 1.5px;
      color: #111827;
      break-inside: avoid !important;
      page-break-inside: avoid !important;
    }}

    .skill-category-label {{
      font-weight: 700;
      color: #000000;
    }}

    /* Compact Fit Class for Single-Page Optimization */
    body.compact-fit .resume-sheet {{
      padding: 0.30in 0.40in !important;
      font-size: 9.2pt !important;
      line-height: 1.18 !important;
    }}
    body.compact-fit .section-title {{
      margin-top: 4px !important;
      margin-bottom: 1.5px !important;
      font-size: 9.5pt !important;
    }}
    body.compact-fit .summary-text,
    body.compact-fit .bullet-item {{
      font-size: 9.2pt !important;
      line-height: 1.18 !important;
      margin-bottom: 0.8px !important;
    }}
    body.compact-fit .bullet-list {{
      margin-top: 0.5px !important;
      margin-bottom: 1.5px !important;
    }}
    body.compact-fit .entry-item {{
      margin-bottom: 2.5px !important;
    }}

    /* Print media styling */
    @media print {{
      html, body {{
        background: transparent !important;
        padding: 0 !important;
        margin: 0 !important;
        min-height: auto !important;
        -webkit-print-color-adjust: exact !important;
        print-color-adjust: exact !important;
      }}
      .resume-sheet {{
        box-shadow: none !important;
        border-radius: 0 !important;
        padding: 0.35in 0.45in !important;
        max-width: 100% !important;
        width: 100% !important;
        min-height: auto !important;
      }}
      body.compact-fit .resume-sheet {{
        padding: 0.28in 0.38in !important;
      }}
      .entry-item, .exp-item, .edu-item, .proj-item {{
        break-inside: avoid !important;
        page-break-inside: avoid !important;
      }}
      .section-title {{
        break-after: avoid !important;
        page-break-after: avoid !important;
      }}
      .two-col-line, .sub-line {{
        break-after: avoid !important;
        page-break-after: avoid !important;
        break-inside: avoid !important;
        page-break-inside: avoid !important;
      }}
      .bullet-item {{
        break-inside: avoid !important;
        page-break-inside: avoid !important;
      }}
      .bullet-list {{
        orphans: 2 !important;
        widows: 2 !important;
      }}
      @page {{
        size: letter;
        margin: 0;
      }}
    }}

    /* Live Paper Editor Styles */
    body.editor-mode-active [contenteditable="true"] {{
      transition: background 0.12s ease, outline 0.12s ease;
      cursor: text !important;
      border-radius: 2px;
      min-height: 1.1em;
    }}
    body.editor-mode-active a {{
      cursor: text !important;
    }}
    body.editor-mode-active [contenteditable="true"]:hover {{
      outline: 1.5px dashed rgba(2, 132, 199, 0.45) !important;
      background: rgba(2, 132, 199, 0.04) !important;
    }}
    body.editor-mode-active [contenteditable="true"]:focus {{
      outline: 2px solid #0284c7 !important;
      background: rgba(2, 132, 199, 0.07) !important;
      box-shadow: 0 0 6px rgba(2, 132, 199, 0.25) !important;
    }}
    body.editor-mode-active .bullet-item:empty:before {{
      content: "Type new bullet point here...";
      color: #9ca3af;
      font-style: italic;
    }}
  </style>
</head>
<body class="editor-mode-active">
  <div class="resume-sheet">
    {body_content}
  </div>
  <script>
    function enableEditor(active) {{
      var selector = "[data-edit], .section-title, .candidate-name, .target-role, .two-col-left, .two-col-right, .sub-left, .sub-right, .bullet-item, .summary-text, .skill-category-list, .skill-category-label, .contact-line, .contact-line a, .contact-line span:not(.contact-sep), .gpa-line, p, li, h1, h2, h3, h4";
      if (active) {{
        document.body.classList.add("editor-mode-active");
        document.querySelectorAll(selector).forEach(function(el) {{
          if (!el.classList.contains("contact-sep") && el.tagName !== "UL") {{
            el.setAttribute("contenteditable", "true");
            el.setAttribute("spellcheck", "false");
          }}
        }});
        // Ensure every leaf text node inside resume sheet is editable so no section/word is locked
        var sheet = document.querySelector(".resume-sheet");
        if (sheet) {{
          sheet.querySelectorAll("*").forEach(function(el) {{
            if (el.classList.contains("contact-sep") || el.tagName === "UL" || el.children.length > 0) return;
            if (el.innerText && el.innerText.trim().length > 0) {{
              el.setAttribute("contenteditable", "true");
              el.setAttribute("spellcheck", "false");
            }}
          }});
        }}
      }} else {{
        document.body.classList.remove("editor-mode-active");
        document.querySelectorAll('[contenteditable="true"]').forEach(function(el) {{
          el.removeAttribute("contenteditable");
        }});
      }}
    }}

    // Intercept clicks on links in editor mode so clicking focuses text for inline editing instead of navigating away
    document.addEventListener("click", function(e) {{
      if (document.body.classList.contains("editor-mode-active")) {{
        var a = e.target.closest("a");
        if (a) {{
          e.preventDefault();
          e.stopPropagation();
          a.focus();
        }}
      }}
    }}, true);

    if (!window.matchMedia || !window.matchMedia('print').matches) {{
      enableEditor(true);
    }}

    var _undoStack = [];
    var _redoStack = [];
    var _isRestoring = false;
    var _lastSnapshot = null;
    var _snapshotTimer = null;

    function notifyUndoState() {{
      if (window.parent && typeof window.parent.updateUndoRedoButtons === "function") {{
        window.parent.updateUndoRedoButtons(_undoStack.length, _redoStack.length);
      }}
    }}

    function captureSnapshot(immediate) {{
      if (_isRestoring) return;
      var sheet = document.querySelector(".resume-sheet");
      if (!sheet) return;

      var currentHTML = sheet.innerHTML;
      if (_lastSnapshot === null) {{
        _lastSnapshot = currentHTML;
        return;
      }}
      if (currentHTML === _lastSnapshot) return;

      var doPush = function() {{
        if (_lastSnapshot !== null && currentHTML !== _lastSnapshot) {{
          _undoStack.push(_lastSnapshot);
          if (_undoStack.length > 50) _undoStack.shift();
          _redoStack = [];
          _lastSnapshot = currentHTML;
          notifyUndoState();
        }}
      }};

      if (immediate) {{
        if (_snapshotTimer) clearTimeout(_snapshotTimer);
        doPush();
      }} else {{
        if (_snapshotTimer) clearTimeout(_snapshotTimer);
        _snapshotTimer = setTimeout(doPush, 350);
      }}
    }}

    function docUndo() {{
      if (_undoStack.length === 0) return false;
      var sheet = document.querySelector(".resume-sheet");
      if (!sheet) return false;

      var currentHTML = sheet.innerHTML;
      _redoStack.push(currentHTML);
      var prev = _undoStack.pop();
      _isRestoring = true;
      sheet.innerHTML = prev;
      _lastSnapshot = prev;
      enableEditor(true);
      _isRestoring = false;
      notifyUndoState();
      if (window.parent && typeof window.parent.onPreviewDocEdited === "function") {{
        window.parent.onPreviewDocEdited();
      }}
      return true;
    }}

    function docRedo() {{
      if (_redoStack.length === 0) return false;
      var sheet = document.querySelector(".resume-sheet");
      if (!sheet) return false;

      var currentHTML = sheet.innerHTML;
      _undoStack.push(currentHTML);
      var next = _redoStack.pop();
      _isRestoring = true;
      sheet.innerHTML = next;
      _lastSnapshot = next;
      enableEditor(true);
      _isRestoring = false;
      notifyUndoState();
      if (window.parent && typeof window.parent.onPreviewDocEdited === "function") {{
        window.parent.onPreviewDocEdited();
      }}
      return true;
    }}

    window.docUndo = docUndo;
    window.docRedo = docRedo;

    setTimeout(function() {{
      var sheet = document.querySelector(".resume-sheet");
      if (sheet) _lastSnapshot = sheet.innerHTML;
      notifyUndoState();
    }}, 120);

    document.addEventListener("input", function() {{
      captureSnapshot(false);
      if (window.parent && typeof window.parent.onPreviewDocEdited === "function") {{
        window.parent.onPreviewDocEdited();
      }}
    }});

    document.addEventListener("keydown", function(e) {{
      // Ctrl+S / Cmd+S: Save
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {{
        e.preventDefault();
        if (window.parent && typeof window.parent.savePreviewEdits === "function") {{
          window.parent.savePreviewEdits();
        }}
        return;
      }}

      // Ctrl+Z / Cmd+Z: Undo
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key === "z" || e.key === "Z")) {{
        e.preventDefault();
        docUndo();
        return;
      }}

      // Ctrl+Y / Cmd+Y / Ctrl+Shift+Z: Redo
      if ((e.ctrlKey || e.metaKey) && (e.key === "y" || e.key === "Y" || (e.shiftKey && (e.key === "z" || e.key === "Z")))) {{
        e.preventDefault();
        docRedo();
        return;
      }}

      var activeEl = document.activeElement;
      if (!activeEl) return;

      if (e.key === "Enter" && !e.shiftKey) {{
        if (activeEl.classList.contains("bullet-item") || activeEl.tagName === "LI") {{
          e.preventDefault();
          captureSnapshot(true);
          var newLi = document.createElement("li");
          newLi.className = "bullet-item";
          newLi.setAttribute("data-edit", "bullet");
          newLi.setAttribute("contenteditable", "true");
          newLi.setAttribute("spellcheck", "false");
          activeEl.parentNode.insertBefore(newLi, activeEl.nextSibling);
          newLi.focus();
          captureSnapshot(true);
          if (window.parent && typeof window.parent.onPreviewDocEdited === "function") {{
            window.parent.onPreviewDocEdited();
          }}
        }} else if (activeEl.classList.contains("section-title") || activeEl.classList.contains("candidate-name") || activeEl.classList.contains("target-role") || activeEl.classList.contains("two-col-left") || activeEl.classList.contains("two-col-right") || activeEl.classList.contains("sub-left") || activeEl.classList.contains("sub-right")) {{
          e.preventDefault();
          activeEl.blur();
        }}
      }} else if (e.key === "Backspace") {{
        if (activeEl.classList.contains("bullet-item") || activeEl.tagName === "LI") {{
          if (!activeEl.innerText.trim()) {{
            var prev = activeEl.previousElementSibling;
            if (prev) {{
              e.preventDefault();
              captureSnapshot(true);
              activeEl.remove();
              prev.focus();
              try {{
                var sel = window.getSelection();
                var range = document.createRange();
                range.selectNodeContents(prev);
                range.collapse(false);
                sel.removeAllRanges();
                sel.addRange(range);
              }} catch (_) {{}}
              captureSnapshot(true);
              if (window.parent && typeof window.parent.onPreviewDocEdited === "function") {{
                window.parent.onPreviewDocEdited();
              }}
            }}
          }}
        }}
      }}
    }});
  </script>
</body>
</html>"""


def resume_json_to_html(
    resume: dict,
    company: str = "",
    role: str = "",
    editor_styles: dict = None,
    editable: bool = False,
) -> str:
    """
    Convert a structured resume dictionary (base_resume.json / tailored_resume.json)
    into a high-fidelity HTML document with 100% pixel-perfect editor and PDF parity.
    Supports dynamic style overrides (fonts, sizes, gaps, margins) and section reordering.
    """
    if not isinstance(resume, dict):
        return _get_base_html_template("<p>Invalid resume data.</p>", editor_styles=editor_styles)

    if editor_styles is None:
        editor_styles = resume.get("editor_styles") or {}

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

    # 1. Header Block
    header_lines = []
    if editable:
        header_lines.append('<div class="editor-block" data-block-id="header" data-block-type="header">')
    header_lines.append('<div class="resume-header">')
    header_lines.append(f'<div class="candidate-name" data-edit="name">{html.escape(name.upper())}</div>')
    if clean_role:
        header_lines.append(f'<div class="target-role" data-edit="target_role">{html.escape(clean_role)}</div>')

    # Contact line
    contact_parts = []
    seen_contacts = set()

    email_val = contact.get("email")
    if email_val:
        em = html.escape(str(email_val).strip())
        contact_parts.append(f'<a href="mailto:{em}" data-edit="contact-email">{em}</a>')
        seen_contacts.add(em.lower())

    phone_val = str(contact.get("phone") or "").strip()
    if phone_val:
        if any(k in phone_val.lower() for k in ("linkedin", "http", "github", "www.", ".com")) or re.search(r'[a-zA-Z]', phone_val):
            if not contact.get("linkedin") and "linkedin" in phone_val.lower():
                contact["linkedin"] = phone_val
            phone_val = ""
        elif phone_val.lower() not in seen_contacts:
            ph = html.escape(phone_val)
            contact_parts.append(f'<a href="tel:{ph}" data-edit="contact-phone">{ph}</a>')
            seen_contacts.add(phone_val.lower())

    loc_val = contact.get("location")
    if loc_val:
        loc_str = str(loc_val).strip()
        if loc_str.lower() not in seen_contacts:
            contact_parts.append(f'<span data-edit="contact-location">{html.escape(loc_str)}</span>')
            seen_contacts.add(loc_str.lower())

    li_val = contact.get("linkedin")
    if li_val:
        li_str = str(li_val).strip()
        if li_str.lower().rstrip('/') not in seen_contacts:
            li_esc = html.escape(li_str)
            url = li_str if li_str.startswith("http") else f"https://{li_str}"
            contact_parts.append(f'<a href="{url}" target="_blank" data-edit="contact-linkedin">{li_esc}</a>')
            seen_contacts.add(li_str.lower().rstrip('/'))

    gh_val = contact.get("github")
    if gh_val:
        gh_str = str(gh_val).strip()
        if gh_str.lower().rstrip('/') not in seen_contacts:
            gh_esc = html.escape(gh_str)
            url = gh_str if gh_str.startswith("http") else f"https://{gh_str}"
            contact_parts.append(f'<a href="{url}" target="_blank" data-edit="contact-github">{gh_esc}</a>')
            seen_contacts.add(gh_str.lower().rstrip('/'))

    pf_val = contact.get("portfolio")
    if pf_val:
        pf_str = str(pf_val).strip()
        if pf_str.lower().rstrip('/') not in seen_contacts:
            pf_esc = html.escape(pf_str)
            url = pf_str if pf_str.startswith("http") else f"https://{pf_str}"
            contact_parts.append(f'<a href="{url}" target="_blank" data-edit="contact-portfolio">{pf_esc}</a>')
            seen_contacts.add(pf_str.lower().rstrip('/'))

    if contact_parts:
        sep = '<span class="contact-sep">|</span>'
        header_lines.append(f'<div class="contact-line">{sep.join(contact_parts)}</div>')
    header_lines.append('</div>')  # /resume-header
    if editable:
        header_lines.append('</div>')  # /editor-block
    body_parts.append("\n".join(header_lines))

    headings = resume.get("section_headings", {})
    summary_title = sanitize_text(headings.get("summary", "Professional Summary")) or "Professional Summary"
    skills_title = sanitize_text(headings.get("skills", "Technical Skills")) or "Technical Skills"
    exp_title = sanitize_text(headings.get("experience", "Professional Experience")) or "Professional Experience"
    edu_title = sanitize_text(headings.get("education", "Education")) or "Education"
    cert_title = sanitize_text(headings.get("certifications", "Certifications")) or "Certifications"
    proj_title = sanitize_text(headings.get("projects", "Key Projects")) or "Key Projects"

    # Section renderers
    def _render_summary() -> str:
        if not summary:
            return ""
        lines = []
        if editable:
            lines.append('<div class="editor-block" data-block-id="section-summary" data-block-type="summary">')
        lines.append(f'<div class="section-title" data-edit="section-heading" data-section="summary">{html.escape(summary_title)}</div>')
        lines.append(f'<p class="summary-text" data-edit="summary">{html.escape(summary)}</p>')
        if editable:
            lines.append('</div>')
        return "\n".join(lines)

    def _render_skills() -> str:
        skills = resume.get("skills", [])
        if not skills:
            return ""
        lines = []
        if editable:
            lines.append('<div class="editor-block" data-block-id="section-skills" data-block-type="skills">')
        lines.append(f'<div class="section-title" data-edit="section-heading" data-section="skills">{html.escape(skills_title)}</div>')
        from resume_builder import _categorize_skills
        categorized = _categorize_skills(skills)
        for cat_name, cat_skills in categorized.items():
            if cat_skills:
                skills_str = ", ".join(cat_skills)
                lines.append(
                    f'<div class="skill-category" data-cat="{html.escape(cat_name)}"><span class="skill-category-label" data-edit="skill-cat-label">{html.escape(cat_name)}:</span> <span class="skill-category-list" data-edit="skills-list">{html.escape(skills_str)}</span></div>'
                )
        if editable:
            lines.append('</div>')
        return "\n".join(lines)

    def _render_experience() -> str:
        experience = resume.get("experience", [])
        if not experience:
            return ""
        lines = []
        if editable:
            lines.append('<div class="editor-block" data-block-id="section-experience" data-block-type="experience">')
        lines.append(f'<div class="section-title" data-edit="section-heading" data-section="experience">{html.escape(exp_title)}</div>')
        for exp_idx, exp in enumerate(experience):
            title = sanitize_text(exp.get("title") or exp.get("role") or "")
            company_name = sanitize_text(exp.get("company", ""))
            dates = sanitize_text(exp.get("dates") or exp.get("date") or exp.get("period") or exp.get("duration") or "")
            if not dates and exp.get("start_date"):
                dates = sanitize_text(f"{exp.get('start_date')} - {exp.get('end_date', 'Present')}")
            loc = sanitize_text(exp.get("location", ""))

            # Robust fallback: if dates missing, search base_resume inside resume dict
            if not dates and company_name:
                base_exp = (resume.get("base_resume", {}) or {}).get("experience", []) or resume.get("_orig_experience", [])
                for b_item in base_exp:
                    b_comp = b_item.get("company", "").strip().lower()
                    if b_comp and (b_comp in company_name.lower() or company_name.lower() in b_comp):
                        dates = sanitize_text(b_item.get("dates") or b_item.get("date") or "")
                        if not loc:
                            loc = sanitize_text(b_item.get("location", ""))
                        break
            bullets = exp.get("bullets", [])

            entry_wrap = f'<div class="entry-item exp-item" data-exp-index="{exp_idx}">'
            if editable:
                entry_wrap = f'<div class="entry-item exp-item editor-block" data-block-id="exp-{exp_idx}" data-block-type="experience-entry" data-exp-index="{exp_idx}">'
            lines.append(entry_wrap)
            lines.append('<div class="two-col-line">')
            lines.append(f'<span class="two-col-left role-title" data-edit="exp-title">{html.escape(title)}</span>')
            if dates:
                lines.append(f'<span class="two-col-right role-dates" data-edit="exp-dates">{html.escape(dates)}</span>')
            lines.append('</div>')

            if company_name or loc:
                lines.append('<div class="sub-line">')
                lines.append(f'<span class="sub-left role-company" data-edit="exp-company">{html.escape(company_name)}</span>')
                if loc:
                    lines.append(f'<span class="sub-right role-location" data-edit="exp-loc">{html.escape(loc)}</span>')
                lines.append('</div>')

            if bullets:
                lines.append('<ul class="bullet-list" data-edit="bullet-list">')
                for b in bullets:
                    b_clean = sanitize_text(b)
                    if b_clean and len(b_clean) > 5:
                        lines.append(f'<li class="bullet-item" data-edit="bullet">{html.escape(b_clean)}</li>')
                lines.append('</ul>')
            lines.append('</div>')  # /entry-item
        if editable:
            lines.append('</div>')
        return "\n".join(lines)

    def _render_education() -> str:
        education = resume.get("education", [])
        if not education:
            return ""
        lines = []
        if editable:
            lines.append('<div class="editor-block" data-block-id="section-education" data-block-type="education">')
        lines.append(f'<div class="section-title" data-edit="section-heading" data-section="education">{html.escape(edu_title)}</div>')
        for edu in education:
            inst = sanitize_text(edu.get("institution", ""))
            deg = sanitize_text(edu.get("degree", ""))
            fld = sanitize_text(edu.get("field", ""))
            gdate = sanitize_text(edu.get("graduation_date") or edu.get("grad_date") or edu.get("date") or edu.get("year") or "")
            gpa = sanitize_text(edu.get("gpa", ""))

            deg_title = f"{deg} in {fld}" if (deg and fld and not deg.lower().endswith("in")) else (deg or fld or inst)
            lines.append('<div class="entry-item">')
            lines.append('<div class="two-col-line">')
            lines.append(f'<span class="two-col-left" data-edit="edu-degree">{html.escape(deg_title)}</span>')
            if gdate:
                lines.append(f'<span class="two-col-right" data-edit="edu-date">{html.escape(gdate)}</span>')
            lines.append('</div>')

            if inst and deg_title != inst:
                lines.append(f'<div class="sub-line"><span class="sub-left" data-edit="edu-school">{html.escape(inst)}</span></div>')
            if gpa:
                lines.append(f'<div class="gpa-line" data-edit="edu-gpa" style="font-size: 9.5pt; color: #374151;">GPA: {html.escape(gpa)}</div>')
            lines.append('</div>')
        if editable:
            lines.append('</div>')
        return "\n".join(lines)

    def _render_certifications() -> str:
        certs = resume.get("certifications", [])
        if not certs:
            return ""
        lines = []
        if editable:
            lines.append('<div class="editor-block" data-block-id="section-certifications" data-block-type="certifications">')
        lines.append(f'<div class="section-title" data-edit="section-heading" data-section="certifications">{html.escape(cert_title)}</div>')
        lines.append('<ul class="bullet-list">')
        for c in certs:
            c_clean = sanitize_text(c)
            if c_clean:
                lines.append(f'<li class="bullet-item" data-edit="bullet">{html.escape(c_clean)}</li>')
        lines.append('</ul>')
        if editable:
            lines.append('</div>')
        return "\n".join(lines)

    def _render_projects() -> str:
        projects = resume.get("projects", [])
        if not projects:
            return ""
        lines = []
        if editable:
            lines.append('<div class="editor-block" data-block-id="section-projects" data-block-type="projects">')
        lines.append(f'<div class="section-title" data-edit="section-heading" data-section="projects">{html.escape(proj_title)}</div>')
        for p in projects:
            pname = sanitize_text(p.get("name", ""))
            pdesc = sanitize_text(p.get("description", ""))
            pbullets = p.get("bullets", [])
            lines.append('<div class="entry-item">')
            lines.append(f'<div class="two-col-left" data-edit="proj-name">{html.escape(pname)}</div>')
            if pdesc:
                lines.append(f'<p class="summary-text" data-edit="proj-desc" style="margin-bottom:2px;">{html.escape(pdesc)}</p>')
            if pbullets:
                lines.append('<ul class="bullet-list">')
                for b in pbullets:
                    b_clean = sanitize_text(b)
                    if b_clean:
                        lines.append(f'<li class="bullet-item" data-edit="bullet">{html.escape(b_clean)}</li>')
                lines.append('</ul>')
            lines.append('</div>')
        if editable:
            lines.append('</div>')
        return "\n".join(lines)

    section_renderers = {
        "summary": _render_summary,
        "skills": _render_skills,
        "experience": _render_experience,
        "education": _render_education,
        "certifications": _render_certifications,
        "projects": _render_projects,
    }

    order = (editor_styles or {}).get("sectionOrder") or [
        "summary", "skills", "experience", "education", "certifications", "projects"
    ]
    for sec_id in order:
        renderer = section_renderers.get(sec_id)
        if renderer:
            sec_html = renderer()
            if sec_html:
                body_parts.append(sec_html)

    content = "\n".join(body_parts)
    return _get_base_html_template(content, title=f"{name} - Resume", editor_styles=editor_styles)


def _iter_table_paragraphs(table):
    """Recursively yield all paragraphs in all table cells."""
    for row in table.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                yield para
            for nested_table in cell.tables:
                yield from _iter_table_paragraphs(nested_table)


def _get_all_paragraphs_from_doc(doc):
    """Yield all paragraphs from body AND table cells in visual document flow order."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in doc.element.body:
        tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
        if tag == 'p':
            yield Paragraph(child, doc)
        elif tag == 'tbl':
            yield from _iter_table_paragraphs(Table(child, doc))


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
    header_open = False
    header_done = False
    candidate_name_done = False
    seen_contact_items = set()

    try:
        paras = list(_get_all_paragraphs_from_doc(doc))
    except Exception:
        paras = list(doc.paragraphs)

    for para in paras:
        raw_text = para.text.strip()
        if not raw_text:
            if in_bullet_list:
                body_parts.append("</ul>")
                in_bullet_list = False
            continue

        style_name = para.style.name.lower() if para.style and para.style.name else ""
        has_numPr = False
        try:
            pPr = para._p.pPr
            if pPr is not None and pPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr') is not None:
                has_numPr = True
        except Exception:
            pass

        is_bullet = (
            "bullet" in style_name
            or "list" in style_name
            or has_numPr
            or raw_text.startswith(('•', '·', '▪', '▸', '►', '*', '- '))
        )

        # 1. The very first non-empty paragraph of the document is ALWAYS the Candidate Name
        if not candidate_name_done:
            body_parts.append('<div class="resume-header">')
            body_parts.append(f'<div class="candidate-name" data-edit="name">{html.escape(raw_text)}</div>')
            header_open = True
            candidate_name_done = True
            continue

        # Check if it's a section header (bordered paragraph or short uppercase text)
        is_header = False
        pPr = para._p.get_or_add_pPr()
        if pPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pBdr') is not None:
            is_header = True
        elif raw_text.isupper() and len(raw_text) < 40 and '@' not in raw_text and not raw_text.startswith('HTTP') and not is_bullet:
            is_header = True

        # Header zone processing (Target role subtitle and contact info at top of resume)
        if not header_done:
            if is_header:
                if header_open:
                    body_parts.append('</div>')
                    header_open = False
                header_done = True
                # Falls through to section header handler below
            else:
                # Inside header between candidate name and first section header
                if "@" in raw_text or "|" in raw_text or "linkedin" in raw_text.lower() or "github" in raw_text.lower() or re.search(r'\+?\d[\d\s\-()]{7,}\d', raw_text):
                    parts = [p.strip() for p in re.split(r'\s*\|\s*', raw_text) if p.strip()]
                    c_html = []
                    for p in parts:
                        norm_p = p.lower().rstrip('/')
                        if norm_p in seen_contact_items:
                            continue
                        if "@" in p and not p.startswith("http"):
                            seen_contact_items.add(norm_p)
                            c_html.append(f'<a href="mailto:{html.escape(p)}" data-edit="contact-email">{html.escape(p)}</a>')
                        elif "linkedin" in p.lower():
                            seen_contact_items.add(norm_p)
                            url = p if p.startswith("http") else f"https://{p}"
                            c_html.append(f'<a href="{url}" target="_blank" data-edit="contact-linkedin">{html.escape(p)}</a>')
                        elif "github" in p.lower():
                            seen_contact_items.add(norm_p)
                            url = p if p.startswith("http") else f"https://{p}"
                            c_html.append(f'<a href="{url}" target="_blank" data-edit="contact-github">{html.escape(p)}</a>')
                        elif "http" in p:
                            seen_contact_items.add(norm_p)
                            url = p if p.startswith("http") else f"https://{p}"
                            c_html.append(f'<a href="{url}" target="_blank" data-edit="contact-portfolio">{html.escape(p)}</a>')
                        elif re.match(r'^\+?[\d\s\-().]{7,}$', p):
                            seen_contact_items.add(norm_p)
                            c_html.append(f'<a href="tel:{html.escape(p)}" data-edit="contact-phone">{html.escape(p)}</a>')
                        else:
                            seen_contact_items.add(norm_p)
                            c_html.append(f'<span data-edit="contact-location">{html.escape(p)}</span>')
                    if c_html:
                        sep = '<span class="contact-sep">|</span>'
                        body_parts.append(f'<div class="contact-line" style="margin-bottom: 4px;">{sep.join(c_html)}</div>')
                    continue
                elif len(raw_text) < 65 and not is_bullet and not any(k in raw_text.lower() for k in ("experience", "education", "summary", "skills", "projects")):
                    # Target role subtitle directly under name
                    from scraper import clean_role_title
                    clean_role = clean_role_title(raw_text)
                    if clean_role.upper() not in ("UNKNOWN", "NONE", "RESUME", ""):
                        body_parts.append(f'<div class="target-role" data-edit="target_role">{html.escape(clean_role)}</div>')
                    continue
                else:
                    if header_open:
                        body_parts.append('</div>')
                        header_open = False
                    header_done = True

    in_exp_section = False
    in_entry_item = False

    DATE_RE = re.compile(
        r'(\b(?:(?:19|20)\d{2}|Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)[a-zA-Z\s,]*[-–—/]\s*(?:(?:19|20)\d{2}|Present|Current)\b|\b(?:19|20)\d{2}\s*[-–—]\s*(?:(?:19|20)\d{2}|Present|Current)\b|\b(?:19|20)\d{2}\b)',
        re.IGNORECASE
    )

    for para in paras:
        raw_text = sanitize_text(para.text)
        if not raw_text:
            if in_bullet_list:
                body_parts.append("</ul>")
                in_bullet_list = False
            continue

        style_name = para.style.name.lower() if para.style and para.style.name else ""
        has_numPr = False
        try:
            pPr = para._p.pPr
            if pPr is not None and pPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr') is not None:
                has_numPr = True
        except Exception:
            pass

        is_bullet = (
            "bullet" in style_name
            or "list" in style_name
            or has_numPr
            or raw_text.startswith(('•', '·', '▪', '▸', '►', '*', '- '))
        )

        # 1. The very first non-empty paragraph of the document is ALWAYS the Candidate Name
        if not candidate_name_done:
            body_parts.append('<div class="resume-header">')
            body_parts.append(f'<div class="candidate-name" data-edit="name">{html.escape(raw_text)}</div>')
            header_open = True
            candidate_name_done = True
            continue

        # Check if it's a section header (bordered paragraph or short uppercase text)
        is_header = False
        pPr = para._p.get_or_add_pPr()
        if pPr.find('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pBdr') is not None:
            is_header = True
        elif raw_text.isupper() and len(raw_text) < 40 and '@' not in raw_text and not raw_text.startswith('HTTP') and not is_bullet:
            is_header = True

        # Header zone processing (Target role subtitle and contact info at top of resume)
        if not header_done:
            if is_header:
                if header_open:
                    body_parts.append('</div>')
                    header_open = False
                header_done = True
                # Falls through to section header handler below
            else:
                # Inside header between candidate name and first section header
                if "@" in raw_text or "|" in raw_text or "linkedin" in raw_text.lower() or "github" in raw_text.lower() or re.search(r'\+?\d[\d\s\-()]{7,}\d', raw_text):
                    parts = [p.strip() for p in re.split(r'\s*\|\s*', raw_text) if p.strip()]
                    c_html = []
                    for p in parts:
                        norm_p = p.lower().rstrip('/')
                        if norm_p in seen_contact_items:
                            continue
                        if "@" in p and not p.startswith("http"):
                            seen_contact_items.add(norm_p)
                            c_html.append(f'<a href="mailto:{html.escape(p)}" data-edit="contact-email">{html.escape(p)}</a>')
                        elif "linkedin" in p.lower():
                            seen_contact_items.add(norm_p)
                            url = p if p.startswith("http") else f"https://{p}"
                            c_html.append(f'<a href="{url}" target="_blank" data-edit="contact-linkedin">{html.escape(p)}</a>')
                        elif "github" in p.lower():
                            seen_contact_items.add(norm_p)
                            url = p if p.startswith("http") else f"https://{p}"
                            c_html.append(f'<a href="{url}" target="_blank" data-edit="contact-github">{html.escape(p)}</a>')
                        elif "http" in p:
                            seen_contact_items.add(norm_p)
                            url = p if p.startswith("http") else f"https://{p}"
                            c_html.append(f'<a href="{url}" target="_blank" data-edit="contact-portfolio">{html.escape(p)}</a>')
                        elif re.match(r'^\+?[\d\s\-().]{7,}$', p):
                            seen_contact_items.add(norm_p)
                            c_html.append(f'<a href="tel:{html.escape(p)}" data-edit="contact-phone">{html.escape(p)}</a>')
                        else:
                            seen_contact_items.add(norm_p)
                            c_html.append(f'<span data-edit="contact-location">{html.escape(p)}</span>')
                    if c_html:
                        sep = '<span class="contact-sep">|</span>'
                        body_parts.append(f'<div class="contact-line" style="margin-bottom: 4px;">{sep.join(c_html)}</div>')
                    continue
                elif len(raw_text) < 65 and not is_bullet and not any(k in raw_text.lower() for k in ("experience", "education", "summary", "skills", "projects")):
                    # Target role subtitle directly under name
                    from scraper import clean_role_title
                    clean_role = clean_role_title(raw_text)
                    if clean_role.upper() not in ("UNKNOWN", "NONE", "RESUME", ""):
                        body_parts.append(f'<div class="target-role" data-edit="target_role">{html.escape(clean_role)}</div>')
                    continue
                else:
                    if header_open:
                        body_parts.append('</div>')
                        header_open = False
                    header_done = True

        if is_header:
            if header_open:
                body_parts.append('</div>')
                header_open = False
            header_done = True
            if in_bullet_list:
                body_parts.append("</ul>")
                in_bullet_list = False
            if in_entry_item:
                body_parts.append("</div>")
                in_entry_item = False

            raw_lower = raw_text.lower()
            in_exp_section = any(k in raw_lower for k in ("experience", "employment", "work history"))

            body_parts.append(f'<div class="section-title" data-edit="section-heading">{html.escape(raw_text)}</div>')
            continue

        # Handle bullets (strictly inside <ul><li class="bullet-item">, NEVER as two-col-line!)
        if is_bullet:
            if not in_bullet_list:
                body_parts.append('<ul class="bullet-list">')
                in_bullet_list = True
            clean_b = sanitize_text(raw_text)
            clean_b = re.sub(r'^[•·▪▸►\*\-]\s*', '', clean_b).strip()
            clean_b = clean_b.replace('\t', ' ')
            if clean_b:
                body_parts.append(f'<li class="bullet-item" data-edit="bullet">{html.escape(clean_b)}</li>')
            continue

        # If we reach here and was in bullet list, close it
        if in_bullet_list:
            body_parts.append("</ul>")
            in_bullet_list = False

        # Two-column row check (separated by tab \t OR multiple spaces before date range)
        left = ""
        right = ""

        if "\t" in raw_text and not is_bullet and len(raw_text) < 140:
            parts = [p.strip() for p in raw_text.split("\t") if p.strip()]
            left = parts[0] if parts else ""
            right = parts[1] if len(parts) > 1 else ""
        elif not is_bullet and len(raw_text) < 140:
            # Check for trailing date pattern or multi-space separation
            dm = DATE_RE.search(raw_text)
            if dm and dm.start() > 3:
                left = raw_text[:dm.start()].strip(' \t|-–—')
                right = raw_text[dm.start():].strip()
            elif "   " in raw_text:
                parts = [p.strip() for p in re.split(r'\s{3,}', raw_text) if p.strip()]
                if len(parts) == 2:
                    left, right = parts[0], parts[1]

        if left:
            has_bold = any(r.bold for r in para.runs if r.bold)
            has_italic = any(r.italic for r in para.runs if r.italic)

            if has_bold or not has_italic:
                # If we are in experience section and a new role begins, wrap in entry-item
                if in_exp_section:
                    if in_entry_item:
                        body_parts.append("</div>")
                    body_parts.append('<div class="entry-item exp-item">')
                    in_entry_item = True

                body_parts.append('<div class="two-col-line">')
                body_parts.append(f'<span class="two-col-left" data-edit="text">{html.escape(left)}</span>')
                if right:
                    body_parts.append(f'<span class="two-col-right" data-edit="text">{html.escape(right)}</span>')
                body_parts.append('</div>')
            else:
                body_parts.append('<div class="sub-line">')
                body_parts.append(f'<span class="sub-left" data-edit="text">{html.escape(left)}</span>')
                if right:
                    body_parts.append(f'<span class="sub-right" data-edit="text">{html.escape(right)}</span>')
                body_parts.append('</div>')
            continue

        # Sub-line check (e.g. italic institution or company line without tab)
        has_italic = any(r.italic for r in para.runs if r.italic)
        if has_italic and len(raw_text) < 80:
            body_parts.append(f'<div class="sub-line"><span class="sub-left" data-edit="text">{html.escape(raw_text)}</span></div>')
            continue

        # Category line check (e.g. "Languages: Python, Java...")
        colon_idx = raw_text.find(":")
        if colon_idx > 0 and colon_idx < 35 and not raw_text.startswith("http"):
            cat_label = raw_text[:colon_idx + 1]
            cat_rest = raw_text[colon_idx + 1:].strip()
            body_parts.append(
                f'<div class="skill-category"><span class="skill-category-label" data-edit="skill-cat-label">{html.escape(cat_label)}</span> <span class="skill-category-list" data-edit="skills-list">{html.escape(cat_rest)}</span></div>'
            )
            continue

        # Normal paragraph
        body_parts.append(f'<p class="summary-text" data-edit="summary">{html.escape(raw_text)}</p>')

    if in_bullet_list:
        body_parts.append("</ul>")
    if in_entry_item:
        body_parts.append("</div>")
    if header_open:
        body_parts.append("</div>")

    content = "\n".join(body_parts)
    title = f"{Path(docx_path).stem.replace('_', ' ')} - Resume"
    return _get_base_html_template(content, title=title)


def generate_pdf_from_html(
    html_content: str,
    output_pdf_path: str,
    candidate_name: str = "",
    role: str = "",
) -> bool:
    """
    Generate an authentic PDF file from an HTML resume string using Playwright headless Chromium.
    Works natively on Render Linux, Docker, and Windows with 100% pixel-perfect preview parity.
    Applies smart 1-page fit to prevent accidental 1-2 bullet spillovers onto a second page.
    Immediately sanitizes PDF metadata to eliminate Chromium/Skia signatures.
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

            # Smart single-page fit check:
            # 11 inches at 96 DPI = 1056px. If content slightly exceeds 1 page (up to ~1240px),
            # activate compact-fit to prevent 1-2 bullets from spilling onto an unjustified 2nd page!
            try:
                sheet_h = page.evaluate("() => { const s = document.querySelector('.resume-sheet'); return s ? s.scrollHeight : document.body.scrollHeight; }")
                if 1056 < sheet_h <= 1350:
                    page.evaluate("() => { document.body.classList.add('compact-fit'); }")
                    page.wait_for_timeout(80)
            except Exception:
                pass

            page.pdf(
                path=output_pdf_path,
                format="Letter",
                print_background=True,
                margin={
                    "top": "0in",
                    "bottom": "0in",
                    "left": "0in",
                    "right": "0in"
                },
                prefer_css_page_size=True,
            )
            browser.close()

        success = os.path.exists(output_pdf_path) and os.path.getsize(output_pdf_path) > 1000
        if success:
            try:
                from resume_builder import sanitize_pdf_metadata
                sanitize_pdf_metadata(output_pdf_path, candidate_name=candidate_name, role=role)
            except Exception:
                pass
        return success
    except Exception as e:
        logger.error(f"[HtmlToPdf] Playwright PDF generation failed: {e}")
        return False
