"""
resume_refiner.py — Interactive Resume Refinement Copilot Engine.
Allows candidates to give direct, freeform or preset instructions to adjust, add,
or remove anything in their newly tailored resume.
Fast (~2-3s), fully grounded in base_resume ground truth, enforces Human Voice rules,
and instantly outputs updated resume data + rebuilds the Word (.docx) & PDF documents.
"""

import json
import re
import sys
from typing import Tuple, Dict, Any
from google import genai
from google.genai import types
from gemini_client import execute_with_failover

# Fix Windows terminal encoding for Unicode output
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REFINEMENT_SYSTEM_PROMPT = """You are the ATS Agent Senior Resume Refiner & Career Copilot.
Your job is to apply explicit candidate revision requests to a newly tailored resume.

The candidate has reviewed the current tailored resume and said:
"I want the resume to be like this: should have this, not this, change this, etc."

You must execute their revision instructions with 100% precision across ANY requested part of the resume:
- Summary (length, tone, focus, specific tech, executive level)
- Skills list (add technologies, remove tools, reorganize, specialize)
- Experience bullets (rewrite specific bullets, add hard numbers/metrics, front-load impact, change focus)
- Bullet additions or deletions (if requested to cut or expand)
- Negative constraints (e.g., "do not mention AWS", "remove bullet 3", "no buzzwords")

STRICT GROUNDING & COMPLIANCE RULES:
1. TRUTH ANCHOR: All company names, job titles, employment dates, and educational degrees from the Base Resume MUST remain authentic. Never invent fake employers or fake academic degrees.
2. HUMAN VOICE RULES:
   - Front-load business impact and concrete metrics (e.g., "Reduced pipeline runtimes by 42% by...", NOT "Responsible for...").
   - Ban all corporate throat-clearing and AI cliches: "spearheaded", "orchestrated", "leveraged", "testament to", "synergy", "seamlessly", "passionate about", "delving into", "fostered".
   - Plain, strong engineering verbs: built, cut, owned, migrated, automated, tuned, deployed, designed.
3. ATS KEYWORD PRESERVATION: Keep previously injected ATS keywords unless the user explicitly requested their removal.
4. RETURN FORMAT: Return ONLY a valid JSON object with NO markdown formatting, backticks, or code fencing.
5. JSON SYNTAX: Ensure all arrays (e.g. skills, experience, bullets, education) are properly opened with [ and closed with ]. Never close an array with } or an object with ].

JSON Schema:
{
  "change_summary": "1-2 sentence human-readable summary of exactly what you revised",
  "refined_resume": {
    "name": "Candidate Name",
    "contact": { "email": "...", "phone": "...", "location": "...", "linkedin": "...", "github": "..." },
    "summary": "Updated professional summary",
    "skills": ["Skill 1", "Skill 2"],
    "experience": [
      {
        "company": "Company Name",
        "role": "Role Title",
        "dates": "Date Range",
        "bullets": ["Bullet 1", "Bullet 2"]
      }
    ],
    "education": [],
    "projects": [],
    "certifications": []
  }
}
"""

def _repair_and_load_json(raw_text: str) -> dict:
    """Safely parse and auto-repair common LLM JSON formatting quirks."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Fix common LLM mistake: closing array with '}' instead of ']'
    # e.g. "skills": [ ... \n    },\n    "experience":
    repaired = re.sub(
        r'([\"0-9a-zA-Z_\-\.\s])\s*\n\s*\}\s*,\s*\n\s*\"(experience|education|projects|certifications|skills)\"',
        r'\1\n    ],\n    "\2"',
        cleaned
    )
    try:
        return json.loads(repaired)
    except Exception:
        pass

    # Fix trailing commas before } or ]
    repaired2 = re.sub(r',\s*([\}\]])', r'\1', repaired)
    try:
        return json.loads(repaired2)
    except Exception:
        pass

    # Re-raise standard json.loads on cleaned to preserve traceback if unrecoverable
    return json.loads(cleaned)


def refine_tailored_resume(
    current_resume: dict,
    instruction: str,
    base_resume: dict,
    jd_text: str = "",
    company: str = "",
    role: str = "",
) -> Tuple[dict, str]:
    """
    Refine a tailored resume using user's explicit instructions.
    Returns (refined_resume_dict, change_summary_str).
    """
    if not instruction or not instruction.strip():
        return current_resume, "No revision instructions provided."

    user_prompt = f"""
CANDIDATE'S EXACT REVISION REQUEST:
"{instruction.strip()}"

TARGET JOB CONTEXT:
- Company: {company or 'Target Company'}
- Role: {role or 'Target Role'}
- Key JD Snippet: {jd_text[:1500] if jd_text else 'Not provided'}

CANDIDATE'S MASTER TRUTH (Base Resume):
{json.dumps(base_resume, indent=2)}

CURRENT TAILORED RESUME TO REVISE:
{json.dumps(current_resume, indent=2)}

INSTRUCTIONS:
1. Apply the candidate's exact feedback above.
2. Return the full refined_resume JSON object with the changes applied.
3. Provide a clear, punchy change_summary string describing what you changed.
"""

    def _call_gemini(client: genai.Client):
        models = ["gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
        last_err = None
        for m in models:
            try:
                response = client.models.generate_content(
                    model=m,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=REFINEMENT_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        temperature=0.2,
                        max_output_tokens=8192,
                    ),
                )
                if response and response.text:
                    return response.text
            except Exception as e:
                print(f"[ResumeRefiner] Model {m} note: {e}")
                last_err = e
                continue
        if last_err:
            raise last_err
        return ""

    raw_text = execute_with_failover(_call_gemini)

    try:
        data = _repair_and_load_json(raw_text)
        refined = data.get("refined_resume") or data
        change_summary = data.get("change_summary", "Applied candidate revisions and updated document.")

        # Ensure mandatory keys exist
        if "name" not in refined and "name" in current_resume:
            refined["name"] = current_resume["name"]
        if "contact" not in refined and "contact" in current_resume:
            refined["contact"] = current_resume["contact"]
        if "experience" not in refined and "experience" in current_resume:
            refined["experience"] = current_resume["experience"]

        return refined, change_summary

    except Exception as e:
        print(f"[ResumeRefiner] JSON parse error: {e}. Full raw response:\n{raw_text}\n--- END RAW ---")
        # Fallback return
        return current_resume, f"Refinement encountered parsing issue: {e}"
