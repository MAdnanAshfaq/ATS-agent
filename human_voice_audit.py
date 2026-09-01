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

    # 3. Audit Banned AI Lexicon across entire resume
    full_text = json.dumps(resume, ensure_ascii=False).lower()
    banned_found = []
    for bw in banned_words:
        # Match whole word
        if re.search(r'\b' + re.escape(bw) + r'\b', full_text):
            banned_found.append(bw)
            findings.append(f"Banned AI tell word detected: '{bw}'")

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


if __name__ == "__main__":
    sample = {
        "summary": "Data Engineer with 8 years of experience building scalable data pipelines.",
        "skills": ["Python", "SQL", "Databricks"],
        "experience": [
            {
                "title": "Data Engineer II",
                "company": "Strive Health",
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
    print("Audit Report Sample:", json.dumps(report, indent=2))
