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
- Target role / title under candidate name (e.g., "Senior Data Engineer", remove unwanted leveling tags, codes like "Con II", or change headline)
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
    "target_role": "Target role or headline subtitle under candidate name (e.g. Senior Data Engineer)",
    "contact": { "email": "...", "phone": "...", "location": "...", "linkedin": "...", "github": "..." },
    "summary": "Updated professional summary",
    "skills": ["Skill 1", "Skill 2"],
    "experience": [
      {
        "company": "Company Name",
        "title": "Role Title",
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
        models = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash"]
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
        if "target_role" not in refined and "target_role" in current_resume:
            refined["target_role"] = current_resume["target_role"]
        if "contact" not in refined and "contact" in current_resume:
            refined["contact"] = current_resume["contact"]
        if "experience" not in refined and "experience" in current_resume:
            refined["experience"] = current_resume["experience"]

        # Deterministic handler for target_role adjustments (e.g. user asks to remove "Con Ii" from title under name)
        inst_lower = (instruction or "").lower()
        if any(kw in inst_lower for kw in ("title under", "under name", "subtitle", "target_role", "target role", "headline", "con ii", "con 2", "con i")):
            curr_target = refined.get("target_role") or current_resume.get("target_role") or role or ""
            if "con ii" in inst_lower or "con 2" in inst_lower:
                curr_target = re.sub(r'[\s\-–—|/,]*\bcon\s*(?:ii|2)\b', '', curr_target, flags=re.I).strip(' -–—|/,:;')
                refined["target_role"] = curr_target
            elif "con i" in inst_lower or "con 1" in inst_lower:
                curr_target = re.sub(r'[\s\-–—|/,]*\bcon\s*(?:i|1)\b', '', curr_target, flags=re.I).strip(' -–—|/,:;')
                refined["target_role"] = curr_target
            elif "remove the title" in inst_lower or "delete the title" in inst_lower or "no title under" in inst_lower:
                refined["target_role"] = ""
            elif refined.get("target_role"):
                # Also strip any leftover leveling tags
                refined["target_role"] = re.sub(r'[\s\-–—|/,]*\b(?:con|cons|consultant|tier|grade|band|ic)\s*(?:i{1,3}|iv|v|\d+)\b.*$', '', refined["target_role"], flags=re.I).strip(' -–—|/,:;')

        # Normalize experience entries (ensure title exists and multi-role is preserved)
        ref_exp = refined.get("experience", [])
        for exp_e in ref_exp:
            if isinstance(exp_e, dict) and not exp_e.get("title") and exp_e.get("role"):
                exp_e["title"] = exp_e["role"]

        # Preserve any past jobs from base_resume that LLM might have omitted
        base_exp = base_resume.get("experience", [])
        existing_companies = {e.get("company", "").lower().strip() for e in ref_exp if isinstance(e, dict)}
        for orig_e in base_exp:
            orig_comp = orig_e.get("company", "").lower().strip()
            if orig_comp not in existing_companies:
                ref_exp.append(orig_e)
        refined["experience"] = ref_exp

        # ── MASTER SKILLS ZERO-LOSS GUARANTEE ──
        # Preserve all original skills from base_resume; never drop master skills
        base_skills = [str(s).strip() for s in base_resume.get("skills", []) if s and str(s).strip()]
        ref_skills = refined.get("skills", []) or []
        ref_skills_clean = [str(s).strip() for s in ref_skills if s and str(s).strip() and len(str(s).split()) <= 4]

        combined_skills = list(base_skills)
        combined_lower = {s.lower() for s in combined_skills}
        for s in ref_skills_clean:
            if s.lower() not in combined_lower:
                combined_skills.append(s)
                combined_lower.add(s.lower())
        refined["skills"] = combined_skills

        return refined, change_summary

    except Exception as e:
        print(f"[ResumeRefiner] JSON parse error: {e}. Full raw response:\n{raw_text}\n--- END RAW ---")
        # Fallback return
        return current_resume, f"Refinement encountered parsing issue: {e}"
