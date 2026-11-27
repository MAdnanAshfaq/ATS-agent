"""One deterministic report on a tailored resume, used everywhere it is judged.

The pipeline gate, the results panel and HollaBuddy all read this same report,
so the same resume always gets the same findings. Nothing here calls an LLM.
The limits it checks live in resume_rules.py, which the pipeline also uses to
fix them, so "the pipeline passed" and "HollaBuddy found no issues" agree.

Each finding says who can fix it:
  - "pipeline": the tailoring pipeline fixes it automatically (and re-checks).
  - "master":   it comes from a fact the pipeline must keep (title, dates, the
                template), so only an edit to the master resume changes it.
  - "you":      needs a decision from the candidate.

Responsibilities, keywords and numbers added beyond the master resume are the
owner's intended design. They are listed as interview-prep topics, never as issues.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from ats_scoring import (
    keyword_present,
    keywords_added_beyond,
    resume_json_text,
    resume_prose_text,
    score_docx,
    score_text,
)

# Year a tool became common in industry job posts. A bullet claiming it in a role
# that ended earlier is a claim an interviewer can disprove from the dates alone.
TOOL_ERA = {
    "langchain": 2022, "llamaindex": 2023, "chatgpt": 2022, "gpt-4": 2023, "gpt-3": 2020,
    "llm": 2022, "llms": 2022, "large language models": 2022, "generative ai": 2022, "genai": 2022,
    "rag": 2022, "retrieval-augmented generation": 2022, "prompt engineering": 2022,
    "vector database": 2021, "pinecone": 2021, "weaviate": 2020, "chroma": 2023, "milvus": 2020,
    "openai": 2020, "hugging face": 2018, "transformers": 2018, "copilot": 2021,
    "microsoft fabric": 2023, "fabric": 2023, "onelake": 2023, "databricks": 2015, "delta lake": 2019,
    "unity catalog": 2022, "dbt": 2018, "snowflake": 2016, "airbyte": 2021, "fivetran": 2017,
    "kubernetes": 2016, "k8s": 2016, "terraform": 2016, "docker": 2014, "github actions": 2019,
    "argo": 2019, "mlflow": 2018, "kubeflow": 2018, "dagster": 2020, "prefect": 2019,
    "apache airflow": 2016, "airflow": 2016, "apache iceberg": 2019, "iceberg": 2019,
    "apache kafka": 2012, "kafka": 2012, "apache spark": 2014, "pyspark": 2015, "spark": 2014,
    "fastapi": 2019, "next.js": 2017, "react": 2014, "typescript": 2014, "vue": 2015, "svelte": 2019,
    "graphql": 2016, "rust": 2016, "polars": 2021, "duckdb": 2020, "bigquery": 2012, "redshift": 2013,
    "aws lambda": 2015, "lambda": 2015, "azure synapse": 2020, "synapse": 2020, "power bi": 2015,
    "looker": 2014, "tableau": 2010, "streamlit": 2019, "gradio": 2020,
}

_SEVERITY_ORDER = {"blocker": 0, "warning": 1, "info": 2}
_BELIEVABILITY = {"credibility", "facts", "keyword_stuffing", "new_claims", "length"}


def _year_span(dates: str) -> tuple[Optional[int], Optional[int]]:
    """('2019 – Present') -> (2019, current year); unknown parts are None."""
    text = str(dates or "")
    years = [int(y) for y in re.findall(r"(?:19|20)\d{2}", text)]
    start = years[0] if years else None
    if re.search(r"\b(present|current|now|today)\b", text, re.I):
        end = date.today().year
    else:
        end = years[-1] if years else None
    return start, end


def era_violations(resume: dict, keywords: list[str]) -> list[dict]:
    """Job keywords placed only in roles that ended before the tool existed.
    Only the job's keywords are checked: common words like "react" elsewhere in a
    bullet are not tool claims."""
    out = []
    roles = [e for e in (resume.get("experience") or []) if isinstance(e, dict)]
    for term in dict.fromkeys(keywords or []):
        era = TOOL_ERA.get(str(term).lower())
        if not era:
            continue
        placed, plausible = [], False
        for e in roles:
            text = "\n".join(str(b) for b in (e.get("bullets") or []))
            if not keyword_present(term, text):
                continue
            _, end = _year_span(e.get("dates"))
            placed.append(e)
            if end is None or end >= era:
                plausible = True
        if placed and not plausible:
            out.append({"keyword": term, "era": era,
                        "where": "; ".join(f"{e.get('company', '?')} ({e.get('dates', '?')})" for e in placed)})
    return out


def _fixed_fact_findings(resume: dict, base_resume: Optional[dict]) -> list[dict]:
    if not base_resume:
        return []
    out = []
    base_roles = [e for e in (base_resume.get("experience") or []) if isinstance(e, dict)]
    new_roles = [e for e in (resume.get("experience") or []) if isinstance(e, dict)]
    for i, b in enumerate(base_roles):
        if i >= len(new_roles):
            out.append({"severity": "blocker", "category": "facts", "fix": "pipeline",
                        "issue": f"The role at {b.get('company', '?')} from your master resume is missing."})
            continue
        n = new_roles[i]
        for field in ("company", "title", "dates"):
            bv, nv = str(b.get(field) or "").strip(), str(n.get(field) or "").strip()
            if bv and nv and bv != nv:
                out.append({"severity": "blocker", "category": "facts", "fix": "pipeline",
                            "issue": f"{field.title()} changed from '{bv}' to '{nv}'. Companies, titles and dates must match your master resume."})
    return out


def _classify_voice(msg: str) -> dict:
    if msg.startswith("Suspicious employment date"):
        return {"severity": "warning", "category": "dates", "fix": "master",
                "issue": msg + " Add 'Present' to your current role in the master resume if you still work there."}
    return {"severity": "warning", "category": "writing_style", "fix": "pipeline", "issue": msg}


def _classify_ats(msg: str) -> dict:
    if msg.startswith("Gate 3"):
        return {"severity": "warning", "category": "title_match", "fix": "you",
                "issue": msg + " Your real titles are kept as-is; decide whether to add the suggested equivalent in your master resume."}
    if msg.startswith("Gate 4"):
        return {"severity": "warning", "category": "date_format", "fix": "master",
                "issue": msg + " Dates are copied from your master resume; change the format there."}
    if msg.startswith("Gate 2"):
        return {"severity": "warning", "category": "parse_safety", "fix": "master", "issue": msg}
    return {"severity": "warning", "category": "keyword_density", "fix": "pipeline", "issue": msg}


def build_resume_report(
    resume: dict,
    base_resume: Optional[dict] = None,
    keywords: Optional[list[str]] = None,
    role: str = "",
    platform: Any = None,
    docx_path: Optional[str] = None,
    jd_text: str = "",
) -> dict[str, Any]:
    """Measure a tailored resume. Same inputs always give the same report.

    Coverage and believability are reported side by side: must-have keywords must
    appear in bullets, nice-to-have keywords may sit in Skills only, and the
    believability checks (eras, stuffing, new numbers, length caps) guard the other side."""
    from human_voice_audit import audit_ats_compliance, audit_resume_dict
    from platform_rules import get_profile, get_safe_mode_profile
    import resume_rules as rr

    resume = resume if isinstance(resume, dict) else {}
    base = base_resume or {}
    keywords = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    tiers = rr.split_keyword_tiers(keywords, jd_text) if jd_text else {"must_have": list(keywords), "nice_to_have": []}
    must, nice = tiers["must_have"], tiers["nice_to_have"]
    themes = rr.extract_core_themes(jd_text) if jd_text else []
    profile = platform
    if profile is None or isinstance(profile, str):
        try:
            profile = get_profile(profile) if profile else get_safe_mode_profile()
        except Exception:
            profile = get_safe_mode_profile()

    findings: list[dict] = []

    def add(severity: str, category: str, fix: str, issue: str) -> None:
        findings.append({"severity": severity, "category": category, "fix": fix, "issue": issue})

    # ── Coverage ──────────────────────────────────────────────────────────────
    if docx_path:
        cov = score_docx(docx_path, keywords)
        for pf in cov.get("parse_findings") or []:
            add("blocker" if pf.get("severity") == "critical" else "warning", "parse_safety", "master", pf.get("issue", ""))
        source = "delivered_docx"
    else:
        cov = score_text(resume_json_text(resume), keywords)
        source = "resume_json"
    missing = list(cov.get("missing") or [])
    must_missing_file = [k for k in must if k in missing]
    nice_missing_file = [k for k in nice if k in missing]
    if must_missing_file:
        add("blocker", "keywords", "pipeline", f"Must-have keyword(s) not in the resume at all: {', '.join(must_missing_file)}.")
    if nice_missing_file:
        add("warning", "keywords", "pipeline", f"Nice-to-have keyword(s) not even in Skills: {', '.join(nice_missing_file)}.")
    prose = resume_prose_text(resume)
    must_not_in_bullets = [k for k in must if k not in missing and not keyword_present(k, prose)]
    if must_not_in_bullets:
        add("blocker", "keywords", "pipeline",
            f"Must-have keyword(s) only in Skills, not in any bullet or the summary: {', '.join(must_not_in_bullets)}.")
    nice_skills_only = [k for k in nice if k not in missing and not keyword_present(k, prose)]
    theme_gaps = rr.missing_themes(resume, themes)
    if theme_gaps:
        add("warning", "core_themes", "pipeline",
            "Core responsibilities of this job not shown in the summary or the two most recent roles: "
            + "; ".join(theme_gaps) + ".")
    summary_kws = [k for k in keywords if keyword_present(k, str(resume.get("summary") or ""))]
    if len(summary_kws) > rr.MAX_SUMMARY_KEYWORDS:
        add("warning", "keyword_stuffing", "pipeline",
            f"The summary lists {len(summary_kws)} job keywords (limit {rr.MAX_SUMMARY_KEYWORDS}); it reads as a tool list.")
    if role and resume.get("summary") and not rr.summary_names_target(resume.get("summary") or "", role):
        add("warning", "summary", "pipeline",
            f"The summary does not connect your background to the target role '{role}'.")

    # ── Believability ─────────────────────────────────────────────────────────
    findings += _fixed_fact_findings(resume, base)
    for v in era_violations(resume, keywords):
        add("blocker", "credibility", "pipeline",
            f"'{v['keyword']}' is claimed at {v['where']}, but it only came into common use around {v['era']}. "
            f"An interviewer can spot this from the dates. Move it to a later role.")
    stuffed = rr.stuffed_bullets(base, resume, keywords) if base else []
    for sb in stuffed:
        add("warning", "keyword_stuffing", "pipeline",
            f"A bullet at {sb['company']} crams {len(sb['keywords'])} new job keywords ({', '.join(sb['keywords'])}); "
            f"keep at most {rr.MAX_NEW_KEYWORDS_PER_BULLET} per bullet: '{sb['bullet'][:90]}'")
    roles = [e for e in (resume.get("experience") or []) if isinstance(e, dict)]
    base_roles = [e for e in (base.get("experience") or []) if isinstance(e, dict)]
    for i, e in enumerate(roles):
        mcount = len(base_roles[i].get("bullets") or []) if i < len(base_roles) else len(e.get("bullets") or [])
        cap = rr.role_cap(i, mcount)
        n = len(e.get("bullets") or [])
        if n > cap:
            add("warning", "length", "pipeline",
                f"{e.get('company', '?')} has {n} bullets (limit {cap} for this position; master had {mcount}).")
    total_bullets = sum(len(e.get("bullets") or []) for e in roles)
    if total_bullets > rr.MAX_TOTAL_BULLETS:
        add("warning", "length", "pipeline", f"{total_bullets} bullets in total (limit {rr.MAX_TOTAL_BULLETS}).")
    words = rr.prose_word_count(resume)
    if words > rr.MAX_PROSE_WORDS:
        add("warning", "length", "pipeline", f"Summary and bullets run {words} words (limit {rr.MAX_PROSE_WORDS}, about two pages).")
    skills = [str(s) for s in (resume.get("skills") or [])]
    dupes = rr.duplicate_skills(skills)
    if dupes:
        add("warning", "skills", "pipeline", "Duplicate skills: " + "; ".join(" / ".join(g) for g in dupes) + ".")
    if len(skills) > rr.MAX_SKILLS:
        add("warning", "skills", "pipeline", f"{len(skills)} skills listed (limit {rr.MAX_SKILLS}).")
    claims = rr.new_claims(base, resume) if base else []
    if len(claims) > rr.MAX_NEW_NUMERIC_CLAIMS:
        add("warning", "new_claims", "pipeline",
            f"{len(claims)} bullets state numbers that are not in your master resume (limit {rr.MAX_NEW_NUMERIC_CLAIMS}).")
    for b in rr.bullets_with_too_many_numbers(resume):
        add("warning", "new_claims", "pipeline", f"Bullet has more than {rr.MAX_NUMBERS_PER_BULLET} numbers: '{b[:90]}'")

    # ── Writing style and ATS format (the same audits the pipeline runs) ─────
    voice = audit_resume_dict(resume)
    findings += [_classify_voice(m) for m in voice.get("findings", [])]
    ats = audit_ats_compliance(resume, ats_profile=profile, jd_keywords=keywords, jd_title=role)
    findings += [_classify_ats(m) for m in ats.get("findings", [])]

    # De-duplicate and sort so the same resume always lists findings in the same order.
    uniq, seen = [], set()
    for f in findings:
        key = (f["category"], f["issue"])
        if f["issue"] and key not in seen:
            seen.add(key)
            uniq.append(f)
    uniq.sort(key=lambda f: (_SEVERITY_ORDER.get(f["severity"], 9), f["category"], f["issue"]))

    added = keywords_added_beyond(base, resume_json_text(resume), keywords) if base_resume else []
    blockers = [f for f in uniq if f["severity"] == "blocker"]
    pipeline_fixable = [f for f in uniq if f["fix"] == "pipeline"]
    if blockers:
        verdict = "needs_fixes"
    elif pipeline_fixable:
        verdict = "ready_with_minor_issues"
    else:
        verdict = "ready"

    return {
        "verdict": verdict,
        "keyword_score": cov.get("score"),
        "keywords_total": len(keywords),
        "keywords_matched": cov.get("matched", []),
        "keywords_missing": missing,
        "keywords_skills_only": must_not_in_bullets + nice_skills_only,
        "must_have": must,
        "nice_to_have": nice,
        "core_themes": themes,
        "score_source": source,
        "coverage": {
            "file_keyword_score": cov.get("score"),
            "must_have_in_bullets": f"{len(must) - len(must_not_in_bullets) - len(must_missing_file)}/{len(must)}",
            "nice_to_have_in_file": f"{len(nice) - len(nice_missing_file)}/{len(nice)}",
            "nice_to_have_skills_only": nice_skills_only,
            "core_themes_shown": f"{len(themes) - len(theme_gaps)}/{len(themes)}",
            "missing_themes": theme_gaps,
        },
        "believability": {
            "flags": sum(1 for f in uniq if f["category"] in _BELIEVABILITY),
            "era_flags": sum(1 for f in uniq if f["category"] == "credibility"),
            "stuffed_bullets": len(stuffed),
            "new_numeric_claims": len(claims),
            "bullets_total": total_bullets,
            "bullets_by_role": [{"company": e.get("company", ""), "bullets": len(e.get("bullets") or []),
                                 "master": len(base_roles[i].get("bullets") or []) if i < len(base_roles) else None}
                                for i, e in enumerate(roles)],
            "prose_words": words,
        },
        "findings": uniq,
        "counts": {
            "blocker": len(blockers),
            "warning": sum(1 for f in uniq if f["severity"] == "warning"),
            "pipeline_fixable": len(pipeline_fixable),
            "from_master": sum(1 for f in uniq if f["fix"] == "master"),
            "needs_you": sum(1 for f in uniq if f["fix"] == "you"),
        },
        "interview_prep": added,
        "interview_prep_claims": claims,
        "style": {"voice_score": voice.get("score"), "burstiness_cv": voice.get("burstiness_cv"),
                  "mean_bullet_words": voice.get("mean_bullet_words")},
        "platform": getattr(profile, "display_name", "Safe Mode"),
    }


def report_as_text(report: dict) -> str:
    """Plain-text rendering for prompts and logs."""
    if not report:
        return "No measured report available."
    lines = [
        f"Verdict: {report.get('verdict')}",
        f"Keyword coverage: {report.get('keyword_score')}% of {report.get('keywords_total')} job keywords "
        f"(measured on {report.get('score_source')})",
    ]
    cov, bel = report.get("coverage") or {}, report.get("believability") or {}
    if cov:
        lines.append(f"Coverage: must-have keywords in bullets {cov.get('must_have_in_bullets')}, "
                     f"nice-to-have in file {cov.get('nice_to_have_in_file')} (Skills-only is fine for these), "
                     f"core themes shown {cov.get('core_themes_shown')}")
    if bel:
        lines.append(f"Believability: {bel.get('flags', 0)} flag(s); era flags {bel.get('era_flags', 0)}, "
                     f"stuffed bullets {bel.get('stuffed_bullets', 0)}, new numeric claims {bel.get('new_numeric_claims', 0)}, "
                     f"{bel.get('bullets_total')} bullets, {bel.get('prose_words')} words")
    if report.get("keywords_missing"):
        lines.append("Missing keywords: " + ", ".join(report["keywords_missing"]))
    findings = report.get("findings") or []
    if findings:
        lines.append(f"Findings ({len(findings)}):")
        for f in findings:
            lines.append(f"- [{f['severity']}] [{f['category']}] [fix: {f['fix']}] {f['issue']}")
    else:
        lines.append("Findings: none.")
    if report.get("interview_prep"):
        lines.append("Interview prep, keywords added beyond the master resume (intentional, NOT issues): "
                     + ", ".join(report["interview_prep"]))
    claims = report.get("interview_prep_claims") or []
    if claims:
        lines.append("Interview prep, new numbers/claims to be ready to explain (intentional, NOT issues):")
        for c in claims:
            lines.append(f"- {c.get('company')}: {', '.join(c.get('numbers') or [])} in '{str(c.get('bullet'))[:100]}'")
    return "\n".join(lines)
