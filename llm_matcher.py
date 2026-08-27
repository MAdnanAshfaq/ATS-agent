"""
llm_matcher.py — Gemini LLM-based Keyword & Resume Analysis Engine.

Pushes BOTH the parsed Job Description AND the candidate's Master Resume to Gemini in Step 1.
Gemini semantically compares them and returns:
- Missing hard technical skills & job titles
- Already matching hard technical skills & job titles
- Accurate ATS match score (0-100%)
"""

import json
import os
import re
import sys
from google import genai
from google.genai import types

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

GENERIC_FILLER_WORDS = {
    "responsiveness", "knowledge", "leading", "work", "code", "ensure", "ensuring",
    "optimize", "optimizing", "integrating", "integration", "current", "design",
    "dynamic", "using", "use", "building", "build", "developing", "development",
    "maintaining", "maintenance", "collaborating", "collaboration", "implementing",
    "implementation", "understanding", "working", "deliver", "delivering", "create",
    "creating", "manage", "managing", "management", "provide", "providing",
    "support", "supporting", "help", "helping", "drive", "driving", "write",
    "writing", "test", "testing", "solution", "solutions", "platform", "platforms",
    "system", "systems", "application", "applications", "user", "users", "feature",
    "features", "requirement", "requirements", "quality", "process", "environment",
    "architecture", "teams", "player", "communication", "skills", "ability",
    "strong", "great", "good", "well", "experience", "candidate", "position", "job",
    "opportunity", "company", "including", "required", "preferred", "bonus", "etc",
    "scalable", "robust", "innovative", "transformative", "groundbreaking", "seamless"
}

def _flatten_resume_text(resume: dict) -> str:
    """Flatten entire resume JSON into a single lowercase searchable string."""
    text_chunks = []
    def _extract(val):
        if isinstance(val, str):
            text_chunks.append(val)
        elif isinstance(val, list):
            for item in val:
                _extract(item)
        elif isinstance(val, dict):
            for v in val.values():
                _extract(v)
    _extract(resume)
    return " ".join(text_chunks).lower()


def _normalize_token(text: str) -> str:
    """Normalize text by stemming plurals and common aliases."""
    t = text.lower().strip()
    t = re.sub(r'\brestful\b', 'rest', t)
    t = re.sub(r'\bpostgresql\b', 'postgres', t)
    t = re.sub(r'\bjavascript\b', 'js', t)
    t = re.sub(r'\btypescript\b', 'ts', t)
    t = re.sub(r'(?:houses|es|s)\b', '', t)
    return t


def is_keyword_in_resume(kw: str, resume_full_text: str, resume_skills_list: list) -> bool:
    """Intelligently check if a keyword or tool exists in candidate's resume."""
    kw_raw = kw.strip()
    kw_lower = kw_raw.lower()
    if not kw_lower:
        return False
    
    # Direct substring or word-boundary check
    if kw_lower in resume_full_text:
        return True
    
    pattern = r'\b' + re.escape(kw_lower) + r'\b'
    if re.search(pattern, resume_full_text):
        return True
        
    # Check normalized singular form
    norm_kw = _normalize_token(kw_lower)
    norm_resume = _normalize_token(resume_full_text)
    if norm_kw and norm_kw in norm_resume:
        return True

    # Check skills list directly
    for s in resume_skills_list:
        s_lower = str(s).lower().strip()
        if s_lower == kw_lower or s_lower in kw_lower or kw_lower in s_lower:
            return True
        if _normalize_token(s_lower) == norm_kw:
            return True

    # Compound skill check (e.g. 'Azure DevOps CI/CD', 'Delta Lake CDC', 'RESTful APIs')
    sub_parts = [p.strip() for p in re.split(r'[/&+|, ]+', kw_lower) if len(p.strip()) > 1]
    if sub_parts and len(sub_parts) > 1:
        match_count = sum(1 for p in sub_parts if p in resume_full_text or _normalize_token(p) in norm_resume)
        if match_count >= len(sub_parts) * 0.5:
            return True

    return False


def analyze_jd_and_resume_with_gemini(jd_text: str, base_resume: dict) -> dict:
    """
    Passes BOTH the scraped Job Description AND the candidate's Base Resume to Gemini.
    Gemini compares them semantically and returns high-value missing keywords,
    already matching keywords, and an accurate ATS match score.
    """
    from dotenv import load_dotenv
    load_dotenv()
    from gemini_client import get_gemini_client, execute_with_failover, get_all_gemini_keys

    keys = get_all_gemini_keys()
    if not keys:
        print("[LLM Matcher] Warning: GEMINI_API_KEY missing — returning empty keyword set")
        return {"score": 70, "matching_keywords": [], "missing_keywords": [], "total_keywords": 0}

    # ── JD quality gate ──
    # If the JD text is too thin or looks like a bot page, bail immediately.
    # This prevents Gemini from hallucinating keyword matches against garbage content.
    JD_BOT_SIGNATURES = [
        "human verification", "verify you are human", "just a moment",
        "access denied", "403 forbidden", "captcha", "checking your browser",
        "security check", "cloudflare", "enable javascript", "are you a human",
        "please wait", "ddos protection",
    ]
    jd_stripped = (jd_text or "").strip()
    jd_lower = jd_stripped.lower()
    if len(jd_stripped) < 800:
        print(f"[LLM Matcher] ❌ JD too short ({len(jd_stripped)} chars) — refusing to analyze; would produce hallucinated keywords.")
        return {"score": 0, "matching_keywords": [], "missing_keywords": [],
                "total_keywords": 0, "error": "jd_too_short"}
    for sig in JD_BOT_SIGNATURES:
        if sig in jd_lower:
            print(f"[LLM Matcher] ❌ JD matches bot-block pattern '{sig}' — refusing to analyze.")
            return {"score": 0, "matching_keywords": [], "missing_keywords": [],
                    "total_keywords": 0, "error": "jd_is_bot_page"}

    try:
        prompt = f"""You are an expert ATS (Applicant Tracking System) recruiter and resume architect.
Analyze the following Job Description against the Candidate's Master Resume.

YOUR TASK:
1. Extract 12-25 HIGH-VALUE HARD TECHNICAL SKILLS, programming languages, databases, cloud tools, frameworks, and job role qualifications THAT ARE EXPLICITLY PRESENT IN THE JOB DESCRIPTION.
2. Extract clean, concise tools/technologies (e.g. "Python", "PySpark", "SQL", "Pandas", "Polars", "Airflow", "AWS", "Databricks", "dbt", "Selenium") rather than long descriptions.
3. Categorize them into:
   - "matching_keywords": present in the candidate's resume
   - "missing_keywords": missing from the candidate's resume
4. Extract the following comparison data:
   - "job_title_jd": Target job title from the JD (e.g. "Data Engineer")
   - "job_title_resume": Candidate's current/recent job title from resume (e.g. "Data Engineer II")
   - "job_title_match": true if titles are semantically aligned/equivalent, else false
   - "exp_years_jd": Minimum years of experience requested in JD (e.g. "3+ years exp" or "5+ years exp" or "Entry level")
   - "exp_years_resume": Candidate total years of experience calculated from resume (e.g. "8+ years exp")
   - "exp_years_match": true if candidate meets or exceeds the required years, else false
   - "industries": Array of 3-7 relevant industry/domain tags for this company & role (e.g. ["Finance", "Financial Services", "FinTech", "Data Platform", "Analytics"])
   - "industries_match": true or false
   - "summary_feedback": 1-2 sentences evaluating how well the candidate's summary matches this specific role and what is missing.
   - "summary_match": true if summary is strong match, false if it needs tailoring
   - "score": Overall ATS match score (integer from 0 to 100)
   - "score_scale_10": Float from 0.0 to 10.0 (e.g. 5.5, 7.8, 8.5)
   - "score_rating": One of "Poor" (under 6.0), "Fair" (6.0-6.9), "Good" (7.0-7.9), "Great" (8.0-8.9), "Excellent" (9.0+)

CRITICAL RULES:
- ONLY extract skills/tools that are EXPLICITLY STATED in the Job Description text provided.
- STRICTLY EXCLUDE legal disclaimers, EEOC text, veteran disclosures, disability forms, and soft skill filler words.
- If the Job Description does not contain recognizable technical requirements, return empty lists and score 0.

JOB DESCRIPTION:
{jd_text[:6000]}

CANDIDATE MASTER RESUME:
{json.dumps(base_resume, indent=2, ensure_ascii=False)[:6000]}

OUTPUT FORMAT:
Return ONLY a valid JSON object matching this schema:
{{
  "score": 55,
  "score_scale_10": 5.5,
  "score_rating": "Poor",
  "job_title_jd": "Data Engineer",
  "job_title_resume": "Data Engineer II",
  "job_title_match": true,
  "exp_years_jd": "3+ years exp",
  "exp_years_resume": "8+ years exp",
  "exp_years_match": true,
  "industries": ["Finance", "FinTech", "Lending", "Data Platform"],
  "industries_match": false,
  "matching_keywords": ["Python", "PySpark", "SQL"],
  "missing_keywords": ["Dataframe Technologies", "Pandas", "Polars", "Airflow", "AWS"],
  "summary_feedback": "Your current summary does not effectively showcase your qualifications and alignment with this job.",
  "summary_match": false
}}"""

        def _call_gemini(client):
            models = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash"]
            resp = None
            last_err = None
            for m in models:
                try:
                    resp = client.models.generate_content(
                        model=m,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.1,
                            response_mime_type="application/json",
                        ),
                    )
                    if resp and resp.text:
                        print(f"[LLM Matcher] [OK] Extracted ATS matrix with {m} (JSON mode)")
                        return resp
                except Exception as model_err:
                    print(f"[LLM Matcher] {m} JSON mode note: {str(model_err)[:120]}")
                    last_err = model_err
                    continue

            # Fallback to plain text mode
            for m in models:
                try:
                    resp = client.models.generate_content(
                        model=m,
                        contents=prompt,
                    )
                    if resp and resp.text:
                        print(f"[LLM Matcher] [OK] Extracted ATS matrix with {m} (Plain text mode)")
                        return resp
                except Exception as model_err:
                    print(f"[LLM Matcher] {m} plain text note: {str(model_err)[:120]}")
                    last_err = model_err
                    continue

            if last_err and ("429" in str(last_err) or "RESOURCE_EXHAUSTED" in str(last_err)):
                raise last_err

            return resp

        response = execute_with_failover(_call_gemini)

        if not response or not response.text:
            return {"score": 70, "matching_keywords": [], "missing_keywords": [], "total_keywords": 0}

        raw_text = response.text.strip()
        # Strip markdown fences if present
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)

        parsed = json.loads(raw_text)

        # Extract structured matrix data with safe fallbacks
        raw_matching = parsed.get("matching_keywords", [])
        raw_missing  = parsed.get("missing_keywords", [])

        resume_full = _flatten_resume_text(base_resume)
        resume_skills = [str(s) for s in base_resume.get("skills", [])]

        final_matching = []
        final_missing  = []
        seen = set()

        for kw in raw_matching:
            k_clean = kw.strip()
            if not k_clean or k_clean.lower() in seen or k_clean.lower() in GENERIC_FILLER_WORDS:
                continue
            seen.add(k_clean.lower())
            final_matching.append(k_clean)

        for kw in raw_missing:
            k_clean = kw.strip()
            if not k_clean or k_clean.lower() in seen or k_clean.lower() in GENERIC_FILLER_WORDS:
                continue
            seen.add(k_clean.lower())
            if is_keyword_in_resume(k_clean, resume_full, resume_skills):
                final_matching.append(k_clean)
            else:
                final_missing.append(k_clean)

        tot = len(final_matching) + len(final_missing)
        score = parsed.get("score")
        if not score or not isinstance(score, (int, float)):
            score = round((len(final_matching) / max(tot, 1)) * 100)
        score = max(5, min(99, int(score)))

        score_10 = parsed.get("score_scale_10")
        if not score_10 or not isinstance(score_10, (int, float)):
            score_10 = round(score / 10.0, 1)
        else:
            score_10 = round(float(score_10), 1)

        rating = parsed.get("score_rating")
        if not rating:
            if score_10 < 6.0: rating = "Poor"
            elif score_10 < 7.0: rating = "Fair"
            elif score_10 < 8.0: rating = "Good"
            elif score_10 < 9.0: rating = "Great"
            else: rating = "Excellent"

        # Candidate name & file representation
        cand_name = base_resume.get("name", "Candidate")
        resume_name_tag = f"{cand_name.replace(' ', '_')}_Resume"

        res = {
            "score": score,
            "score_scale_10": score_10,
            "score_rating": rating,
            "resume_name": resume_name_tag,
            "job_title_jd": parsed.get("job_title_jd") or "Target Role",
            "job_title_resume": parsed.get("job_title_resume") or (base_resume.get("experience", [{}])[0].get("title", "Data Engineer")),
            "job_title_match": bool(parsed.get("job_title_match", True)),
            "exp_years_jd": parsed.get("exp_years_jd") or "3+ years exp",
            "exp_years_resume": parsed.get("exp_years_resume") or "8+ years exp",
            "exp_years_match": bool(parsed.get("exp_years_match", True)),
            "industries": parsed.get("industries", ["Technology", "Data Platform"]),
            "industries_match": bool(parsed.get("industries_match", False)),
            "matching_keywords": final_matching,
            "missing_keywords": final_missing,
            "total_keywords": tot,
            "summary_feedback": parsed.get("summary_feedback") or "Your current summary does not effectively showcase your qualifications and alignment with this job.",
            "summary_match": bool(parsed.get("summary_match", False)),
        }

        print(f"[LLM Matcher] ATS Matrix Result: Score {score_10}/10 ({rating}) | {len(final_matching)} matched / {tot} total keywords")
        return res

    except Exception as e:
        print(f"[LLM Matcher] Error calling Gemini: {e}")

    return {
        "score": 70,
        "score_scale_10": 7.0,
        "score_rating": "Fair",
        "resume_name": "Candidate_Resume",
        "job_title_jd": "Role",
        "job_title_resume": "Role",
        "job_title_match": True,
        "exp_years_jd": "3+ years exp",
        "exp_years_resume": "5+ years exp",
        "exp_years_match": True,
        "industries": ["Technology"],
        "industries_match": False,
        "matching_keywords": [],
        "missing_keywords": [],
        "total_keywords": 0,
        "summary_feedback": "Review your summary against the target job requirements.",
        "summary_match": False,
    }


def extract_keywords_with_gemini(jd_text: str) -> list[str]:
    """Compatibility wrapper for extract_keywords_with_gemini."""
    res = analyze_jd_and_resume_with_gemini(jd_text, {})
    return res.get("missing_keywords", [])


if __name__ == "__main__":
    sample_jd = """
    Senior Full Stack Engineer — Ashby / Infinity Constellation.
    Building web application infrastructure with React, Next.js, TypeScript, Node.js, GraphQL, PostgreSQL, Docker, AWS Lambda.
    Requires strong knowledge of system design, microservices, CI/CD automation tools, and Zapier integrations.
    """
    base_resume = {
        "summary": "Full Stack Engineer with React, Node.js, TypeScript, PostgreSQL",
        "skills": ["React", "TypeScript", "Node.js", "PostgreSQL", "Git", "REST APIs"]
    }
    analysis = analyze_jd_and_resume_with_gemini(sample_jd, base_resume)
    print("\n--- GEMINI JD VS RESUME ANALYSIS ---")
    print(json.dumps(analysis, indent=2))
