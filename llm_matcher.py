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
from google import genai
from google.genai import types

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


def analyze_jd_and_resume_with_gemini(jd_text: str, base_resume: dict) -> dict:
    """
    Passes BOTH the scraped Job Description AND the candidate's Base Resume to Gemini.
    Gemini compares them semantically and returns high-value missing keywords,
    already matching keywords, and an accurate ATS match score.
    """
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("[LLM Matcher] Warning: GEMINI_API_KEY missing — returning empty keyword set")
        return {"score": 70, "matching_keywords": [], "missing_keywords": [], "total_keywords": 0}

    try:
        client = genai.Client(api_key=api_key)

        prompt = f"""You are an expert ATS (Applicant Tracking System) recruiter and resume architect.
Analyze the following Job Description against the Candidate's Master Resume.

YOUR TASK:
1. Extract 12-25 HIGH-VALUE HARD TECHNICAL SKILLS, frameworks, programming languages, databases, cloud tools, and job role qualifications required by the Job Description.
2. Cross-check each keyword against the candidate's Master Resume.
3. Categorize them into "matching_keywords" (present in candidate resume) and "missing_keywords" (missing from candidate resume).
4. Calculate an accurate ATS Match Score (0-100%) based on how well candidate's experience covers the core requirements.

CRITICAL EXCLUSION RULES:
- ONLY HARD TECHNICAL SKILLS & ROLE TITLES (e.g. Python, React, Next.js, TypeScript, Node.js, AWS, Docker, PostgreSQL, GraphQL, Microservices, CI/CD, Redis, System Design).
- STRICTLY EXCLUDE legal disclaimers, EEOC text, veteran disclosures, disability forms, paperwork reduction act, executive orders, locations (e.g. San Francisco, United States), application form fields (e.g. cover letter drag, gender select, education add), and soft skill filler words.

JOB DESCRIPTION:
{jd_text[:6000]}

CANDIDATE MASTER RESUME:
{json.dumps(base_resume, indent=2, ensure_ascii=False)[:6000]}

OUTPUT FORMAT:
Return ONLY a valid JSON object matching this schema:
{{
  "score": 75,
  "matching_keywords": ["React", "TypeScript", "Node.js", "PostgreSQL"],
  "missing_keywords": ["GraphQL", "Docker", "AWS Lambda", "Redis"]
}}"""

        # Confirmed working order: gemini-3.1-flash-lite is verified with this key type.
        # gemini-3.5-flash / gemini-2.5-flash may return None text in JSON mode with some key types.
        models = [
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",
            "gemini-3.5-flash",
            "gemini-3.1-pro-preview",
        ]
        response = None

        # Pass 1: try with JSON mode (cleanest output)
        for m in models:
            try:
                response = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                    ),
                )
                if response and response.text:
                    print(f"[LLM Matcher] Using model: {m} (JSON mode)")
                    break
                response = None  # reset if text is None
            except Exception as model_err:
                print(f"[LLM Matcher] {m} JSON mode error: {model_err}")
                response = None
                continue

        # Pass 2: if JSON mode gave None, retry without mime type constraint
        if not response or not response.text:
            print("[LLM Matcher] JSON mode returned None — retrying in plain text mode...")
            for m in models:
                try:
                    response = client.models.generate_content(
                        model=m,
                        contents=prompt + "\n\nIMPORTANT: Respond ONLY with a raw JSON object, no markdown, no explanation.",
                        config=types.GenerateContentConfig(temperature=0.1),
                    )
                    if response and response.text:
                        print(f"[LLM Matcher] Using model: {m} (plain text mode)")
                        break
                    response = None
                except Exception as model_err:
                    print(f"[LLM Matcher] {m} plain mode error: {model_err}")
                    response = None
                    continue

        if not response or not response.text:
            raise RuntimeError("All Gemini models exhausted — no usable response")


        raw_text = response.text or ""
        match_json = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match_json:
            cleaned_text = match_json.group(0)
        else:
            cleaned_text = raw_text.replace("```json", "").replace("```", "").strip()
        data = json.loads(cleaned_text)

        if isinstance(data, dict):
            raw_missing = [str(k).strip() for k in data.get("missing_keywords", []) if str(k).strip()]
            raw_matching = [str(k).strip() for k in data.get("matching_keywords", []) if str(k).strip()]

            # Combine all keywords extracted from JD
            all_extracted = set(raw_missing + raw_matching)
            all_extracted = {k for k in all_extracted if k.lower().strip() not in GENERIC_FILLER_WORDS}

            # Deterministically verify every single keyword against candidate's master resume
            resume_full_text = _flatten_resume_text(base_resume)
            verified_matching = []
            verified_missing = []

            for kw in sorted(all_extracted):
                kw_lower = kw.lower().strip()
                pattern = r'\b' + re.escape(kw_lower) + r'\b'
                if re.search(pattern, resume_full_text) or kw_lower in resume_full_text:
                    verified_matching.append(kw)
                else:
                    verified_missing.append(kw)

            total = len(verified_matching) + len(verified_missing)
            calc_score = round((len(verified_matching) / total) * 100) if total > 0 else data.get("score", 70)

            print(f"[LLM Matcher] Deterministic Verification — Score: {calc_score}%, Matching ({len(verified_matching)}), Missing ({len(verified_missing)})")
            return {
                "score": calc_score,
                "matching_keywords": verified_matching,
                "missing_keywords": verified_missing,
                "total_keywords": total
            }

    except Exception as e:
        print(f"[LLM Matcher] Error calling Gemini: {e}")

    return {"score": 70, "matching_keywords": [], "missing_keywords": [], "total_keywords": 0}


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
