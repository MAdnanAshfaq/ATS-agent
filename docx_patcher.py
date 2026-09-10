"""
docx_patcher.py - In-place DOCX editor that preserves original styling with 100% fidelity.

Instead of building a new DOCX from scratch, this module:
1. Loads the user's original master DOCX template
2. In-place patches:
   - Professional Summary (without altering section styling)
   - Technical Skills rows (categorized or atomic, preserving bold labels)
   - 1-to-1 sequential experience bullets per role across all canonical companies
3. Preserves all original layout, fonts, colors, margins, and section borders.
4. Saves directly to the job's output directory.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from resume_builder import _categorize_skills, sanitize_text


def slugify(text: str) -> str:
    text = re.sub(r'[^\w\s-]', '', str(text))
    text = re.sub(r'[\s_-]+', '_', text)
    return text.strip('_')


def _get_para_full_text(para) -> str:
    """Get full text of a paragraph across all runs."""
    return "".join(run.text for run in para.runs)


def _set_para_text_preserve_format(para, new_text: str):
    """
    Replace paragraph text while preserving the formatting of runs.
    If the paragraph has a label prefix (e.g. bold 'Languages: '),
    it preserves run[0]'s label and formatting, and puts new text into run[1].
    Otherwise, preserves run[0]'s formatting and puts new text in run[0].
    """
    if not para.runs:
        para.add_run(new_text)
        return

    full_orig = _get_para_full_text(para).strip()

    # Check if there is a bold/distinct label prefix (e.g. "Languages:", "Cloud & DevOps:", "Tools & Platforms:")
    colon_idx = full_orig.find(":")
    if colon_idx != -1 and colon_idx < 35 and len(para.runs) > 1:
        label_prefix = full_orig[:colon_idx + 1].strip()
        r0_text = para.runs[0].text.strip()
        # If run[0] matches the label prefix
        if r0_text.startswith(label_prefix) or label_prefix.startswith(r0_text):
            # Strip label from new_text if already present in new_text
            val = new_text
            if val.startswith(label_prefix):
                val = val[len(label_prefix):].strip()
            para.runs[0].text = label_prefix + " "
            para.runs[1].text = val
            for r in para.runs[2:]:
                r.text = ""
            return

    # Standard replacement: keep formatting of run[0], clear others
    para.runs[0].text = new_text
    for run in para.runs[1:]:
        run.text = ""


def _normalize(text: str) -> str:
    """Normalize text for comparison."""
    return re.sub(r'\s+', ' ', text.lower().strip())


def _fuzzy_match_score(a: str, b: str) -> float:
    """Simple word-overlap ratio between two strings."""
    a_words = set(_normalize(a).split())
    b_words = set(_normalize(b).split())
    if not a_words or not b_words:
        return 0.0
    intersection = a_words & b_words
    return len(intersection) / max(len(a_words), len(b_words))


def _iter_table_paragraphs(table):
    """Recursively yield all paragraphs in all table cells."""
    for row in table.rows:
        for cell in row.cells:
            for para in cell.paragraphs:
                yield para
            for nested_table in cell.tables:
                yield from _iter_table_paragraphs(nested_table)


def _get_all_paragraphs_from_doc(doc):
    """
    Yield all paragraphs from both body AND table cells, in document order.
    Critical for DOCX files with table-based layouts.
    """
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    def iter_blocks(parent):
        for child in parent.element.body:
            tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
            if tag == 'p':
                yield Paragraph(child, parent)
            elif tag == 'tbl':
                yield from _iter_table_paragraphs(Table(child, parent))

    yield from iter_blocks(doc)


def _is_section_header(text: str) -> bool:
    """Check if a paragraph text looks like a major section header."""
    norm = _normalize(text)
    headers = {
        "professional summary", "summary", "executive summary", "career profile", "profile",
        "technical skills", "skills", "skills & competencies", "core competencies",
        "professional experience", "work experience", "experience", "employment history",
        "education", "academic background", "certifications", "licenses & certifications",
        "projects", "key projects"
    }
    return norm in headers or (len(norm) < 30 and any(h == norm for h in headers))


def patch_docx_with_rewritten_resume(
    original_docx_path: str,
    rewritten_resume: dict,
    company: str,
    role: str,
    output_dir: str = None,
) -> str:
    """
    Patch the original DOCX with rewritten content, preserving 100% of formatting.

    Args:
        original_docx_path: Path to the user's original uploaded/baseline DOCX
        rewritten_resume: The tailored resume dict
        company: For output folder naming
        role: For output folder naming
        output_dir: Base output directory

    Returns:
        Path to the patched DOCX file
    """
    from docx import Document

    if not os.path.exists(original_docx_path):
        raise FileNotFoundError(f"Original DOCX not found: {original_docx_path}")

    # Set up output path
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), "output")

    folder_name = f"{slugify(company)}_{slugify(role)}"[:80]
    folder_path = Path(output_dir) / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)

    # Derive candidate name for file
    name = rewritten_resume.get("name", "Resume").replace(" ", "_")
    out_filename = f"{name}_{slugify(company)}_{slugify(role)}.docx"
    out_path = folder_path / out_filename

    # Copy original to output (we edit the copy)
    shutil.copy2(original_docx_path, out_path)
    print(f"[Patcher] Copied original DOCX to: {out_path}")

    doc = Document(str(out_path))
    all_paras = list(_get_all_paragraphs_from_doc(doc))
    print(f"[Patcher] Found {len(all_paras)} paragraphs in original DOCX")

    # ── 1. Patch Target Role (if present in header) ───────────────────────────
    target_role = rewritten_resume.get("target_role") or role or ""
    if target_role and len(all_paras) > 1:
        p1_text = _get_para_full_text(all_paras[1]).strip()
        # If paragraph 1 is a role subtitle (short, uppercase, not contact)
        if 2 <= len(p1_text) <= 50 and "@" not in p1_text and not p1_text.startswith("+"):
            from scraper import clean_role_title
            clean_r = clean_role_title(target_role)
            if p1_text.isupper():
                clean_r = clean_r.upper()
            else:
                clean_r = clean_r.title()
            if clean_r:
                _set_para_text_preserve_format(all_paras[1], clean_r)
                print(f"[Patcher] Updated target role subtitle to: {clean_r}")

    # ── 2. Patch Professional Summary ─────────────────────────────────────────
    rewritten_summary = rewritten_resume.get("summary", "").strip()
    if rewritten_summary:
        summary_patched = False
        for i, para in enumerate(all_paras):
            text = _normalize(_get_para_full_text(para))
            if text in ("professional summary", "summary", "executive summary", "profile", "career profile"):
                # The next non-empty paragraph is the summary content
                for j in range(i + 1, min(i + 4, len(all_paras))):
                    cand_text = _get_para_full_text(all_paras[j]).strip()
                    if cand_text and not _is_section_header(cand_text):
                        _set_para_text_preserve_format(all_paras[j], rewritten_summary)
                        print(f"[Patcher] Updated summary paragraph under header '{text}'")
                        summary_patched = True
                        break
            if summary_patched:
                break

        # Fallback: find paragraph with highest overlap or length > 50 before experience
        if not summary_patched:
            for para in all_paras[:8]:
                text = _get_para_full_text(para).strip()
                if len(text) > 60 and not _is_section_header(text) and "@" not in text:
                    _set_para_text_preserve_format(para, rewritten_summary)
                    print(f"[Patcher] Updated summary paragraph (fallback detection)")
                    break

    # ── 3. Patch Technical Skills Rows ────────────────────────────────────────
    rewritten_skills = rewritten_resume.get("skills", [])
    if rewritten_skills:
        clean_skills = [sanitize_text(s) for s in rewritten_skills if s and len(sanitize_text(s)) <= 40]
        categorized = _categorize_skills(clean_skills)

        # Locate the skills section
        skills_start_idx = None
        for i, para in enumerate(all_paras):
            text = _normalize(_get_para_full_text(para))
            if text in ("technical skills", "skills", "skills & competencies", "core competencies"):
                skills_start_idx = i
                break

        if skills_start_idx is not None:
            # Look at paragraphs following the skills header until next section header
            skill_paras = []
            for j in range(skills_start_idx + 1, min(skills_start_idx + 8, len(all_paras))):
                cand_text = _get_para_full_text(all_paras[j]).strip()
                if not cand_text:
                    continue
                if _is_section_header(cand_text):
                    break
                skill_paras.append(all_paras[j])

            # Check if paragraphs have labeled categories (e.g. "Languages:", "Cloud & DevOps:")
            labeled_rows = []
            for p in skill_paras:
                p_txt = _get_para_full_text(p).strip()
                c_idx = p_txt.find(":")
                if c_idx != -1 and c_idx < 30:
                    labeled_rows.append((p, p_txt[:c_idx].strip()))

            if labeled_rows:
                # In-place update each labeled row matching category
                for p, label in labeled_rows:
                    label_lower = label.lower()
                    matched_items = []
                    for cat_name, cat_items in categorized.items():
                        if cat_name.lower() in label_lower or label_lower in cat_name.lower():
                            matched_items.extend(cat_items)

                    # If no direct match, match keywords in label
                    if not matched_items:
                        if "lang" in label_lower:
                            matched_items = categorized.get("Languages", [])
                        elif "cloud" in label_lower or "devops" in label_lower:
                            matched_items = categorized.get("Cloud & DevOps", [])
                        elif "tool" in label_lower or "platform" in label_lower:
                            matched_items = categorized.get("Tools & Platforms", [])
                        elif "database" in label_lower:
                            matched_items = categorized.get("Databases", [])
                        elif "framework" in label_lower:
                            matched_items = categorized.get("Frameworks & Libraries", [])

                    if matched_items:
                        new_content = f"{label}: {', '.join(matched_items)}"
                        _set_para_text_preserve_format(p, new_content)
                        print(f"[Patcher] Updated skills row '{label}': {len(matched_items)} items")
            elif skill_paras:
                # Single or multi-paragraph unlabelled skills list
                all_skills_str = ", ".join(clean_skills)
                _set_para_text_preserve_format(skill_paras[0], all_skills_str)
                print(f"[Patcher] Updated generic skills paragraph with {len(clean_skills)} skills")

    # ── 4. Patch Experience Bullets (Zero-Exempt 1-to-1 Sequential Mapping) ───
    rewritten_exp = rewritten_resume.get("experience", [])
    total_replacements = 0

    # Collect indices of role header paragraphs
    role_anchors = []
    for exp_idx, exp in enumerate(rewritten_exp):
        comp = _normalize(exp.get("company", ""))
        title = _normalize(exp.get("title", ""))
        best_para_idx = None
        best_score = 0.0

        for i, para in enumerate(all_paras):
            text = _normalize(_get_para_full_text(para))
            if not text or _is_section_header(text):
                continue
            # Score against company and title
            score = 0.0
            if comp and comp in text:
                score += 0.6
            if title and title in text:
                score += 0.5
            if score > best_score and score >= 0.5:
                best_score = score
                best_para_idx = i

        if best_para_idx is not None:
            # If the best match is line 2 (e.g. company name) and line 1 above it is the title/date,
            # or vice versa, the true start of this role block is the earlier paragraph.
            start_idx = best_para_idx
            if best_para_idx > 0:
                prev_text = _normalize(_get_para_full_text(all_paras[best_para_idx - 1]))
                if title and title in prev_text:
                    start_idx = best_para_idx - 1
                elif comp and comp in prev_text:
                    start_idx = best_para_idx - 1
            
            role_anchors.append((exp_idx, start_idx, exp))
            print(f"[Patcher] Located role '{exp.get('company')}' starting at paragraph {start_idx}")

    # Sort role anchors by paragraph index
    role_anchors.sort(key=lambda x: x[1])

    # Now for each role, define its paragraph range and patch bullets
    for r_i, (exp_idx, anchor_idx, exp) in enumerate(role_anchors):
        comp = _normalize(exp.get("company", ""))
        title = _normalize(exp.get("title", ""))
        
        # Determine end index: next role anchor or next section header
        if r_i + 1 < len(role_anchors):
            end_idx = role_anchors[r_i + 1][1]
        else:
            # Last role: find next section header or end of document
            end_idx = len(all_paras)
            for j in range(anchor_idx + 1, len(all_paras)):
                p_text = _get_para_full_text(all_paras[j]).strip()
                if _is_section_header(p_text):
                    end_idx = j
                    break

        # Header lines can span 1 or 2 paragraphs (e.g. Title line + Company line)
        content_start = anchor_idx + 1
        if content_start < end_idx:
            next_p_text = _normalize(_get_para_full_text(all_paras[content_start]))
            if (comp and comp in next_p_text) or (title and title in next_p_text) or any(loc in next_p_text for loc in ("remote", "usa", "ca", "ny", "tx")):
                content_start += 1

        # Collect bullet paragraphs in range (content_start .. end_idx)
        role_bullet_paras = []
        for p_idx in range(content_start, end_idx):
            p = all_paras[p_idx]
            p_text = _get_para_full_text(p).strip()
            # Skip empty, location lines (very short), or dates
            if not p_text or len(p_text) < 10:
                continue
            # Skip if this line looks like a role title or company or date range
            if re.search(r'\b(20\d\d|19\d\d)\s*[-–—]\s*(20\d\d|present)\b', p_text, re.IGNORECASE):
                continue
            
            # Check if it looks like a bullet or description
            is_bullet = (
                p.style.name.startswith("List")
                or p_text.startswith(('•', '·', '▪', '-', '*'))
                or len(p_text) >= 20
            )
            if is_bullet:
                role_bullet_paras.append(p)

        new_bullets = exp.get("bullets", [])
        print(f"[Patcher] Role '{exp.get('company')}': {len(role_bullet_paras)} original bullets, {len(new_bullets)} new bullets")

        # 1-to-1 sequential mapping
        for b_i, new_b in enumerate(new_bullets):
            clean_b = sanitize_text(new_b)
            if not clean_b:
                continue
            if b_i < len(role_bullet_paras):
                target_para = role_bullet_paras[b_i]
                _set_para_text_preserve_format(target_para, clean_b)
                total_replacements += 1
            else:
                # If there are more new bullets than original paragraphs, clone bullet formatting
                if role_bullet_paras:
                    last_p = role_bullet_paras[-1]
                    new_p = doc.add_paragraph(style=last_p.style)
                    new_p.paragraph_format.left_indent = last_p.paragraph_format.left_indent
                    new_p.paragraph_format.space_after = last_p.paragraph_format.space_after
                    new_p.paragraph_format.line_spacing = last_p.paragraph_format.line_spacing
                    run = new_p.add_run(clean_b)
                    if last_p.runs:
                        run.font.name = last_p.runs[0].font.name
                        run.font.size = last_p.runs[0].font.size
                    total_replacements += 1

        # If original had more bullets than new, clear excess paragraphs
        if len(role_bullet_paras) > len(new_bullets):
            for extra_p in role_bullet_paras[len(new_bullets):]:
                extra_p.text = ""

    print(f"[Patcher] Total bullet replacements made: {total_replacements}")

    # Save patched document
    doc.save(str(out_path))
    print(f"[Patcher] Successfully saved patched DOCX: {out_path}")

    return str(out_path)


def get_original_docx_path(user_data_dir: Optional[str | Path] = None) -> str | None:
    """
    Returns the path to the user's original uploaded DOCX.
    Checks user_data_dir first, then falls back to repository root.
    """
    candidates = []
    if user_data_dir:
        u_dir = Path(user_data_dir)
        candidates.extend([
            u_dir / "master_resume_original.docx",
            u_dir / "master_resume_original.pdf",
        ])

    base_dir = Path(__file__).parent
    candidates.extend([
        base_dir / "master_resume_original.docx",
        base_dir / "master_resume_original.pdf",
    ])

    for p in candidates:
        if p.exists() and str(p).endswith(".docx"):
            return str(p)

    return None
