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

REFINEMENT_SYSTEM_PROMPT = """You are the ATS Agent Senior Resume Precision-Refiner & Career Copilot.
Your ONE job: execute the candidate's revision instructions with SURGICAL, LINE-BY-LINE EXACTNESS.

═══════════════════════════════════════════════════════════════
⚠️  COMMAND-EXECUTION MODE — USER INSTRUCTIONS ARE LAW ⚠️
═══════════════════════════════════════════════════════════════
The candidate's revision request is a LIST OF COMMANDS, not suggestions.
You must parse EVERY sentence, EVERY comma-separated item, EVERY bullet in their request
as an independent, non-negotiable directive. Nothing is optional. Nothing is skipped.

If the user says:
  - "Replace ALL skills with: Python, SQL, Tableau" → output EXACTLY those skills, nothing more
  - "Change skill X to Y" → make that exact swap
  - "Add Z to skills" → add Z verbatim
  - "Rewrite bullet 2 of Company A to focus on cost savings" → rewrite THAT SPECIFIC bullet only
  - "Remove 'leveraged' from all bullets" → scan every bullet and remove it
  - "Add the following responsibilities to my experience: [...]" → weave EVERY listed item into relevant experience bullets
  - "Change summary to focus on [topic]" → do EXACTLY that, word for word per their description

Do NOT:
  ❌ Skip any instruction because it seems minor
  ❌ Partially apply a list (if user gives 20 keywords, ALL 20 must appear)
  ❌ Add skills the user didn't ask for
  ❌ Remove skills the user didn't ask to remove (unless they said "replace all")
  ❌ Preserve old skills if user explicitly said to replace/overwrite/clear the skills section
  ❌ Hallucinate new employers, dates, or degrees
  ❌ Use banned clichés: "spearheaded", "orchestrated", "leveraged", "synergy", "seamlessly",
     "passionate about", "delving into", "fostered", "testament to"

SKILLS OVERWRITE RULE:
  - If user says "replace skills with X,Y,Z" or "my skills should be: ..." or "only these skills: ...",
    output EXACTLY those skills and ONLY those skills in the skills array.
  - If user says "add X to skills", add X to existing list.
  - If user says "remove X from skills", remove only X.
  - Default: preserve existing skills + apply requested additions/removals.

JD RESPONSIBILITIES WEAVING RULE:
  - If user provides responsibilities from a job description to add to experience:
    EVERY responsibility must be represented in a bullet point (may be combined/adapted but not omitted).
  - Integrate naturally as first-person, impact-led bullets with strong action verbs.

SECTION TAG & @MENTION TARGETING RULE (CRITICAL):
  When the instruction contains lines or directives starting with an @mention, an @(...) tag (e.g. @(summary), @(skills), @(experience), @(title), @(all bullets)),
  or a section tag in square brackets [TAG], parse each directive independently and apply it ONLY to the targeted section:
  
  Format Examples:
    @(summary) (or @summary or [SUMMARY]) ...                         → update ONLY the "summary" field
    @(skills) (or @skills or [SKILLS]) ...                           → update ONLY the "skills" array
    @(experience) (or @experience or [EXPERIENCE]) ...               → update experience roles and bullet points
    @(experience/Acme Corp) (or [EXPERIENCE/Acme Corp])               → update ONLY the experience entry where company ≈ "Acme Corp"
    @(education) (or [EDUCATION]) ...                                 → update ONLY the "education" section
    @(projects) (or [PROJECTS]) ...                                   → update ONLY the "projects" section
    @(certifications) (or [CERTIFICATIONS]) ...                       → update ONLY the "certifications" section
    @(title) (or @title or [TITLE]) ...                               → update ONLY the "target_role" headline
    @(all), @(all bullets), or @all (or [ALL BULLETS])               → apply changes globally / across all sections
  
  Rules:
  - If a directive has an @(...), @mention, or [TAG], that instruction applies EXCLUSIVELY to that targeted section.
  - All non-targeted sections MUST remain EXACTLY unchanged (preserved verbatim from current resume).
  - Multiple tags can appear in a single instruction (e.g. "@(skills) add Python\n@(summary) make executive\n@(all) active voice").
    Apply EACH directive to its respective section without dropping other sections!
  - @all / @(all) applies globally across the entire resume.
  - If a tag references a company name (e.g. @(experience/Strive Health)), match it case-insensitively
    against the "company" field of each experience entry.

HUMAN VOICE:
  Front-load business impact and metrics. Plain, strong verbs: built, cut, owned, migrated,
  automated, tuned, deployed, designed, shipped, reduced, scaled.

TRUTH ANCHOR:
  Company names, job titles, employment dates, and educational degrees from Base Resume
  MUST remain authentic. Never invent fake employers or degrees.

RETURN: ONLY a valid JSON object. NO markdown, NO backticks, NO code fencing.
JSON SYNTAX: Arrays opened with [ and closed with ]. Objects opened with { and closed with }.

JSON Schema:
{
  "change_summary": "Precise 1-3 sentence summary listing EVERY change you made",
  "skills_mode": "overwrite | additive",
  "refined_resume": {
    "name": "Candidate Name",
    "target_role": "Target role headline under candidate name",
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

    # Detect if this instruction implies a skills overwrite (user wants ONLY their listed skills)
    _inst_lower = instruction.lower()
    _skills_overwrite = any(phrase in _inst_lower for phrase in [
        "replace all skills", "replace my skills", "replace skills with",
        "my skills should be", "only these skills", "skills should only be",
        "replace the skills", "change the skills to", "change skills to",
        "set skills to", "skills are:", "skills list should be", "new skills:",
        "overwrite skills", "replace skill section",
        # Section-tag, @mention, and @(...) variants
        "[skills] replace", "[skills] set", "[skills] overwrite", "[skills] change to",
        "[skills] only", "[skills] use only", "[skills] use these",
        "@skills replace", "@skills set", "@skills overwrite", "@skills change to",
        "@skills only", "@skills use only", "@skills use these",
        "@(skills) replace", "@(skills) set", "@(skills) overwrite", "@(skills) change to",
        "@(skills) only", "@(skills) use only", "@(skills) use these",
    ])

    # Check whether any section tags, @mentions, or @(...) tags are used (for checklist reminder)
    _has_section_tags = bool(re.search(
        r'(\[(?:SUMMARY|SKILLS|TITLE|ALL BULLETS|EXPERIENCE\/[^\]]+)\]|@\(?(?:summary|skills|experience|education|projects|certifications|all|all bullets|everything|general|title|bullets)[^\s\)]*\)?|@(summary|skills|experience|education|projects|certifications|all|everything|general|title)\b)',
        instruction,
        re.IGNORECASE
    ))

    # Parse instruction into numbered items so the model sees them clearly
    _instr_lines = [l.strip() for l in re.split(r'[;\n]+', instruction.strip()) if l.strip()]
    if len(_instr_lines) > 1:
        _instr_formatted = "\n".join(f"{i+1}. {line}" for i, line in enumerate(_instr_lines))
    else:
        _instr_formatted = instruction.strip()

    user_prompt = f"""
═══════════════════════════════════════════════════════════════
CANDIDATE'S EXACT REVISION REQUEST ({len(_instr_lines)} directive(s)):
═══════════════════════════════════════════════════════════════
{_instr_formatted}

⚠️  APPLY EVERY DIRECTIVE ABOVE — nothing is optional or skippable.
⚠️  SKILLS MODE: {"OVERWRITE — output ONLY the skills the user specified" if _skills_overwrite else "ADDITIVE — add/remove specific skills as requested, preserve existing"}
{"⚠️  SECTION TARGETING (@(...) tags, @mentions, or [TAGS]) DETECTED — parse each @(...) or [TAG] prefix and apply that directive ONLY to the targeted section. Leave ALL other sections exactly as in current resume." if _has_section_tags else ""}

TARGET JOB CONTEXT:
- Company: {company or 'Target Company'}
- Role: {role or 'Target Role'}
- Job Description (for context when weaving responsibilities):
{jd_text[:4000] if jd_text else 'Not provided'}

CANDIDATE'S MASTER TRUTH (Base Resume — for grounding only, do NOT revert changes):
{json.dumps(base_resume, indent=2)}

CURRENT TAILORED RESUME TO REVISE:
{json.dumps(current_resume, indent=2)}

CHECKLIST BEFORE RETURNING:
☑ Every numbered directive above is addressed
☑ If skills overwrite was requested: output ONLY the requested skills
☑ If JD responsibilities were listed: EVERY one appears in experience bullets
{"☑ Section targeting used — each @section / [TAG] directive applied ONLY to its target section; ALL non-targeted sections preserved verbatim" if _has_section_tags else ""}
☑ No banned clichés used
☑ change_summary lists every discrete change made
☑ skills_mode is set to "overwrite" or "additive"

Return ONLY valid JSON now.
"""

    def _call_gemini(client: genai.Client):
        from gemini_client import get_candidate_models, extract_clean_text, get_standard_genai_config, record_model_failure, record_model_success
        models = get_candidate_models()
        last_err = None
        for m in models:
            try:
                cfg = get_standard_genai_config(model_name=m, max_output_tokens=8192, temperature=0.2)
                cfg.system_instruction = REFINEMENT_SYSTEM_PROMPT
                if "gemma" not in m:
                    cfg.response_mime_type = "application/json"
                response = client.models.generate_content(
                    model=m,
                    contents=user_prompt,
                    config=cfg,
                )
                clean_text = extract_clean_text(response)
                if clean_text:
                    record_model_success(m)
                    return clean_text
            except Exception as e:
                record_model_failure(m, e)
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

        # ── SKILLS MERGE / OVERWRITE — respects user instruction ──
        # If user asked to replace/overwrite skills, honour that (don't add old skills back).
        # If additive, merge refined skills with base skills so nothing is silently lost.
        ai_skills_mode = data.get("skills_mode", "additive").lower().strip()
        # Also detect from instruction text as a fallback
        _il = (instruction or "").lower()
        _user_wants_overwrite = ai_skills_mode == "overwrite" or any(phrase in _il for phrase in [
            "replace all skills", "replace my skills", "replace skills with",
            "my skills should be", "only these skills", "skills should only be",
            "replace the skills", "change the skills to", "change skills to",
            "set skills to", "new skills:", "overwrite skills", "replace skill section",
        ])

        ref_skills = refined.get("skills", []) or []
        from rewriter import sanitize_keywords_list
        ref_skills_clean = sanitize_keywords_list(ref_skills)

        if _user_wants_overwrite:
            # USER SAID REPLACE — trust AI output exactly; do NOT add base skills back
            refined["skills"] = ref_skills_clean
        else:
            # ADDITIVE MODE — merge: base first, then any new skills the AI added
            base_skills = [str(s).strip() for s in base_resume.get("skills", []) if s and str(s).strip()]
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
