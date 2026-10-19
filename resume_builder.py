"""
resume_builder.py — Generates a clean, ATS-optimized Word document from the final resume JSON.
Single font, clean bullets, no special characters that break ATS parsing.
"""
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List


def slugify(text: str) -> str:
    """Convert text to a safe folder/file name."""
    text = re.sub(r'[^\w\s-]', '', str(text))
    text = re.sub(r'[\s_-]+', '_', text)
    return text.strip('_')


def sanitize_text(text: str) -> str:
    """Remove/replace characters that break ATS parsing."""
    if not text:
        return ""
    # Replace em dashes and en dashes with hyphens
    text = text.replace('\u2014', '-').replace('\u2013', '-')
    # Replace fancy quotes
    text = text.replace('\u2019', "'").replace('\u2018', "'")
    text = text.replace('\u201c', '"').replace('\u201d', '"')
    # Remove bullet characters (we'll use docx bullets instead)
    text = re.sub(r'^[•·▪▸►\*]\s*', '', text)
    # Remove excessive whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def build_resume_docx(
    resume: dict,
    company: str,
    role: str,
    output_dir: str = None,
    font_family: str = None,
) -> str:
    """
    Build a clean Word document from the resume dict.
    
    Args:
        resume: Final cleaned resume dict
        company: Company name (for folder/file naming)
        role: Job role (for folder/file naming)
        output_dir: Base output directory (default: job-agent/output/)
    
    Returns:
        Absolute path to the generated .docx file
    """
    try:
        from docx import Document
        from docx.shared import Pt, Inches, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.oxml import OxmlElement
    except ImportError:
        raise RuntimeError("python-docx not installed. Run: pip install python-docx")
    
    # ─── Setup output path ───────────────────────────────────────────────────
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), "output")
    
    folder_name = f"{slugify(company)}_{slugify(role)}"[:80]
    folder_path = Path(output_dir) / folder_name
    folder_path.mkdir(parents=True, exist_ok=True)
    
    name = sanitize_text(resume.get("name", "Candidate Name"))
    file_name = f"{slugify(name)}_Resume.docx"
    file_path = folder_path / file_name
    
    # ─── Create Document ─────────────────────────────────────────────────────
    doc = Document()

    # ─── Professional Metadata (Scrub python-docx signatures) ────────────────
    try:
        cp = doc.core_properties
        cp.author = name
        cp.title = f"{name} - Resume"
        cp.last_modified_by = name
        cp.comments = ""
        cp.subject = f"{target_role} Resume" if target_role else "Resume"
        cp.category = "Resume"
    except Exception:
        pass

    # Set page margins (clean professional standard)
    for section in doc.sections:
        section.top_margin = Inches(0.5)
        section.bottom_margin = Inches(0.5)
        section.left_margin = Inches(0.55)
        section.right_margin = Inches(0.55)
    
    # Determine primary font (dynamic based on uploaded PDF/DOCX or user preference)
    active_font = font_family or resume.get("_detected_font") or "Calibri"

    # Content width: 8.5 - 2*0.55 = 7.40 inches = 10656 twips
    CONTENT_WIDTH_TWIPS = '10656'
    
    # ─── Helper functions ─────────────────────────────────────────────────────
    
    def set_font(run, size=10, bold=False, italic=False, color=(0, 0, 0)):
        run.font.name = active_font
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.italic = italic
        if color:
            run.font.color.rgb = RGBColor(*color)
    
    def add_paragraph_spacing(para, space_before=0, space_after=0):
        para.paragraph_format.space_before = Pt(space_before)
        para.paragraph_format.space_after = Pt(space_after)
        para.paragraph_format.line_spacing = 1.1
    
    def add_section_header(title: str):
        """Add an authentic section header with a thin black bottom border line and keep_with_next."""
        para = doc.add_paragraph()
        para.paragraph_format.keep_with_next = True
        add_paragraph_spacing(para, space_before=6, space_after=2)
        run = para.add_run(title.upper())
        set_font(run, size=11, bold=True, color=(0, 0, 0))
        
        # Add bottom border to paragraph
        pPr = para._p.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        bottom = OxmlElement('w:bottom')
        bottom.set(qn('w:val'), 'single')
        bottom.set(qn('w:sz'), '6')
        bottom.set(qn('w:space'), '1')
        bottom.set(qn('w:color'), '000000')  # Solid crisp black
        pBdr.append(bottom)
        pPr.append(pBdr)
        
        return para
    
    def add_bullet(text: str, keep_next: bool = False):
        """Add a clean bullet point with optional keep_with_next for layout integrity."""
        text = sanitize_text(text).lstrip("•·▪-* ").strip()
        if not text or len(text) < 8:
            return
        para = doc.add_paragraph(style='List Bullet')
        if keep_next:
            para.paragraph_format.keep_with_next = True
        run = para.add_run(text)
        set_font(run, size=9.5)
        add_paragraph_spacing(para, space_before=0, space_after=1.5)
        para.paragraph_format.left_indent = Inches(0.2)
    
    def add_normal_text(text: str, size=9.5, bold=False, italic=False, keep_next=False):
        """Add a normal paragraph."""
        text = sanitize_text(text)
        para = doc.add_paragraph()
        if keep_next:
            para.paragraph_format.keep_with_next = True
        run = para.add_run(text)
        set_font(run, size=size, bold=bold)
        run.italic = italic
        add_paragraph_spacing(para, space_before=0, space_after=1.5)
        return para
    
    def add_two_column_line(left: str, right: str, left_bold=False, left_italic=False, right_bold=False, right_italic=False, keep_next=True):
        """Add a line with text on left and right (e.g., role + dates) with keep_with_next."""
        para = doc.add_paragraph()
        if keep_next:
            para.paragraph_format.keep_with_next = True
        add_paragraph_spacing(para, space_before=2, space_after=1)
        
        # Add right-aligned tab stop at exact right margin
        pPr = para._p.get_or_add_pPr()
        tabs = OxmlElement('w:tabs')
        tab = OxmlElement('w:tab')
        tab.set(qn('w:val'), 'right')
        tab.set(qn('w:pos'), CONTENT_WIDTH_TWIPS)
        tabs.append(tab)
        pPr.append(tabs)
        
        run_left = para.add_run(sanitize_text(left))
        set_font(run_left, size=10, bold=left_bold, italic=left_italic)
        
        if right:
            tab_run = para.add_run("\t")
            set_font(tab_run, size=9.5)
            run_right = para.add_run(sanitize_text(right))
            set_font(run_right, size=9.5, bold=right_bold, italic=right_italic)
        
        return para
    
    # ─── HEADER: Candidate Name & Target Role ────────────────────────────────
    contact = resume.get("contact", {})
    name = sanitize_text(resume.get("name", "Candidate Name"))
    
    # Extract & clean role title (strip any brackets/parentheses like "(Databricks)")
    from scraper import clean_role_title
    raw_role = resume.get("target_role") or role or ""
    clean_role = clean_role_title(raw_role)
    
    name_para = doc.add_paragraph()
    name_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    add_paragraph_spacing(name_para, space_before=0, space_after=1)
    
    run_name = name_para.add_run(name.upper())
    set_font(run_name, size=20, bold=True, color=(0, 0, 0))
    
    if clean_role and clean_role.upper() not in ("UNKNOWN", "NONE"):
        role_para = doc.add_paragraph()
        role_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_paragraph_spacing(role_para, space_before=0, space_after=3)
        run_role = role_para.add_run(clean_role.title())
        set_font(run_role, size=13.5, bold=False, italic=True, color=(0, 0, 0))
    
    # ─── HEADER: Contact lines (matching authentic layout) ────────────────────
    contact_parts = []
    seen_contacts = set()

    def _add_contact(val, is_phone=False):
        if not val:
            return
        val_str = sanitize_text(str(val)).strip()
        if not val_str:
            return
        # If marked as phone, reject if it contains links or letters
        if is_phone:
            if any(k in val_str.lower() for k in ("linkedin", "http", "github", "www.", ".com")):
                return
            if re.search(r'[a-zA-Z]', val_str):
                return
        val_lower = val_str.lower().rstrip('/')
        if val_lower in seen_contacts:
            return
        seen_contacts.add(val_lower)
        contact_parts.append(val_str)

    _add_contact(contact.get("email"))
    _add_contact(contact.get("phone"), is_phone=True)
    _add_contact(contact.get("location"))
    _add_contact(contact.get("linkedin"))
    _add_contact(contact.get("github"))
    _add_contact(contact.get("portfolio"))

    if contact_parts:
        contact_para = doc.add_paragraph()
        contact_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_paragraph_spacing(contact_para, space_before=0, space_after=3)
        run = contact_para.add_run("   |   ".join(contact_parts))
        set_font(run, size=9.5, color=(40, 40, 40))
    
    # ─── Dynamic Section Headings ─────────────────────────────────────────────
    headings = resume.get("section_headings", {}) or {}

    # ─── SUMMARY ─────────────────────────────────────────────────────────────
    summary = resume.get("summary", "")
    if summary:
        add_section_header(headings.get("summary") or "Professional Summary")
        add_normal_text(sanitize_text(summary), size=10)
    
    # ─── SKILLS ──────────────────────────────────────────────────────────────
    skills = resume.get("skills", [])
    if skills:
        add_section_header(headings.get("skills") or "Technical Skills")
        
        # Group skills into rows of ~6 per line for clean layout
        clean_skills = [sanitize_text(s) for s in skills if s]
        
        # Try to categorize if possible
        categories = _categorize_skills(clean_skills)
        
        for category, skill_list in categories.items():
            if not skill_list:
                continue
            para = doc.add_paragraph()
            add_paragraph_spacing(para, space_before=1, space_after=1)
            
            label_run = para.add_run(f"{category}: ")
            set_font(label_run, size=10, bold=True)
            
            skills_run = para.add_run(", ".join(skill_list))
            set_font(skills_run, size=10)
    
    # ─── EXPERIENCE ──────────────────────────────────────────────────────────
    experience = resume.get("experience", [])
    if experience:
        add_section_header(headings.get("experience") or "Professional Experience")
        
        for role_entry in experience:
            title = sanitize_text(role_entry.get("title") or role_entry.get("role", ""))
            company_name = sanitize_text(role_entry.get("company", ""))
            dates = sanitize_text(role_entry.get("dates") or role_entry.get("date") or role_entry.get("period") or role_entry.get("duration") or "")
            if not dates and role_entry.get("start_date"):
                dates = sanitize_text(f"{role_entry.get('start_date')} - {role_entry.get('end_date', 'Present')}")
            location = sanitize_text(role_entry.get("location", ""))
            
            # Robust fallback to base_resume if dates or location missing
            if (not dates or not location) and company_name:
                base_exp = (resume.get("base_resume", {}) or {}).get("experience", []) or resume.get("_orig_experience", [])
                for b_item in base_exp:
                    b_comp = b_item.get("company", "").strip().lower()
                    if b_comp and (b_comp in company_name.lower() or company_name.lower() in b_comp):
                        if not dates:
                            dates = sanitize_text(b_item.get("dates") or b_item.get("date") or "")
                        if not location:
                            location = sanitize_text(b_item.get("location", ""))
                        break
            
            bullets = role_entry.get("bullets", [])
            
            if not title:
                continue
            
            # Authentic 2-line header matching original document:
            # Line 1: Title (bold) on left, Dates (regular) on right
            add_two_column_line(title, dates, left_bold=True, right_bold=False, keep_next=True)
            
            # Line 2: Company (italic) on left, Location (regular) on right
            if company_name or location:
                add_two_column_line(company_name, location, left_italic=True, right_italic=False, keep_next=True)
            
            # Bullet points (keep_next on first bullet to prevent orphaned headers across pages)
            for b_idx, bullet in enumerate(bullets):
                if bullet and len(sanitize_text(bullet)) > 5:
                    add_bullet(bullet, keep_next=(b_idx == 0 and len(bullets) > 1))
    
    # ─── PROJECTS ────────────────────────────────────────────────────
    projects = resume.get("projects", [])
    if projects:
        add_section_header(headings.get("projects") or "Projects")
        
        for project in projects:
            proj_name = sanitize_text(project.get("name", ""))
            tech_stack = project.get("tech_stack", [])
            description = sanitize_text(project.get("description", ""))
            url = sanitize_text(project.get("url", ""))
            
            if not proj_name:
                continue
            
            # Project name + tech stack
            tech_str = f" | {', '.join(tech_stack)}" if tech_stack else ""
            url_str = f" | {url}" if url else ""
            
            para = doc.add_paragraph()
            add_paragraph_spacing(para, space_before=3, space_after=1)
            run = para.add_run(f"{proj_name}{tech_str}{url_str}")
            set_font(run, size=10.5, bold=True)
            
            if description:
                add_bullet(description)
    
    # ─── EDUCATION ───────────────────────────────────────────────────
    education = resume.get("education", [])
    if education:
        add_section_header(headings.get("education") or "Education")
        
        for edu in education:
            institution = sanitize_text(edu.get("institution", ""))
            degree = sanitize_text(edu.get("degree", ""))
            field = sanitize_text(edu.get("field", ""))
            grad_date = sanitize_text(edu.get("graduation_date", ""))
            gpa = sanitize_text(edu.get("gpa", ""))
            
            if not institution and not degree:
                continue
            
            # Authentic format: Degree & Field on left, Grad Date on right
            degree_title = f"{degree} in {field}" if (degree and field and not degree.lower().endswith("in")) else (degree or field or institution)
            add_two_column_line(degree_title, grad_date, left_bold=True, right_bold=False, keep_next=True)
            
            if institution and degree_title != institution:
                add_normal_text(institution, size=10, italic=True)
            if gpa:
                add_normal_text(f"GPA: {gpa}", size=9.5)
    
    # ─── CERTIFICATIONS ──────────────────────────────────────────────────────
    certifications = resume.get("certifications", [])
    if certifications:
        add_section_header(headings.get("certifications") or "Certifications")
        for cert in certifications:
            if cert:
                add_bullet(sanitize_text(cert))
    
    # ─── Save ─────────────────────────────────────────────────────────────────
    doc.save(str(file_path))
    
    print(f"[Builder] [OK] Resume saved: {file_path}")
    print(f"[Builder]    Folder: {folder_path}")
    
    return str(file_path)


def _categorize_skills(skills: list) -> dict:
    """Auto-categorize skills into clean, balanced groups with zero duplicates or bloated catch-all categories."""
    from skills_cleaner import clean_technical_skills_list
    sanitized_skills = clean_technical_skills_list(skills)

    categories = {
        "Languages": [],
        "Cloud & Platforms": [],
        "Frameworks & Tools": [],
        "Databases & Storage": [],
        "Architecture & Methodologies": [],
        "Compliance & Security": [],
    }

    lang_keywords = {
        'python', 'sql', 't-sql', 'pl/sql', 'javascript', 'typescript', 'java', 'kotlin', 'swift',
        'golang', 'go', 'rust', 'c++', 'c#', 'ruby', 'php', 'scala', 'r', 'html', 'css', 'bash', 'shell'
    }
    platform_keywords = {
        'microsoft azure', 'azure', 'aws', 'gcp', 'google cloud', 'google cloud platform',
        'databricks', 'snowflake', 'microsoft fabric', 'fabric', 'power bi', 'tableau', 'palantir foundry'
    }
    db_keywords = {
        'postgresql', 'postgres', 'mysql', 'mongodb', 'sqlite', 'redis', 'elasticsearch',
        'dynamodb', 'cassandra', 'delta lake', 'onelake', 'adls', 'adls gen2', 'data lake',
        'data warehouse', 'bigquery', 'redshift', 'mariadb', 'oracle', 'sql server', 'synapse sql'
    }
    engineering_keywords = {
        'pyspark', 'spark', 'apache spark', 'dbt', 'azure data factory', 'data factory',
        'apache airflow', 'airflow', 'apache kafka', 'kafka', 'auto loader', 'rest apis', 'rest api',
        'graphql', 'grpc', 'fastapi', 'flask', 'django', 'node.js', 'react', 'odata', 'sftp',
        'algolia', 'git', 'docker', 'kubernetes', 'terraform', 'ci/cd', 'github actions',
        'gitlab ci', 'azure devops', 'ansible', 'helm', 'prefect', 'dagster'
    }
    architecture_keywords = {
        'medallion architecture', 'incremental loads', 'merge/cdc', 'cdc', 'semantic models',
        'semantic modeling', 'data modeling', 'data governance', 'microsoft purview', 'unity catalog',
        'data lineage', 'schema evolution', 'repository governance', 'dataset versioning',
        'audit readiness', 'hr data governance', 'agile', 'scrum'
    }
    compliance_keywords = {
        'hipaa', 'hitrust', 'phi', 'pii', 'soc 2', 'gdpr', 'compliance'
    }

    def _matches(candidate: str, kw_set: set) -> bool:
        c_lower = candidate.lower().strip()
        for kw in kw_set:
            if c_lower == kw:
                return True
            pattern = r'(?:^|[\s,/\(\)\-\_\:])' + re.escape(kw) + r'(?:$|[\s,/\(\)\-\_\:])'
            if re.search(pattern, c_lower):
                return True
        return False

    placed_skills_lower = set()

    for skill in sanitized_skills:
        skill_clean = sanitize_text(skill).lstrip("•·▪-* ").strip()
        if not skill_clean or len(skill_clean) < 2 or skill_clean.endswith(".") or len(skill_clean) > 40:
            continue

        c_lower = skill_clean.lower()
        if c_lower in placed_skills_lower:
            continue

        # Priority 1: Languages
        if _matches(skill_clean, lang_keywords) and not _matches(skill_clean, {'sql server', 'postgresql', 'mysql'}):
            categories["Languages"].append(skill_clean)
            placed_skills_lower.add(c_lower)
        # Priority 2: Cloud & Core Enterprise Platforms
        elif _matches(skill_clean, platform_keywords):
            categories["Cloud & Platforms"].append(skill_clean)
            placed_skills_lower.add(c_lower)
        # Priority 3: Databases & Storage Layers
        elif _matches(skill_clean, db_keywords):
            categories["Databases & Storage"].append(skill_clean)
            placed_skills_lower.add(c_lower)
        # Priority 4: Compliance & Healthcare/Security Standards
        elif _matches(skill_clean, compliance_keywords):
            categories["Compliance & Security"].append(skill_clean)
            placed_skills_lower.add(c_lower)
        # Priority 5: Architecture, Methodologies & Governance
        elif _matches(skill_clean, architecture_keywords):
            categories["Architecture & Methodologies"].append(skill_clean)
            placed_skills_lower.add(c_lower)
        # Priority 6: Frameworks, Libraries & Developer Tools
        elif _matches(skill_clean, engineering_keywords):
            categories["Frameworks & Tools"].append(skill_clean)
            placed_skills_lower.add(c_lower)
        elif len(skill_clean) > 1:
            categories["Frameworks & Tools"].append(skill_clean)
            placed_skills_lower.add(c_lower)

    # Balance and prune: cap each category to max 8 items to prevent text walls
    out = {}
    for k, v in categories.items():
        if v:
            out[k] = v[:8]
    return out


def sanitize_pdf_metadata(
    pdf_path: str,
    candidate_name: str = "",
    role: str = "",
    title: str = "",
) -> bool:
    """
    Sanitizes background PDF metadata using pypdf to ensure 100% recruiter-clean
    and ATS-compliant document properties:
    - Overwrites 'Creator: Chromium' or 'Producer: Skia/PDF' with 'Microsoft® Word 2021'.
    - Replaces 'Author: Unknown' with the authentic candidate name.
    - Sets professional Title and Subject matching the target role.
    - Preserves authentic creation and modification timestamps.
    """
    try:
        import pypdf
        import io
        if not pdf_path or not os.path.exists(pdf_path):
            return False

        reader = pypdf.PdfReader(pdf_path)
        writer = pypdf.PdfWriter()
        writer.append(reader)

        # 1. Dynamically resolve candidate name & role if not explicitly passed
        if not candidate_name:
            # Check companion .docx core properties
            docx_companion = Path(pdf_path).with_suffix(".docx")
            if docx_companion.exists():
                try:
                    from docx import Document
                    d = Document(str(docx_companion))
                    if d.core_properties.author and d.core_properties.author != "python-docx":
                        candidate_name = d.core_properties.author.strip()
                    if not role and d.core_properties.subject:
                        role = d.core_properties.subject.strip()
                except Exception:
                    pass

        if not candidate_name:
            # Check for candidate's tailored_resume.json or base_resume.json in adjacent paths
            p_dir = Path(pdf_path).parent
            for cand_json in [
                p_dir / "tailored_resume.json",
                p_dir / "base_resume.json",
                p_dir.parent / "base_resume.json",
            ]:
                if cand_json.exists():
                    try:
                        import json
                        with open(cand_json, "r", encoding="utf-8") as f:
                            jdata = json.load(f)
                            if jdata.get("name"):
                                candidate_name = jdata["name"].strip()
                                break
                    except Exception:
                        pass

        if not candidate_name:
            stem = Path(pdf_path).stem.replace("_", " ")
            candidate_name = stem.split(" Resume")[0].split(" Master")[0].strip() or "Candidate"

        clean_title = title or f"{candidate_name} - Resume"

        metadata = {
            '/Title': clean_title,
            '/Author': candidate_name,
            '/Creator': 'Microsoft® Word 2021',
            '/Producer': 'Microsoft® Word 2021',
            '/Subject': role or 'Resume',
        }
        writer.add_metadata(metadata)

        temp_buf = io.BytesIO()
        writer.write(temp_buf)
        temp_buf.seek(0)
        with open(pdf_path, 'wb') as f:
            f.write(temp_buf.read())
        return True
    except Exception as e:
        print(f"[PDF Sanitize] Note: {e}")
        return False


def convert_to_pdf(
    doc_path: str,
    candidate_name: str = "",
    role: str = "",
    resume_dict: Optional[dict] = None,
    force_refresh: bool = False,
) -> str:
    """
    Convert resume to .pdf with 100% pixel-perfect preview parity and clean metadata.
    Priority 1: Renders directly from structured JSON via resume_json_to_html + Playwright Chromium.
                This guarantees the downloaded PDF is an exact, 1-to-1 clone of the in-browser preview.
    Priority 2: Native Word COM automation on Windows.
    Priority 3: docx_to_html + Playwright Chromium fallback.
    """
    if not doc_path or not os.path.exists(doc_path):
        return ""

    pdf_path = str(Path(doc_path).with_suffix(".pdf"))
    target_dir = Path(doc_path).parent

    # Check if existing PDF is already up-to-date and not forced to refresh
    if not force_refresh and os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000:
        json_file = target_dir / "tailored_resume.json"
        doc_mtime = max(
            os.path.getmtime(doc_path),
            json_file.stat().st_mtime if json_file.exists() else 0
        )
        if os.path.getmtime(pdf_path) >= doc_mtime:
            sanitize_pdf_metadata(pdf_path, candidate_name=candidate_name, role=role)
            return pdf_path

    # Extract author and role from docx or structured JSON if not supplied
    if not resume_dict:
        for json_candidate in [
            target_dir / "tailored_resume.json",
            target_dir / "base_resume.json",
            target_dir.parent / "base_resume.json",
        ]:
            if json_candidate.exists():
                try:
                    with open(json_candidate, "r", encoding="utf-8") as jf:
                        loaded = json.load(jf)
                        if loaded and loaded.get("name"):
                            resume_dict = loaded
                            break
                except Exception:
                    pass

    if resume_dict and not candidate_name:
        candidate_name = resume_dict.get("name", "")
    if resume_dict and not role:
        role = resume_dict.get("target_role", "")

    if not candidate_name:
        try:
            from docx import Document
            d = Document(doc_path)
            candidate_name = d.core_properties.author or ""
            if not role:
                role = d.core_properties.subject or ""
        except Exception:
            pass

    # ── Attempt 1: Playwright Chromium from Structured Resume JSON (100% PREVIEW PARITY) ──
    if resume_dict:
        try:
            from resume_html import resume_json_to_html, generate_pdf_from_html
            html_content = resume_json_to_html(resume_dict, role=role)
            if generate_pdf_from_html(html_content, pdf_path, candidate_name=candidate_name, role=role):
                sanitize_pdf_metadata(pdf_path, candidate_name=candidate_name, role=role)
                print(f"[PDF] [OK] Converted via Playwright Chromium JSON (100% Preview Parity): {pdf_path}")
                return pdf_path
        except Exception as e:
            print(f"[PDF] Playwright JSON conversion note: {e}")

    # ── Attempt 2: Native Windows Word COM Automation (Windows Only) ──
    if sys.platform == "win32":
        try:
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()
            word = win32com.client.DispatchEx("Word.Application")
            word.Visible = False
            word.DisplayAlerts = 0
            doc = word.Documents.Open(os.path.abspath(doc_path))
            doc.SaveAs(os.path.abspath(pdf_path), FileFormat=17) # 17 = wdFormatPDF
            doc.Close()
            word.Quit()
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000:
                sanitize_pdf_metadata(pdf_path, candidate_name=candidate_name, role=role)
                print(f"[PDF] [OK] Converted via Word COM: {pdf_path}")
                return pdf_path
        except Exception as e:
            print(f"[PDF] Word COM conversion note: {e}")

    # ── Attempt 3: Playwright Chromium from DOCX-to-HTML ──
    try:
        from resume_html import docx_to_html, generate_pdf_from_html
        html_content = docx_to_html(doc_path)
        if generate_pdf_from_html(html_content, pdf_path, candidate_name=candidate_name, role=role):
            sanitize_pdf_metadata(pdf_path, candidate_name=candidate_name, role=role)
            print(f"[PDF] [OK] Converted via Playwright Chromium DOCX: {pdf_path}")
            return pdf_path
    except Exception as e:
        print(f"[PDF] Playwright DOCX conversion note: {e}")

    if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 1000:
        sanitize_pdf_metadata(pdf_path, candidate_name=candidate_name, role=role)
        return pdf_path

    return ""



if __name__ == "__main__":
    """Quick test of the Word builder."""
    import sys
    
    resume_path = os.path.join(os.path.dirname(__file__), "base_resume.json")
    if not os.path.exists(resume_path):
        print("ERROR: base_resume.json not found.")
        sys.exit(1)
    
    with open(resume_path, 'r', encoding='utf-8') as f:
        resume = json.load(f)
    
    output = build_resume_docx(resume, "TestCompany", "Software Engineer")
    print(f"Generated: {output}")
