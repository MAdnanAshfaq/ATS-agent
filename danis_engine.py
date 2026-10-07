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

from gemini_client import (
    get_gemini_client, is_quota_error, rotate_key, get_all_gemini_keys,
    get_standard_genai_config, get_candidate_models, record_model_failure, record_model_success
)
from human_voice_audit import audit_resume_dict, load_ai_tells


def _clean_json(text: str) -> str:
    """Strip markdown code fences and extraneous text from LLM responses."""
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text.strip(), flags=re.MULTILINE)
    match = re.search(r'(\{[\s\S]*\})', text)
    if match:
        return match.group(1).strip()
    return text.strip()


def deterministic_voice_cleanup(draft_resume: dict) -> dict:
    """Fast, local regex cleanup of AI clichés, banned buzzwords, and formulaic phrases (0 API calls)."""
    if not isinstance(draft_resume, dict):
        return draft_resume

    cliche_replacements = {
        r'\b[Ss]pearheaded\b': 'Led',
        r'\b[Ll]everaged\b': 'Used',
        r'\b[Uu]tilized\b': 'Used',
        r'\b[Ff]acilitated\b': 'Managed',
        r'\b[Ee]nsured\b': 'Maintained',
        r'\b[Dd]emonstrated\b': 'Showed',
        r'\b[Cc]ollaborated with\b': 'Worked with',
        r'\b[Cc]ollaborated\b': 'Partnered',
        r'\b[Ss]treamlined\b': 'Simplified',
        r'\b[Cc]hampioned\b': 'Drove',
        r'\b[Ff]ostered\b': 'Supported',
        r'\b[Hh]arnessed\b': 'Applied',
        r'\b[Nn]avigated\b': 'Handled',
        r'\b[Oo]rchestrated\b': 'Built',
        r'\b[Pp]ioneered\b': 'Introduced',
        r'\b[Rr]evolutionized\b': 'Overhauled',
        r'\b[Aa]rchitected\b': 'Designed',
        r'\b[Ee]mpowered\b': 'Enabled',
        r'\b[Ee]levated\b': 'Improved',
        r'\b[Uu]nlocked\b': 'Achieved',
        r'\b[Rr]obust\b': 'reliable',
        r'\b[Ss]eamless\b': 'smooth',
        r'\b[Ss]eamlessly\b': 'smoothly',
        r'\b[Tt]apestry\b': 'mix',
        r'\b[Pp]ivotal\b': 'key',
        r'\b[Tt]estament\b': 'proof',
        r'\b[Tt]ransformative\b': 'major',
        r'\b[Gg]roundbreaking\b': 'new',
        r'\b[Cc]utting-edge\b': 'modern',
        r'\b[Ss]ynergy\b': 'cooperation',
        r'\b[Dd]ynamic\b': 'active',
        r'\b[Ff]urthermore,?\s*': '',
        r'\b[Mm]oreover,?\s*': '',
    }

    try:
        cleaned = json.loads(json.dumps(draft_resume))
    except Exception:
        cleaned = dict(draft_resume)

    def _clean_str(text: str) -> str:
        if not isinstance(text, str):
            return text
        res = text
        for pat, rep in cliche_replacements.items():
            res = re.sub(pat, rep, res)
        return res

    if "summary" in cleaned and isinstance(cleaned["summary"], str):
        s = cleaned["summary"]
        for opener in [
            r'^[Rr]esults-driven\s+\w+\s+with\b',
            r'^[Rr]esults-oriented\s+\w+\s+with\b',
            r'^[Dd]ynamic and experienced\s+\w+\s+with\b',
            r'^[Ss]easoned professional\s+with\b',
            r'^[Pp]assionate and dedicated\s+\w+\s+with\b',
            r'^[Pp]roven track record\s+in\b',
        ]:
            s = re.sub(opener, 'Engineer with', s)
        cleaned["summary"] = _clean_str(s)

    if "experience" in cleaned and isinstance(cleaned["experience"], list):
        for exp in cleaned["experience"]:
            if isinstance(exp, dict) and "bullets" in exp:
                exp["bullets"] = [_clean_str(b) for b in exp.get("bullets", []) if isinstance(b, str)]

    return cleaned


def run_researcher_phase(
    jd_text: str,
    company: str,
    role: str,
    client: Optional[genai.Client] = None,
    missing_keywords: Optional[list[str]] = None,
    keyword_contexts: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """
    Role 1: Researcher.
    Converts raw JD and keyword contexts into an atomic requirement rubric locally (0 API calls).
    Preserves 100% of user API calls and RPM limits for the Writer phase.
    """
    hard_reqs = []
    soft_reqs = []
    if keyword_contexts:
        for kw, ctx in keyword_contexts.items():
            if ctx and len(ctx.strip()) > 8:
                hard_reqs.append(ctx.strip())
            else:
                hard_reqs.append(f"Demonstrated experience with {kw}")
    elif missing_keywords:
        hard_reqs = [f"Hands-on experience with {kw}" for kw in missing_keywords[:10]]

    if jd_text:
        for line in jd_text.splitlines():
            l_strip = line.strip().lstrip("-*• ")
            if any(w in l_strip.lower() for w in ["collaborat", "lead", "communicat", "agile", "cross-functional", "mentor"]):
                if 15 < len(l_strip) < 160 and l_strip not in soft_reqs:
                    soft_reqs.append(l_strip)
                    if len(soft_reqs) >= 4:
                        break

    canonical_titles = [role.strip()] if role else []
    # Derive canonical industry title variants
    if role:
        clean_r = role.strip()
        for prefix in ["Senior ", "Lead ", "Principal ", "Staff ", "Junior ", "Associate "]:
            if clean_r.startswith(prefix):
                base_title = clean_r[len(prefix):].strip()
                if base_title not in canonical_titles:
                    canonical_titles.append(base_title)
        if "Data Engineer" in clean_r and "Big Data Engineer" not in canonical_titles:
            canonical_titles.append("Big Data Engineer")
        if "Software Engineer" in clean_r and "Backend Engineer" not in canonical_titles:
            canonical_titles.append("Backend Engineer")

    # Keyword Evidence Matrix: 3 Tiers
    keyword_matrix = {
        "tier_1_hard_requirements": hard_reqs[:10],
        "tier_2_soft_competencies": soft_reqs[:5],
        "tier_3_canonical_titles": canonical_titles,
    }

    return {
        "role_title": role,
        "company_name": company,
        "hard_requirements": hard_reqs[:10],
        "soft_requirements": soft_reqs[:5],
        "key_buzzwords_and_acronyms": missing_keywords or [],
        "keyword_matrix": keyword_matrix,
        "canonical_title_variants": canonical_titles,
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
    keyword_contexts: Optional[dict[str, str]] = None,
    ats_profile: Any = None,
) -> dict[str, Any]:
    """
    Role 2: Writer.
    Applies Rules 0–16 (Human Voice, So What test, Front-load value, Plain strong verbs)
    AND injects target ATS platform constraints (phrasing style, density ceiling, date format).
    """
    from platform_rules import get_profile, get_safe_mode_profile
    profile = ats_profile if ats_profile is not None else get_safe_mode_profile()
    if isinstance(profile, str):
        profile = get_profile(profile)

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

    context_section = ""
    if keyword_contexts:
        ctx_items = []
        for kw, ctx in keyword_contexts.items():
            if ctx and ctx.strip():
                ctx_items.append(f'- "{kw}": JD Context: "{ctx.strip()}"')
            else:
                ctx_items.append(f'- "{kw}"')
        if ctx_items:
            context_section = f"""
===================================================================
MISSING KEYWORDS WITH EXACT JOB DESCRIPTION CONTEXT:
===================================================================
Pay careful attention to the EXACT domain meaning and context in which these keywords appear in the job description.
Do NOT treat keywords generically or hallucinate unrelated domain meanings (e.g. if 'forecasting' is used for predictive time-series data pipelines, do NOT write weather or financial forecasting):
{chr(10).join(ctx_items)}
Weave these technologies into relevant work experience bullets adhering strictly to how the target company uses them.
"""

    ats_section = f"""
===================================================================
TARGET ATS PLATFORM MANDATES ({profile.display_name.upper()}):
===================================================================
- Target ATS Platform: {profile.display_name} ({profile.matching_style.upper()} matching algorithm)
  {"* LITERAL BOOLEAN MANDATE: The target ATS uses exact string search. Match required tools, skills, and certifications verbatim in experience bullets." if profile.matching_style == "exact_weighted" else "* SEMANTIC/VECTOR MANDATE: The target ATS and recruiters evaluate contextual accomplishment. Use the primary keyword naturally, and use organic domain synonyms across other bullets."}
- Keyword Density Ceiling: STRICT MAXIMUM {profile.keyword_density_ceiling*100:.1f}%. Never repeat any single keyword excessively across bullets (2-3 natural occurrences max across the whole resume). Avoid keyword stuffing flags.
- Date Formatting Standard: All job and education dates MUST be strictly formatted as {profile.date_format}.
- Title Equivalence (Rule 0 Guardrail): Master resume job titles must remain truthful. If the candidate's existing title represents an equivalent role to '{role}', you may include an authentic parenthetical equivalent in the summary or bullet context (e.g. 'Software Engineer ({role} focus)'), but NEVER fabricate a false past title.
"""

    system_prompt = f"""You are the Writer in Dani's Multi-Agent Resume Team.
Your job is to tailor the candidate's resume with strict adherence to human voice, authenticity, and high HR impact.

{ats_section}

EDITORIAL PRIORITY ORDER (NEVER INVERT):
1. AUTHENTICITY / TRUTH: Never invent fake metrics, fake companies, or fake degrees.
2. HUMAN VOICE (RULES 0–5): Brevity, rhythmic sentence variation (jazz, not metronome), plain language.
3. HR IMPACT: Real quantified numbers, front-loaded impact (first 3 words carry weight).
4. DEEP ATS & BULLET WEAVING (CRITICAL):
   - NEVER simply dump required keywords only into the "skills" list.
   - You MUST actively weave key required frameworks, database tools, and cloud platforms from the JD and missing keywords directly into work experience bullets across the candidate's canonical roles (e.g. demonstrating active hands-on design, migration, ETL, or deployment in real engineering context).
   - CRITICAL DOMAIN CONTEXT: When weaving missing keywords, you MUST match their precise technical domain meaning as used in the Job Description context provided. Never misapply a technical keyword.

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

ALL CANONICAL EXPERIENCES & BULLET COUNTS MUST BE PRESERVED:
- If the master profile has multiple jobs, your output MUST contain ALL of them.
- MANDATORY BULLET COUNT: For EACH role, output the EXACT same number of bullet points as present in the master resume. NEVER compress, truncate, or drop bullets!
- MANDATORY COMPANY NAMES: The ONLY allowed company names in the "experience" array are: {[e.get('company') for e in base_resume.get('experience', [])]}. NEVER replace, invent, or substitute company names. Preserve the exact company names and dates!

BULLET STRUCTURE REQUIREMENTS:
- Every bullet MUST be a complete, self-contained accomplishment sentence of at least 15 words.
- NEVER output short 2-to-3-word header fragments (e.g. NEVER output "Streamed data." or "ETL pipelines.").
- Start every bullet with a capitalized strong action verb and end with a period.

SKILLS CONSTRAINTS:
The "skills" array must retain all candidate master skills and include new relevant keywords (< 4 words each). NEVER drop or prune the candidate's core hard skills!

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

{context_section}

{custom_section}

MASTER RESUME:
{json.dumps(base_resume, ensure_ascii=False, separators=(',', ':'))}

Draft the optimized resume now as valid JSON."""

    from gemini_client import (
        is_key_invalid_error, mark_key_dead, get_active_key,
        extract_retry_delay, get_candidate_models, record_model_failure, record_model_success,
        extract_clean_text
    )

    last_err = None
    keys = get_all_gemini_keys()
    max_attempts = max(4, len(keys) * 2)

    for attempt in range(1, max_attempts + 1):
        models = get_candidate_models()
        for model_name in models:
            try:
                current_client = get_gemini_client()
                response = current_client.models.generate_content(
                    model=model_name,
                    contents=[types.Content(role="user", parts=[types.Part(text=system_prompt + "\n\n" + user_prompt)])],
                    config=get_standard_genai_config(model_name=model_name, max_output_tokens=4096, temperature=0.3),
                )
                raw_text = extract_clean_text(response)
                if not raw_text:
                    raise ValueError(f"Model {model_name} returned empty text or only thought tokens")
                record_model_success(model_name)
                parsed = json.loads(_clean_json(raw_text))
                return deterministic_voice_cleanup(parsed)
            except Exception as e:
                last_err = e
                record_model_failure(model_name, e)
                err_str = str(e).upper()
                print(f"[Dani's Engine - Writer] {model_name} note: {e}")

                if is_key_invalid_error(e):
                    mark_key_dead(get_active_key(), reason="API key invalid")
                    if get_all_gemini_keys():
                        rotate_key(reason="Purged invalid key")
                    break

                if "404" in err_str or "NOT_FOUND" in err_str:
                    continue

                time.sleep(0.5)

        # If all models on the current active key failed, rotate to the backup key
        keys = get_all_gemini_keys()
        if len(keys) > 1:
            rotate_key(reason=f"Attempt {attempt} models exhausted — rotating to backup key")
            time.sleep(1.0)
        else:
            delay = extract_retry_delay(last_err) if last_err else 5.0
            time.sleep(min(delay, 8.0))

    raise RuntimeError(f"Writer failed across all models: {last_err}")


def reduce_keyword_density_to_ceiling(
    resume_dict: dict,
    ats_profile: Any = None,
    jd_keywords: Optional[list[str]] = None,
) -> dict:
    """
    Deterministically revises down over-stuffed keywords so density complies with
    ats_profile.keyword_density_ceiling (§4.4, §4.5 & Acceptance Criteria #5).
    Replaces redundant repetitions with natural phrasing/pronouns without losing truth.
    """
    from platform_rules import get_profile, get_safe_mode_profile
    profile = ats_profile if ats_profile is not None else get_safe_mode_profile()
    if isinstance(profile, str):
        profile = get_profile(profile)

    ceiling = getattr(profile, "keyword_density_ceiling", 0.015)
    if not jd_keywords:
        return resume_dict

    try:
        cleaned = json.loads(json.dumps(resume_dict))
    except Exception:
        cleaned = dict(resume_dict)

    # Extract all prose text to count total words exactly as audit_ats_compliance does
    full_text_parts = []
    if cleaned.get("summary"):
        full_text_parts.append(str(cleaned["summary"]))
    for sk in cleaned.get("skills", []):
        full_text_parts.append(str(sk))
    for exp in cleaned.get("experience", []):
        if exp.get("title"):
            full_text_parts.append(str(exp["title"]))
        if exp.get("company"):
            full_text_parts.append(str(exp["company"]))
        for b in exp.get("bullets", []):
            full_text_parts.append(str(b))
    for pr in cleaned.get("projects", []):
        if isinstance(pr, dict):
            full_text_parts.append(str(pr.get("name", "")))
            for b in pr.get("bullets", []):
                full_text_parts.append(str(b))
        elif isinstance(pr, str):
            full_text_parts.append(pr)

    combined_text = " ".join(full_text_parts)
    words = [w.lower() for w in re.findall(r'[a-zA-Z0-9_\-\+\#\.]+', combined_text)]
    total_words = max(1, len(words))

    # For each keyword, calculate allowable occurrences
    for kw in jd_keywords:
        if not kw or len(kw.strip()) < 2:
            continue
        kw_clean = kw.strip()
        pattern = re.compile(r'\b' + re.escape(kw_clean) + r'\b', re.IGNORECASE)
        matches = len(pattern.findall(combined_text))

        # Target occurrences: strictly below or equal to platform density ceiling
        max_allowed = max(1, int(total_words * ceiling))
        while max_allowed > 1 and (max_allowed / total_words > ceiling):
            max_allowed -= 1

        if matches > max_allowed:
            surplus = matches - max_allowed
            replaced = 0
            for exp in reversed(cleaned.get("experience", [])):
                new_bullets = []
                for b in exp.get("bullets", []):
                    b_str = str(b)
                    while surplus > replaced and pattern.search(b_str):
                        b_str = pattern.sub("the technology", b_str, count=1)
                        replaced += 1
                    new_bullets.append(b_str)
                exp["bullets"] = new_bullets
                if replaced >= surplus:
                    break

    return cleaned


def run_editor_phase(
    draft_resume: dict,
    audit_findings: list[str],
    client: genai.Client,
    ats_profile: Any = None,
    jd_keywords: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Role 4: Editor.
    Fixes audit findings. Applies deterministic voice and ATS keyword density cleanup (0 API calls).
    Only calls LLM if unresolvable findings remain.
    """
    cleaned_draft = deterministic_voice_cleanup(draft_resume)
    if ats_profile and jd_keywords:
        cleaned_draft = reduce_keyword_density_to_ceiling(cleaned_draft, ats_profile, jd_keywords)

    re_audit = audit_resume_dict(cleaned_draft)
    from human_voice_audit import audit_ats_compliance
    re_ats = audit_ats_compliance(cleaned_draft, ats_profile=ats_profile, jd_keywords=jd_keywords)

    if (re_audit.get("passed") or not re_audit.get("findings")) and (re_ats.get("passed") or not re_ats.get("findings")):
        print(f"[Dani's Engine - Editor] Deterministic regex & density cleanup resolved all audit findings! (0 API calls burned)")
        return cleaned_draft

    combined_to_fix = list(re_audit.get("findings", []))
    for f in re_ats.get("findings", []):
        if f not in combined_to_fix:
            combined_to_fix.append(f)

    system_prompt = """You are the Editor in Dani's Multi-Agent Resume Team.
The Auditor has flagged specific human-voice, AI-tell, or ATS keyword density findings in the draft resume.
Your task is to fix ONLY the flagged lines while preserving all facts, numbers, tools, and experiences.

Replace any cliché opener with a plain strong action verb (Built, Designed, Cut, Led, Shipped, Automated, Improved).
Replace any banned AI words with plain equivalents.
Shorten overlong sentences to under 24 words.
If keyword density ceiling was exceeded, replace redundant repetitions with pronouns or synonyms so total occurrences decrease.

Return the fully corrected resume as valid JSON."""

    user_prompt = f"""AUDITOR FINDINGS TO FIX:
{json.dumps(combined_to_fix or audit_findings, indent=2)}

DRAFT RESUME TO EDIT:
{json.dumps(cleaned_draft, ensure_ascii=False, separators=(',', ':'))}

Return the corrected JSON now."""

    from gemini_client import get_candidate_models, record_model_failure, record_model_success, extract_clean_text
    models = get_candidate_models()
    for model_name in models:
        try:
            current_client = get_gemini_client()
            response = current_client.models.generate_content(
                model=model_name,
                contents=[types.Content(role="user", parts=[types.Part(text=system_prompt + "\n\n" + user_prompt)])],
                config=get_standard_genai_config(model_name=model_name, max_output_tokens=4096, temperature=0.2),
            )
            raw_text = extract_clean_text(response)
            if not raw_text:
                continue
            record_model_success(model_name)
            return json.loads(_clean_json(raw_text))
        except Exception as e:
            record_model_failure(model_name, e)
            print(f"[Dani's Engine - Editor] {model_name} note: {e}")
            if is_quota_error(e) or "503" in str(e) or "UNAVAILABLE" in str(e).upper():
                keys = get_all_gemini_keys()
                if len(keys) > 1:
                    rotate_key(reason=f"Editor Failover ({model_name})")
            time.sleep(0.3)

    return cleaned_draft


def execute_danis_engine_pipeline(
    base_resume: dict,
    jd_text: str,
    missing_keywords: list[str],
    company: str,
    role: str,
    custom_bullets: str = "",
    log_callback: Optional[Callable[[int, str, str, Optional[dict], str], None]] = None,
    keyword_contexts: Optional[dict[str, str]] = None,
    ats_profile: Any = None,
) -> dict[str, Any]:
    """
    Main Orchestrator for Dani's Multi-Agent Engine.
    Executes:
    1. Researcher (JD Rubric & 3-Tier Keyword Matrix Extraction)
    2. Writer (Rules 0-16 Grounded Drafting with JD Domain Context & ATS Profile Constraints)
    3. Auditor (Human Voice & 4-Gate ATS Compliance Verification)
    4. Editor (Targeted Fixes if Voice or ATS Audit flags issues)
    5. Post-Processing & Multi-Role Guarantee
    """
    from platform_rules import get_profile, get_safe_mode_profile
    from human_voice_audit import audit_resume_dict, audit_ats_compliance

    profile = ats_profile if ats_profile is not None else get_safe_mode_profile()
    if isinstance(profile, str):
        profile = get_profile(profile)

    def log(step: int, title: str, desc: str, data: dict = None, status: str = "working"):
        if log_callback:
            log_callback(step, title, desc, data, status)
        print(f"[Dani's Engine] [{status.upper()}] Step {step}: {title} — {desc}")

    client = get_gemini_client()

    # Step 1: Researcher Phase (Deterministic & local - preserves 100% quota for Writer)
    log(4, "Dani's Researcher", f"Extracting 3-tier keyword matrix for {role} at {company}...", status="working")
    research_rubric = run_researcher_phase(
        jd_text, company, role, client,
        missing_keywords=missing_keywords, keyword_contexts=keyword_contexts
    )
    log(4, "Dani's Researcher", f"Extracted {len(research_rubric.get('hard_requirements', []))} hard requirements & {len(research_rubric.get('canonical_title_variants', []))} canonical title variants.", status="success")

    # Step 2: Writer Phase (Rules 0-16 + ATS Constraints)
    log(4, "Dani's Writer", f"Drafting resume tailored for {profile.display_name} (Cap: {profile.keyword_density_ceiling*100:.1f}%, Dates: {profile.date_format})...", status="working")
    draft = run_writer_phase(
        base_resume=base_resume,
        research_rubric=research_rubric,
        missing_keywords=missing_keywords,
        company=company,
        role=role,
        custom_bullets=custom_bullets,
        client=client,
        keyword_contexts=keyword_contexts,
        ats_profile=profile,
    )
    log(4, "Dani's Writer", f"Draft created with strict human-voice protocols & {profile.display_name} phrasing rules.", status="success")

    # Step 2.5: Cover Letter Generation (§4.4 & Acceptance Criteria #3)
    # If target ATS actively scores cover letters (e.g. Greenhouse, Taleo), generate one before Auditor runs
    cover_letter_text = draft.get("_cover_letter", "")
    if getattr(profile, "cover_letter_scored", False) and not cover_letter_text:
        try:
            from cover_letter_generator import generate_cover_letter
            log(4, "Dani's Writer", f"Generating mandatory cover letter ({profile.display_name} actively scores cover letters)...", status="working")
            cl_dict = generate_cover_letter(
                base_resume=base_resume,
                company=company,
                role=role,
                missing_keywords=missing_keywords,
                ats_profile=profile,
            )
            cover_letter_text = cl_dict.get("text", "")
            draft["_cover_letter"] = cover_letter_text
            log(4, "Dani's Writer", f"Generated cover letter tailored for {profile.display_name} scoring.", status="success")
        except Exception as cl_err:
            print(f"[Dani's Engine] Cover letter auto-generation note: {cl_err}")

    # Step 3: Auditor Phase (Human Voice + 4-Gate ATS Compliance)
    log(5, "Dani's Auditor", f"Running Human Voice & {profile.display_name} 4-Gate ATS Compliance Audit...", status="working")
    audit_report = audit_resume_dict(draft)
    ats_report = audit_ats_compliance(draft, ats_profile=profile, jd_keywords=missing_keywords, jd_title=role)

    all_passed = audit_report["passed"] and ats_report["passed"]
    combined_findings = list(audit_report.get("findings", []))
    for f in ats_report.get("findings", []):
        if f not in combined_findings:
            combined_findings.append(f)

    log(5, "Dani's Auditor",
        f"Voice Score: {audit_report['score']}% (CV: {audit_report['burstiness_cv']}) | ATS ({profile.display_name}) Score: {ats_report['score']}%",
        data={"voice_audit": audit_report, "ats_audit": ats_report},
        status="success" if all_passed else "warning")

    # Step 4: Editor Phase (if findings exist)
    if not all_passed and combined_findings:
        log(5, "Dani's Editor", f"Correcting {len(combined_findings)} auditor findings...", status="working")
        draft = run_editor_phase(draft, combined_findings, client, ats_profile=profile, jd_keywords=missing_keywords)
        re_audit = audit_resume_dict(draft)
        re_ats_audit = audit_ats_compliance(draft, ats_profile=profile, jd_keywords=missing_keywords, jd_title=role)
        ats_report = re_ats_audit
        log(5, "Dani's Editor", f"Corrected draft re-audited. Voice: {re_audit['score']}%, ATS: {re_ats_audit['score']}%", data={"voice_audit": re_audit, "ats_audit": re_ats_audit}, status="success")

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

    # Bullet sanitization across all experiences (purge 2-word lead-in fragments, ensure complete sentences)
    for exp_entry in final_exp:
        raw_bullets = exp_entry.get("bullets", [])
        clean_bullets = []
        for b in raw_bullets:
            if not b or not isinstance(b, str):
                continue
            b_clean = b.strip()
            # Strip leading bullet glyphs or numbering
            b_clean = re.sub(r'^[•·▪▸►\*\-]\s*', '', b_clean)
            b_clean = re.sub(r'^\d+[\.\)]\s*', '', b_clean).strip()

            # Filter out short fragments (< 25 chars or < 4 words, e.g. "Streamed data.", "Core duties:")
            if len(b_clean) < 25 or len(b_clean.split()) < 4:
                continue

            # Capitalize first character
            if b_clean and b_clean[0].islower():
                b_clean = b_clean[0].upper() + b_clean[1:]

            # Ensure it ends with a period
            if b_clean and not b_clean.endswith(('.', '!', '?')):
                b_clean += '.'

            # Check for substring duplicates within the same role
            is_fragment = False
            for existing in clean_bullets:
                if b_clean.lower() in existing.lower() or existing.lower() in b_clean.lower():
                    if len(existing) >= len(b_clean):
                        is_fragment = True
                        break
            if not is_fragment and b_clean not in clean_bullets:
                clean_bullets.append(b_clean)

        # If all bullets were somehow dropped, fall back to base bullets
        if not clean_bullets and exp_entry.get("company"):
            for orig in base_exp:
                if orig.get("company") == exp_entry.get("company"):
                    clean_bullets = orig.get("bullets", [])
                    break
        exp_entry["bullets"] = clean_bullets

    merged["experience"] = final_exp

    # ── MASTER SKILLS ZERO-LOSS GUARANTEE ──
    # Always retain 100% of the candidate's master resume skills verbatim
    base_skills = [str(s).strip() for s in base_resume.get("skills", []) if s and str(s).strip()]
    final_skills = list(base_skills)
    final_skills_lower = {s.lower() for s in final_skills}

    # Only append verified technical missing keywords / new tools from the draft
    for s in draft.get("skills", []):
        s_str = str(s).strip()
        words = s_str.split()
        if len(words) <= 4 and not s_str.endswith(".") and len(s_str) < 35:
            if s_str.lower() not in final_skills_lower:
                final_skills.append(s_str)
                final_skills_lower.add(s_str.lower())

    for kw in (missing_keywords or []):
        kw_clean = str(kw).strip()
        if len(kw_clean.split()) <= 3 and kw_clean.lower() not in final_skills_lower:
            final_skills.append(kw_clean)
            final_skills_lower.add(kw_clean.lower())

    merged["skills"] = final_skills
    merged["_ats_platform"] = profile.platform_id
    merged["_ats_profile"] = profile.to_dict()
    merged["_ats_audit"] = ats_report

    return merged

