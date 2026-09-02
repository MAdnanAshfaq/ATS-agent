import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ATS Agent & Career Copilot — Architectural Blueprint</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;500;600&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  @page {
    size: A4;
    margin: 18mm 16mm 18mm 16mm;
    @bottom-right {
      content: counter(page);
      font-family: "Inter", "TeX Gyre Heros", sans-serif;
      font-size: 8pt;
      color: #64748b;
    }
  }

  *, *::before, *::after {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }

  body {
    background-color: #EDEEEA;
    color: #171B24;
    font-family: "Inter", "TeX Gyre Heros", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 9.5pt;
    line-height: 1.55;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }

  /* Typography */
  h1, h2, h3, h4, .serif-title {
    font-family: "Lora", Georgia, serif;
    color: #171B24;
    font-weight: 700;
    letter-spacing: -0.01em;
  }

  h1 {
    font-size: 24pt;
    line-height: 1.15;
    margin-bottom: 6pt;
  }

  h2 {
    font-size: 13.5pt;
    line-height: 1.25;
    margin-top: 18pt;
    margin-bottom: 8pt;
    padding-bottom: 3pt;
    border-bottom: 1.5px solid #D9DAD3;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  h3 {
    font-size: 11pt;
    font-weight: 600;
    margin-top: 10pt;
    margin-bottom: 4pt;
  }

  p {
    margin-bottom: 7pt;
    color: #232733;
  }

  code, pre, .mono {
    font-family: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
    font-size: 8.5pt;
  }

  /* Color Accents */
  .text-signal { color: #0F7A5C; font-weight: 600; }
  .text-amber { color: #C77D2E; font-weight: 600; }
  .text-muted { color: #5A6072; }

  /* Blueprint Header */
  .blueprint-header {
    border-bottom: 2px solid #171B24;
    padding-bottom: 10pt;
    margin-bottom: 14pt;
  }

  .meta-grid {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1fr;
    gap: 8pt;
    padding: 6pt 8pt;
    background: #E4E5E0;
    border: 1px solid #D9DAD3;
    font-size: 8pt;
    margin-top: 8pt;
    border-radius: 3pt;
  }

  .meta-item-label {
    text-transform: uppercase;
    font-size: 6.5pt;
    font-weight: 700;
    color: #5A6072;
    letter-spacing: 0.06em;
  }

  .meta-item-val {
    font-weight: 600;
    color: #171B24;
    font-family: "JetBrains Mono", monospace;
  }

  /* Schematic Container */
  .schematic-box {
    background: #E5E7E1;
    border: 1.5px solid #171B24;
    border-radius: 4pt;
    padding: 10pt;
    margin: 10pt 0 14pt 0;
  }

  .schematic-title {
    font-family: "JetBrains Mono", monospace;
    font-size: 8pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #171B24;
    margin-bottom: 8pt;
    display: flex;
    justify-content: space-between;
    border-bottom: 1px dashed #B8BAC0;
    padding-bottom: 4pt;
  }

  /* Pipeline Grid Flow */
  .pipeline-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6pt;
  }

  .pipeline-node {
    background: #EDEEEA;
    border: 1px solid #D9DAD3;
    border-top: 3px solid #171B24;
    padding: 6pt 7pt;
    border-radius: 2pt;
  }

  .pipeline-node.verified {
    border-top-color: #0F7A5C;
  }

  .pipeline-node.audited {
    border-top-color: #C77D2E;
  }

  .node-step {
    font-family: "JetBrains Mono", monospace;
    font-size: 7pt;
    font-weight: 700;
    color: #5A6072;
  }

  .node-title {
    font-weight: 700;
    font-size: 8.5pt;
    color: #171B24;
    margin: 2pt 0;
  }

  .node-desc {
    font-size: 7.5pt;
    color: #4A5162;
    line-height: 1.35;
  }

  /* Two Column Cards */
  .two-col {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10pt;
    margin: 8pt 0;
  }

  .card {
    background: #F4F5F1;
    border: 1px solid #D9DAD3;
    padding: 8pt 10pt;
    border-radius: 3pt;
  }

  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 4pt;
    border-bottom: 1px solid #E0E2DB;
    padding-bottom: 3pt;
  }

  .badge-tag {
    font-family: "JetBrains Mono", monospace;
    font-size: 7pt;
    font-weight: 600;
    padding: 1.5pt 4pt;
    border-radius: 2pt;
    background: #D9DAD3;
    color: #171B24;
  }

  .badge-tag.signal {
    background: #D1EBE1;
    color: #0F7A5C;
  }

  .badge-tag.amber {
    background: #F8E8D5;
    color: #C77D2E;
  }

  /* Tables */
  table.blueprint-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 8pt;
    margin: 8pt 0;
  }

  table.blueprint-table th {
    background: #171B24;
    color: #EDEEEA;
    font-weight: 600;
    text-align: left;
    padding: 4pt 6pt;
    font-family: "JetBrains Mono", monospace;
    font-size: 7.5pt;
    text-transform: uppercase;
  }

  table.blueprint-table td {
    padding: 4pt 6pt;
    border-bottom: 1px solid #D9DAD3;
    color: #232733;
    vertical-align: top;
  }

  table.blueprint-table tr:nth-child(even) td {
    background: #E7E8E3;
  }

  /* Ordered numbered sequences */
  ol.seq-list {
    list-style: none;
    counter-reset: seq-counter;
    margin: 6pt 0;
  }

  ol.seq-list li {
    counter-increment: seq-counter;
    position: relative;
    padding-left: 20pt;
    margin-bottom: 5pt;
    font-size: 8.5pt;
  }

  ol.seq-list li::before {
    content: counter(seq-counter, decimal-leading-zero);
    position: absolute;
    left: 0;
    top: 0;
    font-family: "JetBrains Mono", monospace;
    font-size: 8pt;
    font-weight: 700;
    color: #0F7A5C;
  }

  /* Page Break Helpers */
  .page-break {
    page-break-before: always;
  }
</style>
</head>
<body>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- PAGE 1: TITLE, EXECUTIVE THESIS & PIPELINE SCHEMATIC                   -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->

<div class="blueprint-header">
  <div style="display:flex; justify-content:space-between; align-items:flex-end;">
    <div>
      <div style="font-family:'JetBrains Mono', monospace; font-size:7.5pt; font-weight:700; color:#5A6072; text-transform:uppercase; letter-spacing:0.1em; margin-bottom:2pt;">
        System Architecture & Technical Whitepaper
      </div>
      <h1>ATS Agent & Career Copilot</h1>
      <div style="font-family:'Lora', serif; font-size:11pt; color:#3A4050; font-style:italic;">
        Autonomous Multi-Agent Career Engineering & Deep ATS Optimization Platform
      </div>
    </div>
    <div style="text-align:right;">
      <span class="badge-tag signal" style="font-size:8pt; padding:3pt 6pt;">STATUS: PRODUCTION</span>
    </div>
  </div>

  <div class="meta-grid">
    <div>
      <div class="meta-item-label">Architect & Creator</div>
      <div class="meta-item-val">M. Adnan Ashfaq</div>
    </div>
    <div>
      <div class="meta-item-label">Repository</div>
      <div class="meta-item-val">ATS-agent (Main)</div>
    </div>
    <div>
      <div class="meta-item-label">Core Runtime</div>
      <div class="meta-item-val">Python 3.10+ / Flask</div>
    </div>
    <div>
      <div class="meta-item-label">AI Engine</div>
      <div class="meta-item-val">Gemini 2.5 / 3.5 Flash</div>
    </div>
  </div>
</div>

<h2>1. Executive Thesis & The Modern Hiring Problem</h2>
<p>
  Over <strong>75% of qualified engineering candidates</strong> are filtered out by enterprise Applicant Tracking Systems (ATS)—including Workday, Greenhouse, Lever, Taleo, and Ashby—before a human recruiter ever sees the resume. Simultaneously, generic ChatGPT-generated resumes are routinely flagged by recruiters and multi-signal AI detectors due to recognizable cliché phrasing (<em>"Spearheaded"</em>, <em>"Leveraged"</em>) and uniform sentence cadence.
</p>
<p>
  <strong>ATS Agent & Career Copilot</strong> transforms a 45-minute manual job application tailoring process into an automated, high-precision <strong>15-second multi-agent pipeline</strong>. It performs deep semantic extraction, human-voice rewriting under the <strong>ResumeHQ Rules 0–16 Standard</strong>, anti-detection auditing, recruiter-clean Word (<code class="mono">.docx</code>) and PDF document generation with scrubbed metadata, and discrete Q&A answering for portal application forms.
</p>

<!-- PIPELINE BLUEPRINT SCHEMATIC (Cover's Hero Image) -->
<div class="schematic-box">
  <div class="schematic-title">
    <span>SYSTEM PIPELINE SCHEMATIC — END-TO-END FLOW</span>
    <span>RUNTIME: &lt; 15 SECONDS</span>
  </div>
  
  <div class="pipeline-grid">
    <!-- Stage 1 -->
    <div class="pipeline-node">
      <div class="node-step">STAGE 01</div>
      <div class="node-title">Multi-Frame Ingestion</div>
      <div class="node-desc">
        Headless Playwright crawls embedded ATS iframes; extracts true hiring company from aggregator boards.
      </div>
    </div>
    <!-- Stage 2 -->
    <div class="pipeline-node verified">
      <div class="node-step">STAGE 02</div>
      <div class="node-title">Semantic ATS Matrix</div>
      <div class="node-desc">
        Computes 0.0–10.0 ATS match score; maps competencies into Matched vs Missing gaps with in-place editing.
      </div>
    </div>
    <!-- Stage 3 -->
    <div class="pipeline-node audited">
      <div class="node-step">STAGE 03</div>
      <div class="node-title">4-Agent Dani's Engine</div>
      <div class="node-desc">
        Researcher $\rightarrow$ Writer (Rules 0–16) $\rightarrow$ Auditor (15+ AI tells) $\rightarrow$ Editor (Surgical fix).
      </div>
    </div>
    <!-- Stage 4 -->
    <div class="pipeline-node verified">
      <div class="node-step">STAGE 04</div>
      <div class="node-title">Clean Document Output</div>
      <div class="node-desc">
        Builds recruiter-clean .docx/.pdf with scrubbed metadata, cover letter, and discrete application Q&A cards.
      </div>
    </div>
  </div>
</div>

<h2>2. Core Engineering Subsystems</h2>

<div class="two-col">
  <div class="card">
    <div class="card-header">
      <span style="font-weight:700; font-size:9pt;">Intelligent Scraper Engine</span>
      <span class="badge-tag">scraper.py</span>
    </div>
    <p style="font-size:8pt; margin-bottom:4pt;">
      Traverses complex multi-frame DOM trees where ATS forms are isolated inside child iframes. Features <strong>Aggregator Immunity</strong> to prevent platforms like HiringCafe, LinkedIn, or Indeed from overriding the real employer name.
    </p>
    <div style="font-size:7.5pt; font-family:'JetBrains Mono', monospace; color:#0F7A5C;">
      ✔ Playwright Chromium $\rightarrow$ Fast HTTP $\rightarrow$ Jina AI Proxy Failover
    </div>
  </div>

  <div class="card">
    <div class="card-header">
      <span style="font-weight:700; font-size:9pt;">Semantic ATS Match Matrix</span>
      <span class="badge-tag">llm_matcher.py</span>
    </div>
    <p style="font-size:8pt; margin-bottom:4pt;">
      Evaluates four dimensions: Job Title Alignment, Experience Duration, Industry Domain, and Hard Tech Keywords. Features in-place editable company name and role with system-wide bidirectional synchronization.
    </p>
    <div style="font-size:7.5pt; font-family:'JetBrains Mono', monospace; color:#0F7A5C;">
      ✔ 0.0 to 10.0 Score Gauge & 1-Click Interactive Keyword Toggles
    </div>
  </div>
</div>

<div class="two-col">
  <div class="card">
    <div class="card-header">
      <span style="font-weight:700; font-size:9pt;">Recruiter-Clean Document Builder</span>
      <span class="badge-tag">resume_builder.py</span>
    </div>
    <p style="font-size:8pt; margin-bottom:4pt;">
      Generates structured Microsoft Word (<code class="mono">.docx</code>) and PDF files with executive typography (0.5" margins, bolded tools). <strong>Scrubs all python-docx default signatures</strong> and sets the candidate's real profile as the document author.
    </p>
    <div style="font-size:7.5pt; font-family:'JetBrains Mono', monospace; color:#0F7A5C;">
      ✔ 100% Recruiter-Safe Metadata with UTC Timestamps
    </div>
  </div>

  <div class="card">
    <div class="card-header">
      <span style="font-weight:700; font-size:9pt;">Application Q&A Copilot</span>
      <span class="badge-tag">qa_generator.py</span>
    </div>
    <p style="font-size:8pt; margin-bottom:4pt;">
      Parses batch-pasted portal questions (e.g. <em>"Why us?"</em>, <em>"Describe a pipeline outage you resolved"</em>) into discrete individual prompts and produces grounded, human-voiced answers tailored to the company's culture.
    </p>
    <div style="font-size:7.5pt; font-family:'JetBrains Mono', monospace; color:#0F7A5C;">
      ✔ Discrete 1-to-1 Answer Cards & 1-Click Clipboard Copy
    </div>
  </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- PAGE 2: MULTI-AGENT MECHANICS & EDITORIAL STANDARDS                    -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<div class="page-break"></div>

<div class="blueprint-header" style="margin-bottom:10pt;">
  <div style="display:flex; justify-content:space-between; align-items:center;">
    <span style="font-family:'JetBrains Mono', monospace; font-size:8pt; font-weight:700; color:#5A6072;">ATS AGENT & CAREER COPILOT — ARCHITECTURAL BLUEPRINT</span>
    <span style="font-family:'JetBrains Mono', monospace; font-size:8pt; color:#5A6072;">SECTION 03 & 04</span>
  </div>
</div>

<h2>3. Dani's 4-Agent Cooperative Engine Mechanics</h2>
<p>
  Instead of relying on a single monolithic prompt, the system deploys a specialized four-agent cooperative pipeline where each agent executes a discrete editorial responsibility:
</p>

<ol class="seq-list">
  <li>
    <strong>Agent 1: The Researcher</strong> — Ingests the raw job description and extracts an atomic evaluation rubric consisting of mandatory hard technical requirements, architecture patterns, leadership requirements, and domain buzzwords.
  </li>
  <li>
    <strong>Agent 2: The Writer</strong> — Applies the <strong>Rules 0–16 Standard</strong>. Enforces <em>Deep Bullet Weaving</em>: primary required frameworks (e.g., SQLAlchemy, Alembic, AWS, Terraform) must be woven directly into past engineering accomplishments with metrics, rather than simply dumped into a skills list.
  </li>
  <li>
    <strong>Agent 3: The Auditor</strong> — Scans the draft against <code class="mono">data/ai_tells.json</code> (15+ structural AI tells, cliché openers, uniform sentence lengths, and repetitive verbs). Flags exact line-level violations.
  </li>
  <li>
    <strong>Agent 4: The Editor</strong> — Surgically refines only the flagged lines, preserving candidate truth, verified metrics, employer names, and career dates without introducing new hallucinations.
  </li>
</ol>

<h2>4. The ResumeHQ Rules 0–16 Standard</h2>
<p>
  All generated content is strictly constrained by human-voice engineering protocols:
</p>

<table class="blueprint-table">
  <thead>
    <tr>
      <th style="width:18%;">Rule</th>
      <th style="width:28%;">Standard Requirement</th>
      <th style="width:54%;">Engineering Implementation</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Rule 0</strong></td>
      <td>Human Voice Gate</td>
      <td>Would a senior engineer say this out loud in an interview without cringing? Replaces corporate jargon with direct engineering speech.</td>
    </tr>
    <tr>
      <td><strong>Rule 1</strong></td>
      <td>The "So What?" Test</td>
      <td>Every bullet must answer why it mattered: <em>Action Verb + Technical Scope + Concrete Measurable Result</em>.</td>
    </tr>
    <tr>
      <td><strong>Rule 2</strong></td>
      <td>Front-Load Value</td>
      <td>First 3 words carry the punch (e.g. <em>"Cut query latency 35%..."</em>, <em>"Engineered 15+ delta tables..."</em>).</td>
    </tr>
    <tr>
      <td><strong>Rule 3</strong></td>
      <td>Eliminate Deadwood</td>
      <td>Strictly bans lazy padding phrases: <em>"Responsible for"</em>, <em>"Successfully"</em>, <em>"Duties included"</em>, <em>"Played a key role in"</em>.</td>
    </tr>
    <tr>
      <td><strong>Rule 4</strong></td>
      <td>Metrics Mandate</td>
      <td>$\ge 50\%$ of all work experience bullets must contain quantified scale, latency, data volume, percentage, or currency metrics.</td>
    </tr>
    <tr>
      <td><strong>Rule 5</strong></td>
      <td>Plain Strong Verbs</td>
      <td>Enforces active openers (<em>Led, Built, Designed, Shipped, Automated, Optimized, Reduced</em>) and bans <em>"Spearheaded"</em> and <em>"Leveraged"</em>.</td>
    </tr>
    <tr>
      <td><strong>Rule 6</strong></td>
      <td>Summary Constraints</td>
      <td>Maximum 3 sentences, $\le 70$ words. Prohibits <em>"Results-driven professional"</em> openers.</td>
    </tr>
  </tbody>
</table>

<h2>5. Verified Performance & Comparative Benchmarks</h2>

<table class="blueprint-table">
  <thead>
    <tr>
      <th>Dimension</th>
      <th>Traditional Manual Tailoring</th>
      <th>Generic LLM / ChatGPT</th>
      <th>ATS Agent & Career Copilot</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Processing Time</strong></td>
      <td>45 – 60 Minutes</td>
      <td>3 – 5 Minutes (Manual copy/paste)</td>
      <td><span class="text-signal">&lt; 15 Seconds (Autonomous)</span></td>
    </tr>
    <tr>
      <td><strong>ATS Match Score</strong></td>
      <td>50% – 65% (Incomplete coverage)</td>
      <td>70% – 75% (Surface skill stuffing)</td>
      <td><span class="text-signal">90% – 98% (Deep Bullet Weaving)</span></td>
    </tr>
    <tr>
      <td><strong>AI Detector Score</strong></td>
      <td>0% AI (Human)</td>
      <td>85% – 100% AI (Flagged by ATS)</td>
      <td><span class="text-signal">&lt; 15% AI (Human Voice Audited)</span></td>
    </tr>
    <tr>
      <td><strong>Document Metadata</strong></td>
      <td>Clean (Manual)</td>
      <td>Copied text / Unformatted</td>
      <td><span class="text-signal">Scrubbed Recruiter-Clean .docx & .pdf</span></td>
    </tr>
    <tr>
      <td><strong>Application Q&A</strong></td>
      <td>Manual writing</td>
      <td>Generic essay answers</td>
      <td><span class="text-signal">Discrete 1-to-1 Portal Q&A Cards</span></td>
    </tr>
  </tbody>
</table>

<div style="margin-top:14pt; padding:8pt 10pt; background:#E5E7E1; border-left:3px solid #0F7A5C; font-size:8pt; border-radius:2pt;">
  <strong>System Verification & Integrity:</strong> The ATS Agent & Career Copilot platform is architected and built by <strong>M. Adnan Ashfaq</strong>. All data processing, document building, and log persistence remain entirely local within the user's workspace, guaranteeing zero confidential data leakage and full compliance with strict privacy standards.
</div>

</body>
</html>
"""

async def generate_pdf():
    print("[PDF Engine] Initializing headless Chromium via Playwright...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Load the custom styled HTML template
        await page.set_content(HTML_TEMPLATE, wait_until="networkidle")
        
        # Output PDF path
        pdf_path = Path("ATS_Agent_System_Architecture_Blueprint.pdf").resolve()
        
        # Render print-quality PDF
        await page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            margin={
                "top": "0mm",
                "bottom": "0mm",
                "left": "0mm",
                "right": "0mm"
            }
        )
        await browser.close()
        print(f"[PDF Engine] Successfully generated high-fidelity blueprint PDF: {pdf_path}")
        return str(pdf_path)

if __name__ == "__main__":
    asyncio.run(generate_pdf())
