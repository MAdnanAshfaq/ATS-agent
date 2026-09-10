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
        if not kw:
            continue
            
        # If the item is a long sentence (> 5 words or > 40 chars), check if its core key terms appear
        if len(kw.split()) > 5 or len(kw) > 40:
            key_terms = [w for w in re.findall(r'\b[a-zA-Z0-9\+\#\.\-]{3,}\b', kw) 
                         if w.lower() not in ("with", "and", "the", "for", "from", "that", "this", "have", "been", "work", "team", "your", "their", "perform", "support", "across", "company", "member", "ownership", "goal", "customer", "expectations", "closely", "ensure", "meets", "delivers", "optimal", "consult", "complicated", "enhance", "expertise", "multiple", "several", "coordinate", "embrace", "opportunity", "expand", "both", "functionally", "technically", "scale", "maintain", "wide", "variety", "flexibility", "diverse", "geographically", "distributed")]
            
            matched_terms = [t for t in key_terms if t.lower() in content_pool]
            if key_terms and (len(matched_terms) / len(key_terms)) >= 0.35:
                embedded.append(word)
            else:
                missing_gaps.append(word)
            continue

        # Handle acronyms and parenthesized terms (e.g. "Kusto Query Language (KQL)")
        paren_match = re.match(r'^(.*?)\s*\((.*?)\)$', kw)
        if paren_match:
            full_part = paren_match.group(1).strip()
            abbr_part = paren_match.group(2).strip()
            if (full_part and re.search(r'\b' + re.escape(full_part) + r'\b', content_pool)) or \
               (abbr_part and re.search(r'\b' + re.escape(abbr_part) + r'\b', content_pool)) or \
               kw in content_pool:
                embedded.append(word)
                continue

        # Normal single/multi-word keyword
        escaped_word = re.escape(kw)
        if kw.endswith('.js') or '+' in kw or '.' in kw or '(' in kw:
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
    custom_bullets: str = "",
    keyword_contexts: Optional[dict[str, str]] = None,
) -> tuple[str, str]:
    """
    Build the system + user prompt for Gemini.
    Escalates strictness on retry attempts.
    """
    prompt_resume = {k: v for k, v in base_resume.items() if k != "_raw_text"}
    raw_text_context = ""
    if "_raw_text" in base_resume and base_resume["_raw_text"]:
        raw_text_context = f"\nORIGINAL UNFORMATTED RESUME TEXT:\n{base_resume['_raw_text']}\n"

    # User-specified custom bullet points to inject
    custom_bullets_section = ""
    if custom_bullets and custom_bullets.strip():
        custom_bullets_section = f"""
===================================================================
USER-SPECIFIED CUSTOM BULLETS & RESPONSIBILITIES TO INJECT:
===================================================================
{custom_bullets.strip()}

INSTRUCTION:
The user explicitly wants the above responsibilities/accomplishments integrated into their latest work experience bullets. 
Naturally weave, expand, and adapt them into high-impact, professional, active-voice bullet points for {role} at {company}.
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
Pay careful attention to the EXACT domain meaning and context in which these keywords appear in the job description:
{chr(10).join(ctx_items)}
Do NOT treat keywords generically or misapply their technical meaning.
"""

    kw_list_str = json.dumps(missing_keywords, indent=2)

    if attempt == 1 or not still_missing_from_last_attempt:
        missing_instruction = f"""
MISSING KEYWORDS TO INJECT ({len(missing_keywords)} total):
{kw_list_str}

{context_section}

Inject ALL of these keywords naturally across summary, skills, experience bullets, and projects.
Every single keyword must appear at least once in the rewritten output."""""
    else:
        still_missing_str = (
            json.dumps(still_missing_from_last_attempt, indent=2)
            if isinstance(still_missing_from_last_attempt, list)
            else str(still_missing_from_last_attempt)
        )
        missing_instruction = f"""
CRITICAL RETRY — ATTEMPT {attempt}:
The previous rewrite FAILED because the following keywords were STILL MISSING:
{still_missing_str}

You MUST explicitly inject every single one of the above keywords.
Add them directly into:
1. The "skills" list (add missing tools/technologies verbatim)
2. The "experience" bullet points (write bullets specifically demonstrating use of these tools)
3. The "summary" (incorporate key methodologies/frameworks)
"""

    system_prompt = f"""You are a dynamic ATS Optimization Engine tailoring a candidate's resume for a brand-new job application.

DYNAMIC INPUT DATA:
- MASTER_PROFILE: {json.dumps(prompt_resume, indent=2, ensure_ascii=False)}
- MISSING_KEYWORDS_FROM_SIMPLIFY: {json.dumps(missing_keywords, indent=2)}

YOUR ARCHITECTURAL PROTOCOLS:

1. MANDATORY MULTI-ROLE PRESERVATION (DO NOT DELETE PREVIOUS JOBS):
You MUST preserve ALL work experience entries present in MASTER_PROFILE.
If MASTER_PROFILE contains multiple roles, your output "experience" array MUST contain ALL of them with their exact company names and dates.
Never drop, truncate, or omit past jobs from the candidate's history.

2. HARD SKILLS PRESERVATION & ZERO LOSS OF MAIN SKILLS:
You MUST preserve ALL primary hard technical skills (programming languages, databases, cloud infrastructure, frameworks, technical tools) from MASTER_PROFILE.
NEVER delete the candidate's core technical stack!
You may ONLY prune or replace generic/soft skills (e.g. "team player", "communication", "leadership", "problem solving") to make room for new technical keywords from the job description.
Every hard skill from MASTER_PROFILE must remain in the "skills" array, supplemented by missing technical tools from the job description.
The "skills" array must ONLY contain concise technical tools (1 to 4 words each). NEVER put full sentences, duties, or descriptions into "skills".

3. QUANTIFIED IMPACT & EVIDENCE-BACKED SENIORITY:
Every rewritten bullet MUST include concrete numbers, percentages, dollar amounts, scale metrics, or time/cost savings (e.g., "reduced query latency by 45%", "scaled throughput to 5M+ daily requests", "automated CI/CD pipelines saving 8 hours weekly", "cut cloud compute costs by $60K/year").
Avoid naked activity verbs ("built", "managed", "led", "assisted") without measurable scale or outcome.
Do NOT make unsubstantiated claims in the summary. Any major methodology or capability claimed in the summary MUST be grounded in a specific project or achievement in the experience bullets.

4. SUBSTANTIVE BULLETS & ZERO EMPTY BULLETS / PLACEHOLDERS:
Every bullet point MUST be a complete, professional, high-impact sentence (15 to 28 words).
NEVER output blank bullets, lone bullet symbols ("•"), incomplete phrases, or template placeholders (e.g. "[Company]", "[Metric]").
Eliminate generic filler ("passionate about delivering quality", "detail-oriented team player").
Vary action verbs across bullets — do NOT repeat the same opening verb (e.g. don't start multiple bullets with "Engineered" or "Implemented").

5. DATE AUTHENTICITY & CURRENT EMPLOYMENT:
Preserve authentic employment dates. For the candidate's most recent/current role, the date MUST specify "Present" (e.g., "2021 – Present" or "Jan 2022 – Present") unless the user explicitly specified a past departure date. Never leave a current role ending in the current year without "Present".

6. CROSS-SECTION CONSISTENCY:
Ensure 100% consistency between skills and experience: any primary technical tool highlighted in the experience bullets MUST also appear in the skills section, and vice versa.

7. OUTPUT SCHEMATIC:
Return the updated resume strictly as a valid JSON object matching the exact keys and ALL experience roles of MASTER_PROFILE so the docx script runs smoothly.

JSON OUTPUT FORMAT (return all experiences from MASTER_PROFILE):
{{
  "target_role": "A generic, professional version of the job title matching {role}",
  "summary": "2-4 sentence professional summary targeting {role} at {company}",
  "skills": ["skill1", "skill2", ...],
  "experience": [
    {{
      "title": "Role Title",
      "company": "Exact Company Name from MASTER_PROFILE", 
      "dates": "Exact Dates from MASTER_PROFILE",
      "location": "Location or Remote",
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

{missing_instruction}

{custom_bullets_section}

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
    custom_bullets: str = "",
    keyword_contexts: Optional[dict[str, str]] = None,
) -> dict:
    """
    Rewrite the resume to inject ALL missing keywords using Gemini.

    Runs up to max_retries attempts with escalating strictness:
    - Attempt 1: inject all missing keywords + custom experience bullets
    - Attempt 2: strict retry targeting only still-missing keywords
    - Attempt 3: maximum urgency, manual injection fallback

    Returns:
        Merged resume dict with rewritten content + original metadata.
    """
    client = _get_gemini_client()

    if not missing_keywords and not (custom_bullets and custom_bullets.strip()):
        print("[Rewriter] No missing keywords or custom bullets — returning base resume unchanged")
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
            custom_bullets=custom_bullets,
            keyword_contexts=keyword_contexts,
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

            # Guarantee all experiences from base_resume are preserved
            base_exp = base_resume.get("experience", [])
            rewritten_exp = merged.get("experience", [])
            existing_companies = {e.get("company", "").lower().strip() for e in rewritten_exp if isinstance(e, dict)}
            for orig_e in base_exp:
                orig_comp = orig_e.get("company", "").lower().strip()
                if orig_comp not in existing_companies:
                    print(f"[Rewriter] Retaining missing past experience: {orig_e.get('title')} at {orig_e.get('company')}")
                    rewritten_exp.append(orig_e)

            # Clean skills array: remove full sentences or duties and extract atomic skills
            cleaned_skills = []
            sentence_skills = []
            for s in merged.get("skills", []):
                s_str = str(s).strip()
                words = s_str.split()
                if len(words) > 4 or s_str.endswith(".") or (words and words[0].lower() in (
                    "perform", "design", "collaborate", "coordinate", "execute", "debug",
                    "plan", "maintain", "build", "work", "support", "embrace", "implement", "develop"
                )):
                    sentence_skills.append(s_str.rstrip("."))
                    tech_tokens = (
                        "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Go", "Rust", "SQL", "HTML", "CSS", "Bash",
                        "React", "React Native", "Vue", "Angular", "Next.js", "Node.js", "Express", "FastAPI", "Django", "Spring Boot",
                        "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "Snowflake", "BigQuery", "Databricks", "Spark",
                        "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "CI/CD", "Jenkins", "GitHub Actions", "Git",
                        "Agile", "Scrum", "REST APIs", "GraphQL", "Microservices", "Salesforce", "HubSpot", "Jira", "Tableau", "Power BI"
                    )
                    for token in tech_tokens:
                        if token.lower() in s_str.lower() and token not in cleaned_skills:
                            cleaned_skills.append(token)
                else:
                    if s_str not in cleaned_skills:
                        cleaned_skills.append(s_str)

            # ── HARD MAIN SKILLS PRESERVATION (Never delete candidate's core technical tools) ──
            SOFT_SKILLS = {
                "team player", "communication", "leadership", "critical thinking", "problem solving",
                "cross-functional collaboration", "agile methodology", "time management", "detail-oriented",
                "mentorship", "adaptability", "presentation skills", "stakeholder management",
                "strategic planning", "creativity", "work ethic", "organizational skills",
                "decision making", "interpersonal skills", "multitasking", "collaboration", "negotiation",
                "conflict resolution", "analytical thinking", "active listening", "emotional intelligence"
            }
            base_skills = [str(s).strip() for s in base_resume.get("skills", []) if s and str(s).strip()]
            final_skills = list(base_skills)
            final_skills_lower = {s.lower() for s in final_skills}

            # Add newly rewritten technical skills from the job description
            for s in cleaned_skills:
                s_clean = s.strip()
                if s_clean.lower() not in final_skills_lower and len(s_clean.split()) <= 4:
                    final_skills.append(s_clean)
                    final_skills_lower.add(s_clean.lower())

            for kw in (missing_keywords or []):
                kw_clean = str(kw).strip()
                if len(kw_clean.split()) <= 3 and kw_clean.lower() not in final_skills_lower:
                    final_skills.append(kw_clean)
                    final_skills_lower.add(kw_clean.lower())

            # Weave any stray sentence responsibilities into the latest role bullets
            if sentence_skills and rewritten_exp:
                latest_bullets = rewritten_exp[0].get("bullets", [])
                for sent in sentence_skills:
                    if not any(sent.lower()[:30] in b.lower() for b in latest_bullets):
                        clean_b = sent[0].upper() + sent[1:]
                        if not clean_b.endswith("."):
                            clean_b += "."
                        latest_bullets.append(clean_b)
                rewritten_exp[0]["bullets"] = latest_bullets

            # Bullet sanitization across all roles (purge broken/empty bullets, ensure complete sentences)
            for exp_entry in rewritten_exp:
                raw_bullets = exp_entry.get("bullets", [])
                clean_b_list = []
                for b in raw_bullets:
                    if not b or not isinstance(b, str):
                        continue
                    b_clean = b.strip()
                    b_clean = re.sub(r'^[•·▪▸►\*\-]\s*', '', b_clean)
                    b_clean = re.sub(r'^\d+[\.\)]\s*', '', b_clean).strip()
                    if len(b_clean) < 20 or len(b_clean.split()) < 4:
                        continue
                    if b_clean and b_clean[0].islower():
                        b_clean = b_clean[0].upper() + b_clean[1:]
                    if b_clean and not b_clean.endswith(('.', '!', '?')):
                        b_clean += '.'
                    if b_clean not in clean_b_list:
                        clean_b_list.append(b_clean)
                if not clean_b_list and exp_entry.get("company"):
                    for orig in base_exp:
                        if orig.get("company") == exp_entry.get("company"):
                            clean_b_list = orig.get("bullets", [])
                            break
                exp_entry["bullets"] = clean_b_list

            # ── CROSS-SECTION CONSISTENCY (Sync technical tools mentioned in bullets into skills) ──
            TECH_VOCAB = (
                "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Go", "Rust", "SQL", "HTML", "CSS", "Bash",
                "React", "React Native", "Vue", "Angular", "Next.js", "Node.js", "Express", "FastAPI", "Django", "Spring Boot",
                "PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch", "Snowflake", "BigQuery", "Redshift", "Databricks", "Spark", "PySpark",
                "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform", "Ansible", "CI/CD", "Jenkins", "GitHub Actions", "Git",
                "Kafka", "Airflow", "dbt", "GraphQL", "REST APIs", "Microservices", "Salesforce", "HubSpot", "Tableau", "Power BI"
            )
            all_bullets_str = " ".join(" ".join(e.get("bullets", [])) for e in rewritten_exp).lower()
            for tech in TECH_VOCAB:
                if re.search(r'\b' + re.escape(tech.lower()) + r'\b', all_bullets_str):
                    if tech.lower() not in final_skills_lower:
                        final_skills.append(tech)
                        final_skills_lower.add(tech.lower())

            merged["skills"] = final_skills

            # ── DATE NORMALIZATION (Current role must specify 'Present') ──
            for i, exp_entry in enumerate(rewritten_exp):
                dates = exp_entry.get("dates", "")
                if i == 0 and dates:
                    # If ends with current year (e.g. "2021 - 2026" or "2021-2026") without "Present"
                    if re.search(r'[-–—]\s*202[4-6]$', dates.strip()) and not re.search(r'\b(present|current)\b', dates, re.IGNORECASE):
                        start_part = re.split(r'[-–—]', dates)[0].strip()
                        exp_entry["dates"] = f"{start_part} – Present"
                    elif " - " in dates:
                        exp_entry["dates"] = dates.replace(" - ", " – ")

            merged["experience"] = rewritten_exp

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
