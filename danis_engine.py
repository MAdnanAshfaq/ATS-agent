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


# Every cliché opener in data/ai_tells.json has a plain replacement here, so the
# auditor never re-flags an opener the cleanup could have fixed.
_OPENER_VERB_SWAPS = {
    "spearheaded": "Led", "spearhead": "Lead", "spearheading": "Leading",
    "leveraged": "Used", "leverage": "Use", "leveraging": "Using",
    "utilized": "Used", "utilize": "Use", "utilizing": "Using",
    "facilitated": "Ran", "facilitate": "Run", "facilitating": "Running",
    "ensured": "Maintained", "ensure": "Maintain", "ensuring": "Maintaining",
    "demonstrated": "Showed", "demonstrate": "Show", "demonstrating": "Showing",
    "collaborated": "Worked", "collaborate": "Work", "collaborating": "Working",
    "streamlined": "Simplified", "streamline": "Simplify", "streamlining": "Simplifying",
    "championed": "Led", "champion": "Lead", "championing": "Leading",
    "fostered": "Built", "foster": "Build", "fostering": "Building",
    "harnessed": "Used", "harness": "Use", "harnessing": "Using",
    "navigated": "Handled", "navigate": "Handle", "navigating": "Handling",
    "liaised": "Worked", "liaise": "Work", "liaising": "Working",
    "interfaced": "Worked", "interface": "Work", "interfacing": "Working",
    "orchestrated": "Coordinated", "orchestrate": "Coordinate", "orchestrating": "Coordinating",
    "pioneered": "Introduced", "pioneer": "Introduce", "pioneering": "Introducing",
    "revolutionized": "Overhauled", "revolutionize": "Overhaul", "revolutionizing": "Overhauling",
    "architected": "Designed", "architect": "Design", "architecting": "Designing",
    "empowered": "Enabled", "empower": "Enable", "empowering": "Enabling",
    "elevated": "Improved", "elevate": "Improve", "elevating": "Improving",
    "unlocked": "Delivered", "unlock": "Deliver", "unlocking": "Delivering",
    "synergized": "Combined", "synergize": "Combine", "synergizing": "Combining",
}

# Mid-sentence swaps for every banned word/phrase in data/ai_tells.json that has
# no technical meaning. "dynamic" is only swapped in non-technical phrases, so
# "dynamic programming" or "dynamic SQL" survive.
_ANYWHERE_SWAPS = [
    (r"\bleveraging\b", "using"), (r"\butilizing\b", "using"), (r"\butilize\b", "use"),
    (r"\bseamlessly\b", "smoothly"), (r"\bseamless\b", "smooth"),
    (r"\bcutting-edge\b", "modern"), (r"\bstate-of-the-art\b", "modern"),
    (r"\ba testament to\b", "proof of"), (r"\btapestry\b", "mix"), (r"\btestament\b", "proof"),
    (r"\bpivotal\b", "key"), (r"\btransformative\b", "major"), (r"\btransformational\b", "major"),
    (r"\bgroundbreaking\b", "new"), (r"\btrailblazing\b", "new"),
    (r"\bsynergies\b", "shared gains"), (r"\bsynergy\b", "collaboration"),
    (r"\brobust\b", "reliable"), (r"\bholistic\b", "end-to-end"), (r"\bmultifaceted\b", "varied"),
    (r"\bgame-changer\b", "major improvement"), (r"\bbeacon\b", "example"),
    (r"\bcornerstone\b", "core"), (r"\blinchpin\b", "core"), (r"\bvibrant\b", "active"),
    (r"\bparamount\b", "essential"), (r"\brelentless\b", "steady"), (r"\bunwavering\b", "steady"),
    (r"\bcrucible\b", "test"), (r"\bmyriad of\b", "many"), (r"\bmyriad\b", "many"),
    (r"\ba plethora of\b", "many"), (r"\bplethora of\b", "many"), (r"\bplethora\b", "many"),
    (r"\bdelved into\b", "dug into"), (r"\bdelving into\b", "digging into"), (r"\bdelve into\b", "dig into"),
    (r"\bdelved\b", "dug"), (r"\bdelving\b", "digging"), (r"\bdelve\b", "dig"),
    (r"\bplayed a (?:vital|key) role in\b", "helped with"), (r"\bplay a vital role in\b", "help with"),
    (r"\bplayed a (?:vital|key) role\b", "helped"), (r"\bplay a vital role\b", "help"),
    (r"\bserves as a\b", "is a"), (r"\bserved as a\b", "was a"),
    (r"\bstands as a\b", "is a"), (r"\bstood as a\b", "was a"),
    (r"\bdeep dive\b", "detailed review"), (r"\bat the forefront of\b", "leading"),
    (r"\bat the forefront\b", "in the lead"), (r"\bever-evolving\b", "changing"),
    (r"\bfast-paced environment\b", "busy team"), (r"\bdeeply rooted\b", "grounded"),
    (r"\bit is worth noting that\s*", ""), (r"\bit is worth noting\s*", ""),
    (r"\bdynamic(?= (?:and|team|teams|environment|environments|professional|leader|individual|role|workplace|company))", "fast-moving"),
]


def _swap_keep_case(match: re.Match, replacement: str) -> str:
    word = match.group(0)
    return replacement[0].upper() + replacement[1:] if word[:1].isupper() else replacement


def _clean_phrase(text: str) -> str:
    if not isinstance(text, str):
        return text
    res = text
    for pat, rep in _ANYWHERE_SWAPS:
        res = re.sub(pat, lambda m, r=rep: _swap_keep_case(m, r), res, flags=re.IGNORECASE)
    res = re.sub(r"(^|(?<=[.!?]\s))(?:Furthermore|Moreover|Additionally|Consequently|Notably|In summary|In conclusion),\s*(\w)",
                 lambda m: m.group(1) + m.group(2).upper(), res)
    # Mid-sentence connectives the auditor bans.
    res = re.sub(r",?\s*\b(?:moreover|furthermore|additionally|consequently|notably)\b,?", lambda m: "," if m.group(0).startswith(",") else "", res, flags=re.IGNORECASE)
    res = re.sub(r"\s{2,}", " ", res).replace(" ,", ",").replace(",,", ",").strip()
    if res[:1].islower():
        res = res[0].upper() + res[1:]
    return res


def _clean_bullet(text: str) -> str:
    if not isinstance(text, str):
        return text
    res = _clean_phrase(text)
    m = re.match(r"^(\W*)([A-Za-z]+)(.*)$", res, flags=re.S)
    if m and m.group(2).lower() in _OPENER_VERB_SWAPS:
        res = m.group(1) + _OPENER_VERB_SWAPS[m.group(2).lower()] + m.group(3)
    return res


def deterministic_voice_cleanup(draft_resume: dict) -> dict:
    """Local cleanup of AI clichés (0 API calls). Verb swaps apply only to the
    first word of a bullet; mid-sentence swaps only to non-technical filler words."""
    if not isinstance(draft_resume, dict):
        return draft_resume
    try:
        cleaned = json.loads(json.dumps(draft_resume))
    except Exception:
        cleaned = dict(draft_resume)

    if isinstance(cleaned.get("summary"), str):
        s = cleaned["summary"]
        for opener in (r"^[Rr]esults-driven\s+", r"^[Rr]esults-oriented\s+", r"^[Dd]ynamic and experienced\s+",
                       r"^[Ss]easoned\s+", r"^[Pp]assionate and dedicated\s+", r"^[Hh]ighly motivated\s+"):
            s = re.sub(opener, "", s)
        s = s[:1].upper() + s[1:] if s else s
        cleaned["summary"] = _clean_phrase(s)

    for exp in cleaned.get("experience", []) or []:
        if isinstance(exp, dict) and isinstance(exp.get("bullets"), list):
            exp["bullets"] = [_clean_bullet(b) for b in exp["bullets"] if isinstance(b, str)]
    for pr in cleaned.get("projects", []) or []:
        if isinstance(pr, dict) and isinstance(pr.get("bullets"), list):
            pr["bullets"] = [_clean_bullet(b) for b in pr["bullets"] if isinstance(b, str)]
    _diversify_openers(cleaned)
    return cleaned


# Alternates used when one opener starts 3+ bullets (the auditor flags that),
# including openers the swaps above produce, so the cleanup never creates the repeat.
_OPENER_ALTERNATES = {
    "led": ["Directed", "Headed", "Ran"], "used": ["Applied", "Adopted", "Ran"],
    "worked": ["Partnered", "Teamed up", "Contributed"], "built": ["Created", "Developed", "Set up"],
    "designed": ["Planned", "Modeled", "Drafted"], "developed": ["Built", "Created", "Wrote"],
    "implemented": ["Rolled out", "Deployed", "Put in place"], "created": ["Built", "Wrote", "Set up"],
    "improved": ["Raised", "Boosted", "Upgraded"], "reduced": ["Cut", "Lowered", "Trimmed"],
    "managed": ["Ran", "Oversaw", "Handled"], "maintained": ["Kept", "Sustained", "Upheld"],
    "automated": ["Scripted", "Replaced manual work on", "Removed manual steps from"],
    "coordinated": ["Organized", "Aligned", "Scheduled"], "simplified": ["Cleaned up", "Reworked", "Trimmed"],
    "migrated": ["Moved", "Ported", "Transferred"], "optimized": ["Tuned", "Sped up", "Improved"],
    "delivered": ["Shipped", "Completed", "Launched"], "enabled": ["Allowed", "Opened up", "Supported"],
    "showed": ["Proved", "Confirmed", "Presented"], "handled": ["Managed", "Resolved", "Took on"],
    "introduced": ["Launched", "Brought in", "Started"], "overhauled": ["Rebuilt", "Reworked", "Redesigned"],
    "combined": ["Merged", "Joined", "Unified"], "wrote": ["Authored", "Drafted", "Produced"],
    "deployed": ["Shipped", "Released", "Rolled out"], "integrated": ["Connected", "Wired", "Linked"],
}


def _diversify_openers(resume: dict) -> None:
    """Keep any opener to at most 2 bullets across the resume by swapping the
    3rd+ use for an unused alternate. Mutates resume in place."""
    from collections import Counter
    bullet_lists = [e["bullets"] for e in (resume.get("experience") or [])
                    if isinstance(e, dict) and isinstance(e.get("bullets"), list)]
    counts = Counter()
    for bl in bullet_lists:
        for b in bl:
            m = re.match(r"^\W*([A-Za-z]+)", b) if isinstance(b, str) else None
            if m:
                counts[m.group(1).lower()] += 1
    seen = Counter()
    for bl in bullet_lists:
        for i, b in enumerate(bl):
            m = re.match(r"^(\W*)([A-Za-z]+)(.*)$", b, flags=re.S) if isinstance(b, str) else None
            if not m:
                continue
            verb = m.group(2).lower()
            seen[verb] += 1
            if seen[verb] <= 2 or verb not in _OPENER_ALTERNATES:
                continue
            for alt in _OPENER_ALTERNATES[verb]:
                alt_key = alt.split()[0].lower()
                if counts[alt_key] < 2:
                    bl[i] = m.group(1) + alt + m.group(3)
                    counts[alt_key] += 1
                    counts[verb] -= 1
                    break


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
        "jd_text": jd_text,
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
    model_name: str = "gemini-flash-lite-latest",
    keyword_contexts: Optional[dict[str, str]] = None,
    ats_profile: Any = None,
    target_keywords: Optional[list[str]] = None,
    must_have: Optional[list[str]] = None,
    nice_to_have: Optional[list[str]] = None,
    core_themes: Optional[list[str]] = None,
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
TARGET ATS: {profile.display_name} ({profile.matching_style} matching)
- {"Exact-match ATS: it credits a keyword only when the JD's exact spelling appears. Use the keyword verbatim, never a synonym in its place." if profile.matching_style == "exact_weighted" else "Semantic ATS plus recruiter search: use the JD's exact spelling at least once, then natural phrasing around it."}
- Repetition: each keyword 1-3 times across the whole resume (skills line + 1-2 bullets). Never stack the same keyword in consecutive bullets.
- Dates: copy every role's dates exactly as given in the master resume."""

    all_targets = list(dict.fromkeys([str(k).strip() for k in (target_keywords or []) if str(k).strip()] + [str(k).strip() for k in missing_keywords if str(k).strip()]))
    base_exp = [e for e in base_resume.get("experience", []) if isinstance(e, dict)]
    import resume_rules as _rr
    roles_block = "\n".join(
        f"  {i + 1}. {e.get('title') or e.get('role') or ''} | {e.get('company', '')} | {e.get('dates') or e.get('date') or ''} | "
        f"{len(e.get('bullets') or [])} master bullets | at most {_rr.role_cap(i, len(e.get('bullets') or []))} bullets"
        for i, e in enumerate(base_exp)
    )
    must_list = [k for k in (must_have if must_have is not None else all_targets)]
    nice_list = [k for k in (nice_to_have or []) if k not in must_list]
    themes_list = list(core_themes or [])

    system_prompt = f"""You are the Writer on a resume-tailoring team. You rewrite the candidate's master resume for ONE job so that it (a) passes the employer's ATS keyword screen and (b) reads as a credible, specific, human-written resume to the recruiter who opens it next.

{ats_section}

FIXED FACTS (copy exactly, never change, never add):
- Employers, job titles, employment dates and locations: exactly the roles listed under ROLES below, in the same order. No new employers, no renamed titles.
- Education, degrees, schools, certifications, licences, awards, contact details: unchanged. Never add a certification or degree.
- Total years of experience: as implied by the dates. Never state a larger number.

WHAT YOU WRITE:
1. KEYWORD COVERAGE WITHOUT STUFFING.
   - Every MUST-HAVE keyword appears VERBATIM (the JD's spelling) in at least one experience bullet or the summary. Where the master resume does not show one yet, write a responsibility in an existing role that shows hands-on use of it, matching how the JD context uses it.
   - NICE-TO-HAVE keywords go in Skills. Put one in a bullet only if it fits naturally; never force it.
   - At most {_rr.MAX_NEW_KEYWORDS_PER_BULLET} keywords the master resume does not already show per bullet. Never cram a list of tools into one bullet. If a role needs more, write one new, specific bullet for them in that role instead of stuffing existing ones.
2. PLACEMENT that survives an interview:
   - Put each keyword in the role where it is most believable for that title, seniority, team and company domain. The most recent role carries most new technology.
   - Respect technology eras: never place a tool in a role that ended before the tool was widely used (e.g. LLMs/GenAI/LangChain/vector databases not before 2022; dbt not before 2018; Kubernetes not before 2016; Snowflake not before 2016; Terraform not before 2016). If no role fits a keyword's era, use the most recent role.
   - Keep every technology used correctly: right vendor (no "AWS BigQuery"), right layer (orchestration vs storage vs compute), right verb (you deploy to Kubernetes, model data in dbt, orchestrate with Airflow).
3. BULLETS:
   - Each role tells ONE coherent story that fits its title and dates: what that team owned and what the candidate delivered. New responsibilities must fit that story.
   - Respect each role's "at most N bullets" limit in ROLES (at most {_rr.MAX_ADDED_BULLETS_PER_ROLE} more than the master; older roles get fewer). When a role is over its limit, drop or shorten the master bullets that matter least for THIS job.
   - Whole resume: at most {_rr.MAX_TOTAL_BULLETS} bullets and about {_rr.MAX_PROSE_WORDS} words of summary + bullets (two pages).
   - Shape: strong past-tense verb + what you built or changed + the tool + the result. Present tense only for the current role.
   - Length varies on purpose: mix short bullets (10-14 words) with longer ones (20-28 words). Never more than 28 words.
   - Numbers: about half the bullets carry one number. Reuse the master resume's numbers first; new numbers (at most {_rr.MAX_NEW_NUMERIC_CLAIMS} across the resume) must be modest and believable for the company's scale. Never more than one number per bullet. No invented budgets or headcounts beyond a small team you mentored.
   - Vary openers: no verb starts more than 2 bullets in the whole resume.
   - Write what the candidate did, never the JD's wording about it: no "such as", "e.g.", "experience with", "familiarity with", "a tool like". Name the exact tool once, as used.
   - Keep the resume tight: add a new bullet only when no existing bullet can carry the keyword naturally.
4. CORE THEMES: the job's main responsibilities are listed under CORE THEMES. Show each one in the summary or in a bullet of the two most recent roles, as something the candidate did (e.g. "owned the billing service end to end", "mentored 3 engineers", "worked with product managers on the roadmap").
5. SUMMARY: 2-3 sentences, at most 60 words. Bridge the candidate's real background to the target role: name "{role}" (or its closest truthful equivalent), the real years of experience, and at most {_rr.MAX_SUMMARY_KEYWORDS} of the most important must-have keywords. Never a list of tools. No clichés.
6. SKILLS: a flat list of short items (1-4 words each), no duplicates or synonyms of each other (not both "PostgreSQL" and "Postgres", not both "AWS" and "Amazon Web Services"); use the JD's spelling. Include the must-have and nice-to-have keywords. No sentences.

VOICE:
- Plain, specific, engineer-to-engineer. Would a sharp engineer say this out loud in an interview without wincing?
- Never start a bullet with: {cliche_list}.
- Never use: {banned_list}, "responsible for", "successfully", "various", "utilize".

SELF-CHECK BEFORE ANSWERING:
- Every MUST-HAVE keyword appears verbatim in a bullet or the summary (list where in "_keyword_placement").
- No bullet carries more than {_rr.MAX_NEW_KEYWORDS_PER_BULLET} new keywords; no role exceeds its bullet limit.
- Every role from ROLES is present with its exact company, title and dates.
- No bullet over 28 words; no verb opens more than 2 bullets.

ROLES (fixed, in order):
{roles_block}

OUTPUT: one JSON object, nothing else:
{{
  "target_role": "{role}",
  "summary": "2-3 sentences",
  "skills": ["Skill", "..."],
  "experience": [
    {{"title": "exact master title", "company": "exact master company", "dates": "exact master dates", "location": "master location", "bullets": ["...", "..."]}}
  ],
  "projects": [],
  "_keyword_placement": {{"Keyword": "Company it was placed under"}}
}}"""

    user_prompt = f"""TARGET JOB: {role} at {company}

MUST-HAVE KEYWORDS (each verbatim in a bullet or the summary):
{json.dumps(must_list, ensure_ascii=False)}

NICE-TO-HAVE KEYWORDS (Skills is enough; a bullet only if natural):
{json.dumps(nice_list, ensure_ascii=False)}

CORE THEMES (show each in the summary or a recent-role bullet):
{json.dumps(themes_list, ensure_ascii=False)}

KEYWORDS THE MASTER RESUME DOES NOT SHOW YET (write new responsibilities for these):
{json.dumps(missing_keywords, ensure_ascii=False)}

HARD REQUIREMENTS FROM THE JD:
{json.dumps(research_rubric.get("hard_requirements", []), ensure_ascii=False)}
{context_section}
{custom_section}
MASTER RESUME:
{json.dumps({k: v for k, v in base_resume.items() if not str(k).startswith('_')}, ensure_ascii=False, separators=(',', ':'))}

Write the tailored resume JSON now."""

    from gemini_client import (
        is_key_invalid_error, mark_key_dead, get_active_key,
        extract_retry_delay, get_candidate_models, record_model_failure, record_model_success,
        extract_clean_text
    )

    last_err = None
    keys = get_all_gemini_keys()
    # Ensure at least 3 attempts across candidate models even on single key to ride out 503 spikes
    max_attempts = max(3, len(keys))

    for attempt in range(1, max_attempts + 1):
        models = get_candidate_models()
        for model_name in models:
            for m_retry in range(2):
                try:
                    current_client = get_gemini_client()
                    response = current_client.models.generate_content(
                        model=model_name,
                        contents=[types.Content(role="user", parts=[types.Part(text=system_prompt + "\n\n" + user_prompt)])],
                        config=get_standard_genai_config(model_name=model_name, max_output_tokens=16384, temperature=0.3, is_json=True),
                    )
                    raw_text = extract_clean_text(response)
                    if not raw_text:
                        raise ValueError(f"Model {model_name} returned empty text or only thought tokens")
                    record_model_success(model_name)
                    parsed = json.loads(_clean_json(raw_text))
                    return deterministic_voice_cleanup(parsed)
                except Exception as e:
                    last_err = e
                    err_str = str(e).upper()
                    print(f"[Dani's Engine - Writer] {model_name} (try {m_retry+1}) note: {e}")

                    if is_key_invalid_error(e):
                        mark_key_dead(get_active_key(), reason="API key invalid")
                        if get_all_gemini_keys():
                            rotate_key(reason="Purged invalid key")
                        break

                    record_model_failure(model_name, e)

                    if "503" in err_str or "UNAVAILABLE" in err_str or "HIGH DEMAND" in err_str or "OVERLOADED" in err_str:
                        if m_retry == 0:
                            time.sleep(1.0)
                            continue
                        else:
                            break
                    elif is_quota_error(e):
                        keys = get_all_gemini_keys()
                        if len(keys) > 1:
                            rotate_key(reason=f"Quota exhausted on {model_name}")
                        break
                    else:
                        break

        # If all candidate models on this attempt hit 503/errors, pause with backoff before next attempt
        if attempt < max_attempts:
            keys = get_all_gemini_keys()
            if len(keys) > 1:
                rotate_key(reason=f"Attempt {attempt} models busy — rotating key")
            backoff_delay = min(1.5 * attempt, 4.0)
            print(f"[Dani's Engine - Writer] All candidate models busy on attempt {attempt}. Backing off {backoff_delay:.1f}s...")
            time.sleep(backoff_delay)

    # If Gemini experienced sustained API overload, fall back to the resilient rewriter engine
    # so the user's pipeline NEVER fails with an uncaught exception
    try:
        from rewriter import rewrite_resume
        print(f"[Dani's Engine - Writer] ⚠️ Gemini busy after {max_attempts} attempts. Falling back to resilient rewriter pass: {last_err}")
        fallback_res = rewrite_resume(
            base_resume=base_resume,
            jd_text=research_rubric.get("jd_text", ""),
            missing_keywords=missing_keywords,
            company=company,
            role=role,
            custom_bullets=custom_bullets,
            keyword_contexts=keyword_contexts,
        )
        if fallback_res and isinstance(fallback_res, dict):
            return deterministic_voice_cleanup(fallback_res)
    except Exception as fallback_err:
        print(f"[Dani's Engine - Writer] Fallback rewriter error: {fallback_err}")

    print(f"[Dani's Engine - Writer] ⚠️ Sustained API overload across all keys/models ({last_err}). Falling back to base resume with keyword injection.")
    import copy
    safe_fallback = copy.deepcopy(base_resume)
    safe_fallback.pop("_raw_text", None)
    if missing_keywords:
        existing_skills = list(safe_fallback.get("skills", [])) if isinstance(safe_fallback.get("skills"), list) else []
        existing_lower = {str(s).lower() for s in existing_skills}
        for kw in missing_keywords:
            kw_s = str(kw).strip()
            if kw_s and len(kw_s.split()) <= 3 and kw_s.lower() not in existing_lower:
                existing_skills.append(kw_s)
                existing_lower.add(kw_s.lower())
        safe_fallback["skills"] = existing_skills
    return deterministic_voice_cleanup(safe_fallback)


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
    extra_findings: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Role 4: Editor.
    Fixes audit findings. Applies deterministic voice and ATS keyword density cleanup (0 API calls).
    Only calls LLM if unresolvable findings remain. extra_findings are issues the
    voice/ATS audits do not detect themselves (e.g. a tool placed before its era).
    """
    cleaned_draft = deterministic_voice_cleanup(draft_resume)

    re_audit = audit_resume_dict(cleaned_draft)
    from human_voice_audit import audit_ats_compliance
    re_ats = audit_ats_compliance(cleaned_draft, ats_profile=ats_profile, jd_keywords=jd_keywords)

    if not extra_findings and (re_audit.get("passed") or not re_audit.get("findings")) and (re_ats.get("passed") or not re_ats.get("findings")):
        print(f"[Dani's Engine - Editor] Deterministic regex & density cleanup resolved all audit findings! (0 API calls burned)")
        return cleaned_draft

    combined_to_fix = list(re_audit.get("findings", []))
    for f in list(re_ats.get("findings", [])) + list(extra_findings or []):
        if f not in combined_to_fix:
            combined_to_fix.append(f)

    system_prompt = """You are the Editor in Dani's Multi-Agent Resume Team.
The Auditor has flagged specific human-voice, AI-tell, or ATS keyword density findings in the draft resume.
Your task is to fix ONLY the flagged lines while preserving all facts, numbers, tools, and experiences.
Every technology keyword in a line you edit must still appear, spelled exactly the same, after your edit: ATS matching depends on it.
Never change a company, title, date or location. Keep every role and at least as many bullets per role.

Replace any cliché opener with a plain strong action verb (Built, Designed, Cut, Led, Shipped, Automated, Improved).
Replace any banned AI words with plain equivalents.
Shorten overlong sentences to under 24 words.
If a bullet crams too many new keywords, keep at most 2 in it and move the rest into another bullet of the same role (or drop nice-to-have ones; they stay in Skills).
If core themes are missing, rewrite the summary or a recent-role bullet to show them as something the candidate did.
If there are too many new numbers, remove the least believable ones; never more than one number per bullet.
If the summary does not name the target role, rewrite it to bridge the candidate's background to that role.
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
        for m_retry in range(2):
            try:
                current_client = get_gemini_client()
                response = current_client.models.generate_content(
                    model=model_name,
                    contents=[types.Content(role="user", parts=[types.Part(text=system_prompt + "\n\n" + user_prompt)])],
                    config=get_standard_genai_config(model_name=model_name, max_output_tokens=8192, temperature=0.2, is_json=True),
                )
                raw_text = extract_clean_text(response)
                if not raw_text:
                    continue
                record_model_success(model_name)
                return json.loads(_clean_json(raw_text))
            except Exception as e:
                record_model_failure(model_name, e)
                err_str = str(e).upper()
                print(f"[Dani's Engine - Editor] {model_name} (try {m_retry+1}) note: {e}")
                if "503" in err_str or "UNAVAILABLE" in err_str or "HIGH DEMAND" in err_str or "OVERLOADED" in err_str or "504" in err_str or "DEADLINE" in err_str:
                    if m_retry == 0:
                        time.sleep(0.8)
                        continue
                    else:
                        keys = get_all_gemini_keys()
                        if len(keys) > 1:
                            rotate_key(reason=f"Editor 503/504 Failover ({model_name})")
                        break
                elif is_quota_error(e):
                    keys = get_all_gemini_keys()
                    if len(keys) > 1:
                        rotate_key(reason=f"Editor Failover ({model_name})")
                    break
                else:
                    break

    return cleaned_draft


def _call_json_llm(prompt: str, temperature: float = 0.3, max_tokens: int = 16384, label: str = "LLM") -> Optional[Any]:
    """One JSON-mode Gemini call across the model cascade and key pool; None on failure."""
    from gemini_client import get_candidate_models, record_model_failure, record_model_success, extract_clean_text
    for attempt in range(2):
        for model_name in get_candidate_models():
            try:
                client = get_gemini_client()
                response = client.models.generate_content(
                    model=model_name,
                    contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                    config=get_standard_genai_config(model_name=model_name, max_output_tokens=max_tokens,
                                                     temperature=temperature, is_json=True),
                )
                raw = extract_clean_text(response)
                if not raw:
                    continue
                record_model_success(model_name)
                return json.loads(_clean_json(raw))
            except Exception as e:
                record_model_failure(model_name, e)
                print(f"[Dani's Engine - {label}] {model_name} note: {str(e)[:160]}")
                if is_quota_error(e) and len(get_all_gemini_keys()) > 1:
                    rotate_key(reason=f"{label} quota")
        time.sleep(1.5)
    return None


def run_keyword_weave_phase(
    draft: dict,
    absent_keywords: list[str],
    keyword_contexts: Optional[dict[str, str]] = None,
    role: str = "",
    company: str = "",
) -> dict:
    """Targeted pass for keywords that are still not in any bullet: rewrite or add
    bullets so each appears verbatim, leaving everything else untouched."""
    experience = [e for e in (draft.get("experience") or []) if isinstance(e, dict)]
    if not absent_keywords or not experience:
        return draft
    ctx_lines = "\n".join(
        f'- "{k}": {(keyword_contexts or {}).get(k, "").strip() or "(no JD sentence found)"}' for k in absent_keywords
    )
    prompt = f"""You are editing the EXPERIENCE section of a resume tailored for "{role}" at {company}.

These keywords are not yet in any bullet. Each must appear VERBATIM (exact spelling below) in at least one bullet:
{ctx_lines}

Rules:
- For each keyword, either rewrite the single most related existing bullet to include it, or add ONE new bullet to the most believable role. Never put more than 2 of these keywords in one bullet: prefer one new, specific bullet over cramming.
- Do not add a bullet to a role that already has 7 or more bullets; rewrite one of its weakest bullets instead.
- Place each tool only in a role whose dates fit the era the tool was in common use; otherwise use the most recent role.
- Use each technology correctly for how the JD context above uses it. Strong past-tense verb first, 10-28 words, at most one modest believable number.
- Describe what was done, not the JD's wording: never "such as", "e.g.", "experience with", "a tool like".
- Do NOT change any company, title, dates or location. Do NOT remove or reword bullets you are not using for a keyword.
- Return ONLY the JSON array of roles in the same order and shape as given.

EXPERIENCE (JSON):
{json.dumps(experience, ensure_ascii=False, separators=(',', ':'))}"""
    result = _call_json_llm(prompt, temperature=0.25, label="Weave")
    if isinstance(result, dict):
        result = result.get("experience")
    if not isinstance(result, list) or len(result) != len(experience):
        return draft
    new_exp = []
    for orig, upd in zip(experience, result):
        if not isinstance(upd, dict) or not isinstance(upd.get("bullets"), list):
            new_exp.append(orig)
            continue
        merged = dict(orig)
        bullets = [str(b).strip() for b in upd["bullets"] if str(b).strip()]
        # Never let the weave shrink a role below its previous bullet count.
        merged["bullets"] = bullets if len(bullets) >= len(orig.get("bullets") or []) else orig.get("bullets", [])
        new_exp.append(merged)
    out = dict(draft)
    out["experience"] = new_exp
    return out


def run_unstuff_phase(resume: dict, base_resume: dict, keywords: list[str], must_have: list[str], role: str = "",
                      core_themes: Optional[list[str]] = None) -> tuple[dict, int]:
    """Fix keyword stuffing by REDISTRIBUTING keywords across each role's existing
    bullets (not by adding bullets, which would push a role over its limit and
    force trimming). Also rewrites a summary that lists too many tools.

    The rewrite is accepted only if deterministic checks pass: fewer stuffed
    bullets, every must-have keyword still in prose, no role over its bullet
    limit, no fewer bullets with numbers, no core theme lost, and companies,
    titles and dates unchanged. Returns (resume, items_fixed)."""
    import resume_rules as rr
    from ats_scoring import keyword_present, resume_prose_text
    out = json.loads(json.dumps(resume))
    roles = [e for e in (out.get("experience") or []) if isinstance(e, dict)]
    base_roles = [e for e in (base_resume.get("experience") or []) if isinstance(e, dict)]
    before_stuffed = rr.stuffed_bullets(base_resume, out, keywords)
    summary_hits = [k for k in keywords if keyword_present(k, str(out.get("summary") or ""))]
    fix_summary = len(summary_hits) > rr.MAX_SUMMARY_KEYWORDS
    if not before_stuffed and not fix_summary:
        return out, 0

    caps = [rr.role_cap(i, len((base_roles[i].get("bullets") or [])) if i < len(base_roles) else len(e.get("bullets") or []))
            for i, e in enumerate(roles)]
    from ats_scoring import resume_json_text
    master_text = resume_json_text(base_resume or {})
    new_kws = [k for k in keywords if not keyword_present(k, master_text, allow_aliases=True)]
    exp_view = [{"title": e.get("title", ""), "company": e.get("company", ""), "dates": e.get("dates", ""),
                 "max_bullets": caps[i], "bullets": e.get("bullets") or []} for i, e in enumerate(roles)]
    prompt = f"""You are fixing keyword stuffing in a resume tailored for "{role}".
Some bullets cram several tools into one sentence. Rewrite the EXPERIENCE so that:
- No bullet contains more than {rr.MAX_NEW_KEYWORDS_PER_BULLET} of these NEW KEYWORDS: {json.dumps(new_kws, ensure_ascii=False)}
- Spread them by rewriting OTHER existing bullets of the same role to carry one or two each (keep each bullet's real work, numbers and meaning). A keyword may move to another role only if that role's dates fit when the tool was in common use.
- Keep each role's number of bullets the same, never above its max_bullets.
- Every one of these MUST-HAVE keywords stays in some bullet, spelled exactly: {json.dumps(must_have, ensure_ascii=False)}
- Keep every number that is already in a bullet.
- Keep showing these core responsibilities of the job in the two most recent roles (they are checked): {json.dumps(list(core_themes or []), ensure_ascii=False)}
- Bullets: strong verb first, 10-26 words, specific work, no lists of tools, no "such as".
- Never change title, company or dates.
{"Also rewrite the SUMMARY as 2-3 sentences (max 60 words) that bridges the candidate's background to the role and names at most " + str(rr.MAX_SUMMARY_KEYWORDS) + " tools; never a list of tools." if fix_summary else ""}

EXPERIENCE:
{json.dumps(exp_view, ensure_ascii=False, indent=1)}
{"CURRENT SUMMARY: " + json.dumps(out.get("summary") or "", ensure_ascii=False) if fix_summary else ""}

Return ONLY JSON: {{"experience": [{{"title": "...", "company": "...", "dates": "...", "bullets": ["..."]}}]{', "summary": "..."' if fix_summary else ""}}}"""
    def numeric_bullets(r):
        return sum(1 for e in (r.get("experience") or []) if isinstance(e, dict)
                   for b in (e.get("bullets") or []) if rr._numbers_in(str(b)))

    feedback = ""
    for attempt in range(2):
        result = _call_json_llm(prompt + feedback, temperature=0.2, max_tokens=8192, label="Rebalance")
        if not isinstance(result, dict):
            return out, 0
        candidate, checks, fixed_summary = _apply_rebalance(out, result, caps, roles, keywords, must_have,
                                                            base_resume, before_stuffed, fix_summary, core_themes, numeric_bullets)
        if all(checks.values()):
            return candidate, (len(before_stuffed) - len(rr.stuffed_bullets(base_resume, candidate, keywords))) + int(fixed_summary)
        failed = [k for k, v in checks.items() if not v]
        print(f"[Dani's Engine - Rebalance] attempt {attempt + 1} rejected: {failed}")
        feedback = ("\n\nYOUR PREVIOUS ANSWER FAILED THESE CHECKS: " + ", ".join(failed)
                    + ". Fix them: keep every number, keep the core responsibilities listed above visible, "
                    "keep every must-have keyword, and keep each role within max_bullets.")
    return out, 0


def _apply_rebalance(out, result, caps, roles, keywords, must_have, base_resume, before_stuffed, fix_summary, core_themes, numeric_bullets):
    import resume_rules as rr
    from ats_scoring import keyword_present, resume_prose_text
    candidate = json.loads(json.dumps(out))
    cand_roles = [e for e in (candidate.get("experience") or []) if isinstance(e, dict)]
    new_roles = [e for e in (result.get("experience") or []) if isinstance(e, dict)]
    if len(new_roles) == len(cand_roles):
        for i, (cur, upd) in enumerate(zip(cand_roles, new_roles)):
            bl = [str(b).strip() for b in (upd.get("bullets") or []) if str(b).strip()]
            if bl and len(bl) <= max(caps[i], len(cur.get("bullets") or [])):
                cur["bullets"] = bl  # facts (title/company/dates) stay from `cur`
    fixed_summary = False
    if fix_summary and isinstance(result.get("summary"), str) and result["summary"].strip():
        ns = result["summary"].strip()
        if len([k for k in keywords if keyword_present(k, ns)]) <= rr.MAX_SUMMARY_KEYWORDS and len(ns.split()) <= 70:
            candidate["summary"] = ns
            fixed_summary = True
    candidate = deterministic_voice_cleanup(candidate)
    prose_after = resume_prose_text(candidate)
    themes = list(core_themes or [])
    checks = {
        "less stuffing": len(rr.stuffed_bullets(base_resume, candidate, keywords)) < len(before_stuffed) or (fixed_summary and not before_stuffed),
        "must-have kept": all(keyword_present(k, prose_after) for k in must_have if keyword_present(k, resume_prose_text(out))),
        "within limits": all(len(e.get("bullets") or []) <= max(caps[i], len(roles[i].get("bullets") or []))
                             for i, e in enumerate(cand_roles)),
        "numbers kept": numeric_bullets(candidate) >= numeric_bullets(out),
        "themes kept": len(rr.missing_themes(candidate, themes)) <= len(rr.missing_themes(out, themes)),
    }
    return candidate, checks, fixed_summary


def _keywords_absent_from_prose(resume: dict, keywords: list[str]) -> list[str]:
    from ats_scoring import keyword_present, resume_prose_text
    prose = resume_prose_text(resume)
    return [k for k in keywords if not keyword_present(k, prose)]


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
    target_keywords: Optional[list[str]] = None,
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
    all_targets = list(dict.fromkeys(
        [str(k).strip() for k in (target_keywords or []) if str(k).strip()]
        + [str(k).strip() for k in (missing_keywords or []) if str(k).strip()]
    ))
    # Must-have keywords go in bullets; nice-to-have ones may sit in Skills only.
    # The report uses the same split, so "covered" means the same thing everywhere.
    import resume_rules as rr
    tiers = rr.split_keyword_tiers(all_targets, jd_text)
    must_have, nice_to_have = tiers["must_have"], tiers["nice_to_have"]
    core_themes = rr.extract_core_themes(jd_text)
    log(4, "Keyword Tiers",
        f"{len(must_have)} must-have keyword(s) for bullets, {len(nice_to_have)} nice-to-have for Skills"
        + (f" ({', '.join(nice_to_have)})" if nice_to_have else "")
        + (f"; core themes: {', '.join(core_themes)}" if core_themes else ""),
        data={"must_have": must_have, "nice_to_have": nice_to_have, "core_themes": core_themes}, status="success")

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
        target_keywords=all_targets,
        must_have=must_have,
        nice_to_have=nice_to_have,
        core_themes=core_themes,
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

    # Step 4.5: Keyword coverage loop: every MUST-HAVE keyword must sit in a bullet
    # or the summary (nice-to-have ones may stay in Skills). Up to 2 weave passes.
    absent = _keywords_absent_from_prose(draft, must_have)
    for weave_round in range(2):
        if not absent:
            break
        log(5, "Keyword Coverage", f"{len(absent)} keyword(s) not yet in any bullet: {', '.join(absent[:12])}. Weaving pass {weave_round + 1}...", status="working")
        woven = run_keyword_weave_phase(draft, absent, keyword_contexts=keyword_contexts, role=role, company=company)
        woven = deterministic_voice_cleanup(woven)
        still = _keywords_absent_from_prose(woven, must_have)
        if len(still) < len(absent):
            draft, absent = woven, still
        else:
            break
    if must_have:
        log(5, "Keyword Coverage",
            f"{len(must_have) - len(absent)}/{len(must_have)} must-have keywords placed in bullets/summary"
            + (f"; {len(absent)} only in Skills: {', '.join(absent)}" if absent else ""),
            data={"in_prose": [k for k in must_have if k not in absent], "skills_only": absent},
            status="success" if not absent else "warning")

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
            if rew_comp and orig_comp_lower and (rew_comp == orig_comp_lower or orig_comp_lower in rew_comp or rew_comp in orig_comp_lower):
                matched_rewrite = rew
                break

        if matched_rewrite:
            # Use rewritten entry but FORCE canonical company, title, dates from base_resume
            entry = dict(matched_rewrite)
            entry["company"] = orig_e.get("company") or entry.get("company")
            entry_title = orig_e.get("title") or orig_e.get("role") or entry.get("title") or entry.get("role") or "Data Engineer"
            entry["title"] = entry_title
            entry["role"] = entry_title
            entry["dates"] = orig_e.get("dates") or orig_e.get("date") or entry.get("dates") or ""
            entry["location"] = orig_e.get("location") or entry.get("location") or ""
            final_exp.append(entry)
        else:
            # If LLM omitted or renamed, check if LLM produced an entry at the same index
            if idx < len(raw_rewritten_exp) and isinstance(raw_rewritten_exp[idx], dict):
                entry = dict(raw_rewritten_exp[idx])
                entry["company"] = orig_e.get("company") or entry.get("company")
                entry_title = orig_e.get("title") or orig_e.get("role") or entry.get("title") or entry.get("role") or "Data Engineer"
                entry["title"] = entry_title
                entry["role"] = entry_title
                entry["dates"] = orig_e.get("dates") or orig_e.get("date") or entry.get("dates") or ""
                entry["location"] = orig_e.get("location") or entry.get("location") or ""
                final_exp.append(entry)
            else:
                entry = dict(orig_e)
                entry_title = orig_e.get("title") or orig_e.get("role") or "Data Engineer"
                entry["title"] = entry_title
                entry["role"] = entry_title
                final_exp.append(entry)

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

    # Every target keyword is listed in Skills with the JD's spelling (literal ATS match).
    from ats_scoring import keyword_present
    skills_blob = "\n".join(final_skills)
    for kw in all_targets:
        kw_clean = str(kw).strip()
        if kw_clean and len(kw_clean.split()) <= 4 and not keyword_present(kw_clean, skills_blob):
            final_skills.append(kw_clean)
            skills_blob += "\n" + kw_clean

    merged["skills"] = final_skills
    merged.pop("_keyword_placement", None)

    def _shape(resume: dict) -> dict:
        """Deterministic fixes shared with the report's checks: merge duplicate
        skills (keeping the JD's spelling), cap the Skills list, and trim bullets
        to the per-role, total and length limits."""
        from ats_scoring import resume_prose_text
        shaped, dropped = rr.trim_bullets(resume, base_resume, must_have, nice_to_have, core_themes)
        skills = rr.dedupe_skills(shaped.get("skills") or [], jd_text)
        shaped["skills"] = rr.cap_skills(skills, all_targets, resume_prose_text(shaped))
        if dropped:
            log(5, "Length Limits", f"Dropped {len(dropped)} bullet(s) that matter least for this job to stay within the length limits.",
                data={"dropped": dropped}, status="success")
        return shaped

    merged = _shape(merged)

    # Step 6: Final gate. The same report HollaBuddy and the History card show is
    # run here, and everything the pipeline is allowed to fix is fixed before
    # delivery, so a later audit does not rediscover it.
    from resume_report import build_resume_report
    report = build_resume_report(merged, base_resume, all_targets, role, profile, jd_text=jd_text)

    def _must_gaps(rep: dict) -> int:
        return len([k for k in rep["keywords_missing"] if k in must_have]) + \
            len([k for k in rep["keywords_skills_only"] if k in must_have])

    for gate_round in range(2):
        fixable = [f for f in report["findings"] if f["fix"] == "pipeline"]
        if not fixable:
            break
        log(5, "Final Quality Gate",
            f"Round {gate_round + 1}: fixing {len(fixable)} issue(s) before delivery: "
            + "; ".join(f["issue"][:90] for f in fixable[:4]),
            status="working")
        if any(f["category"] in ("keyword_stuffing", "summary") for f in fixable):
            unstuffed, n_fixed = run_unstuff_phase(merged, base_resume, all_targets, must_have, role, core_themes)
            if n_fixed:
                unstuffed = _shape(unstuffed)
                un_report = build_resume_report(unstuffed, base_resume, all_targets, role, profile, jd_text=jd_text)
                if _must_gaps(un_report) <= _must_gaps(report) and un_report["counts"]["blocker"] <= report["counts"]["blocker"] \
                        and un_report["counts"]["pipeline_fixable"] < report["counts"]["pipeline_fixable"]:
                    merged, report = unstuffed, un_report
                    log(5, "Final Quality Gate", f"Spread keywords across bullets: fixed {n_fixed} stuffed bullet(s)/summary.", status="success")
                    fixable = [f for f in report["findings"] if f["fix"] == "pipeline"]
                    if not fixable:
                        break
        era_or_kw = [f["issue"] for f in fixable if f["category"] in
                     ("credibility", "keywords", "core_themes", "keyword_stuffing", "new_claims", "summary")]
        if any("Low quantified impact" in f["issue"] for f in fixable):
            # Restore the candidate's REAL numbers first, before inventing any.
            real = [str(b) for e in (base_resume.get("experience") or []) if isinstance(e, dict)
                    for b in (e.get("bullets") or []) if rr._numbers_in(str(b))][:10]
            if real:
                era_or_kw.append("Too few bullets carry a number. Reuse these REAL numbers from the master resume in the "
                                 "matching bullets (same role) before adding any new number: " + " | ".join(real))
        edited = run_editor_phase(merged, [f["issue"] for f in fixable], client,
                                  ats_profile=profile, jd_keywords=all_targets, extra_findings=era_or_kw)
        candidate = _shape(_merge_text_edits(merged, edited))
        new_report = build_resume_report(candidate, base_resume, all_targets, role, profile, jd_text=jd_text)
        lost_kw = len(new_report["keywords_missing"]) > len(report["keywords_missing"]) or \
            _must_gaps(new_report) > _must_gaps(report)
        improved = (new_report["counts"]["blocker"] <= report["counts"]["blocker"]
                    and new_report["counts"]["pipeline_fixable"] < report["counts"]["pipeline_fixable"])
        if improved and not lost_kw:
            merged, report = candidate, new_report
        else:
            why = "it would lose a must-have keyword" if lost_kw else (
                f"issues went {report['counts']['pipeline_fixable']} -> {new_report['counts']['pipeline_fixable']}, "
                f"blockers {report['counts']['blocker']} -> {new_report['counts']['blocker']}")
            log(5, "Final Quality Gate", f"Kept the previous version: the edit was not an improvement ({why}).", status="warning")
            break
    remaining = [f for f in report["findings"] if f["fix"] == "pipeline"]
    log(5, "Final Quality Gate",
        f"Verdict: {report['verdict']} | {report['counts']['blocker']} blocker(s), "
        f"{len(remaining)} auto-fixable left, {report['counts']['from_master']} from master resume, "
        f"{report['counts']['needs_you']} need your decision",
        data={"report": report}, status="success" if not remaining else "warning")
    absent = report["keywords_skills_only"]

    # Final audits run on the resume as shipped (after all merges), so the
    # numbers shown to the user describe this exact resume.
    final_voice = audit_resume_dict(merged)
    final_ats = audit_ats_compliance(merged, ats_profile=profile, jd_keywords=all_targets or missing_keywords, jd_title=role)
    merged["_ats_platform"] = profile.platform_id
    merged["_ats_profile"] = profile.to_dict()
    merged["_ats_audit"] = final_ats
    merged["_voice_audit"] = final_voice
    merged["_keyword_coverage"] = {
        "targets": all_targets,
        "in_prose": [k for k in all_targets if k not in absent],
        "skills_only": absent,
    }
    merged["_report"] = report
    return merged


def _merge_text_edits(current: dict, edited: Any) -> dict:
    """Take only the summary and bullet text from an Editor result. Roles, facts,
    skills and every other field stay exactly as in `current`, and a role never
    ends up with fewer bullets than it had."""
    out = json.loads(json.dumps(current))
    if not isinstance(edited, dict):
        return out
    if isinstance(edited.get("summary"), str) and edited["summary"].strip():
        out["summary"] = edited["summary"].strip()
    cur_roles = [e for e in (out.get("experience") or []) if isinstance(e, dict)]
    new_roles = [e for e in (edited.get("experience") or []) if isinstance(e, dict)]
    for i, role in enumerate(cur_roles):
        if i >= len(new_roles):
            break
        nb = [str(b).strip() for b in (new_roles[i].get("bullets") or []) if str(b).strip()]
        if len(nb) >= len(role.get("bullets") or []):
            role["bullets"] = nb
    return deterministic_voice_cleanup(out)

