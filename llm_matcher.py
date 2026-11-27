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
import time
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
    """True if the resume contains `kw` as a whole term, literally (case-insensitive,
    plural tolerant). Literal on purpose: exact-match ATS platforms only credit the
    term as the job description spells it, so "K8s" does not satisfy "Kubernetes"."""
    from ats_scoring import keyword_present
    if not (kw or "").strip():
        return False
    haystack = (resume_full_text or "") + "\n" + "\n".join(str(s) for s in (resume_skills_list or []))
    return keyword_present(kw, haystack)


def _estimate_years_experience(resume: dict) -> int:
    """Sum of role spans in years, from 4-digit years in each role's dates."""
    import datetime
    now_year = datetime.date.today().year
    spans = []
    for exp in resume.get("experience", []) or []:
        if not isinstance(exp, dict):
            continue
        d = str(exp.get("dates") or exp.get("date") or "")
        years = [int(y) for y in re.findall(r"(?:19|20)\d{2}", d)]
        if not years:
            continue
        start = min(years)
        end = now_year if re.search(r"present|current|now", d, re.I) else max(years)
        spans.append((start, end))
    if not spans:
        return 0
    # Merge overlapping spans so concurrent roles are not double counted.
    spans.sort()
    total, cur_s, cur_e = 0, spans[0][0], spans[0][1]
    for s_, e_ in spans[1:]:
        if s_ <= cur_e:
            cur_e = max(cur_e, e_)
        else:
            total += cur_e - cur_s
            cur_s, cur_e = s_, e_
    total += cur_e - cur_s
    return max(total, 0)


def _deterministic_score(matching: list, missing: list) -> dict:
    tot = len(matching) + len(missing)
    score = round(100 * len(matching) / tot) if tot else 0
    s10 = round(score / 10.0, 1)
    if s10 < 6.0: rating = "Poor"
    elif s10 < 7.0: rating = "Fair"
    elif s10 < 8.0: rating = "Good"
    elif s10 < 9.0: rating = "Great"
    else: rating = "Excellent"
    return {"score": score, "score_scale_10": s10, "score_rating": rating, "total_keywords": tot}


def extract_keyword_contexts_from_jd(keywords: list, jd_text: str) -> dict:
    """
    Deterministically scan the Job Description and extract the exact sentence
    or bullet point where each keyword appears to provide 100% domain clarity.
    E.g. distinguishes predictive time-series forecasting from weather or financial forecasting.
    """
    if not jd_text or not keywords:
        return {}

    # Split into sentences or lines
    lines = [line.strip() for line in re.split(r'[\r\n]+', jd_text) if len(line.strip()) >= 15]
    sentences = []
    for line in lines:
        sub_sents = [s.strip() for s in re.split(r'(?<=[.!?])\s+', line) if len(s.strip()) >= 15]
        sentences.extend(sub_sents if sub_sents else [line])

    contexts = {}
    for kw in keywords:
        kw_clean = kw.strip()
        if not kw_clean:
            continue
        pattern = re.compile(r'\b' + re.escape(kw_clean) + r'\b', re.IGNORECASE)
        best_sentence = ""
        for s in sentences:
            if pattern.search(s):
                # Prefer sentences that are substantial (between 30 and 220 chars)
                if not best_sentence or (30 <= len(s) <= 220 and len(s) > len(best_sentence)):
                    best_sentence = s
                    if 40 <= len(best_sentence) <= 180:
                        break
        if best_sentence:
            # Clean up bullet markers from sentence start
            clean_s = re.sub(r'^[•\-\*\d\.\)]+\s*', '', best_sentence).strip()
            contexts[kw_clean] = clean_s[:250]
        else:
            # Fallback search anywhere in jd_text with window
            m = pattern.search(jd_text)
            if m:
                start = max(0, m.start() - 40)
                end = min(len(jd_text), m.end() + 100)
                snip = jd_text[start:end].replace('\n', ' ').strip()
                contexts[kw_clean] = f"...{snip}..."
            else:
                contexts[kw_clean] = ""

    return contexts


def _local_matcher_fallback(jd_text: str, base_resume: dict) -> dict:
    """Deterministic keyword extraction when Gemini is unavailable. Only terms found
    in the JD are used; nothing is assumed about the candidate's field."""
    from keyword_matcher import extract_keywords_from_text
    resume_full = _flatten_resume_text(base_resume)
    resume_skills = [str(s) for s in base_resume.get("skills", [])]
    final_matching, final_missing, seen = [], [], set()

    from ats_scoring import jd_spelling
    for kw in extract_keywords_from_text(jd_text):
        k_title = jd_spelling(kw.strip(), jd_text)
        if not k_title or k_title.lower() in seen or k_title.lower() in GENERIC_FILLER_WORDS:
            continue
        seen.add(k_title.lower())
        (final_matching if is_keyword_in_resume(k_title, resume_full, resume_skills) else final_missing).append(k_title)

    cand_name = base_resume.get("name", "Candidate")
    exps = base_resume.get("experience") or []
    cand_title = (exps[0].get("title") or exps[0].get("role") or "") if exps and isinstance(exps[0], dict) else ""

    first_lines = [l.strip() for l in jd_text.splitlines() if l.strip() and len(l.strip()) < 60]
    job_title_jd = first_lines[0] if first_lines else ""
    job_title_jd = re.sub(r'^(?:Title:\s*|Job Application for\s*|Job Openings\s*)+', '', job_title_jd, flags=re.I).strip()

    exp_match = re.search(r'(\d+)\+?\s*(?:to\s*\d+\+?)?\s*years?', jd_text, re.I)
    req_years = int(exp_match.group(1)) if exp_match else None
    cand_years = _estimate_years_experience(base_resume)

    jd_words = set(re.findall(r'[a-z]{3,}', job_title_jd.lower())) - {"senior", "junior", "lead", "staff", "principal"}
    cv_words = set(re.findall(r'[a-z]{3,}', cand_title.lower())) - {"senior", "junior", "lead", "staff", "principal"}

    res = {
        "resume_name": f"{cand_name.replace(' ', '_')}_Resume",
        "job_title_jd": job_title_jd or "Not stated",
        "job_title_resume": cand_title or "Not stated",
        "job_title_match": bool(jd_words & cv_words),
        "exp_years_jd": f"{req_years}+ years exp" if req_years else "Not stated",
        "exp_years_resume": f"{cand_years}+ years exp" if cand_years else "Not stated",
        "exp_years_match": (cand_years >= req_years) if (req_years and cand_years) else False,
        "industries": [],
        "industries_match": False,
        "matching_keywords": final_matching,
        "missing_keywords": final_missing,
        "missing_keyword_contexts": extract_keyword_contexts_from_jd(final_missing, jd_text),
        "summary_feedback": "Gemini was unavailable; keywords were extracted locally from the job description.",
        "summary_match": False,
        "score_source": "keyword_coverage",
    }
    res.update(_deterministic_score(final_matching, final_missing))
    return res


# ── Stable keyword list per job ────────────────────────────────────────────────
# Gemini picks a slightly different keyword set each time it reads the same JD,
# which made the "before" score move between checks. The list is extracted once
# per job, stored, and every later check scores against that same list.
_JD_CACHE_MEM: dict = {}
_RESULT_CACHE_MEM: dict = {}
_JD_CACHE_FILE = os.environ.get("ATS_JD_CACHE_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "jd_keyword_cache.json")


def _jd_cache_uses_db() -> bool:
    if os.environ.get("ATS_JD_CACHE") == "file":
        return False
    import db as _db
    return _db.is_db_available()
_TRACKING_PARAMS = re.compile(r"^(utm_.*|ref|refId|source|src|gh_src|trk|trackingId|lever-source.*|lever-origin|currentJobId)$", re.I)


def _normalize_job_url(url: str) -> str:
    from urllib.parse import urlsplit, parse_qsl, urlencode
    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        return ""
    parts = urlsplit(url)
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)))
    path = parts.path.rstrip("/")
    return f"{parts.netloc.lower()}{path}" + (f"?{query}" if query else "")


def _jd_cache_keys(jd_text: str, job_url: str = "") -> list:
    import hashlib
    keys = []
    norm_url = _normalize_job_url(job_url)
    if norm_url:
        keys.append("url:" + hashlib.sha1(norm_url.encode("utf-8")).hexdigest())
    norm_jd = re.sub(r"\s+", " ", (jd_text or "").lower()).strip()
    if norm_jd:
        keys.append("jd:" + hashlib.sha1(norm_jd.encode("utf-8")).hexdigest())
    return keys


def _jd_cache_get(keys: list):
    for k in keys:
        if k in _JD_CACHE_MEM:
            return _JD_CACHE_MEM[k]
    try:
        import db as _db
        if _jd_cache_uses_db():
            for k in keys:
                hit = _db.db_get_jd_cache(k)
                if hit:
                    _JD_CACHE_MEM[k] = hit
                    return hit
            return None
    except Exception:
        pass
    try:
        with open(_JD_CACHE_FILE, "r", encoding="utf-8") as f:
            disk = json.load(f)
        for k in keys:
            if k in disk:
                _JD_CACHE_MEM[k] = disk[k]
                return disk[k]
    except Exception:
        pass
    return None


def _jd_cache_put(keys: list, payload: dict) -> None:
    for k in keys:
        _JD_CACHE_MEM.setdefault(k, payload)
    try:
        import db as _db
        if _jd_cache_uses_db():
            for k in keys:
                _db.db_put_jd_cache(k, payload)
            return
    except Exception:
        pass
    try:
        disk = {}
        if os.path.exists(_JD_CACHE_FILE):
            with open(_JD_CACHE_FILE, "r", encoding="utf-8") as f:
                disk = json.load(f)
        for k in keys:
            disk.setdefault(k, payload)
        os.makedirs(os.path.dirname(_JD_CACHE_FILE), exist_ok=True)
        with open(_JD_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(disk, f, ensure_ascii=False)
    except Exception as e:
        print(f"[LLM Matcher] keyword cache write note: {e}")


def _resume_fingerprint(base_resume: dict) -> str:
    import hashlib
    clean = {k: v for k, v in (base_resume or {}).items() if not str(k).startswith("_")}
    return hashlib.sha1(json.dumps(clean, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _result_from_keywords(payload: dict, jd_text: str, base_resume: dict, soft: dict | None = None) -> dict:
    """Deterministic analysis from a stored keyword list: same JD + same resume = same result."""
    resume_full = _flatten_resume_text(base_resume)
    resume_skills = [str(s) for s in base_resume.get("skills", [])]
    matching, missing = [], []
    for kw in payload.get("keywords") or []:
        (matching if is_keyword_in_resume(kw, resume_full, resume_skills) else missing).append(kw)
    exps = base_resume.get("experience") or []
    cand_title = (exps[0].get("title") or exps[0].get("role") or "") if exps and isinstance(exps[0], dict) else ""
    cand_years = _estimate_years_experience(base_resume)
    req = re.search(r"(\d+)", str(payload.get("exp_years_jd") or ""))
    req_years = int(req.group(1)) if req else None
    jd_title = payload.get("job_title_jd") or "Not stated"
    stop = {"senior", "junior", "lead", "staff", "principal", "sr", "jr"}
    jd_words = set(re.findall(r"[a-z]{3,}", jd_title.lower())) - stop
    cv_words = set(re.findall(r"[a-z]{3,}", cand_title.lower())) - stop
    contexts = payload.get("contexts") or {}
    det_ctx = extract_keyword_contexts_from_jd(missing, jd_text)
    soft = soft or {}
    cand_name = base_resume.get("name", "Candidate")
    res = {
        "resume_name": f"{cand_name.replace(' ', '_')}_Resume",
        "job_title_jd": jd_title,
        "job_title_resume": soft.get("job_title_resume") or cand_title or "Not stated",
        "job_title_match": soft.get("job_title_match", bool(jd_words & cv_words)),
        "exp_years_jd": payload.get("exp_years_jd") or "Not stated",
        "exp_years_resume": f"{cand_years}+ years exp" if cand_years else (soft.get("exp_years_resume") or "Not stated"),
        "exp_years_match": (cand_years >= req_years) if (req_years and cand_years) else bool(soft.get("exp_years_match", False)),
        "ai_score": soft.get("ai_score"),
        "score_source": "keyword_coverage",
        "keyword_source": payload.get("source", "gemini"),
        "industries": payload.get("industries") or [],
        "industries_match": bool(soft.get("industries_match", False)),
        "matching_keywords": matching,
        "missing_keywords": missing,
        "missing_keyword_contexts": {k: (contexts.get(k) or det_ctx.get(k) or "").strip() for k in missing},
        "total_keywords": len(matching) + len(missing),
        "summary_feedback": soft.get("summary_feedback") or "",
        "summary_match": bool(soft.get("summary_match", False)),
    }
    res.update(_deterministic_score(matching, missing))
    return res


def analyze_jd_and_resume_with_gemini(jd_text: str, base_resume: dict, job_url: str = "") -> dict:
    """ATS analysis with a stable keyword list per job.

    The first analysis of a job asks Gemini for the JD's keywords and stores the
    list; every later analysis of the same job (same URL or same JD text) reuses
    it, so the score only changes when the resume changes."""
    base_resume = base_resume or {}
    keys = _jd_cache_keys(jd_text, job_url)
    res_key = (keys[-1] if keys else "") + ":" + _resume_fingerprint(base_resume)
    cached = _jd_cache_get(keys) if keys else None
    if cached and cached.get("keywords"):
        print(f"[LLM Matcher] Reusing stored keyword list for this job ({len(cached['keywords'])} keywords), no Gemini call")
        return _result_from_keywords(cached, jd_text, base_resume, _RESULT_CACHE_MEM.get(res_key))

    res = _analyze_uncached(jd_text, base_resume)
    kws = list(dict.fromkeys((res.get("matching_keywords") or []) + (res.get("missing_keywords") or [])))
    # Only a real Gemini extraction is stored; a local fallback (Gemini down) is
    # not, so the next check can still get the better list.
    if keys and len(kws) >= 5 and not res.get("error") and res.get("ai_score") is not None:
        payload = {
            "keywords": kws,
            "job_title_jd": res.get("job_title_jd"),
            "exp_years_jd": res.get("exp_years_jd"),
            "industries": res.get("industries") or [],
            "contexts": res.get("missing_keyword_contexts") or {},
            "source": "gemini",
        }
        _jd_cache_put(keys, payload)
        soft = {k: res.get(k) for k in ("job_title_resume", "job_title_match", "exp_years_resume", "exp_years_match",
                                        "industries_match", "summary_feedback", "summary_match", "ai_score")}
        _RESULT_CACHE_MEM[res_key] = soft
        return _result_from_keywords(payload, jd_text, base_resume, soft)
    return res


def _analyze_uncached(jd_text: str, base_resume: dict) -> dict:
    """
    Passes BOTH the scraped Job Description AND the candidate's Base Resume to Gemini.
    Gemini compares them semantically and returns high-value missing keywords,
    already matching keywords, and an accurate ATS match score.
    """
    from dotenv import load_dotenv
    load_dotenv(override=False)
    from gemini_client import get_gemini_client, execute_with_failover, get_all_gemini_keys

    keys = get_all_gemini_keys()
    if not keys:
        print("[LLM Matcher] GEMINI_API_KEY missing from environment — using local keyword extractor fallback")
        return _local_matcher_fallback(jd_text, base_resume)

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
    # Real bot-block pages are short error screens (< 1200 chars).
    # Real JDs (>= 1200 chars) often contain words like 'cloudflare', 'security check', or cookie notices and must NOT be rejected.
    if len(jd_stripped) < 1200:
        for sig in JD_BOT_SIGNATURES:
            if sig in jd_lower:
                print(f"[LLM Matcher] [WARN] Short JD ({len(jd_stripped)} chars) matches bot-block pattern '{sig}' — refusing to analyze.")
                return {"score": 0, "matching_keywords": [], "missing_keywords": [],
                        "total_keywords": 0, "error": "jd_is_bot_page"}


    try:
        prompt = f"""You are an expert ATS (Applicant Tracking System) recruiter and resume architect.
Analyze the following Job Description against the Candidate's Master Resume.

YOUR TASK:
1. Extract 12-30 ATS KEYWORDS from the Job Description: hard technical skills, programming languages, databases, cloud services, frameworks, tools, methodologies, certifications, and domain terms that a recruiter would type into an ATS search for this role.
2. ONLY extract terms that literally appear in the Job Description text. Copy each keyword EXACTLY as the JD spells it (same casing, punctuation and plural form, e.g. "Node.js", "CI/CD", "PostgreSQL", "REST APIs"), because exact-match ATS platforms only credit the JD's spelling.
3. Do NOT add tools or skills the JD does not mention, even if they are common for the role. If the JD is short, return fewer keywords rather than guessing.
4. Prefer specific terms over generic ones ("Apache Airflow" over "orchestration"; "AWS Lambda" over "cloud"). When the JD gives both an acronym and its long form, extract the form used most often.
5. Categorize all extracted skills into:
   - "matching_keywords": present in the candidate's resume
   - "missing_keywords": missing from the candidate's resume
   - "missing_keyword_contexts": An object mapping EACH missing keyword to the EXACT sentence, requirement bullet, or phrase in the Job Description where that term or concept was specified (e.g. {{"forecasting": "Build scalable time-series feature pipelines and ML models for predictive demand forecasting across 500k daily transactions."}}). This provides critical technical domain context so the AI knows precisely how the technology is applied.
6. Extract the following comparison data:
   - "job_title_jd": Target job title from the JD (e.g. "Software Engineer", "Data Engineer", "Frontend Developer", etc. NEVER return 'Not Specified' or 'None').
   - "job_title_resume": Candidate's current/recent job title from resume (e.g. "Data Engineer II")
   - "job_title_match": true if titles are semantically aligned/equivalent, else false
   - "exp_years_jd": Minimum years of experience requested in JD (e.g. "3+ years exp" or "5+ years exp" or "2+ years exp". NEVER return 'Not Specified').
   - "exp_years_resume": Candidate total years of experience calculated from resume (e.g. "8+ years exp")
   - "exp_years_match": true if candidate meets or exceeds the required years, else false
   - "industries": Array of 3-7 relevant industry/domain tags for this company & role (e.g. ["Information Technology", "Software Engineering", "Cloud Computing"])
   - "industries_match": true or false
   - "summary_feedback": 1-2 sentences evaluating how well the candidate's summary matches this specific role and what is missing.
   - "summary_match": true if summary is strong match, false if it needs tailoring
   - "score": Overall ATS match score (integer from 0 to 100)
   - "score_scale_10": Float from 0.0 to 10.0 (e.g. 5.5, 7.8, 8.5)
   - "score_rating": One of "Poor" (under 6.0), "Fair" (6.0-6.9), "Good" (7.0-7.9), "Great" (8.0-8.9), "Excellent" (9.0+)

CRITICAL RULES:
- STRICTLY EXCLUDE legal disclaimers, EEOC text, veteran disclosures, disability forms, and soft skill filler words.
- A keyword counts as "matching" ONLY if the resume contains that exact term (or its plural/singular). A synonym or related tool is NOT a match: put the keyword in "missing_keywords".
- For EVERY missing keyword, find and include the exact context sentence from the JD in "missing_keyword_contexts".

JOB DESCRIPTION:
{jd_text[:14000]}

CANDIDATE MASTER RESUME:
{json.dumps({k: v for k, v in base_resume.items() if not str(k).startswith('_')}, ensure_ascii=False, separators=(',', ':'))[:16000]}

OUTPUT FORMAT:
Return ONLY a valid JSON object matching this schema:
{{
  "score": 55,
  "score_scale_10": 5.5,
  "score_rating": "Poor",
  "job_title_jd": "Software Engineer",
  "job_title_resume": "Data Engineer II",
  "job_title_match": true,
  "exp_years_jd": "3+ years exp",
  "exp_years_resume": "8+ years exp",
  "exp_years_match": true,
  "industries": ["Information Technology", "Software Engineering", "Cloud Computing"],
  "industries_match": false,
  "matching_keywords": ["Python", "SQL", "Git"],
  "missing_keywords": ["REST APIs", "Docker", "CI/CD", "AWS", "System Design"],
  "missing_keyword_contexts": {{
    "REST APIs": "Design and consume internal REST APIs for microservice communication.",
    "Docker": "Containerize backend microservices using Docker for deployment.",
    "CI/CD": "Maintain automated CI/CD pipelines in GitHub Actions.",
    "AWS": "Deploy serverless workloads on AWS Lambda and S3.",
    "System Design": "Participate in architecture reviews and distributed system design."
  }},
  "summary_feedback": "Your current summary does not effectively showcase your qualifications and alignment with this job.",
  "summary_match": false
}}"""

        from gemini_client import (
            get_candidate_models,
            record_model_failure,
            record_model_success,
            extract_clean_text,
            get_standard_genai_config,
        )

        def _call_gemini(client):
            models = get_candidate_models()
            resp = None
            last_err = None
            for m in models:
                for attempt in range(2):
                    try:
                        cfg = get_standard_genai_config(model_name=m, temperature=0.1, is_json=True)
                        cfg.thinking_config = None  # Never combine thinking with structured JSON
                        if "gemma" not in m:
                            cfg.response_mime_type = "application/json"
                        resp = client.models.generate_content(
                            model=m,
                            contents=prompt,
                            config=cfg,
                        )
                        raw = extract_clean_text(resp)
                        if raw:
                            record_model_success(m)
                            print(f"[LLM Matcher] [OK] Extracted ATS matrix with {m} (JSON mode)")
                            return resp
                    except Exception as model_err:
                        last_err = model_err
                        err_str = str(model_err).upper()
                        record_model_failure(m, model_err)
                        print(f"[LLM Matcher] {m} (try {attempt + 1}) note: {str(model_err)[:120]}")
                        # If momentary 503 high demand or 504 timeout, do a quick pause on attempt 0 before next try
                        if ("503" in err_str or "UNAVAILABLE" in err_str or "504" in err_str) and attempt == 0:
                            time.sleep(1.0)
                            continue
                        break

            if last_err:
                raise last_err

            return resp

        response = execute_with_failover(_call_gemini)

        parsed = {}
        raw_text = extract_clean_text(response)
        if raw_text:
            if raw_text.startswith("```"):
                raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
                raw_text = re.sub(r"\s*```$", "", raw_text)
            try:
                parsed = json.loads(raw_text)
            except Exception as pe:
                print(f"[LLM Matcher] JSON parse note: {pe}")

        # Extract structured matrix data with safe fallbacks
        raw_matching = parsed.get("matching_keywords", [])
        raw_missing  = parsed.get("missing_keywords", [])

        resume_full = _flatten_resume_text(base_resume)
        resume_skills = [str(s) for s in base_resume.get("skills", [])]

        final_matching = []
        final_missing  = []
        seen = set()

        # Gemini's "matching" list is re-verified literally: a semantic match the ATS
        # would not credit (e.g. "K8s" for "Kubernetes") is moved to missing.
        for kw in raw_matching:
            k_clean = str(kw).strip()
            if not k_clean or k_clean.lower() in seen or k_clean.lower() in GENERIC_FILLER_WORDS:
                continue
            seen.add(k_clean.lower())
            if is_keyword_in_resume(k_clean, resume_full, resume_skills):
                final_matching.append(k_clean)
            else:
                final_missing.append(k_clean)

        for kw in raw_missing:
            k_clean = kw.strip()
            if not k_clean or k_clean.lower() in seen or k_clean.lower() in GENERIC_FILLER_WORDS:
                continue
            seen.add(k_clean.lower())
            if is_keyword_in_resume(k_clean, resume_full, resume_skills):
                final_matching.append(k_clean)
            else:
                final_missing.append(k_clean)

        # ── MULTI-TIER ROBUSTNESS FALLBACK ──────────────────────────────────────────
        # If Gemini returned fewer than 4 keywords, extract technical keywords directly from JD text
        if len(final_matching) + len(final_missing) < 4:
            print(f"[LLM Matcher] [FALLBACK] Gemini returned only {len(final_matching)+len(final_missing)} keywords — triggering local TECH_PATTERNS...")
            try:
                from keyword_matcher import extract_keywords_from_text
                local_kws = extract_keywords_from_text(jd_text)
                for kw in local_kws:
                    k_title = kw.title() if len(kw) > 4 and kw.islower() else kw
                    if k_title.lower() in seen or k_title.lower() in GENERIC_FILLER_WORDS:
                        continue
                    seen.add(k_title.lower())
                    if is_keyword_in_resume(k_title, resume_full, resume_skills):
                        final_matching.append(k_title)
                    else:
                        final_missing.append(k_title)
            except Exception as fe:
                print(f"[LLM Matcher] Local keyword fallback error: {fe}")

        # Drop any keyword Gemini returned that does not occur in the JD at all:
        # the ATS searches for the employer's terms, not the model's guesses.
        from ats_scoring import keyword_present as _in_text
        final_matching = [k for k in final_matching if _in_text(k, jd_text)]
        final_missing = [k for k in final_missing if _in_text(k, jd_text)]

        tot = len(final_matching) + len(final_missing)

        job_title_jd = (parsed.get("job_title_jd") or "").strip()
        if not job_title_jd or job_title_jd.lower() in ("not specified", "none", "unknown", "n/a", "null", "target role", "role"):
            first_lines = [l.strip() for l in jd_text.splitlines() if l.strip() and len(l.strip()) < 60]
            job_title_jd = first_lines[0] if first_lines else ""
            job_title_jd = re.sub(r'^(?:Title:\s*|Job Application for\s*|Job Openings\s*)+', '', job_title_jd, flags=re.I).strip()
        job_title_jd = job_title_jd or "Not stated"

        exp_years_jd = (parsed.get("exp_years_jd") or "").strip()
        if not exp_years_jd or exp_years_jd.lower() in ("not specified", "none", "unknown", "n/a", "null"):
            exp_match = re.search(r'(\d+)\+?\s*(?:to\s*\d+\+?)?\s*years?', jd_text, re.I)
            exp_years_jd = f"{exp_match.group(1)}+ years exp" if exp_match else "Not stated"

        industries = parsed.get("industries")
        if not isinstance(industries, list):
            industries = []

        # Score = literal keyword coverage of the master resume: the same measure
        # the pipeline later applies to the delivered DOCX, so before/after compare.
        det = _deterministic_score(final_matching, final_missing)
        score, score_10, rating = det["score"], det["score_scale_10"], det["score_rating"]
        ai_score = parsed.get("score") if isinstance(parsed.get("score"), (int, float)) else None

        cand_name = base_resume.get("name", "Candidate")
        resume_name_tag = f"{cand_name.replace(' ', '_')}_Resume"
        exps = base_resume.get("experience") or []
        cand_title = (exps[0].get("title") or exps[0].get("role") or "") if exps and isinstance(exps[0], dict) else ""
        cand_years = _estimate_years_experience(base_resume)

        # Build exact JD context mapping for every missing keyword
        llm_contexts = parsed.get("missing_keyword_contexts") or {}
        deterministic_contexts = extract_keyword_contexts_from_jd(final_missing, jd_text)
        final_missing_contexts = {}
        for kw in final_missing:
            ctx = llm_contexts.get(kw, "")
            if not ctx or len(ctx.strip()) < 15:
                ctx = deterministic_contexts.get(kw, "")
            final_missing_contexts[kw] = ctx.strip()

        res = {
            "score": score,
            "score_scale_10": score_10,
            "score_rating": rating,
            "resume_name": resume_name_tag,
            "job_title_jd": job_title_jd,
            "job_title_resume": parsed.get("job_title_resume") or cand_title or "Not stated",
            "job_title_match": bool(parsed.get("job_title_match", False)),
            "exp_years_jd": exp_years_jd,
            "exp_years_resume": parsed.get("exp_years_resume") or (f"{cand_years}+ years exp" if cand_years else "Not stated"),
            "exp_years_match": bool(parsed.get("exp_years_match", False)),
            "ai_score": ai_score,
            "score_source": "keyword_coverage",
            "industries": industries,
            "industries_match": bool(parsed.get("industries_match", False)),
            "matching_keywords": final_matching,
            "missing_keywords": final_missing,
            "missing_keyword_contexts": final_missing_contexts,
            "total_keywords": tot,
            "summary_feedback": parsed.get("summary_feedback") or "Your current summary does not effectively showcase your qualifications and alignment with this job.",
            "summary_match": bool(parsed.get("summary_match", False)),
        }

        print(f"[LLM Matcher] ATS Matrix Result: Score {score_10}/10 ({rating}) | {len(final_matching)} matched / {tot} total keywords | {len(final_missing_contexts)} contexts extracted")
        return res

    except Exception as e:
        print(f"[LLM Matcher] Error calling Gemini: {e} — triggering local technical keyword extraction fallback")
        return _local_matcher_fallback(jd_text, base_resume)


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
