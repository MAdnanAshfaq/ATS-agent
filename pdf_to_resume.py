"""
pdf_to_resume.py - Gemini-powered PDF/DOCX resume parser.

Uses Gemini LLM to intelligently structure raw resume text.
Falls back to regex heuristics only if Gemini is unavailable.
"""
import json
import re
import os
import sys

# Fix Windows cp1252 encoding issues — only when running as __main__, not when imported by Flask
if __name__ == "__main__" and hasattr(sys.stdout, 'buffer'):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ─── Gemini LLM Parser (primary) ──────────────────────────────────────────────

def parse_with_gemini(raw_text: str) -> dict:
    """Use Gemini to parse raw resume text into structured JSON."""
    from gemini_client import get_gemini_client
    client = get_gemini_client()

    prompt = f"""You are an expert resume parser. Parse the following resume text into a clean, structured JSON object.

RULES:
- "name": First/last name only (e.g. "Jalal Khan") — NOT the job title
- "contact": {{ email, phone, linkedin (url only), github (url only), portfolio, location }}
- "summary": Professional summary paragraph only (no skill list text)
- "skills": Flat array of individual technology/skill strings extracted from the Skills section.
  Examples: ["JavaScript", "TypeScript", "React.js", "Next.js", "Node.js", "PostgreSQL", "AWS Lambda", "Docker", "Kubernetes", "LangChain", "GraphQL"]
  Extract ALL individual technologies — split comma/colon/pipe separated entries.
- "experience": Array of role objects, each with:
  {{ "title": job title, "company": company name, "dates": date range, "location": city/remote, "bullets": [array of bullet point strings] }}
  IMPORTANT: Correctly identify each role boundary. Bullet points are the actual responsibilities, not new roles.
- "education": Array of {{ institution, degree, field, graduation_date, gpa }}
- "projects": Array of {{ name, description, tech_stack: [], url }}
- "certifications": Array of strings

Return ONLY valid JSON. No markdown fences, no explanations.

RESUME TEXT:
{raw_text}
"""

    models = ["gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-3.5-flash", "gemini-2.5-flash-lite"]
    for model_name in models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={"temperature": 0.1, "max_output_tokens": 8192},
            )
            if not response or not response.text:
                continue
            text = response.text.strip()
            # Strip markdown fences if present
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            parsed = json.loads(text)
            print(f"[PDF Parser] ✅ Gemini parsed resume with model {model_name}")
            return parsed
        except json.JSONDecodeError as e:
            print(f"[PDF Parser] JSON parse error from {model_name}: {e}")
            continue
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                print(f"[PDF Parser] Rate limit on {model_name}, trying next...")
                continue
            print(f"[PDF Parser] Error with {model_name}: {e}")
            continue

    raise RuntimeError("All Gemini models failed or quota exceeded")


# ─── PDF / DOCX Text Extraction ───────────────────────────────────────────────

def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract raw text from a PDF file."""
    print(f"[PDF Parser] Reading PDF: {pdf_path}")
    full_text = ""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
    except Exception:
        try:
            import pypdf
            reader = pypdf.PdfReader(pdf_path)
            for page in reader.pages:
                full_text += (page.extract_text() or "") + "\n"
        except Exception as e:
            raise RuntimeError(f"Could not read PDF: {e}")
    print(f"[PDF Parser] Extracted {len(full_text)} characters from PDF")
    return full_text


def extract_text_from_docx(docx_path: str) -> str:
    """Extract raw text from a DOCX file — reads paragraphs AND table cells."""
    print(f"[PDF Parser] Reading DOCX: {docx_path}")
    try:
        from docx import Document
        from docx.oxml.ns import qn

        doc = Document(docx_path)
        lines = []

        def iter_block_items(parent):
            """Yield paragraphs and tables in document order."""
            from docx.oxml.ns import qn
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            from docx.oxml import OxmlElement

            for child in parent.element.body:
                tag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                if tag == 'p':
                    yield Paragraph(child, parent)
                elif tag == 'tbl':
                    yield Table(child, parent)

        for block in iter_block_items(doc):
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            if isinstance(block, Paragraph):
                text = block.text.strip()
                if text:
                    lines.append(text)
            elif isinstance(block, Table):
                for row in block.rows:
                    row_parts = []
                    for cell in row.cells:
                        cell_text = cell.text.strip()
                        if cell_text:
                            row_parts.append(cell_text)
                    if row_parts:
                        lines.append("  |  ".join(row_parts))

        full_text = "\n".join(lines)

        # Fallback: if we got almost nothing, try the simple path
        if len(full_text) < 200:
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            full_text = "\n".join(paragraphs)

        print(f"[PDF Parser] Extracted {len(full_text)} characters from DOCX ({len(lines)} blocks)")
        return full_text
    except Exception as e:
        raise RuntimeError(f"Could not read DOCX: {e}")


# ─── Public Entry Points ───────────────────────────────────────────────────────

def parse_resume_pdf(file_path: str) -> dict:
    """Parse a PDF or DOCX resume into structured JSON using Gemini."""
    path_lower = file_path.lower()

    if path_lower.endswith(".pdf"):
        raw_text = extract_text_from_pdf(file_path)
    elif path_lower.endswith(".docx"):
        raw_text = extract_text_from_docx(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_path}")

    # Try Gemini first
    try:
        result = parse_with_gemini(raw_text)
        result["_raw_text"] = raw_text  # Keep raw text for agent use
        return result
    except Exception as e:
        print(f"[PDF Parser] Gemini failed, using regex fallback: {e}")
        result = parse_text_to_json_fallback(raw_text)
        result["_raw_text"] = raw_text
        return result


def reparse_from_raw_text(raw_text: str) -> dict:
    """Re-parse an already-extracted raw text block using Gemini. Used for fixing bad parses."""
    try:
        result = parse_with_gemini(raw_text)
        result["_raw_text"] = raw_text
        return result
    except Exception as e:
        print(f"[PDF Parser] Gemini reparse failed: {e}")
        result = parse_text_to_json_fallback(raw_text)
        result["_raw_text"] = raw_text
        return result


# ─── Regex Fallback Parser ────────────────────────────────────────────────────

def parse_text_to_json_fallback(text: str) -> dict:
    """Emergency regex fallback — used only if Gemini is unavailable."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    email_match = re.search(r'[\w.+-]+@[\w-]+\.[a-zA-Z]+', text)
    phone_match = re.search(r'[\+]?[\d][\d\s\-\(\)]{7,15}[\d]', text)
    linkedin_match = re.search(r'linkedin\.com/in/[\w-]+', text, re.IGNORECASE)
    github_match = re.search(r'github\.com/[\w-]+', text, re.IGNORECASE)

    name = lines[0] if lines else ""

    section_headers = {
        'summary': r'(?i)(summary|objective|profile|about)',
        'skills': r'(?i)(skills?|technical skills?|tech[\s-]stack|skill[\s-]set|technologies)',
        'experience': r'(?i)(experience|work experience|employment|professional experience)',
        'education': r'(?i)(education|academic|degree)',
        'projects': r'(?i)(projects?|portfolio)',
        'certifications': r'(?i)(certifications?|certificates?|credentials)',
    }

    section_positions = {}
    for section, pattern in section_headers.items():
        for i, line in enumerate(lines):
            if re.match(pattern, line) and len(line) < 50:
                if section not in section_positions:
                    section_positions[section] = i

    sorted_sections = sorted(section_positions.items(), key=lambda x: x[1])
    section_texts = {}
    for idx, (section, start_line) in enumerate(sorted_sections):
        end_line = sorted_sections[idx + 1][1] if idx + 1 < len(sorted_sections) else len(lines)
        section_texts[section] = lines[start_line+1:end_line]

    summary_lines = section_texts.get('summary', [])
    summary = ' '.join(summary_lines) if summary_lines else ""

    skills_raw = ' '.join(section_texts.get('skills', []))
    skill_items = re.split(r'[,|•·\n:]+', skills_raw)
    skills = [s.strip() for s in skill_items if s.strip() and 2 < len(s.strip()) < 50]

    return {
        "name": name,
        "contact": {
            "email": email_match.group() if email_match else "",
            "phone": phone_match.group().strip() if phone_match else "",
            "linkedin": linkedin_match.group() if linkedin_match else "",
            "github": github_match.group() if github_match else "",
            "portfolio": "",
            "location": ""
        },
        "summary": summary,
        "skills": skills,
        "experience": [],
        "education": [],
        "projects": [],
        "certifications": [],
    }


def extract_location(text: str) -> str:
    loc_match = re.search(
        r'([A-Z][a-zA-Z\s]+,\s*(?:[A-Z]{2}|[A-Za-z]+(?:\s[A-Za-z]+)?))',
        text
    )
    return loc_match.group() if loc_match else ""


if __name__ == "__main__":
    # Quick test: reparse the current base_resume.json _raw_text
    import json
    base_path = os.path.join(os.path.dirname(__file__), "base_resume.json")
    with open(base_path, "r", encoding="utf-8") as f:
        existing = json.load(f)

    raw_text = existing.get("_raw_text", "")
    if not raw_text:
        print("ERROR: No _raw_text in base_resume.json. Upload a resume PDF first.")
        sys.exit(1)

    print("[Reparse] Re-parsing existing resume with Gemini LLM...")
    result = reparse_from_raw_text(raw_text)

    with open(base_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print("\nOK: base_resume.json reparsed successfully!")
    print(f"  Name: {result.get('name')}")
    print(f"  Skills: {len(result.get('skills', []))}")
    print(f"  Experience roles: {len(result.get('experience', []))}")
    for r in result.get('experience', []):
        print(f"    - {r.get('title')} @ {r.get('company')} ({r.get('dates')}) -- {len(r.get('bullets',[]))} bullets")
    print(f"  Education: {len(result.get('education', []))}")
