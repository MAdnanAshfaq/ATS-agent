"""
danis_engine.py — Advanced Multi-Agent Resume & Cover Letter Tailoring Engine.
Directly implements the 4-role native team workflow and Rules 0–16 from ResumeHQ (jananthan30/Resume-Builder).

Roles:
1. Researcher: Extracts atomic hard requirements, soft requirements, and target competencies from the JD.
2. Writer: Rewrites resume using strict Rules 0-16 (front-loaded value, plain verbs, burstiness, zero deadwood).
3. Auditor: Independent gatekeeper running Claim Provenance Audit and Human Voice Audit (exit 0 gate).
4. Editor: Corrects any explicit auditor findings if audit fails.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable, Optional

from google import genai
from google.genai import types

from gemini_client import get_gemini_client, is_quota_error
from human_voice_audit import audit_resume_dict, load_ai_tells


def _clean_json(text: str) -> str:
    """Strip markdown code fences and extraneous text from LLM responses."""
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text.strip(), flags=re.MULTILINE)
    match = re.search(r'(\{[\s\S]*\})', text)
    if match:
        return match.group(1).strip()
    return text.strip()


def run_researcher_phase(
    jd_text: str,
    company: str,
    role: str,
    client: genai.Client,
) -> dict[str, Any]:
    """
    Role 1: Researcher.
    Converts raw JD into an ordered, evidence-anchored requirement rubric.
    """
    system_prompt = """You are the specialized Researcher in the multi-agent resume optimization team.
Your task is to analyze the provided Job Description and convert it into an ordered, atomic requirement rubric.

Distinguish between:
1. "hard_requirements": Mandatory tools, years of experience, core cloud/database tech, critical degrees/certifications.
2. "soft_requirements": Leadership, cross-functional collaboration, agile practices, domain knowledge.
3. "key_buzzwords_and_acronyms": Technical acronyms and tool names that ATS parsers look for.

Return strictly a JSON object:
{
  "role_title": "string",
  "company_name": "string",
  "hard_requirements": ["req1", "req2", ...],
  "soft_requirements": ["req1", "req2", ...],
  "key_buzzwords_and_acronyms": ["skill1", "skill2", ...]
}"""

    user_prompt = f"""TARGET ROLE: {role} at {company}

JOB DESCRIPTION:
{jd_text[:4000]}

Extract the atomic rubric now as valid JSON."""

    models = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash"]
    for model_name in models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[types.Content(role="user", parts=[types.Part(text=system_prompt + "\n\n" + user_prompt)])],
                config=types.GenerateContentConfig(temperature=0.2, top_p=0.85, max_output_tokens=4096),
            )
            data = json.loads(_clean_json(response.text))
            return data
        except Exception as e:
            print(f"[Dani's Engine - Researcher] {model_name} note: {e}")
            time.sleep(1)

    return {
        "role_title": role,
        "company_name": company,
        "hard_requirements": [],
        "soft_requirements": [],
        "key_buzzwords_and_acronyms": []
    }


def run_writer_phase(
    base_resume: dict,
    research_rubric: dict,
    missing_keywords: list[str],
    company: str,
    role: str,
    custom_bullets: str,
    client: genai.Client,
    model_name: str = "gemini-2.5-flash",
) -> dict[str, Any]:
    """
    Role 2: Writer.
    Applies Rules 0–16 (Human Voice, So What test, Front-load value, Plain strong verbs).
    """
    ai_tells = load_ai_tells()
    cliche_list = ", ".join(ai_tells.get("cliche_openers", [])[:15])
    banned_list = ", ".join(ai_tells.get("banned_words", [])[:15])

    custom_section = ""
    if custom_bullets and custom_bullets.strip():
        custom_section = f"""
===================================================================
USER-SPECIFIED EXPERIENCE POINTS (MANDATORY TO INJECT INTO BULLETS):
===================================================================
The user explicitly wants these accomplishments/responsibilities added into their recent experience:
{custom_bullets.strip()}
Weave these points into the candidate's recent work experience bullets, writing them in active engineering voice.
"""

    system_prompt = f"""You are the Writer in Dani's Multi-Agent Resume Team.
Your job is to tailor the candidate's resume with strict adherence to human voice, authenticity, and high HR impact.

EDITORIAL PRIORITY ORDER (NEVER INVERT):
1. AUTHENTICITY / TRUTH: Never invent fake metrics, fake companies, or fake degrees.
2. HUMAN VOICE (RULES 0–5): Brevity, rhythmic sentence variation (jazz, not metronome), plain language.
3. HR IMPACT: Real quantified numbers, front-loaded impact (first 3 words carry weight).
4. ATS MATCH: Weave required skills into both technical skills list and work experience bullets.

WRITING ENHANCEMENT RULES (Rules 0–16 from ResumeHQ):
- Rule 0 (Human Voice Gate): Would a sharp engineer say this out loud in an interview without cringing?
- Rule 1 (The "So What?" Test): Every bullet answers why it matters. Action + measurable result.
- Rule 2 (Front-Load Value): First 3 words carry the punch (e.g. "Cut data errors 40% by...", "Built 15+ data marts using...").
- Rule 3 (Eliminate Deadwood): Never use "Responsible for", "Successfully", "Duties included", "Played a key role in", "Utilized", "Leveraged".
- Rule 4 (Metrics Mandate): >= 50% of bullets need real numbers (scale, speed, money, percentage, frequency).
- Rule 5 (Plain Strong Verbs):
  * GOOD OPENERS: Led, Built, Wrote, Cut, Fixed, Ran, Reviewed, Hired, Closed, Designed, Analyzed, Created, Shipped, Reduced, Increased, Trained, Audited, Implemented, Developed, Established, Improved, Resolved, Validated.
  * BANNED CLICHÉ OPENERS (Strictly Prohibited): {cliche_list}.
  * BANNED AI WORDS (Strictly Prohibited): {banned_list}.
- Rule 6 (Summary Constraints): Max 3 sentences, max 70 words. No "Results-driven" or "Passionate professional" openers.

ALL CANONICAL EXPERIENCES MUST BE PRESERVED:
If the master profile has 2 or more jobs, your output MUST contain all of them.
MANDATORY COMPANY NAMES: The ONLY allowed company names in the "experience" array are: {[e.get('company') for e in base_resume.get('experience', [])]}. NEVER replace, invent, or substitute company names (e.g. NEVER output Apex Systems or any other third-party company name). Preserve the exact company names and dates!

SKILLS CONSTRAINTS:
The "skills" array must ONLY contain concise technical tools (< 4 words each, e.g. "Python", "ANSI SQL", "PL/SQL", "Databricks", "Star Schema"). NEVER put full sentences into skills!

JSON OUTPUT FORMAT:
{{
  "target_role": "{role}",
  "summary": "2-3 crisp sentences.",
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
  "projects": []
}}"""

    user_prompt = f"""TARGET: {role} at {company}

RESEARCHER RUBRIC:
Hard Requirements: {json.dumps(research_rubric.get("hard_requirements", []))}
Keywords & Tech: {json.dumps(missing_keywords)}

{custom_section}

MASTER RESUME:
{json.dumps(base_resume, indent=2, ensure_ascii=False)[:5000]}

Draft the optimized resume now as valid JSON."""

    models = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash"]
    last_err = None
    for model_name in models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[types.Content(role="user", parts=[types.Part(text=system_prompt + "\n\n" + user_prompt)])],
                config=types.GenerateContentConfig(temperature=0.3, top_p=0.88, max_output_tokens=8192),
            )
            return json.loads(_clean_json(response.text))
        except Exception as e:
            last_err = e
            print(f"[Dani's Engine - Writer] {model_name} note: {e}")
            time.sleep(1)

    raise RuntimeError(f"Writer failed across all models: {last_err}")


def run_editor_phase(
    draft_resume: dict,
    audit_findings: list[str],
    client: genai.Client,
) -> dict[str, Any]:
    """
    Role 4: Editor.
    Fixes only explicit audit findings (replaces cliché openers, shortens summary, eliminates banned words).
    """
    system_prompt = """You are the Editor in Dani's Multi-Agent Resume Team.
The Auditor has flagged specific human-voice / AI-tell findings in the draft resume.
Your task is to fix ONLY the flagged lines while preserving all facts, numbers, tools, and experiences.

Replace any cliché opener with a plain strong action verb (Built, Designed, Cut, Led, Shipped, Automated, Improved).
Replace any banned AI words with plain equivalents.
Shorten overlong sentences to under 24 words.

Return the fully corrected resume as valid JSON."""

    user_prompt = f"""AUDITOR FINDINGS TO FIX:
{json.dumps(audit_findings, indent=2)}

DRAFT RESUME TO EDIT:
{json.dumps(draft_resume, indent=2, ensure_ascii=False)}

Return the corrected JSON now."""

    models = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash"]
    for model_name in models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[types.Content(role="user", parts=[types.Part(text=system_prompt + "\n\n" + user_prompt)])],
                config=types.GenerateContentConfig(temperature=0.2, top_p=0.85, max_output_tokens=8192),
            )
            return json.loads(_clean_json(response.text))
        except Exception as e:
            print(f"[Dani's Engine - Editor] {model_name} note: {e}")
            time.sleep(1)

    return draft_resume


def execute_danis_engine_pipeline(
    base_resume: dict,
    jd_text: str,
    missing_keywords: list[str],
    company: str,
    role: str,
    custom_bullets: str = "",
    log_callback: Optional[Callable[[int, str, str, Optional[dict], str], None]] = None,
) -> dict[str, Any]:
    """
    Main Orchestrator for Dani's Multi-Agent Engine.
    Executes:
    1. Researcher (JD Rubric Extraction)
    2. Writer (Rules 0-16 Grounded Drafting)
    3. Auditor (Human Voice & Provenance Verification)
    4. Editor (Targeted Fixes if Audit flags issues)
    5. Post-Processing & Multi-Role Guarantee
    """
    def log(step: int, title: str, desc: str, data: dict = None, status: str = "working"):
        if log_callback:
            log_callback(step, title, desc, data, status)
        print(f"[Dani's Engine] [{status.upper()}] Step {step}: {title} — {desc}")

    client = get_gemini_client()

    # Step 1: Researcher Phase
    log(4, "Dani's Researcher", "Extracting atomic hard & soft requirements from JD...", status="working")
    research_rubric = run_researcher_phase(jd_text, company, role, client)
    log(4, "Dani's Researcher", f"Extracted {len(research_rubric.get('hard_requirements', []))} hard requirements.", status="success")

    # Step 2: Writer Phase (Rules 0-16)
    log(4, "Dani's Writer", "Drafting resume with Rules 0–16 (burstiness, front-loaded value, plain verbs)...", status="working")
    draft = run_writer_phase(
        base_resume=base_resume,
        research_rubric=research_rubric,
        missing_keywords=missing_keywords,
        company=company,
        role=role,
        custom_bullets=custom_bullets,
        client=client,
    )
    log(4, "Dani's Writer", "Draft created with strict human-voice protocols.", status="success")

    # Step 3: Auditor Phase
    log(5, "Dani's Auditor", "Running Human Voice Audit (burstiness CV, AI tells, sentence caps)...", status="working")
    audit_report = audit_resume_dict(draft)
    log(5, "Dani's Auditor",
        f"Audit Score: {audit_report['score']}% (Burstiness CV: {audit_report['burstiness_cv']})",
        data=audit_report,
        status="success" if audit_report["passed"] else "warning")

    # Step 4: Editor Phase (if findings exist)
    if not audit_report["passed"] and audit_report["findings"]:
        log(5, "Dani's Editor", f"Correcting {len(audit_report['findings'])} auditor findings...", status="working")
        draft = run_editor_phase(draft, audit_report["findings"], client)
        re_audit = audit_resume_dict(draft)
        log(5, "Dani's Editor", f"Corrected draft re-audited. Score: {re_audit['score']}%", data=re_audit, status="success")

    # Step 5: Post-Processing & Multi-Role Guarantee
    merged = dict(base_resume)
    merged.update(draft)
    for k in ("education", "certifications", "contact", "name", "projects"):
        if k in base_resume and (k not in merged or not merged[k]):
            merged[k] = base_resume[k]

    # Guarantee strict canonical company mapping from base_resume (prevent hallucinated companies like Apex Systems)
    base_exp = base_resume.get("experience", [])
    raw_rewritten_exp = merged.get("experience", [])
    final_exp = []

    canonical_companies = [e.get("company", "").strip() for e in base_exp if isinstance(e, dict)]
    canonical_lower = [c.lower() for c in canonical_companies]

    # Map rewritten experiences to canonical base experiences
    for idx, orig_e in enumerate(base_exp):
        orig_comp = orig_e.get("company", "").strip()
        orig_comp_lower = orig_comp.lower()

        # Find matching rewritten entry
        matched_rewrite = None
        for rew in raw_rewritten_exp:
            if not isinstance(rew, dict):
                continue
            rew_comp = rew.get("company", "").strip().lower()
            if rew_comp == orig_comp_lower or (orig_comp_lower in rew_comp) or (rew_comp in orig_comp_lower):
                matched_rewrite = rew
                break

        if matched_rewrite:
            # Use rewritten entry but FORCE canonical company, title, dates from base_resume
            entry = dict(matched_rewrite)
            entry["company"] = orig_e.get("company", entry.get("company"))
            entry["title"] = orig_e.get("title", entry.get("title"))
            entry["dates"] = orig_e.get("dates", entry.get("dates"))
            entry["location"] = orig_e.get("location", entry.get("location"))
            final_exp.append(entry)
        else:
            # If LLM omitted or renamed, check if LLM produced an entry at the same index
            if idx < len(raw_rewritten_exp) and isinstance(raw_rewritten_exp[idx], dict):
                entry = dict(raw_rewritten_exp[idx])
                entry["company"] = orig_e.get("company")
                entry["title"] = orig_e.get("title")
                entry["dates"] = orig_e.get("dates")
                entry["location"] = orig_e.get("location")
                final_exp.append(entry)
            else:
                final_exp.append(orig_e)

    merged["experience"] = final_exp

    # Clean skills array: remove full sentences or duties
    cleaned_skills = []
    for s in merged.get("skills", []):
        s_str = str(s).strip()
        words = s_str.split()
        if len(words) <= 4 and not s_str.endswith(".") and len(s_str) < 35:
            if s_str not in cleaned_skills:
                cleaned_skills.append(s_str)
    merged["skills"] = cleaned_skills

    return merged
