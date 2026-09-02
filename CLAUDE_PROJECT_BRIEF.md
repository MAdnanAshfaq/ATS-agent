# ATS AGENT & CAREER COPILOT — SYSTEM ARCHITECTURE & PROJECT BRIEF
================================================================================
Architect & Creator: M. Adnan Ashfaq
Repository: ATS-agent (github.com/MAdnanAshfaq/ATS-agent)
Primary Stack: Python, Flask, Playwright, Google Gemini SDK, BeautifulSoup4, python-docx
================================================================================

## 1. PROJECT VISION & PROBLEM STATEMENT
Modern hiring pipelines reject over 75% of qualified resumes before human review due to 
Applicant Tracking System (ATS) keyword mismatches (Workday, Greenhouse, Lever, Ashby, Taleo). 
Simultaneously, generic LLM-generated resumes are filtered out by recruiters and AI detectors 
due to recognizable AI writing tells (e.g. "Spearheaded", "Leveraged", uniform sentence cadence).

ATS Agent & Career Copilot is an autonomous multi-agent platform that turns a 45-minute manual 
job application tailoring process into an automated, high-precision 15-second workflow. 
It performs deep semantic extraction, human-voice rewriting (Rules 0–16), anti-detection auditing, 
recruiter-clean Word (.docx) & PDF document creation with scrubbed metadata, and generates 
discrete answers for portal application questions.

================================================================================
## 2. HIGH-LEVEL SYSTEM FLOW (ASCII DIAGRAM)
================================================================================

[Live Job URL or Raw JD Text]
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│ 1. INTELLIGENT SCRAPER & MULTI-FRAME EXTRACTOR          │
│    • Multi-frame Playwright for embedded ATS iframes    │
│    • Aggregator Immunity (HiringCafe, LinkedIn, Indeed) │
│    • Fallback pipeline: Playwright -> HTTP -> Jina API  │
└─────────────────────────┬───────────────────────────────┘
                          │ (Clean JD, Real Company, Role)
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 2. SEMANTIC ATS MATCH & GAP MATRIX                      │
│    • 0.0 - 10.0 Match Scoring Scale                     │
│    • Categorization: "Already Matched" vs "Missing"     │
│    • In-Place Editable Company Name & Bidirectional Sync│
└─────────────────────────┬───────────────────────────────┘
                          │ (Missing Hard Requirements & Custom Points)
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 3. DANI'S 4-AGENT COOPERATIVE PIPELINE                  │
│    ├─ Agent 1 (Researcher): Extracts atomic JD rubric   │
│    ├─ Agent 2 (Writer): Applies Rules 0-16 + Deep Weave │
│    ├─ Agent 3 (Auditor): Scans 15+ AI tells & clichés   │
│    └─ Agent 4 (Editor): Surgically fixes flagged lines  │
└─────────────────────────┬───────────────────────────────┘
                          │ (Polished Human-Voiced Profile)
                          ▼
┌─────────────────────────────────────────────────────────┐
│ 4. MULTI-SIGNAL OUTPUT & DOCUMENT GENERATION            │
│    ├─ Recruiter-Clean Word (.docx) & PDF (No AI traces) │
│    ├─ Live-Editable Cover Letter Generator (.docx/.txt) │
│    ├─ Application Q&A Copilot (Discrete Portal Answers) │
│    └─ Multi-Signal AI Content Lab (Detector & Humanizer)│
└─────────────────────────────────────────────────────────┘

================================================================================
## 3. CORE MODULES & FILE RESPONSIBILITIES
================================================================================

1. `scraper.py` (Multi-Frame Extraction Engine):
   - Uses Playwright to traverse embedded ATS iframes (Greenhouse, Lever, Ashby, Workday).
   - Prevents aggregator job boards (e.g. HiringCafe, Indeed, ZipRecruiter) from being 
     mistaken for the actual hiring company by extracting the real employer from the page 
     title ("Role at Company") and DOM headings ("About Company").
   - 3-tier fallback (Playwright -> Fast HTTP -> Jina Reader API proxy).

2. `danis_engine.py` (4-Agent Resume Engine):
   - Multi-Agent workflow:
     * Researcher: Extracts hard/soft skills and technical rubrics.
     * Writer: Applies ResumeHQ Rules 0–16 (Human voice gate, "So What?" test, plain strong 
       action verbs, metric mandate >= 50%). Deeply weaves required frameworks (e.g. SQLAlchemy, 
       Alembic, AWS, Terraform) directly into work experience stories, not just skills lists.
     * Auditor: Scans draft against `data/ai_tells.json` (cliché openers, banned AI words).
     * Editor: Fixes only flagged lines while preserving authentic facts and dates.

3. `llm_matcher.py` & `simplify_reader.py` (ATS Matrix & Scoring):
   - Computes real-time match scores and side-by-side comparisons (Title, Experience, Skills).
   - Generates interactive keyword chips allowing 1-click toggling for injection.

4. `resume_builder.py` & `cover_letter_generator.py` (Recruiter-Clean Document Engine):
   - Produces Microsoft Word (.docx) files using executive styling (0.5" margins, clean hierarchy).
   - Metadata Scrubbing: Removes default python-docx attributes; injects candidate name 
     as Author and live UTC timestamps to pass recruiter inspection.
   - Converts to PDF with native Word automation.

5. `qa_generator.py` (Application Q&A Copilot):
   - Splits batch-pasted portal questions (e.g. "Why ClassLink?", "Describe an outage") 
     into discrete items and crafts personalized, grounded answers in Dani's human voice.

6. `ai_detector.py` (Multi-Signal AI Content Lab):
   - Dual-engine testing: Self-hosted TMR RoBERTa detector server (via Google Colab) and 
     HuggingFace inference API.
   - Text Humanizer Studio: Rewrites text to maximize burstiness and eliminate AI sentence patterns.

7. `app.py`, `static/app.js`, `templates/index.html` (Full-Stack Application):
   - Flask backend with Server-Sent Events (SSE) for real-time progress streaming.
   - In-place editable company name and role with system-wide bidirectional sync.
   - 1-click job description bullets copying (`Copy All Job Bullets`, `Copy Description`).
   - Hard-deletion system that cleans logs and output directories on disk.

================================================================================
## 4. EDITORIAL PRIORITY RULES (RULES 0–16 STANDARD)
================================================================================
1. Authenticity: Never invent fake metrics, fake companies, or fake degrees.
2. Human Voice Gate (Rule 0): Must sound like a sharp engineer talking naturally.
3. The "So What?" Test (Rule 1): Every bullet states the action, technical scope, and measurable result.
4. Front-Load Value (Rule 2): First 3 words carry the punch (e.g., "Cut query latency 35%...").
5. Eliminate Deadwood (Rule 3): Banned phrases include "Responsible for", "Successfully", "Duties included".
6. Metrics Mandate (Rule 4): At least 50% of bullets contain concrete scale, speed, or volume numbers.
7. Plain Strong Verbs (Rule 5): Led, Built, Designed, Shipped, Automated, Optimized, Reduced, Implemented.

================================================================================
## 5. VALUE PROPOSITION & PERFORMANCE BENCHMARKS
================================================================================
- Speed: End-to-end tailoring from raw URL to .docx in < 15 seconds.
- Precision: 90%–98% ATS match rate across Workday, Greenhouse, Lever, and Simplify.
- AI Detection Immunity: Passes multi-signal AI detectors through burstiness & vocabulary variance.
- Comprehensive Output: Tailored Resume (.docx/.pdf) + Cover Letter + Form Q&A Answers.
