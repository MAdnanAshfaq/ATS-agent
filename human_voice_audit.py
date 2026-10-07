"""
human_voice_audit.py — Detect AI-sounding resume/cover-letter prose and verify human voice.
Gated check based on ResumeHQ (jananthan30/Resume-Builder).
Enforces:
- Cliché AI openers (spearheaded, leveraged, facilitated...)
- Banned AI lexicon & transitional fluff
- Summary constraints (<= 3 sentences, <= 70 words, no formulaic openers)
- Burstiness (Coefficient of Variation CV >= 0.25 on bullet lengths)
- Maximum word count cap per bullet (mean <= 24 words, hard cap <= 28 words)
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_TELLS_PATH = DATA_DIR / "ai_tells.json"


def load_ai_tells(path: str | Path | None = None) -> dict[str, Any]:
    """Load shared AI-tell lexicon; return fallback defaults if missing."""
    p = Path(path) if path else DEFAULT_TELLS_PATH
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {
        "cliche_openers": [
            "spearheaded", "leveraged", "utilized", "facilitated", "ensured",
            "demonstrated", "collaborated", "streamlined", "championed", "fostered",
            "harnessed", "navigated", "liaised", "interfaced", "orchestrated",
            "pioneered", "revolutionized", "architected", "empowered", "elevated", "unlocked"
        ],
        "banned_words": [
            "delve", "tapestry", "robust", "seamless", "seamlessly", "multifaceted",
            "holistic", "synergy", "pivotal", "testament", "transformative",
            "groundbreaking", "cutting-edge", "game-changer", "vibrant", "dynamic",
            "paramount", "relentless", "unwavering", "moreover", "furthermore"
        ],
        "formulaic_summary_openers": [
            "results-driven", "results-oriented", "dynamic and experienced",
            "seasoned professional", "passionate and dedicated", "proven track record"
        ],
        "thresholds": {
            "max_mean_bullet_words": 24,
            "hard_max_bullet_words": 28,
            "min_burstiness_cv": 0.25,
            "target_burstiness_cv": 0.30,
            "max_summary_words": 70,
            "max_summary_sentences": 3,
            "max_cliche_opener_ratio": 0.05
        }
    }


def calculate_burstiness_cv(bullets: list[str]) -> float:
    """
    Calculate the Coefficient of Variation (CV = standard_deviation / mean)
    of bullet word counts. Higher CV (>= 0.25-0.30) means natural human rhythmic variation (jazz),
    whereas CV < 0.20 indicates robotic AI metronome phrasing.
    """
    if len(bullets) < 2:
        return 0.35  # Insufficient samples to penalize

    word_counts = [len(b.split()) for b in bullets if b.strip()]
    if not word_counts:
        return 0.0

    mean = sum(word_counts) / len(word_counts)
    if mean == 0:
        return 0.0

    variance = sum((x - mean) ** 2 for x in word_counts) / len(word_counts)
    std_dev = math.sqrt(variance)
    return std_dev / mean


def audit_resume_dict(resume: dict, tells: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Perform a complete human-voice audit on a resume dictionary.
    Returns:
        {
            "passed": bool,
            "score": float (0-100),
            "findings": list[str],
            "burstiness_cv": float,
            "cliche_count": int,
            "banned_word_count": int,
            "word_count_stats": dict
        }
    """
    if tells is None:
        tells = load_ai_tells()

    cliche_openers = set(tells.get("cliche_openers", []))
    banned_words = set(tells.get("banned_words", []))
    formulaic_openers = tells.get("formulaic_summary_openers", [])
    thresholds = tells.get("thresholds", {})

    findings: list[str] = []
    
    # 1. Audit Summary
    summary = resume.get("summary", "").strip()
    if summary:
        words = summary.split()
        max_summary_words = thresholds.get("max_summary_words", 70)
        max_summary_sentences = thresholds.get("max_summary_sentences", 3)
        
        if len(words) > max_summary_words:
            findings.append(f"Summary too long: {len(words)} words (max allowed: {max_summary_words})")
        
        sentences = [s for s in re.split(r'[.!?]+', summary) if s.strip()]
        if len(sentences) > max_summary_sentences:
            findings.append(f"Summary too long: {len(sentences)} sentences (max allowed: {max_summary_sentences})")
            
        summary_lower = summary.lower()
        for f_opener in formulaic_openers:
            if summary_lower.startswith(f_opener):
                findings.append(f"Formulaic AI summary opener detected: '{f_opener}'")

    # 2. Audit Experience Bullets
    all_bullets: list[str] = []
    for exp in resume.get("experience", []):
        if isinstance(exp, dict):
            for b in exp.get("bullets", []):
                if b and isinstance(b, str) and b.strip():
                    all_bullets.append(b.strip())

    cliche_found_count = 0
    overlong_bullets = 0
    hard_max_words = thresholds.get("hard_max_bullet_words", 28)
    max_mean_words = thresholds.get("max_mean_bullet_words", 24)

    for bullet in all_bullets:
        b_words = bullet.split()
        if not b_words:
            continue
            
        first_word = re.sub(r'^[^\w]+|[^\w]+$', '', b_words[0]).lower()
        if first_word in cliche_openers:
            cliche_found_count += 1
            findings.append(f"AI cliché bullet opener: '{first_word}' in bullet: '{bullet[:60]}...'")

        if len(b_words) > hard_max_words:
            overlong_bullets += 1
            findings.append(f"Bullet exceeds word cap ({len(b_words)} words > {hard_max_words}): '{bullet[:50]}...'")

        # Check for broken, empty, or placeholder bullets (Red Flag #1)
        clean_b = bullet.lstrip("•·▪-* ").strip()
        if not clean_b or len(clean_b) < 10:
            findings.append(f"Broken or empty bullet point detected: '{bullet}'")
        if any(ph in bullet.lower() for ph in ("[todo]", "[company]", "<placeholder>", "insert metric", "[metric]")):
            findings.append(f"Unfinished placeholder in bullet: '{bullet[:50]}...'")

    # Quantified Impact Audit (Red Flag #4)
    metric_regex = re.compile(r'(\b\d+[%kKmMbB]?\b|\$\d+|\b\d+\+\b|\b\d+\s*(?:hours|days|mins|minutes|seconds|ms|percent|users|customers|queries|nodes|servers|models|endpoints|million|billion)\b)')
    quantified_bullets = [b for b in all_bullets if metric_regex.search(b)]
    if len(all_bullets) >= 3:
        quantified_pct = (len(quantified_bullets) / len(all_bullets)) * 100
        if quantified_pct < 50:
            findings.append(f"Low quantified impact: Only {len(quantified_bullets)}/{len(all_bullets)} bullets ({quantified_pct:.0f}%) contain numbers, percentages, or scale metrics (target >= 50%)")

    # Repeated Verb Openers Audit (Red Flag #6)
    openers = [re.sub(r'^[^\w]+|[^\w]+$', '', b.split()[0]).lower() for b in all_bullets if b.split()]
    from collections import Counter
    for op, cnt in Counter(openers).items():
        if cnt >= 3:
            findings.append(f"Repeated verb opener: '{op.title()}' starts {cnt} different bullets. Vary action verbs for natural human flow.")

    # Employment Dates Check on Current Role (Red Flag #3)
    exp_list = resume.get("experience", [])
    if exp_list and isinstance(exp_list, list):
        latest_role = exp_list[0]
        if isinstance(latest_role, dict):
            latest_dates = latest_role.get("dates", "")
            if re.search(r'[-–—]\s*202[4-6]$', latest_dates.strip()) and not re.search(r'\b(present|current)\b', latest_dates, re.IGNORECASE):
                findings.append(f"Suspicious employment date on current role: '{latest_dates}' lacks 'Present'.")

    # Burstiness & Mean Word Length
    if all_bullets:
        word_counts = [len(b.split()) for b in all_bullets]
        mean_words = sum(word_counts) / len(word_counts)
        cv = calculate_burstiness_cv(all_bullets)

        if mean_words > max_mean_words:
            findings.append(f"Mean bullet word count too high: {mean_words:.1f} words (target <= {max_mean_words})")

        min_cv = thresholds.get("min_burstiness_cv", 0.25)
        if len(all_bullets) >= 4 and cv < min_cv:
            findings.append(f"Bullet lengths lack rhythmic burstiness: CV={cv:.2f} (target >= {min_cv:.2f})")
    else:
        mean_words = 0.0
        cv = 0.35

    # 3. Audit Banned AI Lexicon & Generic Filler across entire resume (Red Flag #6)
    full_text = json.dumps(resume, ensure_ascii=False).lower()
    banned_found = []
    for bw in banned_words:
        if re.search(r'\b' + re.escape(bw) + r'\b', full_text):
            banned_found.append(bw)
            findings.append(f"Banned AI tell word detected: '{bw}'")

    generic_fillers = [
        "passionate about delivering high-quality results",
        "detail-oriented team player",
        "proven track record of success",
        "seasoned professional with a passion",
        "strong work ethic and communication skills",
        "go-getter attitude"
    ]
    for filler in generic_fillers:
        if filler in full_text:
            findings.append(f"Generic templated filler detected: '{filler}'")

    # Scoring calculation
    penalty = (len(findings) * 12) + (cliche_found_count * 15) + (len(banned_found) * 15)
    score = max(0.0, min(100.0, 100.0 - penalty))
    passed = len(findings) == 0

    return {
        "passed": passed,
        "score": round(score, 1),
        "findings": findings,
        "burstiness_cv": round(cv, 3),
        "cliche_count": cliche_found_count,
        "banned_word_count": len(banned_found),
        "mean_bullet_words": round(mean_words, 1),
        "total_bullets_audited": len(all_bullets)
    }


def audit_ats_compliance(
    resume: dict,
    ats_profile: Any = None,
    jd_keywords: list[str] | None = None,
    jd_title: str | None = None,
) -> dict[str, Any]:
    """
    Simulate target ATS compliance across 4 strict gates:
    Gate 1: Keyword Density Calculator (enforces platform density ceiling, e.g. 1.5% for Workday/Taleo/SafeMode)
    Gate 2: Parse-Safety Simulator (verifies tableless structure, top contact extraction)
    Gate 3: Title-Match Gate (verifies truthful title alignment if title_weight == high)
    Gate 4: Platform Quirks & Format Compliance Gate (date formatting, length boundaries)
    """
    from platform_rules import get_profile, get_safe_mode_profile
    from ats_learning import record_audit_event

    profile = ats_profile if ats_profile is not None else get_safe_mode_profile()
    if isinstance(profile, str):
        profile = get_profile(profile)

    findings: list[str] = []
    gate_4_dict = {"passed": True, "details": []}
    gate_results = {
        "gate_1_density": {"passed": True, "max_density": 0.0, "details": {}},
        "gate_2_parse_safety": {"passed": True, "details": []},
        "gate_3_title_match": {"passed": True, "details": ""},
        "gate_4_quirks": gate_4_dict,
        "gate_4_platform_quirks": gate_4_dict,
    }

    # Extract all prose text to measure words
    full_text_parts = []
    if resume.get("summary"):
        full_text_parts.append(str(resume["summary"]))
    for sk in resume.get("skills", []):
        full_text_parts.append(str(sk))
    for exp in resume.get("experience", []):
        if exp.get("title"):
            full_text_parts.append(str(exp["title"]))
        if exp.get("company"):
            full_text_parts.append(str(exp["company"]))
        for b in exp.get("bullets", []):
            full_text_parts.append(str(b))
    for pr in resume.get("projects", []):
        if isinstance(pr, dict):
            full_text_parts.append(str(pr.get("name", "")))
            for b in pr.get("bullets", []):
                full_text_parts.append(str(b))
        elif isinstance(pr, str):
            full_text_parts.append(pr)

    combined_text = " ".join(full_text_parts)
    words = [w.lower() for w in re.findall(r'[a-zA-Z0-9_\-\+\#\.]+', combined_text)]
    total_word_count = max(1, len(words))

    # ── Gate 1: Keyword Density Calculator ──
    density_ceiling = getattr(profile, "keyword_density_ceiling", 0.015)
    max_density_found = 0.0
    highest_density_kw = ""

    if jd_keywords:
        cleaned_keywords = [k.strip() for k in jd_keywords if k and len(k.strip()) >= 2]
        for kw in cleaned_keywords:
            kw_clean = kw.strip().lower()
            # Match multi-word or single-word keyword occurrences
            pattern = r'\b' + re.escape(kw_clean) + r'\b'
            matches = len(re.findall(pattern, combined_text.lower()))
            if matches > 0:
                density = matches / total_word_count
                if density > max_density_found:
                    max_density_found = density
                    highest_density_kw = kw

                # Natural target is 2-4 occurrences per keyword; never flag 2 or fewer occurrences as stuffing
                if density > density_ceiling and matches > 2:
                    gate_results["gate_1_density"]["passed"] = False
                    finding_msg = (
                        f"Gate 1 [Keyword Density]: Keyword '{kw}' density is {density*100:.2f}% "
                        f"({matches} occurrences / {total_word_count} words), which exceeds "
                        f"{profile.display_name}'s ceiling of {density_ceiling*100:.1f}%."
                    )
                    findings.append(finding_msg)
                    gate_results["gate_1_density"]["details"][kw] = {
                        "occurrences": matches,
                        "density": round(density, 4),
                        "ceiling": density_ceiling,
                    }

    gate_results["gate_1_density"]["max_density"] = round(max_density_found, 4)

    # ── Gate 2: Parse-Safety Simulator ──
    allows_tables = getattr(profile, "allows_tables", False)
    raw_json_str = json.dumps(resume, ensure_ascii=False)
    
    # Check for Markdown/HTML table markers
    has_table_markers = (
        bool(re.search(r'\|(?:\s*-+\s*\|)+', raw_json_str)) or
        "<table" in raw_json_str.lower() or
        resume.get("_has_tables", False)
    )
    if not allows_tables and has_table_markers:
        gate_results["gate_2_parse_safety"]["passed"] = False
        findings.append(
            f"Gate 2 [Parse-Safety]: Tables detected in resume structure. "
            f"{profile.display_name} parser scrambles table content into disorganized text."
        )
        gate_results["gate_2_parse_safety"]["details"].append("Tables detected on strict tableless platform")

    # Check top-level contact info extraction
    contact_ok = bool(resume.get("contact") or resume.get("email") or resume.get("phone") or ("@" in raw_json_str[:300]))
    if not contact_ok:
        gate_results["gate_2_parse_safety"]["details"].append("Contact information not immediately extractable in header block")

    # ── Gate 3: Title-Match Gate ──
    title_weight = getattr(profile, "title_weight", "high")
    if title_weight == "high" and jd_title:
        experiences = resume.get("experience", [])
        most_recent_title = experiences[0].get("title", "") if experiences else ""
        if most_recent_title:
            jd_title_clean = jd_title.strip().lower()
            rec_title_clean = most_recent_title.strip().lower()
            
            # Check overlap or equivalent phrase
            jd_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', jd_title_clean)) - {"senior", "junior", "lead", "principal", "staff"}
            rec_words = set(re.findall(r'\b[a-zA-Z]{3,}\b', rec_title_clean)) - {"senior", "junior", "lead", "principal", "staff"}
            
            overlap = jd_words & rec_words
            has_equiv = any(k in combined_text.lower() for k in [f"({jd_title_clean} equivalent)", "equivalent)", "focus)"])
            
            if not overlap and not has_equiv:
                gate_results["gate_3_title_match"]["passed"] = False
                finding_msg = (
                    f"Gate 3 [Title Match]: Most recent title '{most_recent_title}' does not match "
                    f"target role '{jd_title}' on {profile.display_name} (high title weight). "
                    f"Recommend adding a truthful parenthetical equivalent (e.g. '{most_recent_title} ({jd_title} equivalent)')."
                )
                findings.append(finding_msg)
                gate_results["gate_3_title_match"]["details"] = finding_msg

    # ── Gate 4: Platform Quirks & Format Compliance Gate ──
    date_format_req = getattr(profile, "date_format", "MM/YYYY")
    if date_format_req == "MM/YYYY":
        # Check if experience dates contain spelled out months like 'January 2021'
        spelled_months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
        for exp in resume.get("experience", []):
            d_str = str(exp.get("dates", "")).lower()
            if any(m in d_str for m in spelled_months):
                gate_4_dict["details"].append(
                    f"Dates '{exp.get('dates')}' use full month names; {profile.display_name} standardizes on MM/YYYY."
                )
                break
    elif date_format_req in ("Month YYYY", "Full Month"):
        # Taleo standard: requires full month names (e.g. 'March 2021', not '03/2021')
        for exp in resume.get("experience", []):
            d_str = str(exp.get("dates", ""))
            if re.search(r'\b\d{1,2}/\d{4}\b', d_str):
                gate_4_dict["passed"] = False
                finding_msg = (
                    f"Gate 4 [Platform Quirks]: Dates '{d_str}' in experience use numeric MM/YYYY format. "
                    f"{profile.display_name} requires spelled-out full month names (e.g. 'March 2021', not '03/2021')."
                )
                findings.append(finding_msg)
                gate_4_dict["details"].append(finding_msg)
                break

    # Calculate overall ATS compliance score
    penalty = (len(findings) * 20)
    score = max(0.0, min(100.0, 100.0 - penalty))
    passed = len(findings) == 0

    # Continuous learning: record audit stats
    try:
        record_audit_event(
            platform_id=profile.platform_id,
            passed=passed,
            density_val=max_density_found,
            issues_count=len(findings),
        )
    except Exception:
        pass

    return {
        "passed": passed,
        "score": round(score, 1),
        "platform": profile.platform_id,
        "display_name": profile.display_name,
        "density_ceiling": density_ceiling,
        "max_density_found": round(max_density_found, 4),
        "highest_density_keyword": highest_density_kw,
        "findings": findings,
        "gate_results": gate_results,
    }


def audit_knockout_screening_questions(
    questions: list[dict],
    candidate_profile: dict | None = None,
    ats_profile: Any = None,
) -> dict[str, Any]:
    """
    Audits job application screening questions against candidate profile (§4.5 & §7).

    Standard Platforms (Newton, Greenhouse, Lever, Workday):
      - Disqualifying mismatches flagged as 'knockout_disqualification'.

    Taleo (Oracle):
      - Screening question answers blend directly into the composite ranking % score.
      - A 'weak but not disqualifying' answer (e.g. answer_quality == 'weak_but_not_disqualifying'
        or is_weak is True) is logged as a 'score_risk' (soft composite ranking penalty),
        distinct from a binary knockout!
    """
    from platform_rules import get_profile, get_safe_mode_profile
    profile = ats_profile if ats_profile is not None else get_safe_mode_profile()
    if isinstance(profile, str):
        profile = get_profile(profile)

    results = []
    disqualified = False
    score_risks = []

    for q in questions:
        q_text = q.get("question", "")
        answer = str(q.get("answer", "")).strip()
        expected = q.get("required_answer")
        is_knockout = bool(q.get("is_knockout", False))
        is_weak = bool(q.get("is_weak", False) or q.get("answer_quality") == "weak_but_not_disqualifying" or q.get("status") == "weak")

        # 1. Binary knockout check
        if is_knockout and expected is not None and str(expected).lower() != answer.lower():
            disqualified = True
            entry = {
                "question": q_text,
                "answer": answer,
                "expected": expected,
                "status": "knockout_disqualification",
                "risk_type": "disqualification",
                "message": f"Knockout mismatch on {profile.display_name}: expected '{expected}', got '{answer}'."
            }
            results.append(entry)
        # 2. Taleo composite scoring check: weak but not disqualifying
        elif profile.platform_id == "taleo" and is_weak:
            entry = {
                "question": q_text,
                "answer": answer,
                "status": "score_risk",
                "risk_type": "score_risk",
                "message": f"Taleo composite ranking risk: answer '{answer}' is weak but not disqualifying (deducts from composite scoring percentage)."
            }
            score_risks.append(entry)
            results.append(entry)
        else:
            results.append({
                "question": q_text,
                "answer": answer,
                "status": "passed",
                "risk_type": "none",
                "message": "Answer acceptable."
            })

    return {
        "platform": profile.platform_id,
        "display_name": profile.display_name,
        "disqualified": disqualified,
        "score_risks": score_risks,
        "has_score_risks": len(score_risks) > 0,
        "total_questions": len(questions),
        "results": results,
    }


if __name__ == "__main__":
    sample = {
        "summary": "Data Engineer with 8 years of experience building scalable data pipelines.",
        "skills": ["Python", "SQL", "Databricks"],
        "experience": [
            {
                "title": "Data Engineer II",
                "company": "CloudScale Technologies",
                "dates": "01/2021 - Present",
                "bullets": [
                    "Built Microsoft Fabric lakehouses using PySpark to process 40 EHR feeds for 100k members.",
                    "Cut deployment time from 2 days to 30 minutes with Azure DevOps CI/CD automation.",
                    "Configured row-level security in Power BI to support 10 health-system partners.",
                    "Optimized Spark jobs to reduce compute costs 25%."
                ]
            }
        ]
    }
    report = audit_resume_dict(sample)
    print("Voice Audit Report Sample:", json.dumps(report, indent=2))
    ats_report = audit_ats_compliance(sample, ats_profile="workday", jd_keywords=["PySpark", "Python"], jd_title="Data Engineer")
    print("ATS Audit Report Sample:", json.dumps(ats_report, indent=2))

