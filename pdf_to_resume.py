"""
pdf_to_resume.py — One-time utility to parse Jalal's PDF resume into base_resume.json
Run: python pdf_to_resume.py
"""
import json
import re
import os
import sys

def parse_resume_pdf(pdf_path: str) -> dict:
    """Parse a PDF resume into structured JSON using pdfplumber or pypdf."""
    print(f"[PDF Parser] Reading: {pdf_path}")
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

    print(f"[PDF Parser] Extracted {len(full_text)} characters")
    return parse_text_to_json(full_text)


def parse_text_to_json(text: str) -> dict:
    """Parse raw resume text into structured JSON."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    
    # --- Extract Contact Info ---
    name = lines[0] if lines else "Jalal Khan"
    
    # Find email
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[a-zA-Z]+', text)
    email = email_match.group() if email_match else "jalal.dev.work@gmail.com"
    
    # Find phone
    phone_match = re.search(r'[\+]?[\d][\d\s\-\(\)]{7,15}[\d]', text)
    phone = phone_match.group().strip() if phone_match else ""
    
    # Find LinkedIn
    linkedin_match = re.search(r'linkedin\.com/in/[\w-]+', text, re.IGNORECASE)
    linkedin = linkedin_match.group() if linkedin_match else "linkedin.com/in/mjalalkhan23"
    
    # Find GitHub
    github_match = re.search(r'github\.com/[\w-]+', text, re.IGNORECASE)
    github = github_match.group() if github_match else "github.com/jalaldev1122"
    
    # Find portfolio/website
    portfolio_match = re.search(r'(https?://)?[\w-]+\.(?:dev|io|com|me)/[\w/-]*', text, re.IGNORECASE)
    portfolio = portfolio_match.group() if portfolio_match else ""
    
    # --- Section Detection ---
    section_headers = {
        'summary': r'(?i)(summary|objective|profile|about)',
        'skills': r'(?i)(skills|technical skills|technologies|tech stack)',
        'experience': r'(?i)(experience|work experience|employment|professional experience)',
        'education': r'(?i)(education|academic|degree)',
        'projects': r'(?i)(projects|portfolio|side projects)',
        'certifications': r'(?i)(certifications|certificates|credentials)',
    }
    
    section_positions = {}
    for section, pattern in section_headers.items():
        for i, line in enumerate(lines):
            if re.match(pattern, line) and len(line) < 40:
                if section not in section_positions:
                    section_positions[section] = i
    
    # Sort sections by position
    sorted_sections = sorted(section_positions.items(), key=lambda x: x[1])
    
    # Extract section text blocks
    section_texts = {}
    for idx, (section, start_line) in enumerate(sorted_sections):
        if idx + 1 < len(sorted_sections):
            end_line = sorted_sections[idx + 1][1]
        else:
            end_line = len(lines)
        section_texts[section] = lines[start_line+1:end_line]
    
    # --- Parse Summary ---
    summary_lines = section_texts.get('summary', [])
    summary = ' '.join(summary_lines) if summary_lines else (
        "Software engineer with experience building scalable web applications and distributed systems."
    )
    
    # --- Parse Skills ---
    skills_lines = section_texts.get('skills', [])
    skills_raw = ' '.join(skills_lines)
    # Split on common delimiters
    skill_items = re.split(r'[,|•·\n]+', skills_raw)
    skills = [s.strip() for s in skill_items if s.strip() and len(s.strip()) < 40]
    
    # --- Parse Experience ---
    exp_lines = section_texts.get('experience', [])
    experience = parse_experience_section(exp_lines)
    
    # --- Parse Education ---
    edu_lines = section_texts.get('education', [])
    education = parse_education_section(edu_lines)
    
    # --- Parse Projects ---
    proj_lines = section_texts.get('projects', [])
    projects = parse_projects_section(proj_lines)
    
    # --- Parse Certifications ---
    cert_lines = section_texts.get('certifications', [])
    certifications = [l for l in cert_lines if l and len(l) > 5]
    
    resume = {
        "name": name,
        "contact": {
            "email": email,
            "phone": phone,
            "linkedin": linkedin,
            "github": github,
            "portfolio": portfolio,
            "location": extract_location(text)
        },
        "summary": summary,
        "skills": skills,
        "experience": experience,
        "education": education,
        "projects": projects,
        "certifications": certifications,
        "_raw_text": text  # Keep raw for Gemini to use if parsing is incomplete
    }
    
    return resume


def extract_location(text: str) -> str:
    """Try to find location/city from resume text."""
    # Common patterns: "City, State" or "City, Country"
    loc_match = re.search(
        r'([A-Z][a-zA-Z\s]+,\s*(?:[A-Z]{2}|[A-Za-z]+(?:\s[A-Za-z]+)?))',
        text
    )
    return loc_match.group() if loc_match else ""


def parse_experience_section(lines: list) -> list:
    """Parse experience section into structured list of roles."""
    experience = []
    current_role = None
    current_bullets = []
    
    # Date pattern
    date_pattern = re.compile(
        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|'
        r'April|May|June|July|August|September|October|November|December|\d{4})'
        r'[\s\–\-—]+(?:Present|Current|Now|\d{4})',
        re.IGNORECASE
    )
    
    for line in lines:
        if not line:
            continue
        
        is_date_line = bool(date_pattern.search(line))
        is_bullet = line.startswith(('•', '-', '·', '▪', '*', '–'))
        
        # Heuristic: a new role starts with a title line (no bullet, not just a date)
        if not is_bullet and not is_date_line and len(line) < 80:
            # Save previous role
            if current_role:
                if current_bullets:
                    current_role['bullets'] = current_bullets
                experience.append(current_role)
            
            # Check if next pattern is "Title at Company" or "Title | Company"
            title_company = re.split(r'\s+(?:at|@|\|)\s+', line, maxsplit=1)
            if len(title_company) == 2:
                current_role = {
                    "title": title_company[0].strip(),
                    "company": title_company[1].strip(),
                    "dates": "",
                    "location": "",
                    "bullets": []
                }
            else:
                current_role = {
                    "title": line,
                    "company": "",
                    "dates": "",
                    "location": "",
                    "bullets": []
                }
            current_bullets = []
        
        elif is_date_line and current_role:
            current_role['dates'] = line.strip()
        
        elif is_bullet and current_role:
            bullet_text = re.sub(r'^[•\-·▪\*–]\s*', '', line).strip()
            if bullet_text:
                current_bullets.append(bullet_text)
        
        elif not is_bullet and current_role and not is_date_line:
            # Could be company name on second line, or location
            if not current_role.get('company'):
                current_role['company'] = line
            elif not current_role.get('location'):
                current_role['location'] = line
    
    # Don't forget last role
    if current_role:
        if current_bullets:
            current_role['bullets'] = current_bullets
        experience.append(current_role)
    
    # Clean up: remove roles with no title
    experience = [e for e in experience if e.get('title') and len(e['title']) > 2]
    
    return experience


def parse_education_section(lines: list) -> list:
    """Parse education section."""
    education = []
    current_edu = None
    
    for line in lines:
        if not line:
            continue
        
        # Degree indicators
        is_degree = bool(re.search(
            r'(Bachelor|Master|B\.S\.|M\.S\.|B\.A\.|M\.A\.|PhD|Ph\.D\.|'
            r'Associate|B\.Tech|M\.Tech|B\.E\.|M\.E\.)',
            line, re.IGNORECASE
        ))
        
        # Date pattern
        is_date = bool(re.search(r'\d{4}', line))
        is_bullet = line.startswith(('•', '-', '·', '▪', '*'))
        
        if is_degree or (not is_bullet and not is_date and len(line) < 80 and not current_edu):
            if current_edu:
                education.append(current_edu)
            current_edu = {
                "institution": "",
                "degree": "",
                "field": "",
                "graduation_date": "",
                "gpa": ""
            }
            
            # Try to split degree from institution
            parts = re.split(r'\s+(?:at|from|,|–)\s+', line, maxsplit=1)
            if is_degree:
                current_edu['degree'] = line
            else:
                current_edu['institution'] = line
        
        elif is_date and current_edu:
            if not current_edu.get('graduation_date'):
                current_edu['graduation_date'] = line
        
        elif current_edu:
            if not current_edu.get('institution'):
                current_edu['institution'] = line
            elif not current_edu.get('degree') and not is_bullet:
                current_edu['degree'] = line
    
    if current_edu:
        education.append(current_edu)
    
    return [e for e in education if e.get('institution') or e.get('degree')]


def parse_projects_section(lines: list) -> list:
    """Parse projects section."""
    projects = []
    current_project = None
    current_bullets = []
    
    for line in lines:
        if not line:
            continue
        
        is_bullet = line.startswith(('•', '-', '·', '▪', '*', '–'))
        
        if not is_bullet and len(line) < 80:
            if current_project:
                current_project['description'] = ' '.join(current_bullets)
                projects.append(current_project)
            
            current_project = {
                "name": line,
                "tech_stack": [],
                "description": "",
                "url": ""
            }
            current_bullets = []
            
            # Extract URL if in line
            url_match = re.search(r'https?://[\w./\-?=&#]+', line)
            if url_match:
                current_project['url'] = url_match.group()
        
        elif is_bullet and current_project:
            bullet = re.sub(r'^[•\-·▪\*–]\s*', '', line).strip()
            if bullet:
                current_bullets.append(bullet)
                # Detect tech stack mentions
                tech_found = re.findall(
                    r'\b(React|Vue|Angular|Node\.?js|Python|Django|Flask|FastAPI|'
                    r'TypeScript|JavaScript|Go|Rust|Java|Kotlin|Swift|Ruby|PHP|'
                    r'PostgreSQL|MySQL|MongoDB|Redis|AWS|GCP|Azure|Docker|Kubernetes|'
                    r'GraphQL|REST|API|Playwright|Next\.?js|Express)\b',
                    bullet, re.IGNORECASE
                )
                current_project['tech_stack'].extend(tech_found)
        
        elif current_project:
            current_bullets.append(line)
    
    if current_project:
        current_project['description'] = ' '.join(current_bullets)
        projects.append(current_project)
    
    return projects


def main():
    # Find the PDF
    pdf_paths = [
        r"c:\Users\Dell\Desktop\xd\Agent\Jalal Khan - Resume.pdf",
        r"Jalal Khan - Resume.pdf",
        r"resume.pdf",
    ]
    
    pdf_path = None
    for p in pdf_paths:
        if os.path.exists(p):
            pdf_path = p
            break
    
    if not pdf_path:
        print("ERROR: Could not find resume PDF. Checked:")
        for p in pdf_paths:
            print(f"  - {p}")
        print("\nPlease place your resume PDF in the job-agent folder as 'Jalal Khan - Resume.pdf'")
        sys.exit(1)
    
    resume = parse_resume_pdf(pdf_path)
    
    # Save to base_resume.json
    output_path = os.path.join(os.path.dirname(__file__), "base_resume.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(resume, f, indent=2, ensure_ascii=False)
    
    print(f"\n[PDF Parser] ✅ Saved to {output_path}")
    print("\n[PDF Parser] Parsed Structure:")
    print(f"  Name: {resume['name']}")
    print(f"  Email: {resume['contact']['email']}")
    print(f"  LinkedIn: {resume['contact']['linkedin']}")
    print(f"  GitHub: {resume['contact']['github']}")
    print(f"  Skills ({len(resume['skills'])}): {', '.join(resume['skills'][:8])}{'...' if len(resume['skills']) > 8 else ''}")
    print(f"  Experience Roles: {len(resume['experience'])}")
    for role in resume['experience']:
        print(f"    • {role['title']} at {role['company']} ({role['dates']}) — {len(role['bullets'])} bullets")
    print(f"  Education: {len(resume['education'])} entries")
    print(f"  Projects: {len(resume['projects'])} entries")
    
    print("\n[PDF Parser] ⚠️  Please review base_resume.json and correct any parsing errors.")
    print("[PDF Parser] Pay special attention to: experience bullet points, company names, dates.")


if __name__ == "__main__":
    main()
