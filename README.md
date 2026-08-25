## Quick Start (1-Click on Windows)

1. Clone or download this repository.
2. Double-click **`Start_Agent.bat`**.
3. It will automatically check Python, install all required packages, configure Playwright Chromium, launch the local server, and open your web browser at `http://127.0.0.1:5000`.
4. Enter your free **Gemini API Key** in the web interface (under **Prerequisites & Setup**) and you're ready!

---

## What This Does


You paste a job description URL. The agent does everything from that point automatically:
1. Scrapes the full JD (LinkedIn, Lever, Greenhouse, Workday, Wellfound, and more)
2. Reads your Simplify keyword match score + missing keywords
3. Rewrites your resume with Gemini 1.5 Flash to inject every missing keyword naturally
4. Runs a double AI-writing detection loop (Wikipedia-based rules) to make it sound human
5. Saves a clean ATS-optimized Word document named after the company and role

**Total cost: $0. Permanently free.**

---

## One-Time Setup (Do This Once)

### Step 1: Install Dependencies

```bash
cd job-agent
pip install -r requirements.txt
playwright install chromium
```

### Step 2: Get Your Free Gemini API Key

Go to [aistudio.google.com](https://aistudio.google.com/) → **Get API Key** → Create API Key.  
Free tier: 1,500 requests/day. No credit card required.

### Step 3: Create Your .env File

```bash
copy .env.example .env
```

Open `.env` and fill in:
```
GEMINI_API_KEY=your_key_here
SIMPLIFY_EMAIL=jalal.dev.work@gmail.com
SIMPLIFY_PASSWORD=your_simplify_password
BASE_RESUME_PATH=base_resume.json
```

### Step 4: Parse Your PDF Resume

Place your `Jalal Khan - Resume.pdf` in the `job-agent/` folder, then run:

```bash
python pdf_to_resume.py
```

This generates `base_resume.json`. **Review the output and correct any parsing errors** — especially job titles, companies, and dates.

### Step 5: Set Up the Simplify Chrome Profile

```bash
python setup_simplify_profile.py
```

A Chrome window opens. In that window:
1. Go to the [Chrome Web Store](https://chromewebstore.google.com/) and install **Simplify Jobs**
2. Go to [simplify.jobs](https://simplify.jobs) and **log in** with your account
3. Test that the extension shows resume scores on a job page
4. **Close the Chrome window**

The profile is saved. You'll never need to log in again.

---

## Running the Agent

```bash
python agent.py --url https://jobs.lever.co/company/role-id
```

### Options

| Flag | Description |
|------|-------------|
| `--url URL` | Job description URL (required) |
| `--no-simplify` | Skip Simplify. Extract keywords from JD directly |
| `--passes N` | AI detection passes: 1, 2, or 3 (default: 2) |
| `--output PATH` | Custom output directory |

### Examples

```bash
# Standard full pipeline
python agent.py --url https://jobs.lever.co/tradeify/fullstack-engineer

# Without Simplify (for testing or if Simplify isn't set up)
python agent.py --url https://www.linkedin.com/jobs/view/123/ --no-simplify

# Extra detection pass for important applications
python agent.py --url https://boards.greenhouse.io/company/jobs/456 --passes 3
```

---

## Output

Every application gets its own folder:

```
output/
├── Tradeify_Full_Stack_Engineer/
│   └── Jalal_Khan_Resume.docx
├── Babylist_Staff_Engineer/
│   └── Jalal_Khan_Resume.docx
└── logs/
    └── run_20260810_154230.json
```

---

## The AI Detection Rules

The agent checks every sentence against these AI writing patterns:

| Category | What Gets Flagged |
|----------|-------------------|
| Language & Tone | "leveraged", "streamlined", "spearheaded", "robust", "seamless", "pivotal", "innovative" + 30 more |
| Vague Phrases | "improving convenience", "highlighting significance", "illustrating lasting influence" |
| Sentence Structure | "Not only X but also Y", adjective triplets, uniform bullet lengths |
| Formatting | Em dashes, random boldface, inconsistent title case |
| AI Artifacts | Sign-off phrases, contrast-reframes, "some experts argue" |

---

## Supported Job Boards

| Platform | Status |
|----------|--------|
| LinkedIn | ✅ Full support |
| Lever | ✅ Full support |
| Greenhouse | ✅ Full support |
| Workday | ✅ Full support |
| Wellfound | ✅ Full support |
| Ashby | ✅ Full support |
| SmartRecruiters | ✅ Full support |
| iCIMS | ✅ Full support |
| Generic ATS | ✅ Fallback extraction |

---

## Project Structure

```
job-agent/
├── agent.py                 # Main entry point
├── scraper.py               # JD scraping
├── simplify_reader.py       # Simplify keyword score reader
├── rewriter.py              # Gemini resume rewriter
├── ai_detector.py           # AI detection + cleanup loop
├── resume_builder.py        # Word document generator
├── pdf_to_resume.py         # One-time PDF parser utility
├── setup_simplify_profile.py  # One-time Simplify Chrome setup
├── base_resume.json         # Your master resume (auto-generated)
├── ai_signs.json            # Wikipedia AI writing detection rules
├── .env                     # Your credentials (never commit this)
├── .env.example             # Credentials template
├── requirements.txt         # Dependencies
└── output/                  # Generated resumes
```

---

## Cost Breakdown

| Tool | Cost |
|------|------|
| Gemini 1.5 Flash API | Free (1,500 req/day) |
| Playwright | Free, open source |
| python-docx | Free, open source |
| Simplify account | Free (read-only) |
| **Total** | **$0** |

Each application uses 3 Gemini API calls (1 rewrite + 2 detection passes).  
You can run **500 applications per day** before hitting any free tier limit.

---

## Troubleshooting

**"base_resume.json not found"**  
→ Run `python pdf_to_resume.py` first. Make sure `Jalal Khan - Resume.pdf` is in the job-agent folder.

**"GEMINI_API_KEY not found"**  
→ Check your `.env` file. Make sure `GEMINI_API_KEY=your_key` is set (no spaces around `=`).

**"JD extraction failed"**  
→ Try `--no-simplify` first to verify the rest of the pipeline works. Some sites (especially LinkedIn) require being logged in. Try running the scraper standalone: `python scraper.py https://your-url`.

**Simplify score not reading correctly**  
→ Re-run `python setup_simplify_profile.py` to refresh the Chrome profile. Make sure you're logged into Simplify in the profile window.

**JSON parsing error from Gemini**  
→ The agent retries 3 times automatically. If it keeps failing, check your API key usage at [aistudio.google.com](https://aistudio.google.com/).

---

*Built for Jalal Khan · jalal.dev.work@gmail.com · github.com/jalaldev1122*
