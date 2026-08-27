"""
rewriter.py — Gemini resume rewriter with strict keyword injection.

GOAL: Inject EVERY missing keyword from Simplify into the resume naturally
so the ATS score hits 90%+. Uses a 3-pass retry loop with escalating
strictness if keywords remain missing after the first attempt.
"""

import json
import os
import re
import sys
import time
from typing import Optional
from google import genai
from google.genai import types
from gemini_client import get_gemini_client, is_quota_error, rotate_key, get_all_gemini_keys

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _get_gemini_client():
    """Initialize and return the Gemini client from key pool."""
    return get_gemini_client()


def _clean_json_response(text: str) -> str:
    """Strip markdown code fences from Gemini's JSON response."""
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"\s*```$", "", text.strip(), flags=re.MULTILINE)
    return text.strip()


def _validate_resume_structure(data: dict) -> bool:
    """Validate the rewritten resume has the required top-level keys."""
    required = {"summary", "skills", "experience"}
    return required.issubset(set(data.keys()))


def _build_resume_text(resume: dict) -> str:
    """Flatten the resume dict to plain text for keyword presence checking."""
    parts = []
    if isinstance(resume.get("summary"), str):
        parts.append(resume["summary"])
    if isinstance(resume.get("skills"), list):
        parts.extend(resume["skills"])
    for exp in resume.get("experience", []):
        if isinstance(exp.get("title"), str):
            parts.append(exp["title"])
        for b in exp.get("bullets", []):
            if isinstance(b, str):
                parts.append(b)
    for proj in resume.get("projects", []):
        if isinstance(proj.get("description"), str):
            parts.append(proj["description"])
        for t in proj.get("tech_stack", []):
            if isinstance(t, str):
                parts.append(t)
    return " ".join(parts).lower()


def verify_dynamic_keywords(rewritten_json_output: dict, simplify_keywords: list) -> tuple[list, list]:
    """
    Dynamically checks the newly generated resume text using strict word boundaries,
    ensuring it exactly matches how keyword_matcher and Simplify read it.
    """
    # Flatten the JSON values into a clean string pool
    content_pool = json.dumps(rewritten_json_output).lower()
    missing_gaps = []
    embedded = []
    
    for word in simplify_keywords:
        kw = word.lower().strip()
        
        # Handle special cases with symbols like C++, .JS, or Vue.js cleanly
        escaped_word = re.escape(kw)
        if kw.endswith('.js') or '+' in kw or '.' in kw:
            pattern = re.compile(r'(?:^|[^a-zA-Z0-9])' + escaped_word + r'(?:$|[^a-zA-Z0-9])')
        else:
            pattern = re.compile(r'\b' + escaped_word + r'\b')
            
        if pattern.search(content_pool):
            embedded.append(word)
        else:
            missing_gaps.append(word)
            
    if missing_gaps:
        print(f"[Rewriter] [FAIL] Guardrail Tripped! Missed keywords for this run: {missing_gaps}")
        return embedded, missing_gaps
        
    print("[Rewriter] [OK] 100% Dynamic Keyword Alignment Verified!")
    return embedded, []


def _check_keyword_coverage(resume: dict, keywords: list) -> tuple[list, list]:
    """Wrapper for verify_dynamic_keywords to maintain backwards compatibility."""
    return verify_dynamic_keywords(resume, keywords)


def _build_prompt(
    base_resume: dict,
    jd_text: str,
    missing_keywords: list,
    company: str,
    role: str,
    attempt: int,
    still_missing_from_last_attempt: Optional[list] = None,
) -> tuple[str, str]:
    """
    Build the system + user prompt for Gemini.
    Escalates strictness on retry attempts.
    """
    prompt_resume = {k: v for k, v in base_resume.items() if k != "_raw_text"}
    raw_text_context = ""
    if base_resume.get("_raw_text"):
        raw_text_context = (
            "\n\nORIGINAL RESUME TEXT (use as ground truth for experience/companies/dates):\n"
            f"{base_resume['_raw_text'][:6000]}"
        )

    # Build keyword block based on whether this is a retry
    if attempt == 1 or not still_missing_from_last_attempt:
        keyword_block = (
            "MISSING KEYWORDS — You MUST embed ALL of these in the output:\n"
            + json.dumps(missing_keywords, indent=2)
        )
        urgency = ""
    else:
        keyword_block = (
            f"[CRITICAL - ATTEMPT {attempt}] The previous rewrite FAILED to embed these keywords:\n"
            + json.dumps(still_missing_from_last_attempt, indent=2)
            + "\n\nYou MUST embed ALL of the above. Check every single one before returning."
        )
        urgency = "\n\nURGENCY LEVEL: MAXIMUM. Every keyword listed above MUST appear at least once."

    system_prompt = f"""You are a dynamic ATS Optimization Engine tailoring a candidate's resume for a brand-new job application.

DYNAMIC INPUT DATA:
- MASTER_PROFILE: {json.dumps(prompt_resume, indent=2, ensure_ascii=False)}
- MISSING_KEYWORDS_FROM_SIMPLIFY: {json.dumps(missing_keywords, indent=2)}

YOUR ARCHITECTURAL PROTOCOLS:

1. MANDATORY DUAL-LAYER KEYWORD INJECTION (Skills List + Experience Bullets):
Every missing keyword from MISSING_KEYWORDS_FROM_SIMPLIFY MUST be reflected in BOTH of the following places:
- A) In "skills": Include the exact technical skill, framework, cloud service, or database in the skills array.
- B) In "experience" BULLETS: Weave each new skill/tool into at least 1–2 bullet points in the candidate's recent experience. Explicitly state HOW the tool was applied, for what architecture or pipeline, and what business/technical result was achieved (e.g., "Designed scalable streaming ingestion using Apache Kafka and Databricks Delta Live Tables, ensuring 99.9% data delivery SLA.").
- Never just dump keywords into the skills section alone. Hiring managers and ATS parsers require contextual proof of practical usage in bullet points.

2. IDENTIFY & PURGE (Remove Previous Job Stuffing)
Start strictly from MASTER_PROFILE. If there are hyper-specific keywords from previous application runs that do NOT appear in the current missing keywords list or the master profile (e.g., niche competitor databases if this job doesn't use it), REMOVE or REPLACE them back to the clean master format. Do not carry over baggage from previous job scans.

3. RESUME TRUTH CONSTRAINT & BULLET INTEGRITY
You are allowed to rephrase or adjust terminology and weave in required tools naturally into candidate's experience. Maintain professional numbers, real company names, and dates. Ensure every bullet point starts with a strong action verb (e.g., "Architected", "Engineered", "Optimized", "Implemented", "Automated").

4. NO AI BUZZWORDS
Do NOT use obvious AI buzzwords like "spearheaded", "leveraged", "dynamic", "testament", "transformative", "fostered", "pivotal", "groundbreaking", "innovative", "robust", or "seamless". Use clear, active human engineering language.

5. OUTPUT SCHEMATIC
Return the updated resume strictly as a valid JSON object matching the exact keys of the MASTER_PROFILE so the python-docx script runs smoothly.{urgency}

JSON OUTPUT FORMAT (return exactly this structure):
{{
  "target_role": "A generic, professional version of the job title (e.g. 'Software Engineer' instead of 'Software Eng III - AI (L4)')",
  "summary": "2-4 sentence professional summary targeting {role} at {company}",
  "skills": ["skill1", "skill2", ...],
  "experience": [
    {{
      "title": "string",
      "company": "string", 
      "dates": "string",
      "location": "string",
      "bullets": ["bullet1", "bullet2", ...]
    }}
  ],
  "projects": [
    {{
      "name": "string",
      "tech_stack": ["string"],
      "description": "string",
      "url": "string"
    }}
  ]
}}"""

    user_prompt = f"""TARGET: {role} at {company}

{keyword_block}

JOB DESCRIPTION:
{jd_text[:4000]}

BASE RESUME:
{json.dumps(prompt_resume, indent=2, ensure_ascii=False)[:4000]}
{raw_text_context}

IMPORTANT: Before returning, verify every single missing keyword appears in your output.
Return ONLY valid JSON now."""

    return system_prompt, user_prompt


def rewrite_resume(
    base_resume: dict,
    jd_text: str,
    missing_keywords: list,
    company: str,
    role: str,
    max_retries: int = 3,
) -> dict:
    """
    Rewrite the resume to inject ALL missing keywords using Gemini.

    Runs up to max_retries attempts with escalating strictness:
    - Attempt 1: inject all missing keywords
    - Attempt 2: strict retry targeting only still-missing keywords
    - Attempt 3: maximum urgency, manual injection fallback

    Returns:
        Merged resume dict with rewritten content + original metadata.
    """
    client = _get_gemini_client()

    if not missing_keywords:
        print("[Rewriter] No missing keywords — returning base resume unchanged")
        return base_resume

    models = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash"]
    still_missing = None
    last_valid_resume = None

    for attempt in range(1, max_retries + 1):
        model = models[(attempt - 1) % len(models)]
        system_prompt, user_prompt = _build_prompt(
            base_resume=base_resume,
            jd_text=jd_text,
            missing_keywords=missing_keywords,
            company=company,
            role=role,
            attempt=attempt,
            still_missing_from_last_attempt=still_missing,
        )

        print(f"[Rewriter] Attempt {attempt}/{max_retries} with {model}...")
        print(f"[Rewriter] Target: {len(missing_keywords)} keywords to inject")

        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part(text=system_prompt + "\n\n" + user_prompt)],
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.35 if attempt == 1 else 0.25,
                    top_p=0.9,
                    max_output_tokens=8192,
                ),
            )

            raw_text = response.text
            cleaned = _clean_json_response(raw_text)
            data = json.loads(cleaned)

            if not _validate_resume_structure(data):
                raise ValueError(f"Missing required keys. Got: {list(data.keys())}")

            # Merge with original resume (preserve contact, education, certifications, etc.)
            merged = dict(base_resume)
            merged.update(data)
            for k in ("education", "certifications", "contact", "name", "projects"):
                if k in base_resume and (k not in merged or not merged[k]):
                    merged[k] = base_resume[k]
            merged.pop("_raw_text", None)

            # Verify keyword coverage
            embedded, still_missing = _check_keyword_coverage(merged, missing_keywords)
            coverage_pct = round(len(embedded) / len(missing_keywords) * 100) if missing_keywords else 100

            print(f"[Rewriter] Coverage: {len(embedded)}/{len(missing_keywords)} keywords embedded ({coverage_pct}%)")

            if still_missing:
                print(f"[Rewriter] Still missing ({len(still_missing)}): {still_missing[:8]}"
                      + (f"... +{len(still_missing)-8} more" if len(still_missing) > 8 else ""))
            else:
                print(f"[Rewriter] [OK] All {len(missing_keywords)} keywords successfully embedded!")

            last_valid_resume = merged

            # If we hit 90%+ coverage or all keywords embedded, we're done
            if coverage_pct >= 90 or not still_missing:
                return merged

            # If coverage is < 90%, retry
            if attempt < max_retries:
                print(f"[Rewriter] Coverage {coverage_pct}% < 90%. Retrying with stricter prompt...")
                time.sleep(1)
                continue

        except json.JSONDecodeError as e:
            print(f"[Rewriter] Attempt {attempt}/{max_retries} — JSON error: {e}")
            if attempt < max_retries:
                time.sleep(2)
            continue

        except Exception as e:
            err_str = str(e)
            print(f"[Rewriter] Attempt {attempt}/{max_retries} — Error: {err_str}")
            if is_quota_error(e):
                keys = get_all_gemini_keys()
                if len(keys) > 1:
                    rotate_key(reason="Rewriter Quota Limit")
                    client = _get_gemini_client()
                    time.sleep(1)
                else:
                    print("[Rewriter] Rate limit hit on single key — waiting 10s before retry...")
                    time.sleep(10)
            elif attempt < max_retries:
                time.sleep(2)
            continue

    # All retries exhausted — do a final manual injection pass
    if last_valid_resume and still_missing:
        print(f"[Rewriter] Max retries reached. Manually injecting {len(still_missing)} remaining keywords...")
        last_valid_resume = _manual_keyword_injection(last_valid_resume, still_missing)

    if last_valid_resume:
        # Final coverage check
        embedded, final_missing = _check_keyword_coverage(last_valid_resume, missing_keywords)
        coverage_pct = round(len(embedded) / len(missing_keywords) * 100) if missing_keywords else 100
        print(f"[Rewriter] Final coverage: {coverage_pct}% ({len(embedded)}/{len(missing_keywords)} keywords)")
        return last_valid_resume

    raise RuntimeError(
        f"Gemini rewriter failed after {max_retries} attempts. "
        "Check your GEMINI_API_KEY and try again."
    )


def _manual_keyword_injection(resume: dict, still_missing: list) -> dict:
    """
    Force-injects remaining short items directly into skills array matching
    the structural requirements of your base resume profile.
    Long phrases (> 3 words) are ignored to prevent bizarre skills.
    """
    if "skills" not in resume or not isinstance(resume["skills"], list):
        resume["skills"] = []
        
    for kw in still_missing:
        # Ignore long sentences/phrases that Simplify extracted but the LLM couldn't weave in
        if len(kw.split()) > 3:
            print(f"[Rewriter] Skipping manual injection for long phrase: '{kw}'")
            continue
            
        if kw not in resume["skills"]:
            resume["skills"].append(kw)
            
    return resume


if __name__ == "__main__":
    """Quick test of the rewriter."""
    import sys

    resume_path = os.path.join(os.path.dirname(__file__), "base_resume.json")
    if not os.path.exists(resume_path):
        print("ERROR: base_resume.json not found. Run pdf_to_resume.py first.")
        sys.exit(1)

    with open(resume_path, "r", encoding="utf-8") as f:
        base_resume = json.load(f)

    test_jd = """
    Senior Full Stack Engineer — React, TypeScript, GraphQL, Node.js, PostgreSQL, 
    Redis, AWS, Docker, Kubernetes, CI/CD, REST APIs, Agile, Microservices.
    """
    test_missing = ["GraphQL", "Kubernetes", "Redis", "CI/CD", "Microservices"]

    result = rewrite_resume(base_resume, test_jd, test_missing, "TestCo", "Senior Engineer")
    print("\n--- SUMMARY ---")
    print(result.get("summary"))
    print("\n--- SKILLS ---")
    print(result.get("skills"))
